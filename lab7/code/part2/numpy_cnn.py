"""EE542 Lab 7 Part II: the tutorial's one-filter CNN in pure NumPy, cats vs dogs.

Model (tutorial section 4-6): 3x3x3 conv (one filter, no padding) -> ReLU ->
2x2 max-pool -> flatten -> FC -> ReLU, MSE loss, per-image SGD, lr 1e-3,
10 epochs, only the FC layer trained. Labels: cat 0, dog 1; predict dog if
output > 0.5.

Fixes to the tutorial code, each needed for it to run or to mean anything:
  * W_fc is (31*31, 1), not (32*32*3, 1). 64x64 -> conv 62x62 x 1 channel
    -> pool 31x31 = 961 features; the tutorial's shape raises in np.dot.
  * Training images are shuffled once after loading. load_data returns all
    cats then all dogs, and per-image SGD over that order ends each epoch
    having just seen 10,000 dogs.
  * The test set is the separate test/ folder (prepare_catsdogs.py shuffles
    before splitting) instead of the last 20 % of the cats-then-dogs array.

Because the conv filter is never trained, its output for an image is the same
every epoch. By default features are computed once and cached, which gives the
same weights as the tutorial loop. --faithful-epochs K additionally runs the
tutorial's loop literally (conv inside every forward) for K epochs and times
it, to confirm that the cached path is the same computation.

--conv loop  is the tutorial's double-loop conv2d / maxpool.
--conv vec   is the same arithmetic as 9 shifted multiply-adds over a batch.

Writes one JSON summary line to stdout (prefixed 'RESULT ') and, with --csv,
appends it as a row.

Usage:
  python numpy_cnn.py --data DIR [--conv loop|vec] [--epochs 10] [--seed 0]
                      [--limit N] [--cache feats.npz] [--faithful-epochs 0]
"""
import argparse
import json
import os
import platform
import socket
import time

import numpy as np
from PIL import Image


# ---------------------------------------------------------------- tutorial code
def load_data(data_dir, limit=None):
    X, y = [], []
    for label, folder in enumerate(['cat', 'dog']):
        path = os.path.join(data_dir, folder)
        files = sorted(os.listdir(path))[:limit]
        for file in files:
            img = Image.open(os.path.join(path, file)).convert('RGB').resize((64, 64))
            X.append(np.array(img) / 255.0)
            y.append(label)
    return np.array(X), np.array(y)


def relu(x):
    return np.maximum(0, x)


def relu_derivative(x):
    return (x > 0).astype(float)


def mse_loss(y_true, y_pred):
    return np.mean((y_true - y_pred) ** 2)


def mse_grad(y_true, y_pred):
    return 2 * (y_pred - y_true) / y_true.size


def conv2d(img, kernel):
    h, w, c = img.shape
    kh, kw, kc = kernel.shape
    out = np.zeros((h - kh + 1, w - kw + 1))
    for i in range(out.shape[0]):
        for j in range(out.shape[1]):
            region = img[i:i + kh, j:j + kw, :]
            out[i, j] = np.sum(region * kernel)
    return out


def maxpool(img, size=2):
    h, w = img.shape
    new_h, new_w = h // size, w // size
    pooled = np.zeros((new_h, new_w))
    for i in range(new_h):
        for j in range(new_w):
            pooled[i, j] = np.max(img[i * size:(i + 1) * size, j * size:(j + 1) * size])
    return pooled


# ------------------------------------------------------------ vectorized twin
def features_vec(Xb, kernel):
    """Batch conv(valid) -> ReLU -> 2x2 max-pool -> flatten. Xb: (B,64,64,3)."""
    B, H, W, _ = Xb.shape
    kh, kw, _ = kernel.shape
    oh, ow = H - kh + 1, W - kw + 1
    out = np.zeros((B, oh, ow))
    for i in range(kh):
        for j in range(kw):
            out += Xb[:, i:i + oh, j:j + ow, :] @ kernel[i, j, :]
    out = relu(out)
    ph, pw = oh // 2, ow // 2
    pooled = out[:, :ph * 2, :pw * 2].reshape(B, ph, 2, pw, 2).max(axis=(2, 4))
    return pooled.reshape(B, -1)


