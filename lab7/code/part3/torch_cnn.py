"""EE542 Lab 7 Part III: the cats-vs-dogs CNN in PyTorch, on the GPU.

Models
  catdog  the tutorial's CatDogCNN: conv 3->16 and 16->32 (3x3, pad 1), each
          ReLU + 2x2 max-pool, FC 32*16*16 -> 128 -> 1, ReLU on every layer
          including the output.
  --head linear drops the output ReLU (ablation: the ReLU output can start
          with every sample at 0, where its gradient is 0 and training never moves).
  tiny    the Part II NumPy model rebuilt in PyTorch: one 3x3x3 conv filter
          (frozen, no bias), ReLU, 2x2 max-pool, FC 961 -> 1, ReLU. Same
          arithmetic as numpy_cnn.py, so CPU-vs-GPU on it isolates the hardware.

Training follows the tutorial: MSELoss on labels cat 0 / dog 1, Adam lr 1e-3,
predict dog when output > 0.5.

Input pipelines
  loader   the tutorial's: ImageFolder + Resize((64,64)) + ToTensor + DataLoader
           (JPEG decode on CPU workers every epoch).
  preload  decode every image once into one uint8 tensor that lives on the
           device; batches are index slices. Same pixels, no per-epoch decode.
           This separates the GPU's compute time from the input pipeline.

Timing uses time.perf_counter around torch.cuda.synchronize(), so queued
kernels are counted. Test images are evaluated in blocks (--block) of unseen
images, each block timed end to end including its input pipeline.

Prints per-epoch lines and one 'RESULT {json}' line; --csv appends a row.

Usage:
  python torch_cnn.py --data DIR [--model catdog|tiny] [--device cuda|cpu]
                      [--pipeline loader|preload] [--epochs 10] [--batch 64]
                      [--workers 4] [--seed 0] [--limit N] [--csv out.csv]
"""
import argparse
import csv
import json
import os
import socket
import time

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Subset
from torchvision import datasets, transforms


class CatDogCNN(nn.Module):
    def __init__(self, head='relu'):
        super().__init__()
        self.head = head
        self.conv1 = nn.Conv2d(3, 16, 3, padding=1)   # 64x64 -> pool -> 32x32
        self.conv2 = nn.Conv2d(16, 32, 3, padding=1)  # 32x32 -> pool -> 16x16
        self.fc1 = nn.Linear(32 * 16 * 16, 128)
        self.fc2 = nn.Linear(128, 1)

    def forward(self, x):
        x = F.max_pool2d(F.relu(self.conv1(x)), 2)
        x = F.max_pool2d(F.relu(self.conv2(x)), 2)
        x = torch.flatten(x, 1)
        x = F.relu(self.fc1(x))
        x = self.fc2(x)
        return F.relu(x) if self.head == 'relu' else x


class TinyCNN(nn.Module):
    """numpy_cnn.py in PyTorch: frozen single 3x3x3 filter, FC 961 -> 1."""

    def __init__(self, head='relu'):
        super().__init__()
        self.head = head
        self.conv = nn.Conv2d(3, 1, 3, bias=False)    # 64 -> 62, pool -> 31
        self.conv.weight.data.normal_(0, 0.1)
        self.conv.weight.requires_grad_(False)
        self.fc = nn.Linear(31 * 31, 1)
        self.fc.weight.data.normal_(0, 0.01)
        self.fc.bias.data.zero_()

    def forward(self, x):
        x = F.max_pool2d(F.relu(self.conv(x)), 2)
        x = self.fc(torch.flatten(x, 1))
        return F.relu(x) if self.head == 'relu' else x


def sync(dev):
    if dev.type == 'cuda':
        torch.cuda.synchronize()


def balanced_subset(ds, limit):
    if not limit:
        return ds
    keep, seen = [], {}
    for i, (_, y) in enumerate(ds.samples):
        if seen.get(y, 0) < limit:
            keep.append(i)
            seen[y] = seen.get(y, 0) + 1
    return Subset(ds, keep)


