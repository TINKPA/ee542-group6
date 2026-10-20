"""EE542 Lab 7 Part I: the tutorial's three application examples.

Runs Example 1 (1-D piecewise-linear regression), Example 2 (concentric
rings, binary) and Example 3 (three blobs, multiclass) with the tutorial's
data generators and hyperparameters, then writes

  data/raw/part1_<host>.log     everything printed
  data/raw/part1_<host>.csv     per-epoch loss and seconds for each example
  data/lab7_part1_v1.{png,pdf}  fits / decision boundaries / loss curves

Usage:  python run_examples.py [--no-plot]
"""
import argparse
import csv
import os
import platform
import socket
import sys
import time

import numpy as np

from mlp_numpy import MLP2, train

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, '..', '..', 'data'))
HOST = socket.gethostname().split('.')[0]


def target(x):
    return np.maximum(0, 0.5 * x + 0.2) + 0.3 * np.maximum(0, -x + 0.5)


def rings(n=600, inner_r=0.5, gap=0.2, noise=0.06, seed=0):
    rng = np.random.default_rng(seed)
    n2 = n // 2
    theta1 = rng.uniform(0, 2 * np.pi, n2)
    r1 = inner_r + noise * rng.normal(size=n2)
    x1 = np.c_[r1 * np.cos(theta1), r1 * np.sin(theta1)]
    theta2 = rng.uniform(0, 2 * np.pi, n - n2)
    r2 = inner_r + gap + noise * rng.normal(size=n - n2)
    x2 = np.c_[r2 * np.cos(theta2), r2 * np.sin(theta2)]
    X = np.vstack([x1, x2])
    y = np.array([0] * n2 + [1] * (n - n2))
    return X, y


