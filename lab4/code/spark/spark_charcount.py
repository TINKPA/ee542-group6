#!/usr/bin/env python3
"""Character frequency.  Same escaping as the Streaming version so the two
implementations' outputs are directly diffable."""
from _common import start, finish

ESCAPE = {" ": "<SPACE>", "\t": "<TAB>"}

sc, inp, out, t0 = start("CharCount")
chars = (sc.textFile(inp)
           .flatMap(lambda line: [ESCAPE.get(c, c) for c in line])
           .map(lambda ch: (ch, 1))
           .reduceByKey(lambda a, b: a + b))
chars.saveAsTextFile(out)
finish(sc, "charcount", t0)
