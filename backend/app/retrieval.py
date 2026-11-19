"""Hybrid retrieval (SPEC §8): BM25 + multilingual embeddings -> RRF -> exact-name boost -> top-6 -> gate.

Embeddings degrade gracefully: if the ONNX model or the prebuilt index is unavailable, search is BM25-only.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi

from .arabic import normalize_text, tokenize
from .config import EMBED_MODEL
from .store import Store

log = logging.getLogger("concierge.retrieval")

RRF_K = 60
TOP_N = 20
TOP_K = 6

# Words that are present in nearly every question and say nothing about *which* thing is meant.
# The gate requires the remaining "specific" words to be found, so an invented project name cannot
# pass just because "project" and "price" match many chunks.
GENERIC = set("""
a an the is are was were be of in on at to for from by with and or what which who whom whose how when where
why do does did have has had can could would should will tell me about please show give any some your you
i my we our us it its this that these those there their them they price prices cost costs project projects
property properties development developments info information details detail available offer offers know
much many more list all get find see like want need looking look darglobal dar global wasalt home homes
unit units apartment apartments villa villas listing listings city country new latest work works does
ما ماذا هل كم متى اين كيف من في على عن الى الي مع هو هي هذا هذه ذلك تلك لدي لديكم لديك عندكم اريد ابحث
مشروع مشاريع سعر اسعار السعر عقار عقارات معلومات تفاصيل وصلت دار جلوبال شقه شقق فيلا
""".split())


_GENERIC_TOK = set(tokenize(" ".join(GENERIC))) | {normalize_text(g) for g in GENERIC}


def specific_terms(query: str) -> list[str]:
    toks = tokenize(query)
    generic = _GENERIC_TOK
    return [t for t in toks if t not in generic and len(t) >= 3 and not t.isdigit()]


# Small bilingual bridge for BM25 so an Arabic question can match an English page and vice versa.
# (The multilingual embeddings do this too; this keeps BM25-only mode useful.)
BRIDGE = {
    "مزاد": ["auction"], "مزادات": ["auction", "auctions"], "auction": ["مزاد"], "auctions": ["مزادات"],
    "ايجار": ["rent", "ejar"], "ejar": ["ايجار"], "شقق": ["apartments"], "شقه": ["apartment"], "فلل": ["villas"],
    "فيلا": ["villa"], "اجانب": ["foreigners", "expat"], "مقيمين": ["expat", "residents"], "تمليك": ["ownership"],
    "رهن": ["mortgage"], "تمويل": ["finance", "mortgage"], "mortgage": ["تمويل"], "ارض": ["land"], "اراضي": ["lands"],
}


def expand_query(toks: list[str]) -> list[str]:
    out = list(toks)
    for t in toks:
        out += BRIDGE.get(t, [])
    return out


@dataclass
class Hit:
    chunk: dict
    score: float  # fused RRF score (+ boosts)
    bm25: float
    cosine: float | None


class Embedder:
    """Thin wrapper over fastembed (ONNX, CPU, no torch). Returns None if unavailable."""

    def __init__(self, cache_dir: str | None = None):
        self.model = None
        try:
            from fastembed import TextEmbedding  # noqa: WPS433
            kw = {"model_name": EMBED_MODEL}
            if cache_dir:
                kw["cache_dir"] = cache_dir
            self.model = TextEmbedding(**kw)
        except Exception as e:  # pragma: no cover - environment dependent
            log.warning("embedding model unavailable, BM25-only: %s", type(e).__name__)
            self.model = None

    @property
    def ok(self) -> bool:
        return self.model is not None

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = np.array(list(self.model.embed([normalize_text(t) for t in texts])), dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vecs / norms


class Retriever:
    def __init__(self, store: Store, index_dir: str | None = None, embeddings: str = "auto",
                 cache_dir: str | None = None, cos_threshold: float = 0.45, embedder=None):
        self.store = store
        self.chunks = store.chunks
        self.cos_threshold = cos_threshold
        self._tok = [tokenize(c.get("text") or "") or ["_"] for c in self.chunks]
        self.bm25 = BM25Okapi(self._tok) if self.chunks else None
        self.vecs: np.ndarray | None = None
        self.embedder = None
        self.mode = "bm25"
        if embeddings != "off" and self.chunks:
            self._load_vectors(index_dir, cache_dir, embedder)

    def _load_vectors(self, index_dir, cache_dir, embedder):
        ids_path = os.path.join(index_dir or "", "ids.json")
        vec_path = os.path.join(index_dir or "", "embeddings.npy")
        if not (index_dir and os.path.exists(ids_path) and os.path.exists(vec_path)) and embedder is None:
            log.warning("no embedding index at %s; BM25-only", index_dir)
            return
        emb = embedder or Embedder(cache_dir)
        if not emb.ok:
            return
        if embedder is not None and not os.path.exists(vec_path):
            vecs = emb.embed([c.get("text") or "" for c in self.chunks])
        else:
            ids = json.load(open(ids_path, encoding="utf-8"))
            vecs_all = np.load(vec_path)
            pos = {cid: i for i, cid in enumerate(ids)}
            if any(c["id"] not in pos for c in self.chunks):
                log.warning("embedding index is stale (ids mismatch); BM25-only")
                return
            vecs = vecs_all[[pos[c["id"]] for c in self.chunks]]
        self.vecs = vecs.astype(np.float32)
        self.embedder = emb
        self.mode = "hybrid"

    # ------------------------------------------------------------------
    def search(self, query: str, entity_ids: list[str] | None = None, top_k: int = TOP_K,
               filter_fn=None) -> list[Hit]:
        if not self.chunks:
            return []
        qtok = expand_query(tokenize(query))
        n = len(self.chunks)
        bm = np.array(self.bm25.get_scores(qtok), dtype=np.float32) if qtok else np.zeros(n, dtype=np.float32)
        cos = None
        if self.vecs is not None:
            try:
                qv = self.embedder.embed([query])[0]
                cos = self.vecs @ qv
            except Exception as e:  # pragma: no cover
                log.warning("query embedding failed: %s", type(e).__name__)
        allowed = np.ones(n, dtype=bool)
        if filter_fn is not None:
            allowed = np.array([bool(filter_fn(c)) for c in self.chunks])
        fused = np.zeros(n, dtype=np.float32)
        order_bm = [i for i in np.argsort(-bm) if allowed[i] and bm[i] > 0][:TOP_N]
        for r, i in enumerate(order_bm):
            fused[i] += 1.0 / (RRF_K + r + 1)
        if cos is not None:
            order_v = [i for i in np.argsort(-cos) if allowed[i]][:TOP_N]
            for r, i in enumerate(order_v):
                fused[i] += 1.0 / (RRF_K + r + 1)
        # exact-name boost: chunks belonging to an entity named in the query
        ents = set(entity_ids or [])
        if ents:
            for i, c in enumerate(self.chunks):
                if allowed[i] and c.get("entity_id") in ents:
                    fused[i] += 1.0 / RRF_K
        cand = [i for i in np.argsort(-fused) if fused[i] > 0][:top_k]
        return [Hit(self.chunks[i], float(fused[i]), float(bm[i]), float(cos[i]) if cos is not None else None)
                for i in cand]

    def gate(self, query: str, hits: list[Hit], entity_ids: list[str] | None = None) -> bool:
        """Calibrated retrieval gate. True = enough evidence to answer; False -> no_data template."""
        if not hits:
            return False
        if entity_ids and any(h.chunk.get("entity_id") in set(entity_ids) for h in hits):
            return True
        spec = specific_terms(query)
        if spec:
            top_text = set()
            for h in hits[:3]:
                top_text.update(tokenize(h.chunk.get("text") or ""))
            coverage = sum(1 for t in spec if t in top_text) / len(spec)
            if coverage >= 0.5:
                return True
            best_cos = max((h.cosine for h in hits if h.cosine is not None), default=None)
            return best_cos is not None and best_cos >= max(self.cos_threshold + 0.15, 0.6)
        best_cos = max((h.cosine for h in hits if h.cosine is not None), default=None)
        if best_cos is not None:
            return best_cos >= self.cos_threshold
        return hits[0].bm25 > 0
