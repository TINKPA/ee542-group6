#!/usr/bin/env python3
"""EE542 Lab 6 Part 7: call libmatrix.so from Python through ctypes.

The handout's script, extended so the call can be understood rather than just
timed: for each N it records the first call (which pays CUDA context creation),
then three warm calls, reading back from the library how the call's time splits
into allocation, the two PCIe copies and the kernel; everything left over is
ctypes and Python. numpy's own A @ B is run as the CPU reference a Python user
actually has, and as the correctness check. Two ways of preparing C are timed,
np.zeros (calloc, pages untouched until the copy writes them) and a buffer
written once beforehand, to show the first-touch cost found in Part 5.

Usage: python3 matmul_ctypes.py [N ...]       default 256 ... 3072
Writes data/raw/py_<host>.csv (path relative to this file) and prints a table.
"""
import ctypes
import csv
import os
import socket
import statistics
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "..", "data", "raw")

# Load shared library (handout)
lib = ctypes.cdll.LoadLibrary(os.path.join(HERE, "libmatrix.so"))

# Define argument types (handout), for every exported multiply
ARGS = [
    np.ctypeslib.ndpointer(dtype=np.float32, ndim=1, flags="C_CONTIGUOUS"),
    np.ctypeslib.ndpointer(dtype=np.float32, ndim=1, flags="C_CONTIGUOUS"),
    np.ctypeslib.ndpointer(dtype=np.float32, ndim=1, flags="C_CONTIGUOUS"),
    ctypes.c_int,
]
for name in ("gpu_matrix_multiply", "gpu_matrix_multiply_timed", "gpu_matrix_multiply_fast"):
    getattr(lib, name).argtypes = ARGS
    getattr(lib, name).restype = None
lib.gpu_last_timing.argtypes = [np.ctypeslib.ndpointer(dtype=np.float32, ndim=1)]
lib.gpu_last_timing.restype = None
lib.gpu_device_name.restype = ctypes.c_char_p


def timed_call(fn, A, B, C, N):
    """Wall seconds of one call, plus the library's own [alloc, h2d, kernel, d2h] ms."""
    t0 = time.perf_counter()
    fn(A.ravel(), B.ravel(), C.ravel(), N)
    wall = time.perf_counter() - t0
    parts = np.zeros(4, dtype=np.float32)
    lib.gpu_last_timing(parts)
    return wall, parts


def main():
    sizes = [int(a) for a in sys.argv[1:]] or [256, 512, 768, 1024, 1536, 2048, 3072]
    host = socket.gethostname().split(".")[0]
    gpu = lib.gpu_device_name().decode()
    os.makedirs(RAW, exist_ok=True)
    out = os.path.join(RAW, f"py_{host}.csv")
    rows = []
    print(f"GPU {gpu}, numpy {np.__version__}, host {host}")
    print(f"{'N':>6} {'fn':<6} {'first s':>9} {'warm s':>9} {'alloc ms':>9} {'h2d ms':>8} "
          f"{'kern ms':>8} {'d2h ms':>8} {'py+ctypes ms':>13} {'numpy s':>9} {'maxrel':>8}")

    for N in sizes:
        rng = np.random.default_rng(1)
        A = rng.random((N, N), dtype=np.float32)
        B = rng.random((N, N), dtype=np.float32)

        # CPU reference: numpy's matmul (BLAS, all cores), and the correctness oracle.
        t0 = time.perf_counter(); ref = A @ B; t_np = time.perf_counter() - t0

        for label, fn in (("tiled", lib.gpu_matrix_multiply_timed), ("fast", lib.gpu_matrix_multiply_fast)):
            # Handout style: C = np.zeros, pages untouched until the copy-back writes them.
            C = np.zeros((N, N), dtype=np.float32)
            first_wall, first_parts = timed_call(fn, A, B, C, N)
            maxrel = float(np.max(np.abs(C - ref)) / np.max(np.abs(ref)))
            warm = []
            for _ in range(3):
                C = np.zeros((N, N), dtype=np.float32)
                warm.append(timed_call(fn, A, B, C, N))
            # Same calls into a buffer that was written once before (pages present).
            Cw = np.empty((N, N), dtype=np.float32); Cw.fill(0)
            touched = [timed_call(fn, A, B, Cw, N) for _ in range(3)]

            w = statistics.median(x[0] for x in warm)
            parts = np.median(np.stack([x[1] for x in warm]), axis=0)
            wt = statistics.median(x[0] for x in touched)
            parts_t = np.median(np.stack([x[1] for x in touched]), axis=0)
            overhead = w * 1e3 - parts.sum()
            print(f"{N:>6} {label:<6} {first_wall:>9.4f} {w:>9.4f} {parts[0]:>9.3f} {parts[1]:>8.3f} "
                  f"{parts[2]:>8.3f} {parts[3]:>8.3f} {overhead:>13.3f} {t_np:>9.4f} {maxrel:>8.1e}"
                  f"   | pre-touched C: warm {wt:.4f} s, d2h {parts_t[3]:.3f} ms")
            rows.append(dict(host=host, gpu=gpu, N=N, fn=label, first_s=first_wall, warm_s=w,
                             alloc_ms=parts[0], h2d_ms=parts[1], kernel_ms=parts[2], d2h_ms=parts[3],
                             py_overhead_ms=overhead, touched_warm_s=wt, touched_d2h_ms=parts_t[3],
                             numpy_s=t_np, maxrel=maxrel, first_alloc_ms=first_parts[0]))

    with open(out, "w", newline="") as fh:
        wri = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        wri.writeheader(); wri.writerows(rows)
    print(f"wrote {out}")

    # The handout's own measurement, for the record.
    N = 1024
    A = np.random.rand(N, N).astype(np.float32)
    B = np.random.rand(N, N).astype(np.float32)
    C = np.zeros((N, N), dtype=np.float32)
    start = time.time()
    lib.gpu_matrix_multiply(A.ravel(), B.ravel(), C.ravel(), N)
    end = time.time()
    print(f"Python call to CUDA library completed in {end - start:.4f} seconds")


if __name__ == "__main__":
    main()
