#!/usr/bin/env python3
"""EE542 Lab 9 Part 5: measure how well each embedding retrieves the right chunk.

  python eval_part5.py --collection ads                 # improvement ladder
  python eval_part5.py --collection ads --sweep         # also sweep K and N
  python eval_part5.py --collection ads --clusters 8    # print example clusters

Test set (built once, cached in data/part5/qa_<collection>.json): sample chunks
with real prose (>= 250 chars, >= 35 words), and ask gpt-4o-mini for one
question each that the chunk answers, paraphrased rather than copied. A method
scores when it ranks that source chunk high among ALL chunks of the collection.

Metrics: recall@1/@5/@10 (source chunk in the top k), MRR, and page@5 (some
top-5 chunk comes from the same document page, which forgives the 100-char
overlap between neighbouring chunks).

Methods: OpenAI text-embedding-3-small (the Part 3 vectors), BM25 (lexical
reference), mean Word2Vec vector (reference), and the Part 5 histogram with
each improvement switched on in turn.
"""
import argparse
import csv
import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
from sqlalchemy import select

import rag_core as rc
from hist_embed import STOPWORDS, HistConfig, HistEmbedder, tokenize, train_word2vec

HERE = Path(__file__).resolve().parent
DATA = HERE.parent.parent / "data"


def load_chunks(collection):
    d, c = rc.documents, rc.chunks_t
    with rc.db().connect() as conn:
        rows = conn.execute(select(c.c.id, c.c.content, c.c.page, c.c.faiss_id, d.c.filename)
                            .join(d, d.c.id == c.c.document_id)
                            .where(d.c.collection == collection).order_by(c.c.id)).all()
    return [dict(r._mapping) for r in rows]


def build_qa(chunks, n, path, seed=542):
    if path.exists():
        return json.loads(path.read_text())
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(model=rc.CHAT_MODEL, temperature=0.3)
    pool = [c for c in chunks if len(c["content"]) >= 250 and len(tokenize(c["content"])) >= 35
            and c["content"].count(".....") < 3]          # skip table-of-contents dot leaders
    random.Random(seed).shuffle(pool)
    qa = []
    for c in pool[:n]:
        q = llm.invoke(
            "Here is a passage from a technical document.\n\n" + c["content"] +
            "\n\nWrite ONE question a user might ask that this passage answers. Paraphrase: do not "
            "copy more than three consecutive words from the passage. Output only the question.").content
        qa.append({"chunk_id": c["id"], "question": q.strip()})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(qa, indent=1))
    return qa


def metrics(sim, gold_idx, chunks):
    """sim: (Q, M) similarity matrix; gold_idx: index of the source chunk per query."""
    order = np.argsort(-sim, axis=1)
    ranks = np.array([int(np.where(order[i] == g)[0][0]) + 1 for i, g in enumerate(gold_idx)])
    page_hit = [any((chunks[j]["filename"], chunks[j]["page"]) ==
                    (chunks[g]["filename"], chunks[g]["page"]) for j in order[i, :5])
                for i, g in enumerate(gold_idx)]
    return {"R@1": float((ranks <= 1).mean()), "R@5": float((ranks <= 5).mean()),
            "R@10": float((ranks <= 10).mean()), "MRR": float((1 / ranks).mean()),
            "page@5": float(np.mean(page_hit)), "median_rank": float(np.median(ranks))}


