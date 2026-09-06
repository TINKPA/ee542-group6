// EE542 Lab2 — ftr: fast reliable transfer, one binary, several methods.
//
//   ftr send <file> <dest_ip> [--method M] [--port N] [--rate-mbps X] [--mtu N]
//   ftr recv <out_path>        [--port N] [--drop p]
//
// Methods (M): nak (default, the paper protocol), carousel, ack, stopwait.
// The receiver does NOT take --method: it reads the method from the sender's
// HELLO and dispatches its matching half, so the two ends can never mismatch.
#include "common.hpp"

static void usage() {
  fprintf(stderr,
          "usage: ftr send <file> <dest_ip> [--method nak|carousel|ack|stopwait]\n"
          "                                 [--port N] [--rate-mbps X] [--mtu N]\n"
          "       ftr recv <out_path>       [--port N] [--drop p]\n");
  exit(2);
}

static int run_recv(int argc, char **argv) {
  RecvCfg c;
  c.out = argv[2];
  for (int i = 3; i < argc; i++) {
    std::string a = argv[i];
    auto next = [&]() -> const char * {
      if (i + 1 >= argc) usage();
      return argv[++i];
    };
    if (a == "--port") c.port = atoi(next());
    else if (a == "--drop") c.drop = atof(next());
    else usage();
  }
  // Handshake first, then dispatch on the negotiated method.
  Session s = sess_accept(c.port);
  fprintf(stderr, "[recv] method=%s\n", method_name(s.method));
  switch (s.method) {
    case M_NAK: return nak_recv(c, s);
    case M_CAROUSEL: return carousel_recv(c, s);
    case M_ACK:
    case M_STOPWAIT: return ack_recv(c, s);
    default:
      fprintf(stderr, "[recv] unsupported method %u\n", s.method);
      return 2;
  }
}

static int run_send(int argc, char **argv) {
  SendCfg c;
  c.file = argv[2];
  c.dest = argv[3];
  for (int i = 4; i < argc; i++) {
    std::string a = argv[i];
    auto next = [&]() -> const char * {
      if (i + 1 >= argc) usage();
      return argv[++i];
    };
    if (a == "--method") {
      int m = method_from_name(next());
      if (m < 0) usage();
      c.method = (uint8_t)m;
    } else if (a == "--port") c.port = atoi(next());
    else if (a == "--rate-mbps") c.rate_mbps = atof(next());
    else if (a == "--mtu") c.mtu = atoi(next());
    else usage();
  }
  switch (c.method) {
    case M_NAK: return nak_send(c);
    case M_CAROUSEL: return carousel_send(c);
    case M_ACK: return ack_send(c);
    case M_STOPWAIT: return stopwait_send(c);
    default:
      fprintf(stderr, "[send] unsupported method %u\n", c.method);
      return 2;
  }
}

int main(int argc, char **argv) {
  if (argc < 3) usage();
  std::string mode = argv[1];
  if (mode == "recv") return run_recv(argc, argv);
  if (mode == "send" && argc >= 4) return run_send(argc, argv);
  usage();
}
