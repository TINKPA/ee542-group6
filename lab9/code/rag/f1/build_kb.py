#!/usr/bin/env python3
"""EE542 Lab 9 Part 4: build the 'f1' knowledge base from the fetched sources.

  python f1/build_kb.py [--rebuild] [--hist]

Each source is ingested under a display name "<Agency>: <Title>.<ext>" so the
bot cites it readably, e.g. [USC OIS: Curricular Practical Training (CPT) p.1];
f1/sources.py maps that name back to the page URL. --hist also builds the
Part 5 histogram index for the same chunks.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rag_core as rc  # noqa: E402
from f1.sources import COLLECTION, RAW, display_name, load_manifest  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--rebuild", action="store_true")
ap.add_argument("--hist", action="store_true")
a = ap.parse_args()
if a.rebuild:
    rc.reset_collection(COLLECTION)
items = [(display_name(m), (RAW / m["file"]).read_bytes()) for m in load_manifest()]
vs = rc.ingest(items, COLLECTION)
stats = rc.collection_stats(COLLECTION)
print(f"\n'{COLLECTION}': {len(stats)} documents, {sum(s['pages'] for s in stats)} pages, "
      f"{sum(s['chars'] for s in stats):,} chars, {sum(s['chunks'] for s in stats)} chunks")
if a.hist:
    rc.build_hist_store(COLLECTION)
