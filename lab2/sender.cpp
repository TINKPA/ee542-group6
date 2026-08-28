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

int run_sender(SendCfg cfg) {
  const uint32_t payload = (uint32_t)cfg.mtu - 20 - 8 - sizeof(PktHdr);
  // open + mmap file
  int ffd = open(cfg.file.c_str(), O_RDONLY);
  if (ffd < 0) die("open file");
  struct stat st;
  if (fstat(ffd, &st) != 0) die("fstat");
  uint64_t fsize = (uint64_t)st.st_size;
  if (fsize == 0) die("empty file");
  uint8_t *fmap = (uint8_t *)mmap(nullptr, fsize, PROT_READ, MAP_PRIVATE, ffd, 0);
  if (fmap == MAP_FAILED) die("mmap");
  uint32_t N = (uint32_t)((fsize + payload - 1) / payload);

  // control TCP
  int tfd = tcp_connect(cfg.dest, cfg.port);
  Hello h{};
  h.file_size = fsize;
  h.payload_size = payload;
  h.total_blocks = N;
  if (!tcp_send_msg(tfd, TT_HELLO, &h, sizeof h)) die("hello send");
  uint8_t mt;
  std::vector<uint8_t> mp;
  if (!tcp_recv_msg(tfd, mt, mp) || mt != TT_HELLO_ACK) die("hello ack");

  // data UDP (connected — NAKs come back on same socket)
  int ufd = socket(AF_INET, SOCK_DGRAM, 0);
  if (ufd < 0) die("socket udp");
  int sndbuf = 4 << 20;
  setsockopt(ufd, SOL_SOCKET, SO_SNDBUF, &sndbuf, sizeof sndbuf);
  sockaddr_in ua{};
  ua.sin_family = AF_INET;
  ua.sin_port = htons(cfg.port);
  inet_pton(AF_INET, cfg.dest.c_str(), &ua.sin_addr);
  if (connect(ufd, (sockaddr *)&ua, sizeof ua) != 0) die("udp connect");

  fprintf(stderr, "[send] file=%s size=%llu blocks=%u payload=%u rate=%.1fMbps\n",
          cfg.file.c_str(), (unsigned long long)fsize, N, payload, cfg.rate_mbps);

  Pacer pacer(cfg.rate_mbps * 1e6);
  std::vector<uint8_t> pkt(sizeof(PktHdr) + payload);
  std::vector<uint32_t> missing(N);
  for (uint32_t i = 0; i < N; i++) missing[i] = i;
  uint64_t total_sent = 0;
  uint64_t t_first_real = 0, t0 = 0;
  bool done = false;
  uint16_t round = 1;

  auto send_block = [&](uint32_t seq) {
    uint32_t blen = payload;
    if (seq == N - 1) blen = (uint32_t)(fsize - (uint64_t)(N - 1) * payload);
    PktHdr *ph = (PktHdr *)pkt.data();
    ph->seq = htonl(seq);
    ph->round = htons(round);
    ph->type = PT_DATA;
    ph->magic = MAGIC;
    memcpy(pkt.data() + sizeof(PktHdr), fmap + (uint64_t)seq * payload, blen);
    pacer.pace(blen + 36);  // IP(20)+UDP(8)+hdr(8)+payload counted by tbf
    if (total_sent == 0) {
      t_first_real = real_ns();
      t0 = mono_ns();
      printf("T_FIRST_BIT_NS %llu\n", (unsigned long long)t_first_real);
      fflush(stdout);
    }
    while (send(ufd, pkt.data(), sizeof(PktHdr) + blen, 0) < 0) {
      if (errno == ENOBUFS || errno == EAGAIN || errno == ECONNREFUSED) {
        usleep(200);
        continue;
      }
      die("send data");
    }
    total_sent++;
  };

  auto tcp_poll_done = [&]() -> bool {  // nonblocking peek for early DONE
    pollfd pf{tfd, POLLIN, 0};
    if (poll(&pf, 1, 0) > 0 && (pf.revents & POLLIN)) {
      uint8_t t;
      std::vector<uint8_t> p;
      if (!tcp_recv_msg(tfd, t, p)) die("tcp eof");
      if (t == TT_DONE) return true;
    }
    return false;
  };

  // round loop: blast missing blocks, collect NAK feedback over UDP
  std::vector<uint8_t> rbuf(65536);
  while (!done) {
    fprintf(stderr, "[send] round %u: sending %zu blocks\n", round, missing.size());
    for (size_t k = 0; k < missing.size(); k++) send_block(missing[k]);
    // end-of-round handshake, retry until NAK set or DONE
    bool have_feedback = false;
    std::set<uint32_t> parts_seen;
    uint32_t part_cnt = 0;
    std::vector<uint32_t> next_missing;
    for (int attempt = 0; attempt < 40 && !have_feedback && !done; attempt++) {
      PktHdr er{};
      er.seq = 0;
      er.round = htons(round);
      er.type = PT_END_ROUND;
      er.magic = MAGIC;
      for (int i = 0; i < 5; i++) {
        send(ufd, &er, sizeof er, 0);
        usleep(3000);
      }
      uint64_t deadline = mono_ns() + 400ull * 1000 * 1000;  // 400ms window
      uint64_t idle_after_first = 120ull * 1000 * 1000;
      uint64_t last_rx = 0;
      while (mono_ns() < deadline) {
        pollfd pf{ufd, POLLIN, 0};
        int pr = poll(&pf, 1, 20);
        if (tcp_poll_done()) {
          done = true;
          break;
        }
        if (pr <= 0) {
          if (last_rx && mono_ns() - last_rx > idle_after_first) break;
          continue;
        }
        ssize_t n = recv(ufd, rbuf.data(), rbuf.size(), 0);
        if (n < (ssize_t)sizeof(PktHdr)) continue;
        PktHdr *ph = (PktHdr *)rbuf.data();
        if (ph->magic != MAGIC) continue;
        if (ph->type == PT_DONE) {
          done = true;
          break;
        }
        if (ph->type != PT_NAK || ntohs(ph->round) != round) continue;
        NakSub *ns = (NakSub *)(rbuf.data() + sizeof(PktHdr));
        uint32_t pi = ntohl(ns->part_idx), pc = ntohl(ns->part_cnt), cnt = ntohl(ns->count);
        part_cnt = pc;
        last_rx = mono_ns();
        if (parts_seen.insert(pi).second) {
          uint32_t *seqs = (uint32_t *)(rbuf.data() + sizeof(PktHdr) + sizeof(NakSub));
          for (uint32_t i = 0; i < cnt; i++) next_missing.push_back(ntohl(seqs[i]));
        }
        if (parts_seen.size() == part_cnt) break;  // complete set
      }
      if (!done && !next_missing.empty()) have_feedback = true;
    }
    if (done) break;
    if (!have_feedback) die("no NAK feedback after retries");
    if (parts_seen.size() < part_cnt)
      fprintf(stderr, "[send] round %u: NAK parts %zu/%u (lost parts roll to next round)\n",
              round, parts_seen.size(), part_cnt);
    missing.swap(next_missing);
    round++;
  }
