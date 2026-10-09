#!/usr/bin/env bash
# EE542 Lab 6 Part 7: build libmatrix.so and run the ctypes script on the cloud box.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v nvcc >/dev/null || export PATH="/usr/local/cuda/bin:$PATH"
echo "=== Part 7: build libmatrix.so"
make -s -C "$here/../part7" 2>&1 | grep -v 'nvcc warning' || true
ls -la "$here/../part7/libmatrix.so"
nm -D "$here/../part7/libmatrix.so" | grep ' T gpu_'
echo "=== Part 7: python ctypes"
python3 -c "import numpy; print('numpy', numpy.__version__); numpy.show_config()" 2>&1 | grep -iE 'numpy|blas|lapack|name' | head -8
cd "$here/../part7" && python3 matmul_ctypes.py "$@" | tee "$here/../../data/raw/py_$(hostname -s).log"
echo "DONE"