def preload(ds, dev, workers):
    """Decode a dataset once into a uint8 (N,3,64,64) tensor on dev."""
    to_u8 = transforms.Compose([transforms.Resize((64, 64)), transforms.PILToTensor()])
    base = ds.dataset if isinstance(ds, Subset) else ds
    base.transform = to_u8
    dl = DataLoader(ds, batch_size=512, shuffle=False, num_workers=workers)
    xs, ys = zip(*dl)
    return torch.cat(xs).to(dev), torch.cat(ys).to(dev)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True)
    ap.add_argument('--model', choices=['catdog', 'tiny'], default='catdog')
    ap.add_argument('--device', default='cuda')
    ap.add_argument('--head', choices=['relu', 'linear'], default='relu',
                    help="output activation: tutorial 'relu', or 'linear' (ablation)")
    ap.add_argument('--pipeline', choices=['loader', 'preload'], default='loader')
    ap.add_argument('--epochs', type=int, default=10)
    ap.add_argument('--batch', type=int, default=64)
    ap.add_argument('--lr', type=float, default=1e-3)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--threads', type=int, default=0, help='torch CPU threads (0 = default)')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--limit', type=int, default=None, help='images per class per split')
    ap.add_argument('--block', type=int, default=1000)
    ap.add_argument('--csv', default=None)
    a = ap.parse_args()

    device = torch.device("cuda" if a.device == 'cuda' and torch.cuda.is_available() else "cpu")
    print("Using device:", device, flush=True)
    if a.threads:
        torch.set_num_threads(a.threads)
    torch.manual_seed(a.seed)
    res = dict(impl=f'torch-{a.model}-{device.type}-{a.pipeline}' + ('-linear' if a.head == 'linear' else ''),
               head=a.head, host=socket.gethostname().split('.')[0],
               model=a.model, device=device.type, pipeline=a.pipeline, seed=a.seed, epochs=a.epochs,
               batch=a.batch, workers=a.workers, torch=torch.__version__,
               threads=torch.get_num_threads(),
               gpu=torch.cuda.get_device_name(0) if device.type == 'cuda' else None)

    # data: the tutorial's transform pipeline
    transform = transforms.Compose([transforms.Resize((64, 64)), transforms.ToTensor()])
    train_ds = balanced_subset(datasets.ImageFolder(os.path.join(a.data, 'train'), transform), a.limit)
    test_ds = balanced_subset(datasets.ImageFolder(os.path.join(a.data, 'test'), transform), a.limit)
    classes = (train_ds.dataset if isinstance(train_ds, Subset) else train_ds).classes
    assert classes == ['cat', 'dog'], classes
    res['n_train'], res['n_test'] = len(train_ds), len(test_ds)
    g = torch.Generator().manual_seed(a.seed)
    pin = device.type == 'cuda'
    train_loader = DataLoader(train_ds, batch_size=a.batch, shuffle=True, generator=g,
                              num_workers=a.workers, pin_memory=pin, persistent_workers=a.workers > 0)
    images, labels = next(iter(train_loader))
    print(f"batch: images {tuple(images.shape)} {images.dtype}, labels {tuple(labels.shape)}; "
          f"classes {classes}; {len(train_ds)} train / {len(test_ds)} test", flush=True)

    if a.pipeline == 'preload':
        t0 = time.perf_counter()
        Xtr, Ytr = preload(train_ds, device, a.workers)
        Xte, Yte = preload(test_ds, device, a.workers)
        sync(device)
        res['preload_s'] = time.perf_counter() - t0
        print(f"preloaded {tuple(Xtr.shape)} + {tuple(Xte.shape)} uint8 to {device} "
              f"in {res['preload_s']:.1f}s", flush=True)

    model = (CatDogCNN(a.head) if a.model == 'catdog' else TinyCNN(a.head)).to(device)
    res['params_trainable'] = sum(p.numel() for p in model.parameters() if p.requires_grad)
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=a.lr)

    def train_batches():
        if a.pipeline == 'loader':
            yield from train_loader
        else:
            perm = torch.randperm(len(Xtr), generator=g).to(device)
            for s in range(0, len(perm), a.batch):
                idx = perm[s:s + a.batch]
                yield Xtr[idx], Ytr[idx]

    def prep(images, labels):
        images = images.to(device, non_blocking=True)
        if images.dtype == torch.uint8:
            images = images.float().div_(255)
        return images, labels.to(device, non_blocking=True).float().unsqueeze(1)

    # warm-up step (cuDNN autotune, CUDA context) not timed, then reset weights
    state = {k: v.clone() for k, v in model.state_dict().items()}
    xb, yb = prep(images, labels)
    criterion(model(xb), yb).backward()
    optimizer.zero_grad()
    model.load_state_dict(state)
    optimizer = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=a.lr)
    sync(device)

    epoch_s, epoch_wait_s, epoch_loss, epoch_acc = [], [], [], []
    for epoch in range(a.epochs):
        model.train()
        sync(device)
        t0 = time.perf_counter()
        wait, total, n, correct = 0.0, 0.0, 0, 0
        tw = time.perf_counter()
        for images, labels in train_batches():
            sync(device)
            wait += time.perf_counter() - tw   # time spent waiting for the batch
            images, labels = prep(images, labels)
            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            total += loss.detach() * len(labels)
            correct += ((outputs.detach() > 0.5).float() == labels).sum()
            n += len(labels)
            tw = time.perf_counter()
        sync(device)
        epoch_s.append(time.perf_counter() - t0)
        epoch_wait_s.append(wait)
        epoch_loss.append(float(total) / n)
        epoch_acc.append(float(correct) / n)
        print(f"Epoch {epoch + 1}/{a.epochs} | Loss: {epoch_loss[-1]:.4f} | train acc {epoch_acc[-1]:.4f} "
              f"| {epoch_s[-1]:.2f}s (waiting for data {wait:.2f}s)", flush=True)
    res.update(train_s=sum(epoch_s), epoch_s=epoch_s, epoch_wait_s=epoch_wait_s,
               epoch_loss=epoch_loss, epoch_acc=epoch_acc,
               train_img_per_s=a.epochs * len(train_ds) / sum(epoch_s))

    # evaluation on unseen images, block by block
    model.eval()
    if a.pipeline == 'loader':
        test_loader = DataLoader(test_ds, batch_size=a.block, shuffle=True,
                                 generator=torch.Generator().manual_seed(a.seed + 1),
                                 num_workers=a.workers, pin_memory=pin)
        blocks_iter = iter(test_loader)
    else:
        perm = torch.randperm(len(Xte), generator=torch.Generator().manual_seed(a.seed + 1)).to(device)
        blocks_iter = ((Xte[perm[s:s + a.block]], Yte[perm[s:s + a.block]])
                       for s in range(0, len(perm), a.block))
    blocks, correct, n, t_all, dead = [], 0, 0, 0.0, 0
    with torch.no_grad():
        while True:
            sync(device)
            t0 = time.perf_counter()
            try:
                images, labels = next(blocks_iter)
            except StopIteration:
                break
            images, labels = prep(images, labels)
            outputs = model(images)
            pred = (outputs > 0.5).float()
            c = int((pred == labels).sum())
            sync(device)
            dt = time.perf_counter() - t0
            dead += int((outputs <= 0).sum())
            blocks.append(dict(n=len(labels), acc=c / len(labels), s=dt, ms_per_img=1e3 * dt / len(labels)))
            correct += c
            n += len(labels)
            t_all += dt
            print(f"test block {len(blocks)}: {len(labels)} imgs acc={c / len(labels):.4f} {dt * 1e3:.1f} ms "
                  f"({1e3 * dt / len(labels):.4f} ms/img)", flush=True)
    res.update(test_acc=correct / n, test_s=t_all, test_ms_per_img=1e3 * t_all / n,
               test_img_per_s=n / t_all, test_frac_output_zero=dead / n, blocks=blocks)
    if device.type == 'cuda':
        res['max_mem_MB'] = torch.cuda.max_memory_allocated() / 2**20
    print(f"Test Accuracy: {res['test_acc'] * 100:.2f}% | train {res['train_s']:.1f}s "
          f"({res['train_img_per_s']:.0f} img/s) | test {res['test_img_per_s']:.0f} img/s")
    print('RESULT ' + json.dumps(res))
    if a.csv:
        keys = ['impl', 'host', 'model', 'head', 'device', 'pipeline', 'gpu', 'seed', 'epochs', 'batch', 'workers',
                'threads', 'n_train', 'n_test', 'params_trainable', 'preload_s', 'train_s', 'train_img_per_s',
                'test_acc', 'test_s', 'test_ms_per_img', 'test_img_per_s', 'test_frac_output_zero']
        new = not os.path.exists(a.csv)
        with open(a.csv, 'a', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=keys, extrasaction='ignore')
            if new:
                w.writeheader()
            w.writerow({**res, 'train_acc_last': epoch_acc[-1]})


if __name__ == '__main__':
    main()
