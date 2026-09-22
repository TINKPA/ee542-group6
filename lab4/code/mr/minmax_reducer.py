#!/usr/bin/env python3
"""Global min/max word frequency.

Correct only with -numReduceTasks 1: with more reducers each task sees one
partition of the key space and emits a partition-local extremum, so the job
would produce several contradictory MIN/MAX lines.
"""
import sys

min_word, min_count = None, None
max_word, max_count = None, None

for line in sys.stdin:
    word, _, val = line.rstrip("\n").partition("\t")
    if not word or not val:
        continue
    try:
        count = int(val)
    except ValueError:
        continue
    if min_count is None or count < min_count:
        min_word, min_count = word, count
    if max_count is None or count > max_count:
        max_word, max_count = word, count

if min_count is not None:
    sys.stdout.write(f"MIN\t{min_word}\t{min_count}\n")
    sys.stdout.write(f"MAX\t{max_word}\t{max_count}\n")
