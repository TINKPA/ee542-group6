#!/usr/bin/env python3
"""Sum counts per word.

Hadoop Streaming guarantees that all records with the same key arrive
consecutively, so we fold as we go instead of building a dict of the whole
vocabulary.  The handout's version accumulates every key in memory, which is
fine for a few books and is not fine for the large corpus.
"""
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
