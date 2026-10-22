#!/usr/bin/env bash
# EE542 Lab 8: helper to reach the RunPod box from the Mac.
#   POD=host:port ./pod.sh push          # rsync code/ to /root/lab8/code
#   POD=host:port ./pod.sh pull          # rsync data/raw back
#   POD=host:port ./pod.sh ssh '<cmd>'
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lab="$(cd "$here/../.." && pwd)"
host="${POD%:*}"; port="${POD#*:}"
SSH=(ssh -i ~/.ssh/id_ed25519 -p "$port" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=15 "root@$host")
RSH="ssh -i $HOME/.ssh/id_ed25519 -p $port -o StrictHostKeyChecking=accept-new"
case "${1:-}" in
  push) "${SSH[@]}" "mkdir -p /root/lab8/data/raw"
        rsync -rltz --exclude '*.engine' --exclude '*.onnx*' --exclude 'build/' --exclude .DS_Store -e "$RSH" "$lab/code/" "root@$host:/root/lab8/code/" ;;
  pull) rsync -rltz -e "$RSH" "root@$host:/root/lab8/data/raw/" "$lab/data/raw/" ;;
  ssh)  shift; "${SSH[@]}" "$@" ;;
  *) echo "usage: POD=host:port $0 push|pull|ssh <cmd>"; exit 1 ;;
esac
