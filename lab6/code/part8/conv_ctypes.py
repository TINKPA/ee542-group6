#!/usr/bin/env python3
"""EE542 Lab 6 Part 8.3: the convolution through libmatrix.so from Python.

Three jobs, selectable by subcommand:

  demo    apply the named filters to the three 512 x 512 sample images through
          gpu_convolve, check every output bit-for-bit against
          scipy.ndimage.convolve (int64), and write the panel figure the
          report shows (data/lab6_conv_demo_v1.png).
  compare the three-way timing the handout asks for, at the chosen M and N:
          the C executable (conv_cpu), the CUDA executable (conv_gpu, tiled),
          and Python through the library, one-shot (gpu_convolve) and with the
          image resident on the device (gpu_conv_upload / gpu_conv_apply);
          scipy.ndimage.convolve as the CPU-in-Python reference. Writes
          data/raw/conv3_<host>.csv.
  check   bitwise check of conv_cpu's output file against scipy (no GPU).

Usage: python3 conv_ctypes.py demo|compare|check [--images DIR] [--sizes 512,2048] [--ns 3,5,7]
"""
import argparse
import csv
import ctypes
import os
import socket
import statistics
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.join(HERE, "..", "..")
RAW = os.path.join(LAB, "data", "raw")
FILTERS = os.path.join(HERE, "filters")
DEMO_FILTERS = ["sobel_x_3", "laplacian_3", "gauss_5", "log_5"]
TITLES = {"sobel_x_3": "Sobel x, 3×3", "laplacian_3": "Laplacian, 3×3",
          "gauss_5": "Gaussian, 5×5", "log_5": "LoG, 5×5"}
IMAGES = ["camera", "moon", "astronaut"]


def read_filter(name):
    with open(os.path.join(FILTERS, name + ".txt")) as fh:
        n, div = map(int, fh.readline().split())
        vals = [int(v) for v in fh.read().split()]
    return np.array(vals, dtype=np.int32).reshape(n, n), div


def random_filter(n):
    """Same as conv_io.h's random_filter after random_image(M): not reproducible
    across libc, so compare mode only times with it and checks via checksums."""
    rng = np.random.default_rng(7)
    return rng.integers(-8, 9, size=(n, n), dtype=np.int32), 1


def load_image(d, name, M):
    return np.fromfile(os.path.join(d, f"{name}_{M}.bin"), dtype="<u4").reshape(M, M).astype(np.uint32)


def reference(img, filt, div):
    """scipy's convolve on int64 with zero padding, then |.|/div clamped: the oracle."""
    from scipy import ndimage
    acc = ndimage.convolve(img.astype(np.int64), filt.astype(np.int64), mode="constant", cval=0)
    acc = np.abs(acc) // div
    return np.minimum(acc, np.uint32(0xFFFFFFFF)).astype(np.uint32)


def load_lib():
    lib = ctypes.cdll.LoadLibrary(os.path.join(HERE, "..", "part7", "libmatrix.so"))
    u32 = np.ctypeslib.ndpointer(dtype=np.uint32, ndim=1, flags="C_CONTIGUOUS")
    i32 = np.ctypeslib.ndpointer(dtype=np.int32, ndim=1, flags="C_CONTIGUOUS")
    lib.gpu_convolve.argtypes = [u32, ctypes.c_int, i32, ctypes.c_int, ctypes.c_int, u32]
    lib.gpu_convolve.restype = ctypes.c_int
    lib.gpu_conv_upload.argtypes = [u32, ctypes.c_int]
    lib.gpu_conv_upload.restype = ctypes.c_int
    lib.gpu_conv_apply.argtypes = [ctypes.c_int, i32, ctypes.c_int, ctypes.c_int, u32]
    lib.gpu_conv_apply.restype = ctypes.c_int
    lib.gpu_conv_free.argtypes = [ctypes.c_int]
    lib.gpu_conv_free.restype = ctypes.c_int
    lib.gpu_last_timing.argtypes = [np.ctypeslib.ndpointer(dtype=np.float32, ndim=1)]
    lib.gpu_last_timing.restype = None
    return lib


def last_timing(lib):
    p = np.zeros(4, dtype=np.float32); lib.gpu_last_timing(p); return p


def convolve_oneshot(lib, img, filt, div):
    M, N = img.shape[0], filt.shape[0]
    out = np.empty(M * M, dtype=np.uint32); out.fill(0)
    rc = lib.gpu_convolve(img.ravel(), M, filt.ravel(), N, div, out)
    assert rc == 0, f"gpu_convolve rc={rc}"
    return out.reshape(M, M)


def cmd_check(args):
    d = args.images
    img = load_image(d, "camera", 512)
    for fname in DEMO_FILTERS:
        filt, div = read_filter(fname)
        ref = reference(img, filt, div)
        tmp = os.path.join(d, "_check.bin")
        subprocess.run([os.path.join(HERE, "conv_cpu"), os.path.join(d, "camera_512.bin"), "512",
                        os.path.join(FILTERS, fname + ".txt"), tmp], check=True, capture_output=True)
        got = np.fromfile(tmp, dtype="<u4").reshape(512, 512)
        print(f"{fname:<12} conv_cpu == scipy: {np.array_equal(got, ref)}  checksum {int(got.sum(dtype=np.uint64))}")
    os.remove(tmp)


