# Lab 7 — Artificial Neural Networks, from NumPy to a Cloud GPU

Report: [EE542_Lab7_Report.pdf](EE542_Lab7_Report.pdf)

| Part | Code | What it does |
|---|---|---|
| I | [`code/part1/mlp_numpy.py`](code/part1/mlp_numpy.py), [`run_examples.py`](code/part1/run_examples.py) | The tutorial's two-layer MLP (SGD + backprop, NumPy only) and its three examples: 1-D regression, concentric rings, three blobs |
| — | [`code/dataset/prepare_catsdogs.py`](code/dataset/prepare_catsdogs.py) | Downloads the Asirra cat/dog images (the Kaggle Dogs vs. Cats pool), drops unreadable files, shuffles, splits 80/20 into `train/{cat,dog}` and `test/{cat,dog}` |
| II | [`code/part2/numpy_cnn.py`](code/part2/numpy_cnn.py) | The tutorial's one-filter CNN in pure NumPy; trains, then tests on unseen images in blocks of 1,000 and times every stage |
| III | [`code/part3/torch_cnn.py`](code/part3/torch_cnn.py) | `CatDogCNN` in PyTorch on CPU or CUDA, with the tutorial's `ImageFolder`/`DataLoader` pipeline or a preloaded-to-GPU pipeline; same block evaluation and timing |
| — | [`code/cloud/run_all.sh`](code/cloud/run_all.sh) | The whole measurement campaign on one cloud GPU, stage by stage (`env_probe.sh`, `gpu_health.sh` first) |

## Running it

```bash
# Part I (any machine with numpy + matplotlib)
cd code/part1 && python run_examples.py

# Data (825 MB download, ~25,000 JPEGs)
python code/dataset/prepare_catsdogs.py --out /root/ds/catsdogs

# Part II
python code/part2/numpy_cnn.py --data /root/ds/catsdogs --conv loop   # tutorial's double loop
python code/part2/numpy_cnn.py --data /root/ds/catsdogs --conv vec    # same arithmetic, vectorized

# Part III
python code/part3/torch_cnn.py --data /root/ds/catsdogs --device cuda --pipeline loader
python code/part3/torch_cnn.py --data /root/ds/catsdogs --device cuda --pipeline preload

# everything, on a cloud GPU box (launch detached)
nohup bash code/cloud/run_all.sh > run_all.log 2>&1 < /dev/null &
```

## Results (RunPod, 1 × NVIDIA L4, EPYC 9254 limited to 5.1 cores)

19,998 training and 5,000 unseen test images, 10 epochs.

| Model | Device | Input | Train 10 epochs | Test throughput | Test accuracy |
|---|---|---|---|---|---|
| 1 filter, NumPy loop (tutorial) | CPU | decoded | 2,647 s | 75 img/s | 53.5 % |
| 1 filter, NumPy vectorized | CPU | decoded | 24.6 s | 4,039 img/s | 50.0–56.5 % |
| 1 filter, PyTorch | GPU | preload | 2.1 s | 517,860 img/s | 52.2 % |
| CatDogCNN | CPU (5 threads) | preload | 85.6 s | 2,749 img/s | 78.3 % |
| CatDogCNN | GPU | DataLoader | 61.2 s | 2,009 img/s | 78.2–80.0 % |
| CatDogCNN | GPU | preload | 5.1 s | 74,741 img/s | 77.9 % |
| CatDogCNN, linear output | GPU | preload | 5.2 s | 74,133 img/s | 77.0–78.4 % |

* With the tutorial's `DataLoader`, the GPU spends 89 % of training time waiting for JPEG decoding; preloading the decoded images into GPU memory makes training 12× faster.
* The tutorial's ReLU on the output layer kills training in half of our runs (output 0 for every image, loss stuck at 0.5). A linear output trained in every seed.

## Fixes to the tutorial code

* Part II `W_fc` must be `31*31 × 1` (64×64 → 3×3 valid conv → 62×62 → 2×2 pool → 31×31), not `32*32*3 × 1`.
* `load_data` returns all cats then all dogs; shuffle before the 80/20 split and before image-by-image SGD.
* Kaggle's `train.zip` has no `cat/` and `dog/` subfolders and `test1.zip` has no labels; `prepare_catsdogs.py` builds the layout `ImageFolder` needs.
* PyTorch: `nn.MSELoss` needs `labels.float().unsqueeze(1)`; with shape `(B,)` against outputs `(B,1)` it silently broadcasts to `B×B`.
* GPU timing needs `torch.cuda.synchronize()` before reading the clock.
