#!/usr/bin/env python3
"""EE542 Lab 6 Part 8: sample images for the convolution tests.

Three scikit-image sample images (BSD licensed, shipped with the package, so
the set is reproducible without a download): camera, moon, astronaut (RGB,
converted to gray). Each is 512 x 512 8-bit; it is scaled to the 16-bit range
(x 257) so the pixels use the headroom of the unsigned 32-bit format the lab
asks for, and written as raw little-endian uint32 at M = 512 (native) and,
by bicubic resampling, 1024, 2048 and 4096 for the timing grid.

Output: <out_dir>/<name>_<M>.bin and <name>_512.png (8-bit preview).
Usage: python3 prep_images.py [out_dir]       default ../../data/images
"""
import os
import sys

import numpy as np
from skimage import data, color, transform
from PIL import Image

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "images")
SIZES = [512, 1024, 2048, 4096]

def samples():
    yield "camera", data.camera()
    yield "moon", data.moon()
    yield "astronaut", (color.rgb2gray(data.astronaut()) * 255).round().astype(np.uint8)

def main():
    os.makedirs(OUT, exist_ok=True)
    for name, img8 in samples():
        img8 = img8[:512, :512]
        Image.fromarray(img8).save(os.path.join(OUT, f"{name}_512.png"))
        for M in SIZES:
            if M == 512:
                im = img8.astype(np.float64)
            else:
                im = transform.resize(img8.astype(np.float64), (M, M), order=3,
                                      preserve_range=True, anti_aliasing=False)
            u = (np.clip(im, 0, 255) * 257).round().astype(np.uint32)   # 8-bit -> 16-bit range
            u.astype("<u4").tofile(os.path.join(OUT, f"{name}_{M}.bin"))
            print(f"{name}_{M}.bin  {u.shape}  min {u.min()} max {u.max()}")

if __name__ == "__main__":
    main()
