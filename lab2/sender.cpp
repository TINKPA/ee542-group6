// EE542 Lab2 — sender ("server part sends the file" / scp-like source side).
// Usage: ftr send <file> <dest_ip> [--port N] [--rate-mbps X] [--mtu N]
#include "common.hpp"
#include <poll.h>
#include <set>

struct SendCfg {
  std::string file, dest;
  int port = 5555;
  double rate_mbps = 97.0;  // wire rate target (IP bytes), keep < tbf rate
  int mtu = 1500;
};

static int tcp_connect(const std::string &ip, int port) {
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
    fprintf(stderr, "[send] connect retry (%s)\n", strerror(errno));
    usleep(500 * 1000);
  }
  return fd;
}

struct Pacer {
  double bits_per_ns;
  uint64_t next = 0;
  explicit Pacer(double rate_bps) : bits_per_ns(rate_bps / 1e9) {}
  void pace(uint32_t wire_bytes) {
    uint64_t now = mono_ns();
    if (next == 0) next = now;
    // never accumulate more than 1ms of "credit" — bursts overflow tbf
    if (next < now - 1000000ull) next = now - 1000000ull;
    if (next > now) {
      uint64_t wait = next - now;
      if (wait > 60000) {
        timespec ts{(time_t)0, (long)(wait - 30000)};
        nanosleep(&ts, nullptr);
      }
      while (mono_ns() < next) { /* spin the tail */
      }
    }
    next += (uint64_t)((double)wire_bytes * 8.0 / bits_per_ns);  // ns per packet
  }
};
