#!/usr/bin/env python3
from _common import start, finish

sc, inp, out, t0 = start("WordCount")
counts = (sc.textFile(inp)
            .flatMap(lambda line: line.split())
            .map(lambda word: (word, 1))
            .reduceByKey(lambda a, b: a + b))
counts.saveAsTextFile(out)
finish(sc, "wordcount", t0)
