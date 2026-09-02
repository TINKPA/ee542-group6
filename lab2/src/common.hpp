// EE542 Lab2 — shared transport layer for all transfer methods.
//
// One binary (`ftr`) hosts several send/receive strategies that all sit on the
// same chassis: a paced UDP data plane, a TCP control channel for session
// setup + final confirmation, a receiver-side arrival bitmap, and identical
// timing/stat output. A "method" is a (sender policy, receiver policy) pair;
// the only thing that varies between methods is how the set of blocks still to
// send is narrowed (never / per-packet ACK / per-round NACK / lockstep).
//
// NOTE ON THE WIRE FORMAT: this uses the 8-byte PktHdr the working protocol
// ships (and that the report documents: 1464 B payload + 8 B header at MTU
// 1500). include/protocol.h holds an earlier, richer frozen contract (16-byte
// header, session ids) that was never implemented; reconciling the two is a
// group decision and is deliberately NOT done here.
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

// UDP data-plane packet types. PT_DATA/PT_DONE are shared by every method;
// PT_END_ROUND/PT_NAK are NAK-only; PT_ACK is used by ack + stopwait.
enum PktType : uint8_t {
  PT_DATA = 1,
  PT_END_ROUND = 2,
  PT_NAK = 3,
  PT_DONE = 4,
  PT_ACK = 5,
};
enum TcpType : uint8_t { TT_HELLO = 1, TT_HELLO_ACK = 2, TT_DONE = 3 };

// Transfer methods, negotiated in the HELLO so the receiver auto-selects its
// half — the bench never has to configure both ends and cannot mismatch them.
enum Method : uint8_t {
  M_NAK = 0,        // paper protocol: paced blast + per-round batched NAK
  M_CAROUSEL = 1,   // blindest baseline: loop the whole file, no feedback
  M_ACK = 2,        // per-packet ACK, sender drops acked blocks (naive "big-window TCP")
  M_STOPWAIT = 3,   // window = 1: send one, wait one ACK, timeout-resend
  M_FOUNTAIN = 4,   // reserved for the LT fountain-code line (ltr.cpp)
};
static inline const char *method_name(uint8_t m) {
  switch (m) {
    case M_NAK: return "nak";
    case M_CAROUSEL: return "carousel";
    case M_ACK: return "ack";
    case M_STOPWAIT: return "stopwait";
    case M_FOUNTAIN: return "fountain";
    default: return "?";
  }
}
static inline int method_from_name(const std::string &s) {
  if (s == "nak") return M_NAK;
  if (s == "carousel") return M_CAROUSEL;
  if (s == "ack") return M_ACK;
  if (s == "stopwait") return M_STOPWAIT;
  if (s == "fountain") return M_FOUNTAIN;
  return -1;
}

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
  uint8_t method;    // enum Method — receiver dispatches on this
  uint8_t pad[7];
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

// ---- bitmap helpers ----
struct Bitmap {
  std::vector<uint64_t> w;
  uint32_t nbits = 0;
  uint32_t set_cnt = 0;
  void init(uint32_t n) {
    nbits = n;
    w.assign((n + 63) / 64, 0);
    set_cnt = 0;
  }
  bool test(uint32_t i) const { return (w[i >> 6] >> (i & 63)) & 1; }
  void set(uint32_t i) {
    if (!test(i)) {
      w[i >> 6] |= 1ull << (i & 63);
      set_cnt++;
    }
  }
  bool full() const { return set_cnt == nbits; }
  void missing_list(std::vector<uint32_t> &out) const {
    out.clear();
    for (uint32_t i = 0; i < nbits; i++)
      if (!test(i)) out.push_back(i);
  }
};

static inline uint64_t rng_next(uint64_t &s) {  // xorshift64* for --drop simulation
  s ^= s >> 12;
  s ^= s << 25;
  s ^= s >> 27;
  return s * 0x2545F4914F6CDD1Dull;
}