def bm25_sim(chunk_toks, q_toks, k1=1.5, b=0.75):
    N = len(chunk_toks)
    df = Counter(t for d in chunk_toks for t in set(d))
    idf = {t: math.log(1 + (N - n + 0.5) / (n + 0.5)) for t, n in df.items()}
    avg = np.mean([len(d) for d in chunk_toks])
    tfs = [Counter(d) for d in chunk_toks]
    lens = np.array([len(d) for d in chunk_toks])
    S = np.zeros((len(q_toks), N))
    for qi, q in enumerate(q_toks):
        for t in set(q):
            if t not in idf:
                continue
            tf = np.array([c[t] for c in tfs], float)
            S[qi] += idf[t] * tf * (k1 + 1) / (tf + k1 * (1 - b + b * lens / avg))
    return S


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", default="ads")
    ap.add_argument("--n-questions", type=int, default=200)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--final", action="store_true", help="large-K grid with every improvement, plus hybrids")
    ap.add_argument("--clusters", type=int, default=0, help="print this many example clusters")
    a = ap.parse_args()

    chunks = load_chunks(a.collection)
    if not chunks:
        sys.exit(f"collection '{a.collection}' is empty")
    texts = [c["content"] for c in chunks]
    pos = {c["id"]: i for i, c in enumerate(chunks)}
    qa = build_qa(chunks, a.n_questions, DATA / "part5" / f"qa_{a.collection}.json")
    questions = [x["question"] for x in qa]
    gold = [pos[x["chunk_id"]] for x in qa]
    print(f"{len(chunks)} chunks, {len(qa)} test questions; e.g. "
          f"\"{questions[0]}\" -> chunk {qa[0]['chunk_id']}\n")

    rows = []

    def record(name, sim, family, extra=""):
        m = metrics(sim, gold, chunks)
        rows.append({"method": name, "family": family, **m, "note": extra})
        print(f"{name:<44} R@1 {m['R@1']:.3f}  R@5 {m['R@5']:.3f}  R@10 {m['R@10']:.3f}  "
              f"MRR {m['MRR']:.3f}  page@5 {m['page@5']:.3f}  median rank {m['median_rank']:.0f}  {extra}")

    # --- OpenAI embeddings (Part 3 vectors from the FAISS index)
    vs = rc.load_vectorstore(a.collection)
    posmap = {v: k for k, v in vs.index_to_docstore_id.items()}
    D = np.stack([vs.index.reconstruct(posmap[c["faiss_id"]]) for c in chunks])
    qcache = DATA / "part5" / f"qvec_openai_{a.collection}.npy"
    if qcache.exists() and len(np.load(qcache)) == len(questions):
        Q = np.load(qcache)
    else:
        Q = np.array(rc.embeddings().embed_documents(questions), np.float32)
        np.save(qcache, Q)
    record(f"OpenAI {rc.EMBED_MODEL} (1536-d)", Q @ D.T, "reference")

    # --- BM25 (lexical) and mean word vector
    ctok = [[t for t in tokenize(x) if t not in STOPWORDS] for x in texts]
    qtok = [[t for t in tokenize(x) if t not in STOPWORDS] for x in questions]
    record("BM25 (k1=1.5, b=0.75)", bm25_sim(ctok, qtok), "reference")
    w2v = train_word2vec([tokenize(x) for x in texts], 100)

    def mean_vec(toks):
        v = [w2v.wv[t] for t in toks if t in w2v.wv]
        m = np.mean(v, 0) if v else np.zeros(100)
        return m / (np.linalg.norm(m) + 1e-9)
    record("mean Word2Vec vector (100-d)", np.stack([mean_vec(t) for t in qtok]) @
           np.stack([mean_vec(t) for t in ctok]).T, "reference")

    # --- histogram embedding: baseline then improvements, one at a time and stacked
    def run(cfg, family="histogram", note=""):
        t0 = time.time()
        emb = HistEmbedder.fit(texts, cfg, log=lambda s: None)
        H = np.stack([emb.embed(x) for x in texts])
        Qh = np.stack([emb.embed(x) for x in questions])
        empty = int((np.linalg.norm(Qh, axis=1) < 0.5).sum())
        record(f"hist {cfg.label()}", Qh @ H.T, family,
               (note + f" fit {time.time() - t0:.0f}s" + (f", {empty} empty queries" if empty else "")).strip())
        return emb

    base = dict(n_dim=100, k=200)
    print()
    emb0 = run(HistConfig(**base), note="handout baseline")
    for flag in ("stopwords", "soft", "word_idf", "bin_idf", "sqrt"):
        run(HistConfig(**base, **{flag: True}), note="single improvement")
    best = dict(base, stopwords=True, word_idf=True, bin_idf=True)
    run(HistConfig(**best), note="stacked")
    run(HistConfig(**best, soft=True), note="stacked")
    run(HistConfig(**best, soft=True, sqrt=True), note="stacked")

    if a.sweep:
        print("\nK / N sweep (stopwords + word_idf + bin_idf + soft)")
        for n_dim in (50, 100, 200):
            for k in (50, 100, 200, 400, 800, 1600):
                run(HistConfig(n_dim=n_dim, k=k, stopwords=True, word_idf=True, bin_idf=True, soft=True),
                    family="sweep")

    if a.final:
        print("\nfinal grid: full stack (+sqrt) at large K, and the ablation that drops word_idf")
        finals = {}
        for n_dim in (100, 200):
            for k in (800, 1600, 3200):
                for widf in (True, False):
                    cfg = HistConfig(n_dim=n_dim, k=k, stopwords=True, soft=True, bin_idf=True, sqrt=True,
                                     word_idf=widf)
                    finals[cfg.label()] = (cfg, run(cfg, family="final"))
        # Improvement: hybrid of the histogram (word-group profile) and the mean
        # Word2Vec vector (overall topic), concatenated with weight alpha.
        cfg, emb = finals[HistConfig(n_dim=100, k=1600, stopwords=True, soft=True, bin_idf=True,
                                     sqrt=True, word_idf=True).label()]
        Hh = np.stack([emb.embed(x) for x in texts]); Qh = np.stack([emb.embed(x) for x in questions])
        Hm = np.stack([mean_vec(t) for t in ctok]); Qm = np.stack([mean_vec(t) for t in qtok])
        for alpha in (0.5, 0.7, 0.85):
            record(f"hybrid {alpha:.2f}*hist(K=1600) + {1 - alpha:.2f}*meanW2V",
                   alpha * (Qh @ Hh.T) + (1 - alpha) * (Qm @ Hm.T), "final")

    if a.clusters:
        print(f"\nexample clusters (K={emb0.cfg.k}, most frequent words first):")
        cl = emb0.clusters()
        rng = random.Random(1)
        for j in rng.sample(range(len(cl)), a.clusters):
            print(f"  cluster {j:3d}: {', '.join(cl[j])}")
        ex = texts[gold[0]]
        h = emb0.raw_histogram(ex)
        top = np.argsort(-h)[:6]
        print(f"\nexample chunk {qa[0]['chunk_id']} ({len(tokenize(ex))} words): "
              + "; ".join(f"bin {b} = {h[b]:.3f} [{', '.join(cl[b][:4])}]" for b in top)
              + f"; bins used {int((h > 0).sum())}/{len(h)}, sum {h.sum():.3f}")

    out = DATA / "raw" / f"part5_eval_{a.collection}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
