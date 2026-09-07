/*
 * sender.c - Fast reliable file transfer (sender/server)
 * Sends file specified on command line to receiver
 *
 * Usage: ./sender <port> <filename> [mtu]
 *        mtu: 1500 (default) or 9000
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <arpa/inet.h>
#include <sys/time.h>
#include <openssl/md5.h>
#include "protocol.h"

void compute_md5(const uint8_t *data, uint64_t len, uint8_t *out) {
    MD5_CTX ctx;
    MD5_Init(&ctx);
    MD5_Update(&ctx, data, len);
    MD5_Final(out, &ctx);
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <port> <filename> [mtu]\n", argv[0]);
        fprintf(stderr, "  mtu: 1500 (default) or 9000\n");
        fprintf(stderr, "Example: %s 5000 data.bin\n", argv[0]);
        return 1;
    }

    int port = atoi(argv[1]);
    char *filename = argv[2];

    // Determine block size based on MTU
    uint32_t block = FT_BLOCK_1500;
    if (argc >= 4 && atoi(argv[3]) == 9000) {
        block = FT_BLOCK_9001;
        printf("Using MTU 9000 (block size: %d)\n", block);
    } else {
        printf("Using MTU 1500 (block size: %d)\n", block);
    }

    // Read file
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "Error: Cannot open file: %s\n", filename);
        return 1;
    }
    fseek(fp, 0, SEEK_END);
    uint64_t fsize = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    uint8_t *data = malloc(fsize);
    if (!data) {
        fprintf(stderr, "Error: Out of memory\n");
        return 1;
    }
    fread(data, 1, fsize, fp);
    fclose(fp);

    uint32_t nblocks = (fsize + block - 1) / block;
    printf("File: %s (%lu bytes, %u blocks)\n", filename, (unsigned long)fsize, nblocks);

    // Compute MD5
    uint8_t local_md5[16];
    compute_md5(data, fsize, local_md5);
    printf("MD5: ");
    for (int i = 0; i < 16; i++) printf("%02x", local_md5[i]);
    printf("\n");

    // Create socket
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    int bufsize = FT_SOCKBUF_BYTES;
    setsockopt(sock, SOL_SOCKET, SO_SNDBUF, &bufsize, sizeof(bufsize));
    setsockopt(sock, SOL_SOCKET, SO_RCVBUF, &bufsize, sizeof(bufsize));

    // Bind to port
    struct sockaddr_in myaddr;
    memset(&myaddr, 0, sizeof(myaddr));
    myaddr.sin_family = AF_INET;
    myaddr.sin_port = htons(port);
    myaddr.sin_addr.s_addr = INADDR_ANY;
    if (bind(sock, (struct sockaddr*)&myaddr, sizeof(myaddr)) < 0) {
        perror("bind failed");
        return 1;
    }

    printf("Listening on port %d, waiting for receiver...\n", port);

    uint8_t *sendbuf = malloc(FT_MAX_PACKET);
    uint8_t *recvbuf = malloc(FT_MAX_PACKET);
    struct ft_hdr *shdr = (struct ft_hdr*)sendbuf;
    struct ft_hdr *rhdr = (struct ft_hdr*)recvbuf;

    struct sockaddr_in peer;
    socklen_t peerlen = sizeof(peer);

    // Wait for HELLO from receiver (receiver initiates)
    printf("Waiting for connection request...\n");
    while (1) {
        int n = recvfrom(sock, recvbuf, FT_MAX_PACKET, 0, (struct sockaddr*)&peer, &peerlen);
        if (n > 0 && rhdr->type == FT_HELLO) {
            printf("Received connection from %s:%d\n",
                   inet_ntoa(peer.sin_addr), ntohs(peer.sin_port));
            break;
        }
    }

    uint64_t session = be64toh(rhdr->session);

    // Send HELLO_ACK with file info
    struct ft_hello *hello = (struct ft_hello*)(sendbuf + sizeof(struct ft_hdr));
    shdr->type = FT_HELLO_ACK;
    shdr->session = htobe64(session);
    hello->magic = htonl(FT_MAGIC);
    hello->version = htonl(FT_VERSION);
    hello->file_size = htobe64(fsize);
    hello->block = htonl(block);
    hello->nblocks = htonl(nblocks);

    for (int i = 0; i < 3; i++) {
        sendto(sock, sendbuf, sizeof(struct ft_hdr) + sizeof(struct ft_hello), 0,
               (struct sockaddr*)&peer, peerlen);
    }
    printf("Sent file info, starting transfer...\n");

    // Timestamp: first bit leaves sender
    struct timeval start, end;
    gettimeofday(&start, NULL);

    // Send all data blocks
    for (uint32_t i = 0; i < nblocks; i++) {
        shdr->type = FT_DATA;
        shdr->seq = htonl(i);
        shdr->session = htobe64(session);
        uint32_t len = (i == nblocks-1) ? (fsize - (uint64_t)i*block) : block;
        shdr->len = htons(len);
        memcpy(sendbuf + sizeof(struct ft_hdr), data + (uint64_t)i*block, len);
        sendto(sock, sendbuf, sizeof(struct ft_hdr) + len, 0, (struct sockaddr*)&peer, peerlen);
    }
    printf("Initial blast complete, handling retransmissions...\n");

    // Set timeout for receiving NACKs
    struct timeval tv = {0, 100000};
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    struct ft_range local_ranges[100];

    while (1) {
        int n = recvfrom(sock, recvbuf, FT_MAX_PACKET, 0, (struct sockaddr*)&peer, &peerlen);
        if (n <= 0) continue;

        if (rhdr->type == FT_NACK && be64toh(rhdr->session) == session) {
            struct ft_nack *nack = (struct ft_nack*)(recvbuf + sizeof(struct ft_hdr));
            struct ft_range *ranges = (struct ft_range*)(recvbuf + sizeof(struct ft_hdr) + sizeof(struct ft_nack));
            uint32_t nr = ntohl(nack->nranges);
            if (nr > 100) nr = 100;

            memcpy(local_ranges, ranges, nr * sizeof(struct ft_range));

            for (uint32_t r = 0; r < nr; r++) {
                uint32_t st = ntohl(local_ranges[r].start);
                uint32_t cnt = ntohl(local_ranges[r].count);
                for (uint32_t j = 0; j < cnt; j++) {
                    uint32_t seq = st + j;
                    if (seq >= nblocks) continue;
                    shdr->type = FT_DATA;
                    shdr->seq = htonl(seq);
                    shdr->session = htobe64(session);
                    uint32_t dlen = (seq == nblocks-1) ? (fsize - (uint64_t)seq*block) : block;
                    shdr->len = htons(dlen);
                    memcpy(sendbuf + sizeof(struct ft_hdr), data + (uint64_t)seq*block, dlen);
                    sendto(sock, sendbuf, sizeof(struct ft_hdr) + dlen, 0, (struct sockaddr*)&peer, peerlen);
                }
            }
        }
        else if (rhdr->type == FT_DONE && be64toh(rhdr->session) == session) {
            gettimeofday(&end, NULL);
            double secs = (end.tv_sec - start.tv_sec) + (end.tv_usec - start.tv_usec) / 1000000.0;

            // Verify MD5
            struct ft_done *done = (struct ft_done*)(recvbuf + sizeof(struct ft_hdr));
            int md5_match = (memcmp(local_md5, done->md5, 16) == 0);

            printf("\n========== TRANSFER COMPLETE ==========\n");
            printf("File: %s\n", filename);
            printf("Size: %lu bytes\n", (unsigned long)fsize);
            printf("Time: %.2f seconds\n", secs);
            printf("Throughput: %.2f Mbps\n", fsize * 8.0 / secs / 1000000);
            printf("MD5 Verification: %s\n", md5_match ? "PASSED" : "FAILED");
            printf("========================================\n");

            // Send FIN
            shdr->type = FT_FIN;
            shdr->session = htobe64(session);
            for (int i = 0; i < 3; i++) {
                sendto(sock, sendbuf, sizeof(struct ft_hdr), 0, (struct sockaddr*)&peer, peerlen);
            }
            break;
        }
    }

    free(sendbuf);
    free(recvbuf);
    free(data);
    close(sock);
    return 0;
}
