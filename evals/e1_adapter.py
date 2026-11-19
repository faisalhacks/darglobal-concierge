"""E1 adapter: exposes the real backend Retriever as three ranking functions for evals/experiments.py.

Usage (repo root):
  backend/.venv/Scripts/python.exe evals/experiments.py --only E1 --retrieval-module evals.e1_adapter \
      --bm25 bm25_search --vector vector_search --hybrid hybrid_search

No new ranking logic: bm25 and vector reuse the Retriever's own BM25 scores and embedding matrix;
hybrid is Retriever.search (RRF + exact-name boost), exactly what the app serves.
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.retrieval import Retriever, expand_query, tokenize  # noqa: E402
from backend.app.store import Store  # noqa: E402

_R: Retriever | None = None


def _r() -> Retriever:
    global _R
    if _R is None:
        store = Store.load(os.environ.get("DATA_PATH", "data/concierge.sqlite"))
        _R = Retriever(store, index_dir=os.environ.get("INDEX_DIR", "data/index"),
                       cache_dir=os.environ.get("EMBED_CACHE_DIR") or None)
    return _R


def _rows(order, r: Retriever, k: int):
    return [{"id": r.chunks[i]["id"], "entity_id": r.chunks[i].get("entity_id")} for i in list(order)[:k]]


def bm25_search(q: str, k: int = 6):
    r = _r()
    toks = expand_query(tokenize(q))
    if not toks:
        return []
    s = np.asarray(r.bm25.get_scores(toks))
    return _rows([i for i in np.argsort(-s) if s[i] > 0], r, k)


def vector_search(q: str, k: int = 6):
    r = _r()
    if r.vecs is None:
        raise RuntimeError("embedding index not loaded (mode=bm25)")
    cos = r.vecs @ r.embedder.embed([q])[0]
    return _rows(np.argsort(-cos), r, k)


def hybrid_search(q: str, k: int = 6):
    r = _r()
    return [{"id": h.chunk["id"], "entity_id": h.chunk.get("entity_id")} for h in r.search(q, top_k=k)]
