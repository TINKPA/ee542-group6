#!/usr/bin/env python3
"""Min/max word frequency.

min()/max() are actions, so this job materialises the word counts once and then
scans them twice.  Caching is what stops the second action from recomputing the
whole shuffle -- and it is the cleanest single demonstration of the in-memory
behaviour Section 6's third question asks about, which is why the timing is
reported for the cached and uncached scans separately.
"""
import time

from _common import start, finish

sc, inp, out, t0 = start("MinMax")
counts = (sc.textFile(inp)
            .flatMap(lambda line: line.split())
            .map(lambda word: (word, 1))
            .reduceByKey(lambda a, b: a + b)
            .cache())

t_first = time.time()
min_word = counts.min(key=lambda x: x[1])
t_min = time.time() - t_first

t_second = time.time()
max_word = counts.max(key=lambda x: x[1])
t_max = time.time() - t_second

sc.parallelize([f"MIN\t{min_word[0]}\t{min_word[1]}",
                f"MAX\t{max_word[0]}\t{max_word[1]}"], 1).saveAsTextFile(out)
print("MIN:", min_word)
print("MAX:", max_word)
finish(sc, "minmax", t0, extra=f"min_scan_s={t_min:.3f} max_scan_s={t_max:.3f}")
