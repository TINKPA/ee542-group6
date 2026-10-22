// EE542 Lab 8 Part 4: receive image chunks with DPDK and rebuild the images.
//
//   sudo ./dpdk_rx -l 0 --no-huge -m 512 --no-pci
//     --vdev 'net_pcap0,rx_pcap=images.pcap,tx_pcap=/dev/null'
//     -- frames_rx.bin [--port 5000] [--idle-ms 500] [--expect 16]
//
// Every packet is checked layer by layer: Ethernet type IPv4, IPv4 version 4 /
// header length / protocol UDP / not a fragment / lengths consistent, UDP
// destination port, then our 22-byte chunk header (magic, seq < nseg,
// offset + length within frame_bytes). Anything else is counted and dropped.
// Chunks are copied straight to their offset in the frame buffer, so any
// arrival order works; a per-frame bitmap of received seq numbers rejects
// duplicates. A frame is complete when all nseg chunks have arrived.
//
// End of input: the pcap PMD gives no end-of-file signal; rx_burst just keeps
// returning 0. We stop when (a) --expect N frames are complete, or (b) no
// packet has arrived for --idle-ms after at least one packet was seen.
// Complete frames are written to the output file in frame_id order.
#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <rte_byteorder.h>
#include <rte_cycles.h>
#include <rte_eal.h>
#include <rte_ethdev.h>
#include <rte_ether.h>
#include <rte_ip.h>
#include <rte_mbuf.h>
#include <rte_udp.h>

#define MAGIC 0xEE542008u
#define MAX_FRAMES 1024
#define MAX_FRAME_BYTES (16u << 20)
#define BURST 32

struct chunk_hdr {          // all fields big-endian on the wire
  uint32_t magic, frame_id;
  uint16_t seq, nseg;
  uint32_t offset;
  uint16_t length;
  uint32_t frame_bytes;
} __attribute__((packed));
_Static_assert(sizeof(struct chunk_hdr) == 22, "chunk header must be 22 bytes");

struct frame {
  bool used, done;
  uint32_t id, bytes;
  uint16_t nseg, got;
  uint8_t *data;
  uint8_t *seen;            // bitmap, nseg bits
};

static struct frame frames[MAX_FRAMES];
static struct {
  uint64_t rx, accepted, dup, not_ipv4, bad_ip, not_udp, ip_frag, other_port,
      short_pl, bad_magic, bad_hdr, inconsistent, no_slot;
} st;

static struct frame *lookup(uint32_t id, uint32_t bytes, uint16_t nseg) {
  struct frame *free_slot = NULL;
  for (int i = 0; i < MAX_FRAMES; i++) {
    if (frames[i].used && frames[i].id == id) return &frames[i];
    if (!frames[i].used && !free_slot) free_slot = &frames[i];
  }
  if (!free_slot) return NULL;
  struct frame *f = free_slot;
  f->data = calloc(1, bytes);
  f->seen = calloc((nseg + 7) / 8, 1);
  if (!f->data || !f->seen) rte_exit(EXIT_FAILURE, "out of memory\n");
  f->used = true; f->id = id; f->bytes = bytes; f->nseg = nseg;
  return f;
}