// ---- rate pacing ----
// Meter DATA out at a target wire rate. Credit is capped at ~1ms so a stall
// never releases a burst big enough to overflow tbf's shallow token bucket.
// (Lifted verbatim from the working NAK sender so every method paces the same.)
struct Pacer {
  double bits_per_ns;
  uint64_t next = 0;
  explicit Pacer(double rate_bps) : bits_per_ns(rate_bps / 1e9) {}
  void pace(uint32_t wire_bytes) {
    uint64_t now = mono_ns();
    if (next == 0) next = now;
    if (next < now - 1000000ull) next = now - 1000000ull;
    if (next > now) {
      uint64_t wait = next - now;
      if (wait > 60000) {
        timespec ts{(time_t)0, (long)(wait - 30000)};
        nanosleep(&ts, nullptr);
      }
      while (mono_ns() < next) { /* spin the tail */ }
    }
    next += (uint64_t)((double)wire_bytes * 8.0 / bits_per_ns);
  }
};

// Bytes seen by the router's tbf shaper per DATA packet: IP(20)+UDP(8)+PktHdr(8).
static constexpr uint32_t WIRE_OH = 36;

// ---- session handshake (TCP control + UDP data on one port) ----
// Shared by every method so the control plane is identical and the UDP
// bind-before-HELLO_ACK ordering (which prevents the first data packets from
// racing the bind into ECONNREFUSED) is guaranteed in one place.
struct Session {
  int tfd = -1;   // TCP control
  int ufd = -1;   // UDP data
  int port = 0;
  // negotiated in HELLO:
  uint64_t fsize = 0;
  uint32_t payload = 0;
  uint32_t nblocks = 0;
  uint8_t method = M_NAK;
  // receiver learns the sender's UDP address from the first packet:
  sockaddr_in peer{};
  socklen_t peer_len = 0;
  bool have_peer = false;
};

static inline int tcp_connect_retry(const std::string &ip, int port) {
  int fd = socket(AF_INET, SOCK_STREAM, 0);
  if (fd < 0) die("socket tcp");
  int one = 1;
  setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
  sockaddr_in a{};
  a.sin_family = AF_INET;
  a.sin_port = htons(port);
  if (inet_pton(AF_INET, ip.c_str(), &a.sin_addr) != 1) die("inet_pton");
  for (int tries = 0;; tries++) {
    if (connect(fd, (sockaddr *)&a, sizeof a) == 0) break;
    if (tries > 120) die("connect");
    usleep(500 * 1000);
  }
  return fd;
}

// Sender side: connect TCP, announce the session, connect the UDP socket so
// control replies (NAK/ACK/DONE) return on it.
static inline Session sess_connect(const std::string &dest, int port, uint8_t method,
                                   uint64_t fsize, uint32_t payload, uint32_t nblocks) {
  Session s;
  s.port = port;
  s.method = method;
  s.fsize = fsize;
  s.payload = payload;
  s.nblocks = nblocks;
  s.tfd = tcp_connect_retry(dest, port);
  Hello h{};
  h.file_size = fsize;
  h.payload_size = payload;
  h.total_blocks = nblocks;
  h.method = method;
  if (!tcp_send_msg(s.tfd, TT_HELLO, &h, sizeof h)) die("hello send");
  uint8_t mt;
  std::vector<uint8_t> mp;
  if (!tcp_recv_msg(s.tfd, mt, mp) || mt != TT_HELLO_ACK) die("hello ack");
  s.ufd = socket(AF_INET, SOCK_DGRAM, 0);
  if (s.ufd < 0) die("socket udp");
  int sndbuf = 8 << 20;
  setsockopt(s.ufd, SOL_SOCKET, SO_SNDBUF, &sndbuf, sizeof sndbuf);
  sockaddr_in ua{};
  ua.sin_family = AF_INET;
  ua.sin_port = htons(port);
  inet_pton(AF_INET, dest.c_str(), &ua.sin_addr);
  if (connect(s.ufd, (sockaddr *)&ua, sizeof ua) != 0) die("udp connect");
  return s;
}

