#!/usr/bin/env python3
"""EE542 Lab 8 Part 5: classify the images the DPDK receiver rebuilt, on the GPU,
with the FP16 TensorRT engine, and measure the CPU-to-GPU copy GPUNetIO removes.

  python3 classify.py --rx rx_images_shuf.bin --orig frames_orig.bin \
      --labels labels.json --engine resnet18_fp16.engine --csv part5_<host>.csv

Pipeline per batch (all on one CUDA stream):
  pinned host uint8 HWC  --H2D copy-->  GPU uint8 HWC
  --GPU preprocess-->  float CHW, /255, (x - mean) / std, cast to FP16
  --TensorRT FP16-->  logits  --> argmax
mean/std come from torchvision's ResNet18_Weights.DEFAULT.transforms(). Its
resize-256 / center-crop-224 step was already applied when the images were
made (Part 3), so on the GPU only the layout change and normalization remain.

Checks: class of each received image == class of its original (same
pipeline), and both against the ImageNet ground-truth label.
Timing (CUDA events, mean over --iters after warm-up):
  H2D copy from pinned memory (and from pageable memory, for contrast),
  GPU preprocessing, TensorRT inference; at batch 1 and batch 16.
"""
import argparse
import csv
import json
import os
import socket
import sys
import time

import numpy as np
import torch
import torchvision

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "part2"))
from trt_runner import TrtRunner  # noqa: E402

H = W = 224
FRAME = H * W * 3


def load(path):
    b = np.fromfile(path, dtype=np.uint8)
    assert b.size % FRAME == 0
    return b.reshape(-1, H, W, 3)


class Preprocess:
    def __init__(self, dtype):
        t = torchvision.models.ResNet18_Weights.DEFAULT.transforms()
        self.mean = torch.tensor(t.mean, device="cuda").view(1, 3, 1, 1)
        self.std = torch.tensor(t.std, device="cuda").view(1, 3, 1, 1)
        self.dtype = dtype

    def __call__(self, u8_nhwc):
        x = u8_nhwc.permute(0, 3, 1, 2).float().div_(255.0)
        return ((x - self.mean) / self.std).to(self.dtype).contiguous()


