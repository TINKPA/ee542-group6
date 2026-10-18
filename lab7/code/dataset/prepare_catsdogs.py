"""EE542 Lab 7: build the Dogs-vs-Cats folders the tutorial expects.

Source: Microsoft's distribution of the Asirra cat/dog images
(kagglecatsanddogs_5340.zip, 12,500 + 12,500 JPEGs), the same image pool as
the Kaggle "Dogs vs. Cats" competition's train.zip. We use it because it
downloads without a Kaggle login. Its layout is PetImages/{Cat,Dog}/<n>.jpg
and it contains a handful of unreadable files, which are dropped here.

The Kaggle test/ folder is unlabeled, so like the tutorial we hold out part
of the labeled images. Unlike the tutorial we shuffle BEFORE splitting:
the tutorial's load_data reads all cats then all dogs, so an unshuffled
80/20 cut leaves a test set that is (almost) all dogs.

Output (default --out ./catsdogs):
  train/{cat,dog}/*.jpg   80 %, symlinks to the extracted originals
  test/{cat,dog}/*.jpg    20 %
  manifest.csv            split,label,path,width,height

Usage:  python prepare_catsdogs.py [--zip PATH] [--out DIR] [--seed 0]
"""
import argparse
import csv
import os
import random
import urllib.request
import zipfile

from PIL import Image

URL = ('https://download.microsoft.com/download/3/E/1/'
       '3E1C3F21-ECDB-4869-8368-6DEBA77B919F/kagglecatsanddogs_5340.zip')


def readable(path):
    try:
        with Image.open(path) as im:
            im.convert('RGB').load()
            return im.size
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip', default='kagglecatsanddogs_5340.zip')
    ap.add_argument('--out', default='catsdogs')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--test-frac', type=float, default=0.2)
    a = ap.parse_args()

    if not os.path.exists(a.zip):
        print(f"downloading {URL}", flush=True)
        urllib.request.urlretrieve(URL, a.zip)
    raw = os.path.join(a.out, 'raw')
    if not os.path.isdir(os.path.join(raw, 'PetImages')):
        print("extracting", flush=True)
        with zipfile.ZipFile(a.zip) as z:
            z.extractall(raw)

    rng = random.Random(a.seed)
    rows, dropped = [], []
    for label, folder in (('cat', 'Cat'), ('dog', 'Dog')):
        src = os.path.join(raw, 'PetImages', folder)
        files = sorted(f for f in os.listdir(src) if f.lower().endswith('.jpg'))
        good = []
        for f in files:
            size = readable(os.path.join(src, f))
            (good.append((f, size)) if size else dropped.append(f"{folder}/{f}"))
        rng.shuffle(good)
        n_test = int(round(len(good) * a.test_frac))
        for i, (f, size) in enumerate(good):
            split = 'test' if i < n_test else 'train'
            d = os.path.join(a.out, split, label)
            os.makedirs(d, exist_ok=True)
            dst = os.path.join(d, f"{label}.{f}")
            if not os.path.lexists(dst):
                os.symlink(os.path.abspath(os.path.join(src, f)), dst)
            rows.append((split, label, dst, size[0], size[1]))
        print(f"{label}: {len(good)} readable, {n_test} test, {len(good) - n_test} train", flush=True)

    with open(os.path.join(a.out, 'manifest.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['split', 'label', 'path', 'width', 'height'])
        w.writerows(rows)
    print(f"dropped {len(dropped)} unreadable: {' '.join(dropped)}")
    for s in ('train', 'test'):
        print(s, {l: sum(1 for r in rows if r[0] == s and r[1] == l) for l in ('cat', 'dog')})


if __name__ == '__main__':
    main()
