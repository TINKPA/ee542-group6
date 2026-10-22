#!/usr/bin/env python3
"""EE542 Lab 8 Part 4: check that the receiver rebuilt every image byte for byte.

  python3 verify.py frames_orig.bin frames_rx.bin
"""
import hashlib
import sys

FRAME = 224 * 224 * 3


def frames(path):
    b = open(path, "rb").read()
    assert len(b) % FRAME == 0, f"{path}: {len(b)} bytes is not a whole number of frames"
    return [b[i:i + FRAME] for i in range(0, len(b), FRAME)]


orig, rx = frames(sys.argv[1]), frames(sys.argv[2])
ok = 0
for i, o in enumerate(orig):
    r = rx[i] if i < len(rx) else None
    same = r == o
    ok += same
    diff = "" if same or r is None else f" ({sum(x != y for x, y in zip(o, r))} bytes differ)"
    print(f"frame {i:2d} sha256 {hashlib.sha256(o).hexdigest()[:16]} "
          f"{'MATCH' if same else 'MISSING' if r is None else 'MISMATCH'}{diff}")
print(f"{ok}/{len(orig)} frames identical, rx file has {len(rx)} frames")
sys.exit(0 if ok == len(orig) == len(rx) else 1)