def features(X, kernel, mode, batch=500):
    if mode == 'loop':
        return np.stack([maxpool(relu(conv2d(img, kernel))).flatten() for img in X])
    return np.concatenate([features_vec(X[i:i + batch], kernel)
                           for i in range(0, len(X), batch)])


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True, help='dir with train/{cat,dog} and test/{cat,dog}')
    ap.add_argument('--conv', choices=['loop', 'vec'], default='loop')
    ap.add_argument('--epochs', type=int, default=10)
    ap.add_argument('--lr', type=float, default=0.001)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--limit', type=int, default=None, help='images per class per split')
    ap.add_argument('--block', type=int, default=1000, help='test block size')
    ap.add_argument('--cache', default=None, help='npz with X_train/y_train/X_test/y_test (uint8)')
    ap.add_argument('--faithful-epochs', type=int, default=0)
    ap.add_argument('--b0', type=float, default=0.0,
                    help='initial FC bias; tutorial uses 0 (see dead-output note)')
    ap.add_argument('--head', choices=['relu', 'linear'], default='relu',
                    help="output activation: tutorial 'relu', or 'linear' (ablation)")
    ap.add_argument('--csv', default=None)
    a = ap.parse_args()
    host = socket.gethostname().split('.')[0]
    res = dict(impl=f'numpy-{a.conv}' + ('-linear' if a.head == 'linear' else ''), host=host, seed=a.seed, epochs=a.epochs,
               python=platform.python_version(), numpy=np.__version__)

    # 1. load (decode + resize). The cache stores the same pixels as uint8.
    t0 = time.perf_counter()
    if a.cache and os.path.exists(a.cache):
        z = np.load(a.cache)
        X_train, y_train = z['X_train'] / 255.0, z['y_train']
        X_test, y_test = z['X_test'] / 255.0, z['y_test']
        res['load_from'] = 'cache'
    else:
        X_train, y_train = load_data(os.path.join(a.data, 'train'), a.limit)
        X_test, y_test = load_data(os.path.join(a.data, 'test'), a.limit)
        res['load_from'] = 'jpeg'
        if a.cache:
            np.savez(a.cache, X_train=np.rint(X_train * 255).astype(np.uint8), y_train=y_train,
                     X_test=np.rint(X_test * 255).astype(np.uint8), y_test=y_test)
    res['load_s'] = time.perf_counter() - t0
    res['n_train'], res['n_test'] = len(X_train), len(X_test)
    print(f"loaded {len(X_train)} train / {len(X_test)} test in {res['load_s']:.1f}s "
          f"({res['load_from']})", flush=True)

    # shuffle the cats-then-dogs training order once
    rng = np.random.default_rng(a.seed)
    perm = rng.permutation(len(X_train))
    X_train, y_train = X_train[perm], y_train[perm]

    # 2. parameters, as in the tutorial but seeded and with the 961-wide FC
    np.random.seed(a.seed)
    conv_filter = np.random.randn(3, 3, 3) * 0.1
    W_fc = np.random.randn(31 * 31, 1) * 0.01
    b_fc = np.full((1,), a.b0)
    res['b0'] = a.b0

    # 3. features for the training set (the conv part of every forward pass)
    t0 = time.perf_counter()
    F_train = features(X_train, conv_filter, a.conv)
    res['feat_train_s'] = time.perf_counter() - t0
    res['feat_ms_per_img'] = 1e3 * res['feat_train_s'] / len(X_train)
    print(f"train features ({a.conv}): {res['feat_train_s']:.2f}s = "
          f"{res['feat_ms_per_img']:.3f} ms/img", flush=True)

    # 4. training: the tutorial's per-image SGD on the FC layer
    act, dact = (relu, relu_derivative) if a.head == 'relu' else (lambda z: z, np.ones_like)
    res['head'] = a.head

    def head(flat, W, b):
        return act(np.dot(flat, W) + b)

    W_init = W_fc.copy()
    t0 = time.perf_counter()
    epoch_loss, epoch_s = [], []
    for epoch in range(a.epochs):
        te = time.perf_counter()
        total_loss = 0
        for i in range(len(F_train)):
            flat = F_train[i]
            label = np.array([y_train[i]])
            y_pred = head(flat, W_fc, b_fc)
            total_loss += mse_loss(label, y_pred)
            grad_y = mse_grad(label, y_pred) * dact(y_pred)
            W_fc -= a.lr * np.outer(flat, grad_y)
            b_fc -= a.lr * grad_y
        epoch_s.append(time.perf_counter() - te)
        if epoch == 0:
            W_after1, b_after1 = W_fc.copy(), b_fc.copy()
        epoch_loss.append(total_loss / len(F_train))
        print(f"Epoch {epoch + 1}/{a.epochs} | Loss: {epoch_loss[-1]:.4f} | {epoch_s[-1]:.2f}s", flush=True)
    res['head_train_s'] = time.perf_counter() - t0
    res['epoch_loss'] = epoch_loss
    # what the tutorial's loop costs: conv inside every forward, every epoch
    res['train_equiv_s'] = a.epochs * res['feat_train_s'] + res['head_train_s']
    res['train_acc'] = float(((head(F_train, W_fc, b_fc)[:, 0] > 0.5) == y_train).mean())
    res['frac_dead_init'] = float((relu(F_train @ W_init + a.b0)[:, 0] <= 0).mean())
    res['frac_dead_train'] = float((head(F_train, W_fc, b_fc)[:, 0] <= 0).mean())

    # 5. evaluation on unseen images, block by block, timed end to end
    order = np.random.default_rng(a.seed + 1).permutation(len(X_test))
    blocks, correct, t_all = [], 0, 0.0
    for s in range(0, len(order), a.block):
        idx = order[s:s + a.block]
        t0 = time.perf_counter()
        pred = (head(features(X_test[idx], conv_filter, a.conv), W_fc, b_fc)[:, 0] > 0.5).astype(int)
        dt = time.perf_counter() - t0
        c = int((pred == y_test[idx]).sum())
        blocks.append(dict(n=len(idx), acc=c / len(idx), s=dt, ms_per_img=1e3 * dt / len(idx)))
        correct += c
        t_all += dt
        print(f"test block {len(blocks)}: {len(idx)} imgs acc={c / len(idx):.4f} "
              f"{dt:.2f}s ({1e3 * dt / len(idx):.3f} ms/img)", flush=True)
    res['test_acc'] = correct / len(order)
    res['test_s'] = t_all
    res['test_ms_per_img'] = 1e3 * t_all / len(order)
    res['test_img_per_s'] = len(order) / t_all
    res['blocks'] = blocks
    print(f"Test Accuracy: {res['test_acc'] * 100:.2f}%  ({res['test_img_per_s']:.0f} img/s)")

    # 6. optional: the tutorial loop verbatim (conv in every forward) for K epochs
    if a.faithful_epochs:
        np.random.seed(a.seed)
        cf = np.random.randn(3, 3, 3) * 0.1
        Wf = np.random.randn(31 * 31, 1) * 0.01
        bf = np.full((1,), a.b0)

        def forward(img):
            conv_out = conv2d(img, cf)
            relu_out = relu(conv_out)
            pooled = maxpool(relu_out)
            flat = pooled.flatten()
            fc_out = relu(np.dot(flat, Wf) + bf)
            return fc_out, flat, pooled, relu_out

        t0 = time.perf_counter()
        for epoch in range(a.faithful_epochs):
            total_loss = 0
            for i in range(len(X_train)):
                label = np.array([y_train[i]])
                y_pred, flat, _, _ = forward(X_train[i])
                total_loss += mse_loss(label, y_pred)
                grad_y = mse_grad(label, y_pred) * relu_derivative(y_pred)
                Wf -= a.lr * np.outer(flat, grad_y)
                bf -= a.lr * grad_y
            print(f"[faithful] Epoch {epoch + 1} | Loss: {total_loss / len(X_train):.4f}", flush=True)
        res['faithful_s_per_epoch'] = (time.perf_counter() - t0) / a.faithful_epochs
        res['faithful_epoch1_loss'] = total_loss / len(X_train) if a.faithful_epochs == 1 else None
        if a.faithful_epochs == 1:  # same computation => same weights after epoch 1
            res['faithful_max_abs_dW'] = float(max(np.abs(Wf - W_after1).max(),
                                                   np.abs(bf - b_after1).max()))
            print(f"[faithful] max |W_faithful - W_cached| after 1 epoch = {res['faithful_max_abs_dW']:.3g}")
        print(f"[faithful] {res['faithful_s_per_epoch']:.1f}s/epoch "
              f"(cached path: feat {res['feat_train_s']:.1f}s + head {epoch_s[0]:.1f}s)")

    print('RESULT ' + json.dumps(res))
    if a.csv:
        import csv
        keys = ['impl', 'host', 'seed', 'epochs', 'n_train', 'n_test', 'load_s', 'feat_train_s',
                'feat_ms_per_img', 'head_train_s', 'train_equiv_s', 'train_acc', 'test_acc',
                'test_s', 'test_ms_per_img', 'test_img_per_s', 'b0', 'head', 'frac_dead_init', 'frac_dead_train',
                'faithful_s_per_epoch', 'faithful_max_abs_dW']
        new = not os.path.exists(a.csv)
        with open(a.csv, 'a', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=keys, extrasaction='ignore')
            if new:
                w.writeheader()
            w.writerow(res)


if __name__ == '__main__':
    main()
