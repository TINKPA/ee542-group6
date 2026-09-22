#!/usr/bin/env python3
"""Emit <char>\t1 for every character on stdin.

Space and tab are escaped because the tab is Streaming's key/value separator
and a bare space makes the key invisible in the output file.  Newlines are not
counted: Streaming hands us one record per line and has already eaten them.
"""
import sys

ESCAPE = {" ": "<SPACE>", "\t": "<TAB>"}

for line in sys.stdin:
    for ch in line.rstrip("\n"):
        sys.stdout.write(f"{ESCAPE.get(ch, ch)}\t1\n")
