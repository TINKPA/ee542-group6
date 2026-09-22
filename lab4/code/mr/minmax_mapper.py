#!/usr/bin/env python3
"""Identity mapper for the second pass over /output_wordcount.

The handout runs minmax_reducer.py straight off the raw text, where every
mapper record is "<word>\t1", so MIN and MAX are both 1 and the job answers
nothing.  Min/max over word *frequencies* needs the wordcount output as input,
which means a second job whose mapper only passes records through.
Malformed lines (a word containing a tab) are dropped rather than crashing the
task.
"""
import sys

for line in sys.stdin:
    key, _, val = line.rstrip("\n").partition("\t")
    if not key or not val:
        continue
    try:
        int(val)
    except ValueError:
        continue
    sys.stdout.write(f"{key}\t{val}\n")
