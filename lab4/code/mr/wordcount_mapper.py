#!/usr/bin/env python3
"""Emit <word>\t1 for every whitespace-separated token on stdin."""
import sys

for line in sys.stdin:
    for word in line.split():
        sys.stdout.write(f"{word}\t1\n")
