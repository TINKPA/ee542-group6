#!/usr/bin/env python3
"""EE542 Lab 8 Step 2.4: time PyTorch FP32, TensorRT FP32 and TensorRT FP16 on
ResNet-18 at batch 1, 8 and 32, and check each engine's logits against PyTorch.

  python3 bench.py --warmup 50 --iters 500 --csv ../../data/raw/part2_<host>.csv

Timing: CUDA events around ITERS back-to-back launches on one stream, after
WARMUP launches; reported as mean ms per batch. Input is random and already on
the GPU, so the time is inference only (no host<->device copies).
Accuracy: on the same random input, the largest absolute difference of each
engine's logits from PyTorch FP32, and top-1 agreement. Repeated over
--acc-batches random batches of 32 so top-1 agreement is over many images.
"""
import argparse
import csv
import os
import socket
import sys

import torch
import torchvision

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trt_runner import TrtRunner  # noqa: E402

BATCHES = (1, 8, 32)


def time_fn(fn, warmup, iters):
    for _ in range(warmup):
        fn()
    torch.cuda.synchronize()
    start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
    start.record()
    for _ in range(iters):
        fn()
    end.record()
    end.synchronize()
    return start.elapsed_time(end) / iters


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".", help="where the .engine files are")
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--iters", type=int, default=500)
    ap.add_argument("--acc-batches", type=int, default=32)
    ap.add_argument("--csv", default=None)
    a = ap.parse_args()

    torch.manual_seed(0)
    model = torchvision.models.resnet18(weights="DEFAULT").eval().cuda()
    engines = {
        "TensorRT FP32": TrtRunner(f"{a.dir}/resnet18_fp32.engine"),
        "TensorRT FP16": TrtRunner(f"{a.dir}/resnet18_fp16.engine"),
    }
    print(f"GPU {torch.cuda.get_device_name()} | torch {torch.__version__} | "
          f"cudnn.allow_tf32={torch.backends.cudnn.allow_tf32} "
          f"matmul.allow_tf32={torch.backends.cuda.matmul.allow_tf32}")

    # A dedicated stream: on the legacy default stream TensorRT inserts extra
    # cudaStreamSynchronize calls (it warns about this), which inflates small-batch times.
    stream = torch.cuda.Stream()
    rows = []
    with torch.inference_mode(), torch.cuda.stream(stream):
        for b in BATCHES:
            x = torch.randn(b, 3, 224, 224, device="cuda")
            t = time_fn(lambda: model(x), a.warmup, a.iters)
            rows.append(("PyTorch FP32", b, t))
            for name, eng in engines.items():
                xi = x.to(eng.in_dtype).contiguous()
                t = time_fn(lambda: eng(xi), a.warmup, a.iters)
                rows.append((name, b, t))

        # Accuracy vs PyTorch FP32 on identical inputs.
        acc = {name: [0.0, 0, 0] for name in engines}   # maxdiff, agree, total
        for _ in range(a.acc_batches):
            x = torch.randn(32, 3, 224, 224, device="cuda")
            ref = model(x).float()
            for name, eng in engines.items():
                out = eng(x.to(eng.in_dtype).contiguous()).float()
                torch.cuda.synchronize()
                acc[name][0] = max(acc[name][0], (out - ref).abs().max().item())
                acc[name][1] += (out.argmax(1) == ref.argmax(1)).sum().item()
                acc[name][2] += x.shape[0]

    base = {b: t for n, b, t in rows if n == "PyTorch FP32"}
    print(f"\n{'Implementation':<15}" + "".join(f"{'batch ' + str(b):>28}" for b in BATCHES))
    for name in ["PyTorch FP32", *engines]:
        cells = []
        for b in BATCHES:
            t = next(t for n, bb, t in rows if n == name and bb == b)
            cells.append(f"{t:7.3f} ms {base[b] / t:5.2f}x {b * 1000 / t:7.0f} img/s")
        print(f"{name:<15}" + "".join(f"{c:>28}" for c in cells))
    print("\naccuracy vs PyTorch FP32 "
          f"({a.acc_batches} random batches of 32 = {a.acc_batches * 32} images)")
    for name, (md, ag, tot) in acc.items():
        print(f"  {name}: max|dlogit| = {md:.5f}, top-1 agreement = {ag}/{tot} = {100 * ag / tot:.2f}%")

    if a.csv:
        os.makedirs(os.path.dirname(os.path.abspath(a.csv)), exist_ok=True)
        with open(a.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["host", "impl", "batch", "ms", "speedup", "img_per_s",
                        "max_abs_diff", "top1_agree", "top1_total"])
            for name, b, t in rows:
                md, ag, tot = acc.get(name, ["", "", ""])
                w.writerow([socket.gethostname(), name, b, f"{t:.4f}", f"{base[b] / t:.3f}",
                            f"{b * 1000 / t:.1f}", md if md == "" else f"{md:.6f}", ag, tot])
        print(f"wrote {a.csv}")


if __name__ == "__main__":
    main()
