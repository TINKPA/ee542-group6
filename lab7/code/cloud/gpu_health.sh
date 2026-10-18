#!/usr/bin/env bash
# EE542 Lab 7: is this pod's GPU healthy? Lab 6 met an L4 stuck at 210 MHz
# with the hardware power brake on (every kernel 6-7x slow). Prints the
# throttle state and times an fp32 4096^3 torch matmul (healthy L4 ~ 9-12 ms;
# fp32 peak 30 TFLOP/s, ~13 sustained at 72 W). Exits 1 if hw_slowdown is
# active or the matmul is > 2x the expected time.
set -uo pipefail
nvidia-smi --query-gpu=name,clocks.sm,clocks.max.sm,power.draw,power.limit,pstate,clocks_throttle_reasons.active,clocks_throttle_reasons.hw_slowdown --format=csv
python3 - <<'PY'
import sys, time, torch, subprocess
torch.backends.cuda.matmul.allow_tf32 = False
a = torch.randn(4096, 4096, device='cuda'); b = torch.randn_like(a)
for _ in range(3): a @ b
torch.cuda.synchronize(); ts = []
for _ in range(10):
    t = time.perf_counter(); a @ b; torch.cuda.synchronize(); ts.append(time.perf_counter() - t)
ms = sorted(ts)[5] * 1e3
tf = 2 * 4096**3 / (ms / 1e3) / 1e12
hw = subprocess.run(['nvidia-smi', '--query-gpu=clocks_throttle_reasons.hw_slowdown',
                     '--format=csv,noheader'], capture_output=True, text=True).stdout.strip()
print(f"fp32 matmul 4096: {ms:.2f} ms = {tf:.1f} TFLOP/s; hw_slowdown={hw}")
name = torch.cuda.get_device_name(0)
if hw != 'Not Active' or ('L4' in name and ms > 25):
    print("UNHEALTHY -> terminate this pod and provision another"); sys.exit(1)
print("HEALTHY")
PY
