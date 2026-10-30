"""EE542 Lab 9 Part 5: word-cluster histogram embedding.

Steps from the handout, and where they are:
  1. Word2Vec word vectors of dimension N for every word in the data -> train_word2vec()
  2. Our own code to cluster all words into K clusters                -> kmeans()
  3. The centroid vector of each cluster                               -> kmeans() returns them
  4. For each chunk, bin every word into the cluster whose centroid is
     closest, and divide the K-bin histogram by the chunk's word count -> HistEmbedder.embed()

"Try different methods to improve the result": HistConfig switches on each
improvement separately so their effect can be measured (eval_part5.py):
  stopwords    drop function words ("the", "of", "to") before binning
  soft         soft assignment: a word votes for its `soft_m` nearest
               centroids, weighted by exp(-d^2 / tau) instead of one hard bin
  word_idf     a word's vote is weighted by its IDF over chunks, so rare,
               specific words count more than ubiquitous ones
  bin_idf      TF-IDF over bins: scale bin k by log(#chunks / #chunks using k)
  sqrt         Hellinger mapping (square root of the normalized histogram),
               which damps the few dominant bins
Similarity between two histograms is cosine (vectors are L2-normalized at the end).

HistEmbedder also implements LangChain's Embeddings interface, so it can
replace OpenAIEmbeddings in the FAISS vector store and the conversation chain.
"""
from __future__ import annotations

import json
import math
import pickle
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from langchain_core.embeddings import Embeddings

TOKEN = re.compile(r"[a-z][a-z0-9]+")
# PDF line breaks leave words split as "fre- quency" / "fre-\nquency"; join them
# back before tokenizing (otherwise "frequenc" and "quency" become two junk words).
DEHYPHEN = re.compile(r"([a-z])-\s+([a-z])")
# A compact English stopword list (function words only), so the code has no
# extra download dependency.
STOPWORDS = frozenset("""
a about above after again against all am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further
had has have having he her here hers herself him himself his how i if in into is it its itself
just me more most my myself no nor not now of off on once only or other our ours ourselves out
over own same she should so some such than that the their theirs them themselves then there
these they this those through to too under until up very was we were what when where which
while who whom why will with would you your yours yourself yourselves also may might must shall
one two use used using via per e g eg ie etc
""".split())


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(DEHYPHEN.sub(r"\1\2", text.lower()))


# ---------------------------------------------------------------- 1. Word2Vec
_W2V_CACHE: dict = {}


def train_word2vec(token_lists: list[list[str]], n_dim: int = 100, seed: int = 42, epochs: int = 30):
    """Skip-gram Word2Vec on our own chunks. Skip-gram (sg=1) does better than
    CBOW on a corpus this small; min_count=2 drops one-off typos and OCR junk.
    workers=1 + a fixed seed makes the run reproducible."""
    from gensim.models import Word2Vec
    key = (n_dim, seed, epochs, len(token_lists), sum(map(len, token_lists)))
    if key in _W2V_CACHE:      # the improvement sweep re-uses one model per N
        return _W2V_CACHE[key]
    _W2V_CACHE[key] = Word2Vec(sentences=token_lists, vector_size=n_dim, window=5, min_count=2, sg=1,
                    negative=10, epochs=epochs, workers=1, seed=seed)
    return _W2V_CACHE[key]


# ---------------------------------------------------------------- 2-3. k-means (our own)
def kmeans(X: np.ndarray, k: int, iters: int = 100, seed: int = 0, tol: float = 1e-6):
    """Lloyd's k-means with k-means++ seeding, written out in numpy.
    X: (n, d) word vectors. Returns (centroids (k, d), labels (n,), inertia).
    Squared distances use ||x||^2 - 2 x.c + ||c||^2 so each step is one matmul."""
    rng = np.random.default_rng(seed)
    n = len(X)
    x2 = (X * X).sum(1)
    # k-means++: each new seed is drawn with probability proportional to its
    # squared distance from the nearest seed chosen so far.
    C = np.empty((k, X.shape[1]), X.dtype)
    C[0] = X[rng.integers(n)]
    d2 = np.maximum(x2 - 2 * X @ C[0] + C[0] @ C[0], 0)
    for j in range(1, k):
        C[j] = X[rng.choice(n, p=d2 / d2.sum())]
        d2 = np.minimum(d2, np.maximum(x2 - 2 * X @ C[j] + C[j] @ C[j], 0))
    prev = np.inf
    for _ in range(iters):
        D = x2[:, None] - 2 * X @ C.T + (C * C).sum(1)[None, :]
        labels = D.argmin(1)
        inertia = float(D[np.arange(n), labels].sum())
        for j in range(k):
            members = X[labels == j]
            # An empty cluster is re-seeded with the point farthest from its centroid.
            C[j] = members.mean(0) if len(members) else X[D[np.arange(n), labels].argmax()]
        if prev - inertia <= tol * max(prev, 1.0):
            break
        prev = inertia
    return C, labels, inertia


