// EE542 Lab2 — LT fountain-code UDP file transfer ("ltr").
// Protocol: per 1000-packet block, send the sources verbatim (systematic pass)
// followed by loss-rate-adapted LT repair packets; receiver peels
// (belief-propagation decode) and reports a done-bitmap; sender tops up
// stragglers until the bitmap is full. TCP only for session setup + final DONE.
// Usage: ltr send <file> <dest_ip> [--port N] [--rate-mbps X] [--mtu N] [--loss p]
//        ltr recv <out_path>       [--port N]
#include "common.hpp"
#include <math.h>
#include <memory>
#include <poll.h>

static constexpr int LT_K = 1000;      // source packets per block
static constexpr double LT_C = 0.02;   // robust soliton c
static constexpr double LT_DELTA = 0.5;
static constexpr uint8_t LT_MAGIC = 0xA5;
enum LtType : uint8_t { LT_DATA = 1, LT_STATUS_REQ = 2, LT_STATUS = 3 };

// 12-byte UDP header, network order on the wire.
struct LtHdr {
  uint32_t block;
  uint32_t pkt_id;    // < LT_K: systematic source; >= LT_K: repair
  uint8_t type;
  uint8_t magic;
  uint16_t payload_len;
};
static_assert(sizeof(LtHdr) == 12, "LtHdr must be 12 bytes");

struct LtHello {      // TCP payload of TT_HELLO
  uint64_t file_size;
  uint32_t payload;   // padded payload bytes per packet (multiple of 8)
  uint32_t n_blocks;
  uint32_t loss_pm;   // channel loss estimate, per-mille (both sides need it
                      // to build identical repair degree tables)
  uint8_t pad[12];
};

// ---------------- degree distributions (identical on both sides) -----------
static double g_cdf[LT_K + 1];
static double g_repair_cdf[LT_K + 1];
static int g_repair_m = 0;
static double g_loss = 0.0;

static void build_soliton(double *cdf, int k, double c, double delta) {
  std::vector<double> p(k + 1);
  double S = c * log((double)k / delta) * sqrt((double)k);
  int spike = (int)round((double)k / S);
  if (spike < 1) spike = 1;
  if (spike > k) spike = k;
  double sum = 0.0;
  for (int d = 1; d <= k; d++) {
    double rho = (d == 1) ? 1.0 / k : 1.0 / ((double)d * (d - 1));
    double tau = 0.0;
    if (d < spike) tau = S / ((double)d * k);
    else if (d == spike) tau = S * log(S / delta) / k;
    p[d] = rho + tau;
    sum += p[d];
  }
  double acc = 0.0;
  for (int d = 1; d <= k; d++) { acc += p[d] / sum; cdf[d] = acc; }
  cdf[k] = 1.0;
}
static void build_tables(double loss) {
  g_loss = loss;
  build_soliton(g_cdf, LT_K, LT_C, LT_DELTA);
  if (loss > 0.0) {
    g_repair_m = (int)(1.3 * loss * LT_K + 2);
    if (g_repair_m > LT_K) g_repair_m = LT_K;
    build_soliton(g_repair_cdf, g_repair_m, LT_C, LT_DELTA);
  }
}
static inline double u01(uint64_t &s) { return (rng_next(s) >> 11) * (1.0 / 9007199254740992.0); }
static int cdf_sample(const double *cdf, int k, uint64_t &s) {
  double u = u01(s);
  int lo = 1, hi = k;
  while (lo < hi) { int mid = (lo + hi) / 2; if (cdf[mid] < u) lo = mid + 1; else hi = mid; }
  return lo;
}
// (block, pkt_id) -> neighbor list; pkt_id < LT_K is the source itself.
static int expand_neighbors(uint32_t block, uint32_t pkt_id, uint16_t *nbr) {
  if (pkt_id < LT_K) { nbr[0] = (uint16_t)pkt_id; return 1; }
  uint64_t s = ((uint64_t)block << 32 | pkt_id) * 0x9E3779B97F4A7C15ull + 1;
  rng_next(s);  // one warmup step
  int d;
  if (g_loss > 0.0) {
    int e = cdf_sample(g_repair_cdf, g_repair_m, s);
    d = (int)round((double)e / g_loss);
    if (d < 1) d = 1;
    if (d > LT_K) d = LT_K;
  } else {
    d = cdf_sample(g_cdf, LT_K, s);
  }
  for (int i = 0; i < d; i++) {
    bool redo;
    do {
      nbr[i] = (uint16_t)(rng_next(s) % LT_K);
      redo = false;
      for (int j = 0; j < i; j++)
        if (nbr[j] == nbr[i]) { redo = true; break; }
    } while (redo);
  }
  return d;
}

static inline void xor_buf(uint8_t *dst, const uint8_t *src, uint32_t len) {
  uint64_t *a = (uint64_t *)dst;
  const uint64_t *b = (const uint64_t *)src;
  for (uint32_t i = 0; i < len / 8; i++) a[i] ^= b[i];
}