static void handle(const uint8_t *pkt, uint32_t len, uint16_t want_port) {
  st.rx++;
  if (len < sizeof(struct rte_ether_hdr)) { st.not_ipv4++; return; }
  const struct rte_ether_hdr *eth = (const void *)pkt;
  if (eth->ether_type != rte_cpu_to_be_16(RTE_ETHER_TYPE_IPV4)) { st.not_ipv4++; return; }

  const uint8_t *l3 = pkt + sizeof(*eth);
  uint32_t l3len = len - sizeof(*eth);
  if (l3len < sizeof(struct rte_ipv4_hdr)) { st.bad_ip++; return; }
  const struct rte_ipv4_hdr *ip = (const void *)l3;
  uint32_t ihl = (ip->version_ihl & 0x0f) * 4u;
  uint32_t tot = rte_be_to_cpu_16(ip->total_length);
  if ((ip->version_ihl >> 4) != 4 || ihl < 20 || tot < ihl || tot > l3len) { st.bad_ip++; return; }
  if (ip->next_proto_id != IPPROTO_UDP) { st.not_udp++; return; }
  // MF set or a non-zero fragment offset: a piece of a bigger datagram.
  if (rte_be_to_cpu_16(ip->fragment_offset) & (RTE_IPV4_HDR_MF_FLAG | RTE_IPV4_HDR_OFFSET_MASK)) { st.ip_frag++; return; }

  if (tot - ihl < sizeof(struct rte_udp_hdr)) { st.bad_ip++; return; }
  const struct rte_udp_hdr *udp = (const void *)(l3 + ihl);
  uint32_t ulen = rte_be_to_cpu_16(udp->dgram_len);
  if (ulen < sizeof(*udp) || ulen > tot - ihl) { st.bad_ip++; return; }
  if (rte_be_to_cpu_16(udp->dst_port) != want_port) { st.other_port++; return; }

  const uint8_t *pl = (const uint8_t *)(udp + 1);
  uint32_t pllen = ulen - sizeof(*udp);
  if (pllen < sizeof(struct chunk_hdr)) { st.short_pl++; return; }
  struct chunk_hdr h;
  memcpy(&h, pl, sizeof(h));
  if (rte_be_to_cpu_32(h.magic) != MAGIC) { st.bad_magic++; return; }
  uint32_t id = rte_be_to_cpu_32(h.frame_id), off = rte_be_to_cpu_32(h.offset);
  uint32_t fb = rte_be_to_cpu_32(h.frame_bytes);
  uint16_t seq = rte_be_to_cpu_16(h.seq), nseg = rte_be_to_cpu_16(h.nseg), clen = rte_be_to_cpu_16(h.length);
  if (nseg == 0 || seq >= nseg || fb == 0 || fb > MAX_FRAME_BYTES || clen != pllen - sizeof(h) ||
      (uint64_t)off + clen > fb) { st.bad_hdr++; return; }

  struct frame *f = lookup(id, fb, nseg);
  if (!f) { st.no_slot++; return; }
  if (f->bytes != fb || f->nseg != nseg) { st.inconsistent++; return; }
  if (f->seen[seq / 8] & (1u << (seq % 8))) { st.dup++; return; }
  memcpy(f->data + off, pl + sizeof(h), clen);
  f->seen[seq / 8] |= 1u << (seq % 8);
  st.accepted++;
  if (++f->got == f->nseg) f->done = true;
}

static int cmp_frame(const void *a, const void *b) {
  const struct frame *x = a, *y = b;
  if (x->used != y->used) return x->used ? -1 : 1;
  return (x->id > y->id) - (x->id < y->id);
}

