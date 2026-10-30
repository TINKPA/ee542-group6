#!/usr/bin/env python3
"""EE542 Lab 9 Part 4: answer-level test of F-1 Compass through the RAG API.

  python f1/eval_qa.py [--embedder openai|hist] [--api http://127.0.0.1:8002]

Twelve real student questions, each with the key fact(s) a correct answer must
state (regexes, checked case-insensitively) and the agencies whose pages hold
that fact, plus one out-of-scope question that must be declined. The expected
facts were checked against the fetched sources (data/f1/raw), not written
from memory. Output: data/raw/part4_eval_<embedder>.json and a summary table.
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent.parent.parent / "data" / "raw"

CASES = [
    ("When can I apply for post-completion OPT?",
     [r"90 days", r"60 days"], {"USCIS", "USC OIS", "eCFR", "SEVP"}),
    ("How many hours a week can I work on campus while classes are in session?",
     [r"20 hours"], {"USC OIS", "SEVP", "eCFR"}),
    ("Can I do CPT in my first semester as a graduate student?",
     [r"(one|1) (full )?academic year|first semester|immediate"], {"USC OIS", "eCFR", "SEVP", "ICE"}),
    ("If I do 12 months of full-time CPT, can I still get OPT?",
     [r"(not|no longer) (be )?eligible|ineligible|lose"], {"USC OIS", "eCFR", "SEVP", "ICE"}),
    ("How many days of unemployment are allowed during post-completion OPT?",
     [r"90 days"], {"USCIS", "USC OIS", "SEVP", "eCFR"}),
    ("How many days of unemployment do I get in total with the STEM OPT extension?",
     [r"150 days"], {"USC OIS", "SEVP", "USCIS"}),
    ("How long is the STEM OPT extension?",
     [r"24[- ]month"], {"USCIS", "SEVP", "USC OIS", "eCFR"}),
    ("When should I apply for the STEM OPT extension?",
     [r"90 days"], {"USCIS", "USC OIS", "SEVP", "eCFR"}),
    ("What form does my employer and I complete for a STEM OPT training plan?",
     [r"I-983"], {"SEVP", "USC OIS", "USCIS", "eCFR"}),
    ("How long is the grace period after I complete my program?",
     [r"60[- ]day"], {"USC OIS", "eCFR", "SEVP"}),
    ("What do I need to re-enter the U.S. after traveling abroad as an F-1 student?",
     [r"I-20", r"passport", r"visa"], {"USC OIS", "SEVP"}),
    ("Can I take a reduced course load because of a medical condition, and for how long?",
     [r"12 months|twelve months"], {"USC OIS", "eCFR", "SEVP"}),
]
OUT_OF_SCOPE = "What is the best pizza place near the USC campus?"


def ask(api, q, embedder):
    req = urllib.request.Request(f"{api}/ask", data=json.dumps(
        {"question": q, "embedder": embedder}).encode(), headers={"Content-Type": "application/json"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read()), time.time() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8002")
    ap.add_argument("--embedder", default="openai")
    a = ap.parse_args()
    results, passed = [], 0
    for q, facts, agencies in CASES:
        out, dt = ask(a.api, q, a.embedder)
        ans = out["answer"]
        hit = [bool(re.search(f, ans, re.I)) for f in facts]
        src = {s["agency"] for s in out["sources"]}
        ok = all(hit) and bool(src & agencies) and "Not legal advice" in ans
        passed += ok
        results.append({"question": q, "ok": ok, "facts": dict(zip(facts, hit)), "sources": sorted(src),
                        "seconds": round(dt, 1), "answer": ans})
        print(f"{'PASS' if ok else 'FAIL'}  {dt:4.1f}s  {q}\n      facts {hit}  sources {sorted(src)}")
        if not ok:
            print("      " + ans.replace("\n", " ")[:400])
    out, dt = ask(a.api, OUT_OF_SCOPE, a.embedder)
    declined = out["answer"].strip().startswith("I can only help with F-1") and "Not legal advice" not in out["answer"]
    print(f"{'PASS' if declined else 'FAIL'}  {dt:4.1f}s  [out of scope] {OUT_OF_SCOPE}\n      {out['answer'][:200]}")
    results.append({"question": OUT_OF_SCOPE, "ok": declined, "answer": out["answer"]})
    total = len(CASES) + 1
    passed += declined
    print(f"\n{passed}/{total} passed ({a.embedder} retrieval)")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"part4_eval_{a.embedder}.json").write_text(json.dumps(results, indent=1))
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