// ---------------- sender ---------------------------------------------------
struct LtSendCfg {
  std::string file, dest;
  int port = 5555;
  double rate_mbps = 97.0;
  int mtu = 1500;
  double loss = 0.0;
};

struct LtPacer {
  // Group-paced variant of ftr's Pacer: one clock check per ~3 packets
  // (cheaper under TCG emulation), and the catch-up credit is capped at one
  // group (~4.5KB) so a burst never overflows tbf's 9015-byte bucket.
  double bits_per_ns;
  uint64_t next = 0;
  uint32_t acc = 0;
  static constexpr uint32_t GROUP_BYTES = 4488;  // ~3 MTU-1500 packets
  explicit LtPacer(double rate_bps) : bits_per_ns(rate_bps / 1e9) {}
  void pace(uint32_t wire_bytes) {
    acc += wire_bytes;
    if (acc < GROUP_BYTES) return;
    uint64_t group_ns = (uint64_t)((double)acc * 8.0 / bits_per_ns);
    acc = 0;
    uint64_t now = mono_ns();
    if (next == 0) next = now;
    if (next + group_ns < now) next = now - group_ns;  // credit <= one group
    if (next > now) {
      uint64_t wait = next - now;
      if (wait > 60000) {
        timespec ts{(time_t)0, (long)(wait - 30000)};
        nanosleep(&ts, nullptr);
      }
      while (mono_ns() < next) {}
    }
    next += group_ns;
  }
};