int main(int argc, char **argv) {
  int ret = rte_eal_init(argc, argv);
  if (ret < 0) rte_exit(EXIT_FAILURE, "EAL init failed\n");
  argc -= ret; argv += ret;            // argv[0] is now the program name

  const char *out_path = "frames_rx.bin";
  uint16_t port_no = 5000;
  uint64_t idle_ms = 500;
  int expect = 0;
  for (int i = 1; i < argc; i++) {
    if (!strcmp(argv[i], "--port") && i + 1 < argc) port_no = (uint16_t)atoi(argv[++i]);
    else if (!strcmp(argv[i], "--idle-ms") && i + 1 < argc) idle_ms = strtoull(argv[++i], NULL, 10);
    else if (!strcmp(argv[i], "--expect") && i + 1 < argc) expect = atoi(argv[++i]);
    else out_path = argv[i];
  }

  if (rte_eth_dev_count_avail() == 0) rte_exit(EXIT_FAILURE, "no ethdev port (missing --vdev?)\n");
  struct rte_mempool *pool = rte_pktmbuf_pool_create("mbufs", 8191, 256, 0,
                                                     RTE_MBUF_DEFAULT_BUF_SIZE, rte_socket_id());
  if (!pool) rte_exit(EXIT_FAILURE, "mbuf pool: %s\n", rte_strerror(rte_errno));
  struct rte_eth_conf conf = {0};
  if (rte_eth_dev_configure(0, 1, 1, &conf) < 0 ||
      rte_eth_rx_queue_setup(0, 0, 1024, rte_socket_id(), NULL, pool) < 0 ||
      rte_eth_tx_queue_setup(0, 0, 1024, rte_socket_id(), NULL) < 0 ||
      rte_eth_dev_start(0) < 0)
    rte_exit(EXIT_FAILURE, "port 0 setup failed\n");

  const uint64_t hz = rte_get_timer_hz();
  uint64_t t_first = 0, t_last = 0, empty_polls = 0;
  struct rte_mbuf *bufs[BURST];
  for (;;) {
    uint16_t n = rte_eth_rx_burst(0, 0, bufs, BURST);
    uint64_t now = rte_get_timer_cycles();
    if (n == 0) {
      empty_polls++;
      if (t_last && (now - t_last) * 1000 / hz >= idle_ms) break;   // input exhausted
      continue;
    }
    if (!t_first) t_first = now;
    t_last = now;
    for (uint16_t i = 0; i < n; i++) {
      struct rte_mbuf *m = bufs[i];
      // pcap PMD mbufs are single-segment for <= 2 KB frames; linearize just in case.
      if (m->nb_segs == 1 || rte_pktmbuf_linearize(m) == 0)
        handle(rte_pktmbuf_mtod(m, uint8_t *), rte_pktmbuf_data_len(m), port_no);
      else
        st.rx++, st.bad_ip++;
      rte_pktmbuf_free(m);
    }
    if (expect > 0) {
      int done = 0;
      for (int i = 0; i < MAX_FRAMES; i++) done += frames[i].done;
      if (done >= expect) break;
    }
  }

  struct rte_eth_stats es;
  rte_eth_stats_get(0, &es);
  rte_eth_dev_stop(0);

  qsort(frames, MAX_FRAMES, sizeof(frames[0]), cmp_frame);
  FILE *fo = fopen(out_path, "wb");
  if (!fo) rte_exit(EXIT_FAILURE, "cannot open %s\n", out_path);
  int complete = 0, partial = 0;
  printf("frame_ids written:");
  for (int i = 0; i < MAX_FRAMES && frames[i].used; i++) {
    if (frames[i].done) {
      fwrite(frames[i].data, 1, frames[i].bytes, fo);
      complete++;
      printf(" %" PRIu32, frames[i].id);
    } else {
      partial++;
    }
  }
  fclose(fo);
  printf("\n");
  for (int i = 0; i < MAX_FRAMES && frames[i].used; i++)
    if (!frames[i].done)
      printf("INCOMPLETE frame %" PRIu32 ": %u/%u chunks\n", frames[i].id, frames[i].got, frames[i].nseg);

  double secs = t_last > t_first ? (double)(t_last - t_first) / hz : 0;
  uint64_t dropped = st.rx - st.accepted;
  printf("port stats: ipackets=%" PRIu64 " imissed=%" PRIu64 " ierrors=%" PRIu64 " rx_nombuf=%" PRIu64 "\n",
         es.ipackets, es.imissed, es.ierrors, es.rx_nombuf);
  printf("received=%" PRIu64 " accepted=%" PRIu64 " dropped=%" PRIu64
         " [dup=%" PRIu64 " not_ipv4=%" PRIu64 " bad_ip=%" PRIu64 " not_udp=%" PRIu64 " ip_frag=%" PRIu64
         " other_port=%" PRIu64 " short=%" PRIu64 " bad_magic=%" PRIu64 " bad_hdr=%" PRIu64
         " inconsistent=%" PRIu64 " no_slot=%" PRIu64 "]\n",
         st.rx, st.accepted, dropped, st.dup, st.not_ipv4, st.bad_ip, st.not_udp, st.ip_frag,
         st.other_port, st.short_pl, st.bad_magic, st.bad_hdr, st.inconsistent, st.no_slot);
  printf("frames complete=%d incomplete=%d -> %s\n", complete, partial, out_path);
  printf("rx window %.3f ms (first to last packet), %.0f pkt/s\n", secs * 1e3, secs > 0 ? st.rx / secs : 0);

  rte_eal_cleanup();
  return partial ? 2 : 0;
}