# ---------------------------------------------------------------- 4. histograms
@dataclass
class HistConfig:
    n_dim: int = 100        # N, Word2Vec dimension
    k: int = 200            # K, number of word clusters = histogram bins
    stopwords: bool = False
    soft: bool = False
    soft_m: int = 3
    word_idf: bool = False
    bin_idf: bool = False
    sqrt: bool = False
    normalize_words: bool = True   # cluster unit-length word vectors (cosine geometry)
    seed: int = 42

    def label(self) -> str:
        on = [n for n in ("stopwords", "soft", "word_idf", "bin_idf", "sqrt") if getattr(self, n)]
        return f"N={self.n_dim} K={self.k}" + (" +" + "+".join(on) if on else " baseline")


@dataclass
class HistEmbedder(Embeddings):
    cfg: HistConfig
    vocab: dict[str, int] = field(default_factory=dict)     # word -> row
    word_bins: np.ndarray | None = None      # (V, m) cluster ids per word (m=1 hard, soft_m soft)
    word_wts: np.ndarray | None = None       # (V, m) weight of each of those bins
    word_idf: np.ndarray | None = None       # (V,)
    bin_idf: np.ndarray | None = None        # (K,)
    centroids: np.ndarray | None = None
    tau: float = 1.0

    # -------------------------------------------------- fit
    @classmethod
    def fit(cls, texts: list[str], cfg: HistConfig, log=print) -> "HistEmbedder":
        toks = [tokenize(t) for t in texts]
        w2v = train_word2vec(toks, cfg.n_dim, cfg.seed)
        words = [w for w in w2v.wv.index_to_key if not (cfg.stopwords and w in STOPWORDS)]
        X = np.stack([w2v.wv[w] for w in words]).astype(np.float32)
        if cfg.normalize_words:
            X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
        C, labels, inertia = kmeans(X, cfg.k, seed=cfg.seed)
        self = cls(cfg, vocab={w: i for i, w in enumerate(words)}, centroids=C)

        D = (X * X).sum(1)[:, None] - 2 * X @ C.T + (C * C).sum(1)[None, :]
        D = np.maximum(D, 0)
        if cfg.soft:
            m = cfg.soft_m
            idx = np.argsort(D, axis=1)[:, :m]
            d = np.take_along_axis(D, idx, 1)
            self.tau = float(np.median(d[:, 0])) + 1e-6      # temperature = typical nearest distance
            w = np.exp(-(d - d[:, :1]) / self.tau)
            self.word_bins, self.word_wts = idx, w / w.sum(1, keepdims=True)
        else:
            self.word_bins = labels[:, None]
            self.word_wts = np.ones((len(words), 1), np.float32)

        n_docs = len(texts)
        df = Counter(w for t in toks for w in set(t) if w in self.vocab)
        self.word_idf = np.array([math.log((1 + n_docs) / (1 + df[w])) + 1 for w in words], np.float32)
        if cfg.bin_idf:
            raw = np.stack([self._hist(t, use_bin_idf=False) for t in toks])
            bdf = (raw > 0).sum(0)
            self.bin_idf = np.log((1 + n_docs) / (1 + bdf)).astype(np.float32) + 1
        log(f"{cfg.label()}: vocab {len(words):,} words (of {len(w2v.wv):,}), "
            f"k-means inertia {inertia:.1f}, cluster sizes min/median/max "
            f"{np.bincount(labels, minlength=cfg.k).min()}/{int(np.median(np.bincount(labels, minlength=cfg.k)))}/"
            f"{np.bincount(labels, minlength=cfg.k).max()}")
        self._words, self._labels = words, labels
        return self

    # -------------------------------------------------- embed
    def _hist(self, tokens: list[str], use_bin_idf: bool = True) -> np.ndarray:
        h = np.zeros(self.cfg.k, np.float32)
        n = 0
        for t in tokens:
            if self.cfg.stopwords and t in STOPWORDS:
                continue
            i = self.vocab.get(t)
            if i is None:
                continue          # word Word2Vec never saw: no vector to bin
            v = self.word_idf[i] if self.cfg.word_idf else 1.0
            np.add.at(h, self.word_bins[i], self.word_wts[i] * v)
            n += 1
        if n:
            h /= n                # handout: divide by the number of words in the chunk
        if self.cfg.sqrt:
            h = np.sqrt(h)
        if use_bin_idf and self.bin_idf is not None:
            h = h * self.bin_idf
        return h

    def embed(self, text: str) -> np.ndarray:
        """Normalized K-dim histogram, then L2-normalized so dot product = cosine."""
        h = self._hist(tokenize(text))
        return h / (np.linalg.norm(h) + 1e-9)

    # LangChain Embeddings interface
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t).tolist() for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed(text).tolist()

    # -------------------------------------------------- inspection / persistence
    def raw_histogram(self, text: str) -> np.ndarray:
        """The handout's histogram before the final L2 normalization (bins sum to 1
        for the hard, unweighted baseline)."""
        return self._hist(tokenize(text))

    def clusters(self, top: int = 12) -> list[list[str]]:
        """Most frequent words per cluster (vocab is ordered by frequency)."""
        out = [[] for _ in range(self.cfg.k)]
        for w, c in zip(self._words, self._labels):
            if len(out[c]) < top:
                out[c].append(w)
        return out

    def save(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: str | Path) -> "HistEmbedder":
        with open(path, "rb") as f:
            return pickle.load(f)

    def describe(self) -> str:
        return json.dumps(asdict(self.cfg))
