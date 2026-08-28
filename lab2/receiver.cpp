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
