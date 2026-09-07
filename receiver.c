/*
 * receiver.c - Fast reliable file transfer (receiver/client)
 * Connects to sender and saves file to specified location
 *
 * Usage: ./receiver <sender_ip>:<port> <output_file>
 * Example: ./receiver 10.200.1.83:5000 received.bin
 *
 * Similar to: scp user@host:file local_path
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <sys/time.h>
#include <openssl/md5.h>
#include "protocol.h"

#define BIT_SET(bm, n) (bm[(n)/8] |= (1 << ((n)%8)))
#define BIT_GET(bm, n) ((bm[(n)/8] >> ((n)%8)) & 1)

void compute_md5(const uint8_t *data, uint64_t len, uint8_t *out) {
    MD5_CTX ctx;
    MD5_Init(&ctx);
    MD5_Update(&ctx, data, len);
    MD5_Final(out, &ctx);
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <sender_ip>:<port> <output_file>\n", argv[0]);
        fprintf(stderr, "Example: %s 10.200.1.83:5000 received.bin\n", argv[0]);
        return 1;
    }

    // Parse IP:port
    char *addr_str = strdup(argv[1]);
    char *colon = strchr(addr_str, ':');
    if (!colon) {
        fprintf(stderr, "Error: Invalid address format. Use IP:port\n");
        return 1;
    }
    *colon = '\0';
    char *ip = addr_str;
    int port = atoi(colon + 1);
    char *output_file = argv[2];

    printf("Connecting to %s:%d\n", ip, port);
    printf("Output file: %s\n", output_file);

    // Create socket
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    int bufsize = FT_SOCKBUF_BYTES;
    setsockopt(sock, SOL_SOCKET, SO_SNDBUF, &bufsize, sizeof(bufsize));
    setsockopt(sock, SOL_SOCKET, SO_RCVBUF, &bufsize, sizeof(bufsize));

    struct sockaddr_in peer;
    memset(&peer, 0, sizeof(peer));
    peer.sin_family = AF_INET;
    peer.sin_port = htons(port);
    inet_pton(AF_INET, ip, &peer.sin_addr);

    socklen_t peerlen = sizeof(peer);
    uint64_t session = time(NULL) ^ getpid();

    uint8_t *rxbuf = malloc(FT_MAX_PACKET);
    uint8_t *txbuf = malloc(FT_MAX_PACKET);
    struct ft_hdr *rxhdr = (struct ft_hdr*)rxbuf;
    struct ft_hdr *txhdr = (struct ft_hdr*)txbuf;

    // Send HELLO to initiate connection
    txhdr->type = FT_HELLO;
    txhdr->session = htobe64(session);

    struct timeval tv = {1, 0};
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    printf("Sending connection request...\n");

    uint64_t fsize = 0;
    uint32_t block = 0;
    uint32_t nblocks = 0;

    // Wait for HELLO_ACK with file info
    int got_info = 0;
    for (int i = 0; i < 10 && !got_info; i++) {
        sendto(sock, txbuf, sizeof(struct ft_hdr), 0, (struct sockaddr*)&peer, peerlen);
        int n = recvfrom(sock, rxbuf, FT_MAX_PACKET, 0, (struct sockaddr*)&peer, &peerlen);
        if (n > 0 && rxhdr->type == FT_HELLO_ACK && be64toh(rxhdr->session) == session) {
            struct ft_hello *hello = (struct ft_hello*)(rxbuf + sizeof(struct ft_hdr));
            fsize = be64toh(hello->file_size);
            block = ntohl(hello->block);
            nblocks = ntohl(hello->nblocks);
            got_info = 1;
            printf("Connected! Receiving %lu bytes (%u blocks, block_size=%u)\n",
                   (unsigned long)fsize, nblocks, block);
        }
    }

    if (!got_info) {
        fprintf(stderr, "Error: Could not connect to sender\n");
        return 1;
    }

    // Allocate memory
    uint8_t *filedata = calloc(1, fsize);
    uint8_t *bitmap = calloc(1, (nblocks + 7) / 8);
    if (!filedata || !bitmap) {
        fprintf(stderr, "Error: Out of memory\n");
        return 1;
    }
    int received = 0;

    // Timestamp: receiving starts
    struct timeval start, now, last_nack;
    gettimeofday(&start, NULL);
    last_nack = start;

    // Set short timeout for receiving
    tv.tv_sec = 0;
    tv.tv_usec = 10000;
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    // Receive data
    while (received < (int)nblocks) {
        int n = recvfrom(sock, rxbuf, FT_MAX_PACKET, 0, (struct sockaddr*)&peer, &peerlen);

        if (n > (int)sizeof(struct ft_hdr) && rxhdr->type == FT_DATA && be64toh(rxhdr->session) == session) {
            uint32_t seq = ntohl(rxhdr->seq);
            uint16_t len = ntohs(rxhdr->len);
            if (seq < nblocks && !BIT_GET(bitmap, seq)) {
                uint64_t offset = (uint64_t)seq * block;
                if (offset + len <= fsize) {
                    memcpy(filedata + offset, rxbuf + sizeof(struct ft_hdr), len);
                    BIT_SET(bitmap, seq);
                    received++;
                }
            }
        }

        // Send NACK periodically
        gettimeofday(&now, NULL);
        long ms = (now.tv_sec - last_nack.tv_sec) * 1000 + (now.tv_usec - last_nack.tv_usec) / 1000;
        if (ms >= FT_NACK_INTERVAL_MS && received < (int)nblocks) {
            struct ft_nack *nack = (struct ft_nack*)(txbuf + sizeof(struct ft_hdr));
            struct ft_range *ranges = (struct ft_range*)(txbuf + sizeof(struct ft_hdr) + sizeof(struct ft_nack));
            int nr = 0;

            for (uint32_t i = 0; i < nblocks && nr < 100; ) {
                while (i < nblocks && BIT_GET(bitmap, i)) i++;
                if (i >= nblocks) break;
                uint32_t st = i;
                while (i < nblocks && !BIT_GET(bitmap, i)) i++;
                ranges[nr].start = htonl(st);
                ranges[nr].count = htonl(i - st);
                nr++;
            }

            txhdr->type = FT_NACK;
            txhdr->session = htobe64(session);
            nack->nranges = htonl(nr);
            nack->highest_seq = htonl(received > 0 ? received - 1 : 0);
            nack->bytes_recvd = htobe64((uint64_t)received * block);

            // Send NACK multiple times for reliability
            for (int i = 0; i < FT_NACK_REPEAT; i++) {
                sendto(sock, txbuf, sizeof(struct ft_hdr) + sizeof(struct ft_nack) + nr * sizeof(struct ft_range),
                       0, (struct sockaddr*)&peer, peerlen);
            }
            last_nack = now;
            printf("\rProgress: %d/%u (%.1f%%)", received, nblocks, 100.0 * received / nblocks);
            fflush(stdout);
        }
    }

    // Timestamp: last bit received
    gettimeofday(&now, NULL);
    double secs = (now.tv_sec - start.tv_sec) + (now.tv_usec - start.tv_usec) / 1000000.0;

    // Compute MD5
    uint8_t file_md5[16];
    compute_md5(filedata, fsize, file_md5);

    printf("\n\n========== TRANSFER COMPLETE ==========\n");
    printf("File: %s\n", output_file);
    printf("Size: %lu bytes\n", (unsigned long)fsize);
    printf("Time: %.2f seconds\n", secs);
    printf("Throughput: %.2f Mbps\n", fsize * 8.0 / secs / 1000000);
    printf("MD5: ");
    for (int i = 0; i < 16; i++) printf("%02x", file_md5[i]);
    printf("\n");
    printf("========================================\n");

    // Save file
    FILE *fp = fopen(output_file, "wb");
    if (!fp) {
        fprintf(stderr, "Error: Cannot create output file: %s\n", output_file);
        return 1;
    }
    fwrite(filedata, 1, fsize, fp);
    fclose(fp);
    printf("File saved: %s\n", output_file);

    // Send DONE with MD5
    txhdr->type = FT_DONE;
    txhdr->session = htobe64(session);
    struct ft_done *done = (struct ft_done*)(txbuf + sizeof(struct ft_hdr));
    done->bytes_total = htobe64(fsize);
    memcpy(done->md5, file_md5, 16);

    for (int i = 0; i < 5; i++) {
        sendto(sock, txbuf, sizeof(struct ft_hdr) + sizeof(struct ft_done), 0, (struct sockaddr*)&peer, peerlen);
        usleep(10000);
    }

    // Wait for FIN
    tv.tv_sec = 2;
    tv.tv_usec = 0;
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    recvfrom(sock, rxbuf, FT_MAX_PACKET, 0, (struct sockaddr*)&peer, &peerlen);

    free(filedata);
    free(bitmap);
    free(rxbuf);
    free(txbuf);
    free(addr_str);
    close(sock);

    return 0;
}
