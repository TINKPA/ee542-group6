#!/usr/bin/env python3
"""Sum counts per character.  Same streaming fold as wordcount_reducer.py."""
import sys

cur, total = None, 0
for line in sys.stdin:
    key, _, val = line.rstrip("\n").partition("\t")
    if not val:
        continue
    if key != cur:
        if cur is not None:
            sys.stdout.write(f"{cur}\t{total}\n")
        cur, total = key, 0
    total += int(val)

if cur is not None:
    sys.stdout.write(f"{cur}\t{total}\n")
