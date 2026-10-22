#!/usr/bin/env python3
"""EE542 Lab 8 Part 3: turn 16 test images into UDP packets and write a PCAP.

  python3 gen_pcap.py                       -> images.pcap (in order)
  python3 gen_pcap.py --shuffle -o images_shuf.pcap
  python3 gen_pcap.py --shuffle --dup 0.05 --noise 50 -o images_hard.pcap

Images: 16 ImageNet validation-style samples (one per class, from the
EliSchwartz/imagenet-sample-images repo), resized so the short side is 256 and
center-cropped to 224x224, stored as HWC uint8 RGB = 150,528 bytes. The
originals are saved as frames_orig.bin (16 x 150,528 bytes, frame_id order)
plus labels.json, so the receiver output can be compared byte for byte and
Part 5 has ground-truth classes. --synthetic skips the download and uses
seeded random gradient images instead.

UDP payload = 22-byte header (network byte order) + one chunk of image bytes:
  magic u32 | frame_id u32 | seq u16 | nseg u16 | offset u32 | length u16 | frame_bytes u32
With 1,400 data bytes per packet: ceil(150528 / 1400) = 108 packets per image,
the last one carrying 150528 - 107*1400 = 728 bytes. Largest IP datagram:
20 (IPv4) + 8 (UDP) + 22 + 1400 = 1450 bytes <= 1500-byte MTU (1464-byte frame).

Test options for the receiver's requirements (Step 4.1):
  --shuffle      random packet order (seeded)
  --dup F        re-send a random fraction F of the chunks (duplicates)
  --noise N      add N UDP packets to another port and N non-UDP packets,
                 which the receiver must ignore
"""
import argparse
import io
import json
import math
import os
import random
import struct
import urllib.request

import numpy as np

MAGIC = 0xEE542008
HDR = struct.Struct("!IIHHIHI")          # 22 bytes, big-endian
H = W = 224
FRAME_BYTES = H * W * 3                  # 150,528
SRC_URL = "https://raw.githubusercontent.com/EliSchwartz/imagenet-sample-images/master/{}"
# (ImageNet class index, file) -- index = position in the sorted 1000-class list
SAMPLES = [
    (0, "n01440764_tench.JPEG"), (1, "n01443537_goldfish.JPEG"),
    (22, "n01614925_bald_eagle.JPEG"), (145, "n02056570_king_penguin.JPEG"),
    (207, "n02099601_golden_retriever.JPEG"), (281, "n02123045_tabby.JPEG"),
    (340, "n02391049_zebra.JPEG"), (404, "n02690373_airliner.JPEG"),
    (407, "n02701002_ambulance.JPEG"), (483, "n02980441_castle.JPEG"),
    (555, "n03345487_fire_engine.JPEG"), (779, "n04146614_school_bus.JPEG"),
    (954, "n07753592_banana.JPEG"), (963, "n07873807_pizza.JPEG"),
    (980, "n09472597_volcano.JPEG"), (985, "n11939491_daisy.JPEG"),
]


def load_real(cache_dir):
    from PIL import Image
    os.makedirs(cache_dir, exist_ok=True)
    frames = []
    for _, name in SAMPLES:
        path = os.path.join(cache_dir, name)
        if not os.path.exists(path):
            with urllib.request.urlopen(SRC_URL.format(name), timeout=30) as r:
                open(path, "wb").write(r.read())
        im = Image.open(path).convert("RGB")
        s = 256 / min(im.size)
        im = im.resize((round(im.width * s), round(im.height * s)), Image.BILINEAR)
        l, t = (im.width - W) // 2, (im.height - H) // 2
        frames.append(np.asarray(im.crop((l, t, l + W, t + H)), dtype=np.uint8))
    return frames, [c for c, _ in SAMPLES], [n for _, n in SAMPLES]


def load_synthetic(n, rng):
    yy, xx = np.mgrid[0:H, 0:W]
    frames = []
    for i in range(n):
        base = np.stack([(xx * (i + 1)) % 256, (yy * (i + 3)) % 256, ((xx + yy) * (i + 5)) % 256], -1)
        frames.append((base + rng.integers(0, 32, (H, W, 3))).astype(np.uint8))
    return frames, [-1] * n, [f"synthetic_{i}" for i in range(n)]


def chunk(frame_id, data, size):
    nseg = math.ceil(len(data) / size)
    for seq in range(nseg):
        off = seq * size
        body = data[off:off + size]
        yield HDR.pack(MAGIC, frame_id, seq, nseg, off, len(body), len(data)) + body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="images.pcap")
    ap.add_argument("--orig", default="frames_orig.bin")
    ap.add_argument("--labels", default="labels.json")
    ap.add_argument("--chunk", type=int, default=1400)
    ap.add_argument("--shuffle", action="store_true")
    ap.add_argument("--dup", type=float, default=0.0)
    ap.add_argument("--noise", type=int, default=0)
    ap.add_argument("--seed", type=int, default=542)
    ap.add_argument("--dport", type=int, default=5000)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--cache", default="img_cache")
    a = ap.parse_args()

    from scapy.all import ARP, Ether, IP, UDP, Raw, wrpcap

    rnd = random.Random(a.seed)
    if a.synthetic:
        frames, labels, names = load_synthetic(16, np.random.default_rng(a.seed))
    else:
        frames, labels, names = load_real(a.cache)
    assert all(f.nbytes == FRAME_BYTES for f in frames)
    with open(a.orig, "wb") as f:
        for fr in frames:
            f.write(fr.tobytes())
    json.dump({"frame_bytes": FRAME_BYTES, "shape": [H, W, 3], "layout": "HWC uint8 RGB",
               "labels": labels, "names": names}, open(a.labels, "w"), indent=1)

    eth = Ether(src="02:00:00:00:00:01", dst="02:00:00:00:00:02")
    ip = IP(src="10.0.0.1", dst="10.0.0.2")
    payloads = [p for i, fr in enumerate(frames) for p in chunk(i, fr.tobytes(), a.chunk)]
    nseg = len(payloads) // len(frames)
    pkts = [eth / ip / UDP(sport=40000, dport=a.dport) / Raw(p) for p in payloads]
    n_dup = int(round(a.dup * len(pkts)))
    pkts += [pkts[i].copy() for i in rnd.sample(range(len(pkts)), n_dup)]
    for _ in range(a.noise):   # traffic the receiver must drop
        pkts.append(eth / ip / UDP(sport=40000, dport=a.dport + 1) / Raw(payloads[rnd.randrange(len(payloads))]))
        pkts.append(Ether(src="02:00:00:00:00:01", dst="ff:ff:ff:ff:ff:ff") / ARP(psrc="10.0.0.1", pdst="10.0.0.2"))
    if a.shuffle:
        rnd.shuffle(pkts)
    wrpcap(a.out, pkts)

    largest_ip = max(len(p[IP]) for p in pkts if p.haslayer(IP))
    print(f"{len(frames)} images x {FRAME_BYTES} B, {a.chunk} B/chunk -> {nseg} packets/image "
          f"(last chunk {FRAME_BYTES - (nseg - 1) * a.chunk} B)")
    print(f"largest IP datagram {largest_ip} B (MTU 1500: {'fits' if largest_ip <= 1500 else 'TOO BIG'}), "
          f"largest frame {max(len(p) for p in pkts)} B")
    print(f"wrote {a.out}: {len(pkts)} packets = {len(payloads)} chunks + {n_dup} duplicates "
          f"+ {2 * a.noise} noise; shuffled={a.shuffle}")
    print(f"wrote {a.orig} and {a.labels}")


if __name__ == "__main__":
    main()
