// EE542 Lab2 — baseline: per-packet ACK ("naive big-window UDP-TCP").
//
// What TCP collapses to on a point-to-point link once congestion control is
// gone and the window is effectively infinite: keep blasting at line rate, ACK
// every block, and let the sender drop a block the moment its ACK arrives.
// There is no window and no round barrier — the sender just cycles the set of
// still-unacked blocks. Its waste has two sources, both measurable: an ACK
// lost on the (equally lossy) reverse path, and an ACK still in flight when the
// sender loops back — either way the block is sent again needlessly. It marks
// the "pipe full, precise per-packet feedback, but feedback is continuous and
// costs a reverse packet each" corner.
//
// ack_recv is shared with stopwait (both just: write, set, ACK every DATA,
// DONE when the bitmap fills).
#include "../common.hpp"
#include <poll.h>

// ---------------------------------------------------------------- sender ----
int ack_send(const SendCfg &cfg) {
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

  Session s = sess_connect(cfg.dest, cfg.port, M_ACK, fsize, payload, N);
  int ufd = s.ufd, tfd = s.tfd;

  fprintf(stderr, "[ack-send] size=%llu blocks=%u payload=%u rate=%.1fMbps\n",
          (unsigned long long)fsize, N, payload, cfg.rate_mbps);

  Pacer pacer(cfg.rate_mbps * 1e6);
  std::vector<uint8_t> pkt(sizeof(PktHdr) + payload);
  Bitmap acked;
  acked.init(N);
  uint64_t total_sent = 0;
  uint64_t t_first_real = 0, t0 = 0;
  bool done = false;
  uint16_t pass = 0;
  std::vector<uint8_t> rbuf(65536);

  auto send_block = [&](uint32_t seq) {
    uint32_t blen = payload;
    if (seq == N - 1) blen = (uint32_t)(fsize - (uint64_t)(N - 1) * payload);
    PktHdr *ph = (PktHdr *)pkt.data();
    ph->seq = htonl(seq);
    ph->round = htons(pass);
    ph->type = PT_DATA;
    ph->magic = MAGIC;
    memcpy(pkt.data() + sizeof(PktHdr), fmap + (uint64_t)seq * payload, blen);
    pacer.pace(blen + WIRE_OH);
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

  // Drain all pending ACKs (and any DONE) without blocking.
  auto drain = [&]() {
    for (;;) {
      ssize_t n = recv(ufd, rbuf.data(), rbuf.size(), MSG_DONTWAIT);
      if (n < (ssize_t)sizeof(PktHdr)) break;
      PktHdr *ph = (PktHdr *)rbuf.data();
      if (ph->magic != MAGIC) continue;
      if (ph->type == PT_ACK) {
        uint32_t seq = ntohl(ph->seq);
        if (seq < N) acked.set(seq);
      } else if (ph->type == PT_DONE) {
        done = true;
      }
    }
  };
  auto tcp_done = [&]() -> bool {
    pollfd pf{tfd, POLLIN, 0};
    if (poll(&pf, 1, 0) > 0 && (pf.revents & POLLIN)) {
      uint8_t t;
      std::vector<uint8_t> p;
      if (!tcp_recv_msg(tfd, t, p)) return true;
      if (t == TT_DONE) return true;
    }
    return false;
  };

  while (!done && !acked.full()) {
    for (uint32_t seq = 0; seq < N && !done; seq++) {
      if (acked.test(seq)) continue;
      send_block(seq);
      if ((total_sent & 15) == 0) {
        drain();
        if (done || acked.full() || tcp_done()) { done = true; break; }
      }
    }
    drain();
    if (acked.full() || tcp_done()) break;
    // let the last in-flight ACKs land before another full pass
    pollfd pf{ufd, POLLIN, 0};
    if (poll(&pf, 1, 50) > 0) drain();
    pass++;
  }

  double el = (mono_ns() - t0) / 1e9;
  fprintf(stderr, "[ack-send] DONE passes=%u total_pkts=%llu acked=%u/%u elapsed=%.3fs\n",
          pass + 1, (unsigned long long)total_sent, acked.set_cnt, N, el);
  emit_sender_stats(el, total_sent, pass + 1);
  close(tfd);
  close(ufd);
  munmap(fmap, fsize);
  close(ffd);
  return 0;
}

// ------------------------------------ receiver (shared: ack + stopwait) ----
int ack_recv(const RecvCfg &cfg, Session &s) {
  const uint64_t fsize = s.fsize;
  const uint32_t payload = s.payload, N = s.nblocks;
  int ufd = s.ufd, tfd = s.tfd;

  fprintf(stderr, "[%s-recv] size=%llu blocks=%u payload=%u drop=%.3f\n",
          method_name(s.method), (unsigned long long)fsize, N, payload, cfg.drop);

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
  std::vector<uint8_t> buf(65536);
  bool done_announced = false;

  auto send_ack = [&](uint32_t seq) {
    if (!have_peer) return;
    PktHdr a{};
    a.seq = htonl(seq);
    a.type = PT_ACK;
    a.magic = MAGIC;
    sendto(ufd, &a, sizeof a, 0, (sockaddr *)&peer, peer_len);
  };
  auto send_done_udp = [&]() {
    if (!have_peer) return;
    PktHdr d{};
    d.type = PT_DONE;
    d.magic = MAGIC;
    for (int i = 0; i < 5; i++) {
      sendto(ufd, &d, sizeof d, 0, (sockaddr *)&peer, peer_len);
      usleep(2000);
    }
  };
  auto announce_done = [&]() {
    if (done_announced) return;
    done_announced = true;
    emit_last_bit(t_last_real, (t_last_mono - t_first_mono) / 1e9);
    uint64_t tn = t_last_real;
    tcp_send_msg(tfd, TT_DONE, &tn, sizeof tn);
    send_done_udp();
    fprintf(stderr, "[%s-recv] COMPLETE span=%.3fs\n", method_name(s.method),
            (t_last_mono - t_first_mono) / 1e9);
  };

  pollfd pfds[2] = {{ufd, POLLIN, 0}, {tfd, POLLIN, 0}};
  while (true) {
    int pr = poll(pfds, 2, 1000);
    if (pr < 0) {
      if (errno == EINTR) continue;
      die("poll");
    }
    if (pfds[0].revents & POLLIN) {
      sockaddr_in from{};
      socklen_t flen = sizeof from;
      ssize_t n = recvfrom(ufd, buf.data(), buf.size(), 0, (sockaddr *)&from, &flen);
      if (n < (ssize_t)sizeof(PktHdr)) continue;
      PktHdr *ph = (PktHdr *)buf.data();
      if (ph->magic != MAGIC || ph->type != PT_DATA) continue;
      if (!have_peer) {
        peer = from;
        peer_len = flen;
        have_peer = true;
      }
      if (cfg.drop > 0 && (double)(rng_next(rng) >> 11) / 9007199254740992.0 < cfg.drop)
        continue;  // simulated loss (debug)
      uint32_t seq = ntohl(ph->seq);
      if (seq >= N) continue;
      uint32_t blen = (seq == N - 1) ? (uint32_t)(fsize - (uint64_t)(N - 1) * payload) : payload;
      if (n < (ssize_t)(sizeof(PktHdr) + blen)) continue;
      if (t_first == 0) {
        t_first = real_ns();
        t_first_mono = mono_ns();
      }
      if (!bm.test(seq)) {
        memcpy(fmap + (uint64_t)seq * payload, buf.data() + sizeof(PktHdr), blen);
        bm.set(seq);
        if (bm.full()) {
          t_last_real = real_ns();
          t_last_mono = mono_ns();
        }
      }
      // ACK every DATA, including duplicates: a resend replaces a lost ACK.
      send_ack(seq);
      if (bm.full()) announce_done();
    }
    if (pfds[1].revents & (POLLIN | POLLHUP)) {
      uint8_t t;
      std::vector<uint8_t> p;
      if (!tcp_recv_msg(tfd, t, p)) {
        if (done_announced) break;
        fprintf(stderr, "[%s-recv] tcp closed before completion\n", method_name(s.method));
        break;
      }
    }
    if (done_announced) {
      static uint64_t done_at = 0;
      if (!done_at) done_at = mono_ns();
      send_done_udp();
      if (mono_ns() - done_at > 1500ull * 1000 * 1000) break;
    }
  }

  msync(fmap, fsize, MS_SYNC);
  munmap(fmap, fsize);
  close(ffd);
  close(tfd);
  close(ufd);
  return done_announced ? 0 : 1;
}
