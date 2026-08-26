/* FROZEN v1 (group decision 2026-08-26): do not change unilaterally. */
/*
 * EE 542 Lab 2 - wire format contract.
 *
 * FREEZE THIS FIRST. The sender owner and receiver owner both include this
 * file and must not change it unilaterally. Any change is a group decision,
 * because it breaks the other side.
 *
 * Design: blast + NACK rounds.
 *   The sender paces DATA out at a target rate and never waits for an ACK.
 *   The receiver tracks arrivals in a bitmap and periodically reports what
 *   is still missing. The sender retransmits those, and the loop repeats
 *   until the bitmap is full.
 *
 * The rule that matters: loss NEVER reduces the send rate. In Case 2 the 20%
 * loss is random, not congestion, so backing off is pure lost throughput.
 * Rate is controlled by queue delay and receiver-reported goodput instead.
 *
 * All multi-byte fields are network byte order (big endian).
 */

#ifndef EE542_PROTOCOL_H
#define EE542_PROTOCOL_H

#include <stdint.h>

#define FT_MAGIC        0x45453542u   /* "EE5B" - sanity check in HELLO */
#define FT_VERSION      1

/* Payload sizing. Chosen so a DATA packet never fragments.
 *   MTU 1500 -> 1500 - 20 (IP) - 8 (UDP) - 16 (ft_hdr) = 1456
 *   MTU 9001 -> 9001 - 20 - 8 - 16                      = 8957
 * Both sides must agree on FT_BLOCK for a session; it is announced in HELLO
 * so the receiver can size its bitmap before any DATA arrives. */
#define FT_BLOCK_1500   1456
#define FT_BLOCK_9001   8957
#define FT_BLOCK_MAX    FT_BLOCK_9001

/* Packet types */
enum ft_type {
    FT_HELLO      = 1,   /* sender -> receiver: begin session, file metadata */
    FT_HELLO_ACK  = 2,   /* receiver -> sender: ready, echoes session id      */
    FT_DATA       = 3,   /* sender -> receiver: one block                     */
    FT_NACK       = 4,   /* receiver -> sender: missing ranges + rate report  */
    FT_DONE       = 5,   /* receiver -> sender: bitmap full, md5 enclosed     */
    FT_FIN        = 6,   /* sender -> receiver: acknowledge DONE, close       */
};

/* 16 byte fixed header on every packet. */
struct ft_hdr {
    uint8_t  type;       /* enum ft_type                                     */
    uint8_t  flags;      /* reserved, must be 0                              */
    uint16_t len;        /* payload bytes following this header              */
    uint32_t seq;        /* DATA: block index. control: message counter      */
    uint64_t session;    /* random per transfer, rejects stale/crossed pkts  */
} __attribute__((packed));

/* FT_HELLO payload. Retransmit until HELLO_ACK arrives - it can be dropped. */
struct ft_hello {
    uint32_t magic;      /* FT_MAGIC                                         */
    uint32_t version;    /* FT_VERSION                                       */
    uint64_t file_size;  /* bytes                                            */
    uint32_t block;      /* payload bytes per DATA packet                    */
    uint32_t nblocks;    /* ceil(file_size / block)                          */
    uint32_t name_len;   /* bytes of filename following this struct          */
} __attribute__((packed));

/* One run of missing blocks. Ranges beat individual ids: after a loss burst
 * the gaps are contiguous, so this stays small even with 20% loss. */
struct ft_range {
    uint32_t start;      /* first missing block index                        */
    uint32_t count;      /* how many consecutive blocks are missing          */
} __attribute__((packed));

/*
 * FT_NACK payload: this header, then nranges * struct ft_range.
 *
 * Carries COMPLETE current state, not events. A lost NACK then costs one
 * round trip instead of losing a block forever - which matters because the
 * 20% loss is bidirectional and hits this path too. Send each NACK 3x.
 */
struct ft_nack {
    uint32_t nranges;      /* ft_range entries following                     */
    uint32_t highest_seq;  /* highest block index seen so far                */
    uint64_t bytes_recvd;  /* unique payload bytes stored                    */
    uint32_t goodput_bps;  /* receiver-measured rate since last NACK, /1000  */
    uint32_t rtt_us;       /* receiver's RTT estimate, 0 if unknown          */
} __attribute__((packed));

/* FT_DONE payload: the receiver's md5 of the reassembled file. The sender
 * compares against its own and reports match/mismatch on stdout. */
struct ft_done {
    uint64_t bytes_total;
    uint8_t  md5[16];
} __attribute__((packed));

/* Sizing helpers */
#define FT_HDR_SIZE     ((int)sizeof(struct ft_hdr))
#define FT_MAX_PACKET   (FT_HDR_SIZE + FT_BLOCK_MAX)

/* Tunables the sender owns. Starting points, not final values - Thursday is
 * for measuring these, not guessing them. */
#define FT_NACK_INTERVAL_MS   50    /* receiver NACK cadence                 */
#define FT_NACK_REPEAT        3     /* redundant copies, loss on return path */
#define FT_HELLO_RETRY_MS     200
#define FT_SOCKBUF_BYTES      (16 * 1024 * 1024)
/* ^ Also raise the kernel ceiling or setsockopt is silently clamped:
 *     sudo sysctl -w net.core.rmem_max=16777216
 *     sudo sysctl -w net.core.wmem_max=16777216
 *   Skipping this makes the kernel drop packets at the receiver, and it
 *   looks exactly like network loss. Most common way to lose a day here. */

#endif /* EE542_PROTOCOL_H */