static int lt_tcp_connect(const std::string &ip, int port) {
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

int run_lt_sender(LtSendCfg cfg) {
  uint32_t raw = (uint32_t)cfg.mtu - 20 - 8 - sizeof(LtHdr);
  const uint32_t payload = raw & ~7u;  // multiple of 8 for the XOR loop
  build_tables(cfg.loss);

  int ffd = open(cfg.file.c_str(), O_RDONLY);
  if (ffd < 0) die("open file");
  struct stat st;
  if (fstat(ffd, &st) != 0) die("fstat");
  uint64_t fsize = (uint64_t)st.st_size;
  if (fsize == 0) die("empty file");
  uint8_t *fmap = (uint8_t *)mmap(nullptr, fsize, PROT_READ, MAP_PRIVATE, ffd, 0);
  if (fmap == MAP_FAILED) die("mmap");
  uint64_t block_bytes = (uint64_t)payload * LT_K;
  uint32_t n_blocks = (uint32_t)((fsize + block_bytes - 1) / block_bytes);

  int tfd = lt_tcp_connect(cfg.dest, cfg.port);
  LtHello h{};
  h.file_size = fsize;
  h.payload = payload;
  h.n_blocks = n_blocks;
  h.loss_pm = (uint32_t)(cfg.loss * 1000.0 + 0.5);
  if (!tcp_send_msg(tfd, TT_HELLO, &h, sizeof h)) die("hello send");
  uint8_t mt;
  std::vector<uint8_t> mp;
  if (!tcp_recv_msg(tfd, mt, mp) || mt != TT_HELLO_ACK) die("hello ack");

  int ufd = socket(AF_INET, SOCK_DGRAM, 0);
  if (ufd < 0) die("socket udp");
  int sndbuf = 8 << 20;
  setsockopt(ufd, SOL_SOCKET, SO_SNDBUF, &sndbuf, sizeof sndbuf);
  sockaddr_in ua{};
  ua.sin_family = AF_INET;
  ua.sin_port = htons(cfg.port);
  inet_pton(AF_INET, cfg.dest.c_str(), &ua.sin_addr);
  if (connect(ufd, (sockaddr *)&ua, sizeof ua) != 0) die("udp connect");

  fprintf(stderr, "[ltr-send] file=%llu B blocks=%u payload=%u rate=%.1f loss=%.3f\n",
          (unsigned long long)fsize, n_blocks, payload, cfg.rate_mbps, cfg.loss);

  LtPacer pacer(cfg.rate_mbps * 1e6);
  std::vector<uint8_t> pkt(sizeof(LtHdr) + payload);
  std::vector<uint8_t> tailbuf(payload, 0);  // zero-padded last real packet
  std::vector<uint8_t> encbuf(payload);
  std::vector<uint32_t> next_repair(n_blocks, LT_K);
  std::vector<bool> done(n_blocks, false);
  uint32_t undone = n_blocks;
  uint64_t total_sent = 0, t_first_real = 0, t0 = 0;

  auto kreal_of = [&](uint32_t b) -> uint32_t {
    uint64_t off = (uint64_t)b * block_bytes;
    uint64_t rem = fsize - off;
    uint64_t kr = (rem + payload - 1) / payload;
    return kr > LT_K ? LT_K : (uint32_t)kr;
  };
  // pointer to (padded) source packet s of block b, or NULL for virtual zeros
  auto src_ptr = [&](uint32_t b, uint32_t s) -> const uint8_t * {
    uint64_t off = (uint64_t)b * block_bytes + (uint64_t)s * payload;
    if (off >= fsize) return nullptr;
    if (off + payload <= fsize) return fmap + off;
    memset(tailbuf.data(), 0, payload);
    memcpy(tailbuf.data(), fmap + off, (size_t)(fsize - off));
    return tailbuf.data();
  };
  auto stamp_first = [&]() {
    if (total_sent == 0) {
      t_first_real = real_ns();
      t0 = mono_ns();
      printf("T_FIRST_BIT_NS %llu\n", (unsigned long long)t_first_real);
      fflush(stdout);
    }
  };
  auto udp_send = [&](uint32_t len) {
    while (send(ufd, pkt.data(), sizeof(LtHdr) + len, 0) < 0) {
      if (errno == ENOBUFS || errno == EAGAIN || errno == ECONNREFUSED) {
        usleep(200);
        continue;
      }
      die("send data");
    }
    total_sent++;
  };
  auto send_source = [&](uint32_t b, uint32_t s) {
    uint64_t off = (uint64_t)b * block_bytes + (uint64_t)s * payload;
    uint32_t blen = (uint32_t)((off + payload <= fsize) ? payload : fsize - off);
    LtHdr *ph = (LtHdr *)pkt.data();
    ph->block = htonl(b);
    ph->pkt_id = htonl(s);
    ph->type = LT_DATA;
    ph->magic = LT_MAGIC;
    ph->payload_len = htons((uint16_t)blen);
    memcpy(pkt.data() + sizeof(LtHdr), fmap + off, blen);
    pacer.pace(blen + 40);  // IP20+UDP8+hdr12+payload, as seen by tbf
    stamp_first();
    udp_send(blen);
  };
  auto send_repair = [&](uint32_t b) {
    uint32_t pid = next_repair[b]++;
    uint16_t nbr[LT_K];
    int d = expand_neighbors(b, pid, nbr);
    memset(encbuf.data(), 0, payload);
    for (int i = 0; i < d; i++) {
      const uint8_t *sp = src_ptr(b, nbr[i]);
      if (sp) xor_buf(encbuf.data(), sp, payload);
    }
    LtHdr *ph = (LtHdr *)pkt.data();
    ph->block = htonl(b);
    ph->pkt_id = htonl(pid);
    ph->type = LT_DATA;
    ph->magic = LT_MAGIC;
    ph->payload_len = htons((uint16_t)payload);
    memcpy(pkt.data() + sizeof(LtHdr), encbuf.data(), payload);
    pacer.pace(payload + 40);
    stamp_first();
    udp_send(payload);
  };
  auto drain_status = [&]() {
    uint8_t rbuf[4096];
    for (;;) {
      ssize_t n = recv(ufd, rbuf, sizeof rbuf, MSG_DONTWAIT);
      if (n < (ssize_t)sizeof(LtHdr)) break;
      LtHdr *ph = (LtHdr *)rbuf;
      if (ph->magic != LT_MAGIC || ph->type != LT_STATUS) continue;
      uint32_t nb = ntohl(ph->block);
      if (nb != n_blocks) continue;
      const uint8_t *bm = rbuf + sizeof(LtHdr);
      uint32_t bytes = (n_blocks + 7) / 8;
      if ((size_t)n < sizeof(LtHdr) + bytes) continue;
      for (uint32_t b = 0; b < n_blocks; b++)
        if (!done[b] && ((bm[b >> 3] >> (b & 7)) & 1)) { done[b] = true; undone--; }
    }
  };

  // ---- main stream: systematic pass + proactive repair, block by block ----
  double margin = (cfg.loss > 0) ? (cfg.loss + std::max(0.03, 0.5 * cfg.loss)) / (1.0 - cfg.loss) : 0.0;
  for (uint32_t b = 0; b < n_blocks; b++) {
    uint32_t kr = kreal_of(b);
    for (uint32_t s = 0; s < kr; s++) send_source(b, s);
    uint32_t r = (uint32_t)ceil((double)kr * margin);
    for (uint32_t j = 0; j < r; j++) send_repair(b);
    if ((b & 7) == 0) drain_status();
    if (b % 100 == 99)
      fprintf(stderr, "[ltr-send] block %u/%u t=%.1fs undone=%u\n", b + 1, n_blocks,
              (mono_ns() - t0) / 1e9, undone);
  }
  drain_status();
  fprintf(stderr, "[ltr-send] STREAM_DONE t=%.1fs sent=%llu undone=%u\n",
          (mono_ns() - t0) / 1e9, (unsigned long long)total_sent, undone);

  // ---- cleanup: poll status, top up stragglers until bitmap full ----------
  uint32_t status_seq = 0;
  uint64_t deadline = mono_ns() + 600ull * 1000000000ull;
  auto tcp_done = [&]() -> bool {
    pollfd pf{tfd, POLLIN, 0};
    if (poll(&pf, 1, 0) > 0 && (pf.revents & POLLIN)) {