def cuda_time(fn, warmup, iters):
    for _ in range(warmup):
        fn()
    torch.cuda.synchronize()
    s, e = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
    s.record()
    for _ in range(iters):
        fn()
    e.record()
    e.synchronize()
    return s.elapsed_time(e) / iters


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rx", required=True)
    ap.add_argument("--orig", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--engine", required=True)
    ap.add_argument("--iters", type=int, default=500)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--csv", default=None)
    a = ap.parse_args()

    # Non-default stream for everything (see part2/bench.py).
    torch.cuda.set_stream(torch.cuda.Stream())
    meta = json.load(open(a.labels))
    rx, orig = load(a.rx), load(a.orig)
    n = len(rx)
    eng = TrtRunner(a.engine)
    pre = Preprocess(eng.in_dtype)
    cats = torchvision.models.ResNet18_Weights.DEFAULT.meta["categories"]

    # Pinned (page-locked) host buffer: the DMA engine can read it directly.
    host_pinned = torch.from_numpy(rx.copy()).pin_memory()
    host_pageable = torch.from_numpy(rx.copy())
    dev = torch.empty((n, H, W, 3), dtype=torch.uint8, device="cuda")

    # ---- classify received and original images ----
    def classify(host):
        dev.copy_(host, non_blocking=True)
        logits = eng(pre(dev))
        torch.cuda.synchronize()
        return logits.float().argmax(1).cpu().tolist()

    pred_rx = classify(host_pinned)
    pred_orig = classify(torch.from_numpy(orig.copy()).pin_memory())
    labels = meta["labels"]
    same = sum(p == q for p, q in zip(pred_rx, pred_orig))
    right = sum(p == l for p, l in zip(pred_rx, labels))
    print(f"{'id':>3}  {'received -> class':<34} {'original -> class':<34} truth")
    for i in range(n):
        print(f"{i:3d}  {pred_rx[i]:4d} {cats[pred_rx[i]][:28]:<29} {pred_orig[i]:4d} {cats[pred_orig[i]][:28]:<29} "
              f"{labels[i]:4d} {'OK' if pred_rx[i] == pred_orig[i] else 'DIFF'}")
    print(f"received == original class: {same}/{n}; top-1 vs ImageNet label: {right}/{n}")

    # ---- timing ----
    rows = []
    for b in (1, n):
        hp, hg, d = host_pinned[:b], host_pageable[:b], dev[:b]
        nbytes = b * FRAME
        t_pin = cuda_time(lambda: d.copy_(hp, non_blocking=True), a.warmup, a.iters)
        t_page = cuda_time(lambda: d.copy_(hg), a.warmup, a.iters)
        x = pre(d)
        t_pre = cuda_time(lambda: pre(d), a.warmup, a.iters)
        t_inf = cuda_time(lambda: eng(x), a.warmup, a.iters)
        t_e2e = cuda_time(lambda: eng(pre(d.copy_(hp, non_blocking=True))), a.warmup, a.iters)
        # Latency of one isolated copy, as a receiver would see it: launch the
        # copy and wait for it, host wall clock (includes launch + sync cost).
        lat = []
        for i in range(a.warmup + a.iters):
            t0 = time.perf_counter()
            d.copy_(hp, non_blocking=True)
            torch.cuda.current_stream().synchronize()
            if i >= a.warmup:
                lat.append(time.perf_counter() - t0)
        t_lat = 1e3 * sorted(lat)[len(lat) // 2]
        rows.append(dict(batch=b, bytes=nbytes, h2d_pinned_ms=t_pin, h2d_pageable_ms=t_page,
                         pinned_GBps=nbytes / t_pin / 1e6, pageable_GBps=nbytes / t_page / 1e6,
                         h2d_pinned_sync_median_ms=t_lat,
                         preprocess_ms=t_pre, trt_fp16_ms=t_inf, end_to_end_ms=t_e2e,
                         copy_share_pct=100 * t_pin / t_e2e))
    print(f"\n{'batch':>5} {'bytes':>9} {'H2D pinned':>11} {'GB/s':>6} {'H2D pageable':>13} {'GB/s':>6} "
          f"{'preproc':>8} {'TRT FP16':>9} {'copy+pre+inf':>13} {'copy %':>7}")
    for r in rows:
        print(f"{r['batch']:5d} {r['bytes']:9d} {r['h2d_pinned_ms']:9.4f}ms {r['pinned_GBps']:6.2f} "
              f"{r['h2d_pageable_ms']:11.4f}ms {r['pageable_GBps']:6.2f} {r['preprocess_ms']:6.4f}ms "
              f"{r['trt_fp16_ms']:7.4f}ms {r['end_to_end_ms']:11.4f}ms {r['copy_share_pct']:6.1f}%")
    for r in rows:
        print(f"batch {r['batch']}: one isolated pinned H2D copy incl. launch + sync, median "
              f"{1e3 * r['h2d_pinned_sync_median_ms']:.1f} us")

    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["host", *rows[0].keys()])
            w.writeheader()
            for r in rows:
                w.writerow({"host": socket.gethostname(), **{k: (f"{v:.5f}" if isinstance(v, float) else v) for k, v in r.items()}})
        with open(a.csv.replace(".csv", "_preds.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["frame_id", "name", "label", "pred_rx", "pred_orig", "pred_rx_name"])
            for i in range(n):
                w.writerow([i, meta["names"][i], labels[i], pred_rx[i], pred_orig[i], cats[pred_rx[i]]])
        print(f"wrote {a.csv}")
    sys.exit(0 if same == n else 1)


if __name__ == "__main__":
    main()
