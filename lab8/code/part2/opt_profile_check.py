#!/usr/bin/env python3
"""EE542 Lab 8 Part 2 side check: does the optimization profile's OPT batch
explain TensorRT FP32 being slower than PyTorch at batch 1? Times each given
engine at batch 1, 8, 32 on a non-default stream (same method as bench.py).
  python3 opt_profile_check.py fp32_opt1.engine fp32_opt8.engine fp32_opt32.engine
"""
import os, sys
import torch
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trt_runner import TrtRunner
from bench import time_fn

with torch.cuda.stream(torch.cuda.Stream()):
    for path in sys.argv[1:]:
        eng = TrtRunner(path)
        cells = []
        for b in (1, 8, 32):
            x = torch.randn(b, 3, 224, 224, device="cuda").to(eng.in_dtype)
            cells.append(f"b{b}={time_fn(lambda: eng(x), 50, 500):.3f}ms")
        print(os.path.basename(path), *cells)
