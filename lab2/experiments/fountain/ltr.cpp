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
