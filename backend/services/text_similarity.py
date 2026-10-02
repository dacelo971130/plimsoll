"""Generic bigram TF-IDF cosine similarity — no ML dependency, no embedding
model, pure stdlib (`math`/`collections.Counter`). Extracted from
`backend/services/comparison.py`'s W3 page-alignment signal (where it's
still used, via `build_vectors`/`cosine`, unchanged in behavior) and
generalized from `PageContent` objects to plain strings, so the SAME
validated logic can also rank free-text search candidates — see `rank()`,
used by `backend/services/agent/tools.py`'s `search_text`/`search_history`
to replace naive substring matching with similarity ranking.

Deliberately not a real embedding model (no `sentence-transformers`/`torch`
dependency — this project has none today, see requirements.txt): this is a
sparse, lexical signal, not a dense semantic one. It still beats substring
matching because of the IDF weighting — a query sharing a document's RARE,
distinctive wording scores highly even when phrased differently, while
common/boilerplate wording contributes little. It will not find a true
paraphrase that shares no vocabulary at all; that's the known ceiling of
this approach, not a bug."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

# A "word": a run of Latin letters/digits, or a single CJK character — there's
# no dictionary-based Chinese segmenter in this project, so per-character is
# the cheapest deterministic proxy for "斷詞" (see comparison.py's own
# `_TOKEN_RE`, which this mirrors for the same reason but is kept separate —
# comparison.py's copy also feeds its unrelated step_order_change detection).
TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[一-鿿]")


def text_grams(text: str) -> Counter[str]:
    """Adjacent-token bigrams across the whole string (not a fixed-length
    prefix) — bigrams over single tokens would be too coarse (loses word
    order) and over trigrams+ too sparse for short queries."""
    tokens = TOKEN_RE.findall(text)
    return Counter(a + b for a, b in zip(tokens, tokens[1:]))


Vector = dict[str, float]


@dataclass
class Corpus:
    """Document frequency + size of a fitted batch — enough to vectorize ANY
    text (corpus member or fresh query) against the SAME fixed IDF weights,
    without re-fitting. Separating "fit" (`fit_corpus`) from "vectorize"
    (`vectorize`) — standard IR practice — is what makes caching possible:
    `backend/services/agent/tools.py` fits a session's pages ONCE per agent
    run and reuses the same `Corpus` + precomputed page vectors across every
    `search_text` call in that run, instead of re-fitting per query."""

    doc_freq: Counter[str]
    n_docs: int


def fit_corpus(texts: list[str]) -> Corpus:
    doc_freq: Counter[str] = Counter()
    for t in texts:
        doc_freq.update(text_grams(t).keys())
    return Corpus(doc_freq=doc_freq, n_docs=len(texts))


def vectorize(text: str, corpus: Corpus) -> Vector:
    """TF-IDF (bigram) vector for `text` against an already-fitted `corpus`,
    L2-normalized.

    Smoothed IDF (scikit-learn's TfidfVectorizer default: ln((1+n)/(1+df)) + 1),
    not the textbook ln((1+n)/(1+df)) alone. Without the "+1" floor, a bigram
    that appears in EVERY text in the corpus scores idf=ln(1)=0 and is dropped
    entirely — harmless on a large corpus, but catastrophic on a small one
    (e.g. a single query against a single candidate: their shared wording —
    the very thing that proves they're related — would vanish, leaving only
    the few differing bigrams to decide the score)."""
    grams = text_grams(text)
    weighted = {
        g: count * (math.log((corpus.n_docs + 1) / (corpus.doc_freq.get(g, 0) + 1)) + 1.0) for g, count in grams.items()
    }
    norm = math.sqrt(sum(w * w for w in weighted.values())) or 1.0
    return {g: w / norm for g, w in weighted.items()}


def build_vectors(texts: list[str]) -> list[Vector]:
    """TF-IDF (bigram, corpus = every text passed in) vector per text — each
    text is vectorized against a corpus that includes itself, same as
    `comparison.py`'s page alignment always did. Computed ONCE for the whole
    batch (shared document frequency) rather than pairwise."""
    corpus = fit_corpus(texts)
    return [vectorize(t, corpus) for t in texts]


def cosine(a: Vector, b: Vector) -> float:
    if not a or not b:
        # No signal on at least one side (e.g. no extractable tokens) — never
        # auto-match on "both empty"; a caller with a real reason to treat two
        # empty texts as identical should special-case that itself.
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(g, 0.0) for g, w in a.items())


def rank_against(query: str, corpus: Corpus, candidate_vectors: list[Vector], *, floor: float = 0.05) -> list[tuple[int, float]]:
    """Like `rank()`, but against an already-fitted `corpus` and already-
    vectorized `candidate_vectors` — the cacheable half of ranked search, so
    a caller that already has these (e.g. one per session, reused across
    many queries in one agent run) never re-fits per query."""
    query_vec = vectorize(query, corpus)
    scored = [(i, cosine(query_vec, v)) for i, v in enumerate(candidate_vectors)]
    scored = [(i, s) for i, s in scored if s >= floor]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


def rank(query: str, candidates: list[str], *, floor: float = 0.05) -> list[tuple[int, float]]:
    """Ranks `candidates` by similarity to `query`, descending — the one-off
    retrieval primitive for a caller with no stable corpus worth caching
    (e.g. `search_history`, which re-scans a different set of past sessions
    on every call anyway). Fits the corpus from `[query, *candidates]`
    together, so the IDF weighting reflects this specific batch including the
    query itself. Returns `(candidate_index, score)` pairs, dropping anything
    below `floor` — a conservative default meant to cut only clearly-
    unrelated noise, not to replace the caller's own judgment about whether a
    low-but-nonzero score is still worth showing."""
    if not candidates:
        return []
    corpus = fit_corpus([query, *candidates])
    candidate_vectors = [vectorize(c, corpus) for c in candidates]
    return rank_against(query, corpus, candidate_vectors, floor=floor)
