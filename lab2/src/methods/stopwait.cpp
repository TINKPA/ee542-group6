// EE542 Lab2 — baseline: stop-and-wait (window = 1).
//
// The textbook rdt3.0 lower bound: send one block, wait for its ACK, resend on
// timeout, then move to the next. Reliable and trivially correct, but the pipe
// is empty for a whole RTT per block, so on a 200 ms link it delivers on the
// order of a few blocks per second and 1 GiB takes days — the "correct but no
// pipelining" corner, the mirror image of carousel. Measure its steady-state
// rate over a short window (or a small file) and extrapolate; running it to
// completion on Case 2 is not practical, which is exactly the point.
//
// Receiver side is ack_recv (ACK every DATA, DONE when the bitmap fills).
#include "../common.hpp"
#include <poll.h>

int stopwait_send(const SendCfg &cfg) {
  const uint32_t payload = (uint32_t)cfg.mtu - 20 - 8 - sizeof(PktHdr);
  int ffd = open(cfg.file.c_str(), O_RDONLY);
  if (ffd < 0) die("open file");
  struct stat st;
  if (fstat(ffd, &st) != 0) die("fstat");
  uint64_t fsize = (uint64_t)st.st_size;
  if (fsize == 0) die("empty file");
  uint8_t *fmap = (uint8_t *)mmap(nullptr, fsize, PROT_READ, MAP_PRIVATE, ffd, 0);
  if (fmap == MAP_FAILED) die("mmap");
  uint32_t N = (uint32_t)((fsize + payload - 1) / payload);

  Session s = sess_connect(cfg.dest, cfg.port, M_STOPWAIT, fsize, payload, N);
  int ufd = s.ufd, tfd = s.tfd;
  (void)tfd;

  fprintf(stderr, "[stopwait-send] size=%llu blocks=%u payload=%u\n",
          (unsigned long long)fsize, N, payload);

  std::vector<uint8_t> pkt(sizeof(PktHdr) + payload);
  std::vector<uint8_t> rbuf(4096);
  uint64_t total_sent = 0;
  uint64_t t_first_real = 0, t0 = 0;
  const uint64_t TIMEOUT_NS = 1000ull * 1000 * 1000;  // > worst-case RTT (200ms)

  auto send_block = [&](uint32_t seq) {
    uint32_t blen = payload;
    if (seq == N - 1) blen = (uint32_t)(fsize - (uint64_t)(N - 1) * payload);
    PktHdr *ph = (PktHdr *)pkt.data();
    ph->seq = htonl(seq);
    ph->round = 0;
    ph->type = PT_DATA;
    ph->magic = MAGIC;
    memcpy(pkt.data() + sizeof(PktHdr), fmap + (uint64_t)seq * payload, blen);
    if (total_sent == 0) {
      t_first_real = real_ns();
      t0 = mono_ns();
      emit_first_bit(t_first_real);
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

  // Wait for ACK(want): 1 = acked, 0 = timeout (resend), -1 = receiver DONE.
  auto wait_ack = [&](uint32_t want) -> int {
    uint64_t deadline = mono_ns() + TIMEOUT_NS;
    while (mono_ns() < deadline) {
      pollfd pf{ufd, POLLIN, 0};
      int pr = poll(&pf, 1, 20);
      if (pr <= 0) continue;
      ssize_t n = recv(ufd, rbuf.data(), rbuf.size(), 0);
      if (n < (ssize_t)sizeof(PktHdr)) continue;
      PktHdr *ph = (PktHdr *)rbuf.data();
      if (ph->magic != MAGIC) continue;
      if (ph->type == PT_DONE) return -1;
      if (ph->type == PT_ACK && ntohl(ph->seq) == want) return 1;
    }
    return 0;
  };

  uint64_t retransmits = 0;
  for (uint32_t seq = 0; seq < N; seq++) {
    for (;;) {
      send_block(seq);
      int r = wait_ack(seq);
      if (r == 1) break;
      if (r == -1) { seq = N; break; }  // receiver has everything, stop
      retransmits++;                    // timeout: resend the same block
    }
    if ((seq & 8191) == 0)
      fprintf(stderr, "[stopwait-send] seq %u/%u t=%.1fs retx=%llu\n", seq, N,
              (mono_ns() - t0) / 1e9, (unsigned long long)retransmits);
  }

  double el = (mono_ns() - t0) / 1e9;
  fprintf(stderr, "[stopwait-send] DONE total_pkts=%llu retx=%llu elapsed=%.3fs\n",
          (unsigned long long)total_sent, (unsigned long long)retransmits, el);
  emit_sender_stats(el, total_sent, 1);
  close(tfd);
  close(ufd);
  munmap(fmap, fsize);
  close(ffd);
  return 0;
}