// Receiver side: accept TCP, read the HELLO, bind UDP BEFORE acking, then ack.
static inline Session sess_accept(int port) {
  Session s;
  s.port = port;
  int lfd = socket(AF_INET, SOCK_STREAM, 0);
  if (lfd < 0) die("socket tcp");
  int one = 1;
  setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
  sockaddr_in a{};
  a.sin_family = AF_INET;
  a.sin_addr.s_addr = INADDR_ANY;
  a.sin_port = htons(port);
  if (bind(lfd, (sockaddr *)&a, sizeof a) != 0) die("bind tcp");
  if (listen(lfd, 1) != 0) die("listen");
  fprintf(stderr, "[recv] listening on %d ...\n", port);
  s.tfd = accept(lfd, nullptr, nullptr);
  if (s.tfd < 0) die("accept");
  setsockopt(s.tfd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
  close(lfd);

  uint8_t mt;
  std::vector<uint8_t> mp;
  if (!tcp_recv_msg(s.tfd, mt, mp) || mt != TT_HELLO || mp.size() < sizeof(Hello))
    die("hello");
  Hello h;
  memcpy(&h, mp.data(), sizeof h);
  s.fsize = h.file_size;
  s.payload = h.payload_size;
  s.nblocks = h.total_blocks;
  s.method = h.method;

  // UDP bound on the same port, BEFORE HELLO_ACK — see comment above.
  s.ufd = socket(AF_INET, SOCK_DGRAM, 0);
  if (s.ufd < 0) die("socket udp");
  int rcvbuf = 32 << 20;
  setsockopt(s.ufd, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof rcvbuf);
  if (bind(s.ufd, (sockaddr *)&a, sizeof a) != 0) die("bind udp");

  if (!tcp_send_msg(s.tfd, TT_HELLO_ACK, nullptr, 0)) die("hello ack send");
  return s;
}

// ---- shared timing/stat output (the contract the bench harness greps) ----
// Sender: T_FIRST_BIT_NS on the first byte out; SENDER_ELAPSED_S / TOTAL_PKTS /
// ROUNDS at the end. Receiver: T_LAST_BIT_NS / RECV_SPAN_S at completion.
static inline void emit_first_bit(uint64_t t_first_real) {
  printf("T_FIRST_BIT_NS %llu\n", (unsigned long long)t_first_real);
  fflush(stdout);
}
static inline void emit_sender_stats(double elapsed_s, uint64_t total_pkts, uint32_t rounds) {
  printf("SENDER_ELAPSED_S %.6f\nTOTAL_PKTS %llu\nROUNDS %u\n", elapsed_s,
         (unsigned long long)total_pkts, rounds);
  fflush(stdout);
}
static inline void emit_last_bit(uint64_t t_last_real, double recv_span_s) {
  printf("T_LAST_BIT_NS %llu\nRECV_SPAN_S %.6f\n", (unsigned long long)t_last_real,
         recv_span_s);
  fflush(stdout);
}

// ---- method entry points (one send + one recv per method) ----
struct SendCfg {
  std::string file, dest;
  int port = 5555;
  double rate_mbps = 97.0;
  int mtu = 1500;
  uint8_t method = M_NAK;
};
struct RecvCfg {
  std::string out;
  int port = 5555;
  double drop = 0.0;  // debug-only loss simulation for local (loopback) testing
};

int nak_send(const SendCfg &);
int nak_recv(const RecvCfg &, Session &);
int carousel_send(const SendCfg &);
int carousel_recv(const RecvCfg &, Session &);
int ack_send(const SendCfg &);
int stopwait_send(const SendCfg &);
int ack_recv(const RecvCfg &, Session &);  // shared by M_ACK and M_STOPWAIT