def three_blobs(n=900, seed=0):
    rng = np.random.default_rng(seed)
    means = np.array([[0, 0], [2.5, 0.5], [-2.0, 1.5]])
    cov = np.array([[0.4, 0.0], [0.0, 0.4]])
    Xs, ys = [], []
    for k, m in enumerate(means):
        Xs.append(rng.multivariate_normal(m, cov, size=n // 3))
        ys.append(np.full(n // 3, k))
    return np.vstack(Xs), np.hstack(ys)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-plot', action='store_true')
    args = ap.parse_args()
    os.makedirs(os.path.join(DATA, 'raw'), exist_ok=True)
    print(f"host={HOST} python={platform.python_version()} numpy={np.__version__} "
          f"cpu={platform.processor() or platform.machine()}")
    rows, res = [], {}

    # Example 1: 1-D regression, model 1->32->1
    print("\n== Example 1: 1-D regression (piecewise-linear target)")
    rng = np.random.default_rng(0)
    X = rng.uniform(-2, 2, (400, 1))
    y = target(X) + 0.05 * rng.normal(size=(400, 1))
    m_reg = MLP2(in_dim=1, hidden_dim=32, out_dim=1, mode='regression', seed=1)
    t0 = time.perf_counter()
    L, S = train(m_reg, X, y, epochs=500, lr=1e-2, batch_size=64, weight_decay=1e-4)
    t_reg = time.perf_counter() - t0
    xt = np.linspace(-2, 2, 9).reshape(-1, 1)
    pred = m_reg.forward(xt)
    print("x, target, pred:")
    print(np.array2string(np.hstack([xt, target(xt), pred]), precision=4, suppress_small=True))
    xs = np.linspace(-2, 2, 2001).reshape(-1, 1)
    rmse_noisefree = float(np.sqrt(np.mean((m_reg.predict_proba(xs) - target(xs)) ** 2)))
    print(f"final loss={L[-1]:.5f}  RMSE vs noise-free target on [-2,2]={rmse_noisefree:.4f} "
          f"(noise sd 0.05)  train time={t_reg:.3f}s")
    rows += [('regression', e + 1, l, s) for e, (l, s) in enumerate(zip(L, S))]
    res['reg'] = dict(model=m_reg, X=X, y=y, loss=L)

    # Example 2: concentric rings, 2->64->2
    print("\n== Example 2: binary classification (concentric rings)")
    Xb, yb = rings(n=800, inner_r=0.6, gap=0.5, noise=0.07, seed=1)
    m_bin = MLP2(in_dim=2, hidden_dim=64, out_dim=2, mode='classification', seed=2)
    t0 = time.perf_counter()
    L, S = train(m_bin, Xb, yb, epochs=200, lr=5e-3, batch_size=64, weight_decay=1e-4)
    t_bin = time.perf_counter() - t0
    acc_bin = float((m_bin.forward(Xb).argmax(axis=1) == yb).mean())
    print(f"train accuracy: {acc_bin:.4f}  final loss={L[-1]:.4f}  train time={t_bin:.3f}s")
    rows += [('rings', e + 1, l, s) for e, (l, s) in enumerate(zip(L, S))]
    res['bin'] = dict(model=m_bin, X=Xb, y=yb, loss=L, acc=acc_bin)

    # Example 3: three blobs, 2->64->3
    print("\n== Example 3: multiclass classification (three blobs)")
    Xm, ym = three_blobs(900, seed=4)
    m_multi = MLP2(in_dim=2, hidden_dim=64, out_dim=3, mode='classification', seed=3)
    t0 = time.perf_counter()
    L, S = train(m_multi, Xm, ym, epochs=200, lr=5e-3, batch_size=64)
    t_multi = time.perf_counter() - t0
    acc_multi = float((m_multi.forward(Xm).argmax(1) == ym).mean())
    print(f"train acc: {acc_multi:.4f}  final loss={L[-1]:.4f}  train time={t_multi:.3f}s")
    rows += [('blobs', e + 1, l, s) for e, (l, s) in enumerate(zip(L, S))]
    res['multi'] = dict(model=m_multi, X=Xm, y=ym, loss=L, acc=acc_multi)

    # Extra check: held-out accuracy on fresh draws from the same generators
    Xb2, yb2 = rings(n=800, inner_r=0.6, gap=0.5, noise=0.07, seed=101)
    Xm2, ym2 = three_blobs(900, seed=104)
    print(f"\nheld-out accuracy (new seed): rings={(m_bin.predict_proba(Xb2).argmax(1) == yb2).mean():.4f} "
          f"blobs={(m_multi.predict_proba(Xm2).argmax(1) == ym2).mean():.4f}")

    with open(os.path.join(DATA, 'raw', f'part1_{HOST}.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['example', 'epoch', 'loss', 'epoch_seconds'])
        w.writerows(rows)
    if not args.no_plot:
        plot(res)


def plot(res):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 4, figsize=(15, 3.6))
    r = res['reg']
    xs = np.linspace(-2, 2, 400).reshape(-1, 1)
    ax[0].scatter(r['X'][:, 0], r['y'][:, 0], s=4, c='0.6', label='noisy samples')
    ax[0].plot(xs, target(xs), 'k--', lw=1, label='target')
    ax[0].plot(xs, r['model'].predict_proba(xs), 'C0', lw=2, label='MLP 1-32-1')
    ax[0].set_title('(a) 1-D regression')
    ax[0].legend(fontsize=7, frameon=False)
    for k, (key, title) in enumerate([('bin', '(b) rings'), ('multi', '(c) three blobs')], 1):
        d = res[key]
        X, y = d['X'], d['y']
        pad = 0.4
        gx, gy = np.meshgrid(np.linspace(X[:, 0].min() - pad, X[:, 0].max() + pad, 300),
                             np.linspace(X[:, 1].min() - pad, X[:, 1].max() + pad, 300))
        Z = d['model'].predict_proba(np.c_[gx.ravel(), gy.ravel()]).argmax(1).reshape(gx.shape)
        ax[k].contourf(gx, gy, Z, alpha=0.25, cmap='coolwarm' if key == 'bin' else 'viridis')
        ax[k].scatter(X[:, 0], X[:, 1], c=y, s=5, cmap='coolwarm' if key == 'bin' else 'viridis')
        ax[k].set_title(f"{title}: train acc {d['acc']:.3f}")
        ax[k].set_aspect('equal')
    for key, lab in [('reg', 'regression (MSE)'), ('bin', 'rings (CE)'), ('multi', 'blobs (CE)')]:
        ax[3].plot(np.arange(1, len(res[key]['loss']) + 1), res[key]['loss'], label=lab)
    ax[3].set_yscale('log')
    ax[3].set_xlabel('epoch')
    ax[3].set_title('(d) full-batch loss')
    ax[3].legend(fontsize=7, frameon=False)
    fig.tight_layout()
    for ext in ('png', 'pdf'):
        fig.savefig(os.path.join(DATA, f'lab7_part1_v1.{ext}'), dpi=150)
    print(f"figure -> {os.path.join(DATA, 'lab7_part1_v1.png')}")


if __name__ == '__main__':
    sys.exit(main())
