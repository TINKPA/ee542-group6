# Lab 8 — CNN Inference on Network Packets with NVIDIA DOCA

Report: EE542_Lab8_Report.pdf (added with the final submission)

| Part | Code | What it does |
|---|---|---|
| 1 | [`code/part1/setup.sh`](code/part1/setup.sh), [`check.sh`](code/part1/check.sh) | Package install for an Ubuntu 22.04 GPU box; version census (GPU, driver, CUDA, PyTorch, TensorRT, DPDK) saved to `data/raw/env_<host>.txt` |
| 2 | [`code/part2/export_onnx.py`](code/part2/export_onnx.py), [`build_engine.py`](code/part2/build_engine.py) | ResNet-18 → ONNX (FP32 + FP16, dynamic batch, dynamo exporter with external `.onnx.data`); TensorRT engine build with an optimization profile covering batch 1–32 (OPT=8) |
| 2 | [`code/part2/trt_runner.py`](code/part2/trt_runner.py), [`bench.py`](code/part2/bench.py), [`opt_profile_check.py`](code/part2/opt_profile_check.py) | GPU-buffer inference (`set_tensor_address` + `execute_async_v3`, dedicated stream); the batch 1/8/32 benchmark with logit check against PyTorch; the OPT-profile ablation |
| 3 | [`code/part3/gen_pcap.py`](code/part3/gen_pcap.py) | 16 test images → UDP packets (22-byte header + ≤1,400 B data, 108 packets/image) → `images.pcap`; `--shuffle`, `--dup`, `--noise` variants |
| 4 | [`code/part4/dpdk_rx.c`](code/part4/dpdk_rx.c), [`run_rx.sh`](code/part4/run_rx.sh), [`verify.py`](code/part4/verify.py) | DPDK receiver on the pcap vdev: header checks, port filter, out-of-order reassembly via per-frame bitmap, dedup, idle-timeout end condition; byte-for-byte verification |
| 5 | [`code/part5/classify.py`](code/part5/classify.py) | Rebuilt images → pinned H2D copy → GPU preprocessing → FP16 engine; class check against the originals and copy/preprocess/inference timing |
| 6 | [`code/part6/*.sh`](code/part6/) | Docker + Container Toolkit check; `doca_caps` census; `gpunetio_simple_receive` build (sm_89 added to compile and link flags) and run; open-source GPUNetIO build and `gpunetio_verbs_write_lat` |
| — | [`code/cloud/`](code/cloud/) | RunPod helper (`pod.sh push|pull|ssh`), the Parts 1–5 campaign (`run_part2_5.sh`), measurement-only rerun, and the full-VM Part 6 runbook (`run_part6_vm.sh`) |

Raw measurement logs: [`data/raw/`](data/raw/) (RunPod host `4455d4060973`, DOCA-container host `f15e15e5dba0`, AWS VM `ip-172-31-36-82`).

## Running it

```bash
# Parts 1–5 on a GPU box (RunPod L4, Ubuntu 22.04), detached
nohup bash code/cloud/run_part2_5.sh > data/raw/run25.log 2>&1 < /dev/null &

# or stage by stage
bash code/part1/setup.sh && bash code/part1/check.sh
python code/part2/export_onnx.py && python code/part2/build_engine.py
python code/part2/bench.py                       # batch 1/8/32 table + logit check
python code/part3/gen_pcap.py --out images.pcap  # --shuffle / --dup 0.05 / --noise
bash  code/part4/run_rx.sh                       # three PCAPs, receive + verify
python code/part5/classify.py                    # classify rebuilt images, time the copy

# Part 6 on a full GPU VM (AWS g6.xlarge, NVIDIA driver AMI), exactly as prescribed
bash code/cloud/run_part6_vm.sh
```

## Results (RunPod, 1 × NVIDIA L4; TensorRT 11.4, driver 580/CUDA 13.0)

**Inference** (OPT=8 engines, dedicated stream, mean of 500 runs after 50 warm-ups):

| Implementation | batch 1 | batch 8 | batch 32 |
|---|---|---|---|
| PyTorch FP32 | 0.992 ms · 1,008 img/s | 2.636 ms · 3,035 img/s | 10.259 ms · 3,119 img/s |
| TensorRT FP32 | 1.218 ms · 0.82× | 2.229 ms · 1.18× | 8.528 ms · 1.20× |
| TensorRT FP16 | 0.364 ms · 2.73× | **0.626 ms · 4.21× · 12,789 img/s** | 2.602 ms · 3.94× |

max |Δlogit| vs PyTorch FP32 over 1,024 inputs: 0.011 (TRT FP32), 0.035 (TRT FP16); top-1 agreement 100% for both. The batch-1 FP32 slowdown is the optimization profile: an OPT=1 engine runs 0.783 ms (see `opt_profile_check.py`).

**Receive + reassembly** (16 images × 108 packets):

| PCAP | Received | Accepted | Dropped | Images byte-exact |
|---|---|---|---|---|
| in order | 1,728 | 1,728 | 0 | 16/16 |
| shuffled | 1,728 | 1,728 | 0 | 16/16 |
| shuffled + 5% dup + foreign traffic | 1,914 | 1,728 | 186 (86 dup, 50 non-IPv4, 50 port) | 16/16 |

pcap vdev sustains 0.75–0.8 Mpps; `imissed`/`ierrors`/`rx_nombuf` all zero.

**Copy vs. inference** (pinned memory): 12.6 µs for 1 image (11.9 GB/s), 182 µs for 16 (13.3 GB/s); copy share of the GPU-side path grows 3.1% → 11.7% from batch 1 to 16. All 16 rebuilt images classify identically to their originals.

**DOCA / GPUNetIO**: `doca_caps` reports DOCA 3.5.0098 and 21 libraries but "No DOCA device was found" on both a RunPod DOCA container and the AWS VM. `simple_receive` stops in `init_doca_device` (container: `/dev/infiniband` not mounted, unprivileged, netdev namespaced away; host card is a ConnectX-4 Lx, below GPUNetIO's ConnectX-6 Dx minimum. VM: ENA vNIC only, no Mellanox device). The open-source GPUNetIO builds with `CUDA_ARCH=89` and stops in `open_ib_device()`, same root cause.

## Pitfalls

* TensorRT warns and inserts syncs on PyTorch's legacy default stream; run `execute_async_v3` on a dedicated `torch.cuda.Stream()`.
* One optimization profile cannot be fastest at every batch: kernels are chosen for OPT (engines built at OPT=1/8/32 each win their own column).
* The dynamo ONNX exporter writes weights to a separate `.onnx.data`; keep it next to the `.onnx` and load with `parser.parse_from_file()`.
* In the DOCA container on a driver-595 host, drop `/usr/local/cuda-13/compat` from `LD_LIBRARY_PATH` (the 580 forward-compat libcuda breaks CUDA init).
* Open-source GPUNetIO: `make -j install install_examples` races (examples link before the library lands); run `make install` then `make install_examples`.
* The pcap port never reports end-of-file; the receiver needs its own end condition (500 ms idle, or `--expect N`).
