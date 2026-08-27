// EE542 Lab2 — round-based reliable UDP file transfer, shared definitions.
// Data over UDP (paced rounds); loss feedback = NAK seq-lists over UDP (x3);
// TCP used only for session setup and final confirmation.
#pragma once
#include <arpa/inet.h>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <string>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

static constexpr uint8_t MAGIC = 0x5A;
enum PktType : uint8_t { PT_DATA = 1, PT_END_ROUND = 2, PT_NAK = 3, PT_DONE = 4 };
enum TcpType : uint8_t { TT_HELLO = 1, TT_HELLO_ACK = 2, TT_DONE = 3 };

// UDP header, 8 bytes, network order on the wire.
struct PktHdr {
  uint32_t seq;
  uint16_t round;
  uint8_t type;
  uint8_t magic;
};
static_assert(sizeof(PktHdr) == 8, "PktHdr must be 8 bytes");

// NAK payload sub-header (after PktHdr): part_idx, part_cnt, count, then seqs[].
struct NakSub {
  uint32_t part_idx;
  uint32_t part_cnt;
  uint32_t count;
};
static_assert(sizeof(NakSub) == 12, "NakSub must be 12 bytes");

struct Hello {  // TCP payload of TT_HELLO
  uint64_t file_size;
  uint32_t payload_size;
  uint32_t total_blocks;
  uint8_t pad[8];
};

static inline uint64_t mono_ns() {
  timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (uint64_t)ts.tv_sec * 1000000000ull + ts.tv_nsec;
}
static inline uint64_t real_ns() {
  timespec ts;
  clock_gettime(CLOCK_REALTIME, &ts);
  return (uint64_t)ts.tv_sec * 1000000000ull + ts.tv_nsec;
}

static inline void die(const char *msg) {
  perror(msg);
  exit(1);
}

// ---- length-prefixed TCP messages: [u32 len][u8 type][payload] ----
static inline bool write_full(int fd, const void *buf, size_t n) {
  size_t off = 0;
  while (off < n) {
    ssize_t r = write(fd, (const char *)buf + off, n - off);
    if (r <= 0) {
      if (r < 0 && errno == EINTR) continue;
      return false;
    }
    off += (size_t)r;
  }
  return true;
}

static inline bool tcp_send_msg(int fd, uint8_t type, const void *payload, uint32_t plen) {
  uint32_t len = htonl(1 + plen);
  char hdr[5];
  memcpy(hdr, &len, 4);
  hdr[4] = (char)type;
  if (!write_full(fd, hdr, 5)) return false;
  if (plen && !write_full(fd, payload, plen)) return false;
  return true;
}

static inline bool read_full(int fd, void *buf, size_t n) {
  size_t off = 0;
  while (off < n) {
    ssize_t r = read(fd, (char *)buf + off, n - off);
    if (r <= 0) {
      if (r < 0 && errno == EINTR) continue;
      return false;
    }
    off += (size_t)r;
  }
  return true;
}

// Blocking receive of one TCP message. Returns false on EOF/error.
static inline bool tcp_recv_msg(int fd, uint8_t &type, std::vector<uint8_t> &payload) {
  uint32_t len_n;
  if (!read_full(fd, &len_n, 4)) return false;
  uint32_t len = ntohl(len_n);
  if (len < 1 || len > (64u << 20)) return false;
  if (!read_full(fd, &type, 1)) return false;
  payload.resize(len - 1);
  if (len > 1 && !read_full(fd, payload.data(), len - 1)) return false;
  return true;
}
