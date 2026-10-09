#!/usr/bin/env bash
# Part 8 step: CPU convolution sweep, 20 cells x 3 repeats, alone on the box.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "=== Part 8 CPU sweep"; BIN="$here/../part8/conv_cpu" "$here/../part8/sweep_conv.sh"; echo "DONE"
