// EE542 Lab2 — receiver ("client saves the file" / scp-like destination side).
// Usage: ftr recv <out_path> [--port N] [--drop p]
#include "common.hpp"
#include <poll.h>

struct RecvCfg {
  std::string out;
  int port = 5555;
  double drop = 0.0;  // debug-only loss simulation for local testing
};

int run_receiver(int argc, char **argv) {
  RecvCfg cfg;
  cfg.out = argv[2];
  for (int i = 3; i < argc; i++) {
    std::string a = argv[i];
    auto next = [&]() -> const char * {
      if (i + 1 >= argc) {
        fprintf(stderr, "missing arg value\n");
        exit(2);
      }
      return argv[++i];
    };
    if (a == "--port") cfg.port = atoi(next());
    else if (a == "--drop") cfg.drop = atof(next());
    else {
      fprintf(stderr, "unknown arg %s\n", a.c_str());
      exit(2);
    }
  }

  // TCP listen
  int lfd = socket(AF_INET, SOCK_STREAM, 0);
  if (lfd < 0) die("socket");
  int one = 1;
  setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
  sockaddr_in a{};
  a.sin_family = AF_INET;
  a.sin_addr.s_addr = INADDR_ANY;
  a.sin_port = htons(cfg.port);
  if (bind(lfd, (sockaddr *)&a, sizeof a) != 0) die("bind tcp");
  if (listen(lfd, 1) != 0) die("listen");
  fprintf(stderr, "[recv] listening on %d ...\n", cfg.port);
  int tfd = accept(lfd, nullptr, nullptr);
  if (tfd < 0) die("accept");
  setsockopt(tfd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);

  uint8_t mt;
  std::vector<uint8_t> mp;
  if (!tcp_recv_msg(tfd, mt, mp) || mt != TT_HELLO || mp.size() < sizeof(Hello)) die("hello");
  Hello h;
  memcpy(&h, mp.data(), sizeof h);
  const uint64_t fsize = h.file_size;
  const uint32_t payload = h.payload_size, N = h.total_blocks;
  // UDP bound on same port — MUST be bound before HELLO_ACK, or the sender's
  // first packets race the bind (ICMP unreachable -> ECONNREFUSED on loopback).
  int ufd = socket(AF_INET, SOCK_DGRAM, 0);
  if (ufd < 0) die("socket udp");
  int rcvbuf = 8 << 20;
  setsockopt(ufd, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof rcvbuf);
  if (bind(ufd, (sockaddr *)&a, sizeof a) != 0) die("bind udp");

  if (!tcp_send_msg(tfd, TT_HELLO_ACK, nullptr, 0)) die("hello ack");
  fprintf(stderr, "[recv] size=%llu blocks=%u payload=%u drop=%.3f\n",
          (unsigned long long)fsize, N, payload, cfg.drop);

  // output file mmap
  int ffd = open(cfg.out.c_str(), O_RDWR | O_CREAT | O_TRUNC, 0644);
  if (ffd < 0) die("open out");
  if (ftruncate(ffd, (off_t)fsize) != 0) die("ftruncate");
  uint8_t *fmap = (uint8_t *)mmap(nullptr, fsize, PROT_WRITE | PROT_READ, MAP_SHARED, ffd, 0);
  if (fmap == MAP_FAILED) die("mmap out");

  Bitmap bm;
  bm.init(N);
  sockaddr_in peer{};
  socklen_t peer_len = 0;
  bool have_peer = false;
  uint64_t t_first = 0, t_last_real = 0, t_first_mono = 0, t_last_mono = 0;
  uint64_t rng = 0x9E3779B97F4A7C15ull ^ real_ns();
  std::vector<uint8_t> buf(65536), pkt(65536);
  std::vector<uint32_t> mlist;
  uint16_t last_round_answered = 0;
  uint64_t last_answer_t = 0;
  bool done_announced = false;
  uint32_t rounds_seen = 0;
