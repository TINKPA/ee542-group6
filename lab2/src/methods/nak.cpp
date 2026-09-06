// EE542 Lab2 — method: paced blast + per-round batched NAK (the paper protocol).
//
// Data plane: UDP paced at the known line rate, never slowed by loss. Control
// plane: after each round the receiver sends its missing-sequence list; the
// sender retransmits exactly those. The transfer ends when the bitmap is full,
// so zero-error delivery is structural. TCP carries only setup + final DONE.
//
// This is sender.cpp + receiver.cpp from the original two-file build, moved
// under the multi-method chassis unchanged except for the shared Session
// handshake. Logic is preserved verbatim — it is what produces the reported
// numbers.
#include "../common.hpp"
#include <poll.h>
#include <set>

// ---------------------------------------------------------------- sender ----
int nak_send(const SendCfg &cfg) {
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

  Session s = sess_connect(cfg.dest, cfg.port, M_NAK, fsize, payload, N);
  int ufd = s.ufd, tfd = s.tfd;

  fprintf(stderr, "[nak-send] file=%s size=%llu blocks=%u payload=%u rate=%.1fMbps\n",
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
    fprintf(stderr, "[nak-send] round %u: sending %zu blocks\n", round, missing.size());
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
      fprintf(stderr, "[nak-send] round %u: NAK parts %zu/%u (lost parts roll to next round)\n",
              round, parts_seen.size(), part_cnt);
    missing.swap(next_missing);
    round++;
  }

  double el = (mono_ns() - t0) / 1e9;
  fprintf(stderr, "[nak-send] DONE rounds=%u total_pkts=%llu elapsed=%.3fs\n",
          round, (unsigned long long)total_sent, el);
  emit_sender_stats(el, total_sent, round);
  close(tfd);
  close(ufd);
  munmap(fmap, fsize);
  close(ffd);
  return 0;
}

// -------------------------------------------------------------- receiver ----
int nak_recv(const RecvCfg &cfg, Session &s) {
  const uint64_t fsize = s.fsize;
  const uint32_t payload = s.payload, N = s.nblocks;
  int ufd = s.ufd, tfd = s.tfd;

  fprintf(stderr, "[nak-recv] size=%llu blocks=%u payload=%u drop=%.3f\n",
          (unsigned long long)fsize, N, payload, cfg.drop);

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
    fprintf(stderr, "[nak-recv] COMPLETE rounds_seen=%u span=%.3fs\n", rounds_seen,
            (t_last_mono - t_first_mono) / 1e9);
  };
  auto send_naks = [&](uint16_t round) {
    bm.missing_list(mlist);
    rounds_seen = round;
    fprintf(stderr, "[nak-recv] round %u end: missing=%zu\n", round, mlist.size());
    const uint32_t per = (payload - sizeof(NakSub)) / 4;
    const uint32_t parts = (uint32_t)((mlist.size() + per - 1) / per);
    for (int copy = 0; copy < 3; copy++) {
      for (uint32_t pi = 0; pi < parts; pi++) {
        uint32_t beg = pi * per;
        uint32_t cnt = (uint32_t)std::min<size_t>(per, mlist.size() - beg);
        PktHdr *ph = (PktHdr *)pkt.data();
        ph->seq = 0;
        ph->round = htons(round);
        ph->type = PT_NAK;
        ph->magic = MAGIC;
        NakSub *ns = (NakSub *)(pkt.data() + sizeof(PktHdr));
        ns->part_idx = htonl(pi);
        ns->part_cnt = htonl(parts);
        ns->count = htonl(cnt);
        uint32_t *seqs = (uint32_t *)(pkt.data() + sizeof(PktHdr) + sizeof(NakSub));
        for (uint32_t i = 0; i < cnt; i++) seqs[i] = htonl(mlist[beg + i]);
        sendto(ufd, pkt.data(), sizeof(PktHdr) + sizeof(NakSub) + cnt * 4, 0,
               (sockaddr *)&peer, peer_len);
      }
    }
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
      if (ph->magic != MAGIC) continue;
      if (!have_peer) {
        peer = from;
        peer_len = flen;
        have_peer = true;
      }
      if (ph->type == PT_DATA) {
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
            announce_done();
          }
        }
      } else if (ph->type == PT_END_ROUND) {
        uint16_t round = ntohs(ph->round);
        if (bm.full()) {
          send_done_udp();
          continue;
        }
        uint64_t now = mono_ns();
        if (round == last_round_answered && now - last_answer_t < 200ull * 1000 * 1000)
          continue;  // duplicate marker within window
        last_round_answered = round;
        last_answer_t = now;
        send_naks(round);
      }
    }
    if (pfds[1].revents & (POLLIN | POLLHUP)) {
      uint8_t t;
      std::vector<uint8_t> p;
      if (!tcp_recv_msg(tfd, t, p)) {
        if (done_announced) break;
        fprintf(stderr, "[nak-recv] tcp closed before completion\n");
        break;
      }
    }
    if (done_announced) {
      static uint64_t done_at = 0;
      if (!done_at) done_at = mono_ns();
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