def cmd_demo(args):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    lib = load_lib()
    d = args.images
    fig, axes = plt.subplots(len(IMAGES), len(DEMO_FILTERS) + 1,
                             figsize=(2.2 * (len(DEMO_FILTERS) + 1), 2.3 * len(IMAGES)), dpi=150)
    ok = True
    for r, name in enumerate(IMAGES):
        img = load_image(d, name, 512)
        axes[r, 0].imshow(img, cmap="gray", vmin=0, vmax=65535)
        axes[r, 0].set_title(name if r == 0 else "", fontsize=8)
        axes[r, 0].set_ylabel(name, fontsize=8)
        for c, fname in enumerate(DEMO_FILTERS, start=1):
            filt, div = read_filter(fname)
            out = convolve_oneshot(lib, img, filt, div)
            ref = reference(img, filt, div)
            eq = np.array_equal(out, ref); ok &= eq
            print(f"{name:<10} {fname:<12} gpu == scipy: {eq}  checksum {int(out.sum(dtype=np.uint64))}")
            # display: percentile stretch so edge maps are visible
            hi = np.percentile(out, 99.5) or 1
            axes[r, c].imshow(np.minimum(out, hi), cmap="gray", vmin=0, vmax=hi)
            if r == 0:
                axes[r, c].set_title(TITLES.get(fname, fname), fontsize=8)
        for ax in axes[r]:
            ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout(pad=0.3)
    outpng = os.path.join(LAB, "data", "lab6_conv_demo_v1.png")
    fig.savefig(outpng); fig.savefig(outpng.replace(".png", ".pdf"))
    print("all bitwise equal:", ok, "->", outpng)


def run_bin(cmd):
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    line = [l for l in out.splitlines() if l.startswith("wall=")][0]
    return {k: v for k, v in (kv.split("=") for kv in line.split())}


def cmd_compare(args):
    from scipy import ndimage
    lib = load_lib()
    d = args.images
    host = socket.gethostname().split(".")[0]
    rows = []
    print(f"{'M':>5} {'N':>3} | {'C exe s':>9} {'CUDA exe s':>11} {'(kernel ms)':>11} | {'py oneshot s':>12} "
          f"{'py resident s':>13} {'(kernel ms)':>11} | {'scipy s':>9} | equal")
    for M in args.sizes:
        img = load_image(d, "camera", M)
        for N in args.ns:
            filt, div = random_filter(N)
            ffile = os.path.join(d, f"_f{N}.txt")
            with open(ffile, "w") as fh:
                fh.write(f"{N} {div}\n" + "\n".join(" ".join(map(str, row)) for row in filt) + "\n")
            ibin = os.path.join(d, f"camera_{M}.bin")
            c = [run_bin([os.path.join(HERE, "conv_cpu"), ibin, str(M), ffile]) for _ in range(3)]
            g = [run_bin([os.path.join(HERE, "conv_gpu"), "--kernel", "tiled", ibin, str(M), ffile]) for _ in range(3)]
            t_c = statistics.median(float(x["wall"]) for x in c)
            t_g = statistics.median(float(x["wall"]) for x in g)
            k_g = statistics.median(float(x["kernel_ms"]) for x in g)
            # Python, one-shot (alloc + copies every call), warm
            convolve_oneshot(lib, img, filt, div)
            ones, ks = [], []
            for _ in range(3):
                t0 = time.perf_counter(); out = convolve_oneshot(lib, img, filt, div); ones.append(time.perf_counter() - t0)
                ks.append(last_timing(lib)[2])
            # Python, image resident
            h = lib.gpu_conv_upload(img.ravel(), M); assert h >= 0
            o2 = np.empty(M * M, dtype=np.uint32); o2.fill(0)
            lib.gpu_conv_apply(h, filt.ravel(), N, div, o2)
            res, kr = [], []
            for _ in range(3):
                t0 = time.perf_counter(); rc = lib.gpu_conv_apply(h, filt.ravel(), N, div, o2); res.append(time.perf_counter() - t0)
                assert rc == 0; kr.append(last_timing(lib)[2])
            lib.gpu_conv_free(h)
            t0 = time.perf_counter(); ref = reference(img, filt, div); t_sp = time.perf_counter() - t0
            eq = np.array_equal(out, ref) and np.array_equal(o2.reshape(M, M), ref) \
                and int(c[0]["checksum"]) == int(ref.sum(dtype=np.uint64)) == int(g[0]["checksum"])
            row = dict(host=host, M=M, N=N, c_exe_s=t_c, cuda_exe_s=t_g, cuda_exe_kernel_ms=k_g,
                       py_oneshot_s=statistics.median(ones), py_oneshot_kernel_ms=float(np.median(ks)),
                       py_resident_s=statistics.median(res), py_resident_kernel_ms=float(np.median(kr)),
                       scipy_s=t_sp, all_equal=eq)
            rows.append(row)
            print(f"{M:>5} {N:>3} | {t_c:>9.4f} {t_g:>11.4f} {k_g:>11.3f} | {row['py_oneshot_s']:>12.4f} "
                  f"{row['py_resident_s']:>13.5f} {row['py_resident_kernel_ms']:>11.3f} | {t_sp:>9.4f} | {eq}")
            os.remove(ffile)
    os.makedirs(RAW, exist_ok=True)
    out = os.path.join(RAW, f"conv3_{host}.csv")
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print("wrote", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["demo", "compare", "check"])
    ap.add_argument("--images", default=os.path.join(LAB, "data", "images"))
    ap.add_argument("--sizes", default="512,1024,2048,4096")
    ap.add_argument("--ns", default="3,7,15")
    a = ap.parse_args()
    a.sizes = [int(x) for x in a.sizes.split(",")]
    a.ns = [int(x) for x in a.ns.split(",")]
    {"demo": cmd_demo, "compare": cmd_compare, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    main()
