"""Hybrid retrieval (SPEC §8): BM25 + multilingual embeddings -> RRF -> exact-name boost -> top-6 -> gate.

Embeddings degrade gracefully: if the ONNX model or the prebuilt index is unavailable, search is BM25-only.
"""
from __future__ import annotations

import json
import logging
import os
import re
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


def stem(t: str) -> str:
    """Tiny English plural fold for matching only ("auctions" -> "auction"); Arabic is left to the normaliser."""
    if t.isascii() and len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
        return t[:-3] + "y" if t.endswith("ies") else t[:-1]
    return t


def expand_query(toks: list[str]) -> list[str]:
    out = list(toks)
    for t in toks:
        out += BRIDGE.get(t, [])
        s = stem(t)
        if s != t:
            out.append(s)
    return out


# Pages that list or index other pages (sitemaps, search-result pages, blog indexes). They are kept in the index
# (a listing question may need them) but ranked below content pages for questions that want an explanation.
DEMOTE_PAGE_TYPES = {"sitemap_index", "index", "srp", "guides_index", "listing_index", "search_results"}
DEMOTE_FACTOR = 0.35
# Editorial pages (blog posts, guides, terms, disclaimers). A property question ("cheapest flat for rent") must not be
# answered from one unless it is clearly about the question: the relevance floor below. Starting values from the
# quality council, to be tuned on the eval, not measured yet.
EDITORIAL_PAGE_TYPES = {"guide", "guides_index", "blog", "article", "news", "terms", "disclaimer", "legal", "privacy",
                        "policy"}
_EDITORIAL_URL = re.compile(r"^https?://blog\.|/blog/|/terms|/privacy|/disclaimer|/legal", re.I)
PROPERTY_FLOOR_COS = 0.6
PROPERTY_FLOOR_COVERAGE = 0.5
_TAGS = re.compile(r"<[^>]+>")


def is_index_like(text: str) -> bool:
    """True for chunk text that lists items/prices (e.g. an auctions results page) rather than explains anything."""
    t = re.sub(r"\s+", " ", _TAGS.sub(" ", text or ""))
    listy = len(re.findall(r"\(\d+\)|View Details|Started on|Ends on|Deposit starts", t))
    digits = len(re.findall(r"\d", t)) / max(len(t), 1)
    sentences = len(re.findall(r"[.!?؟](\s|$)", t))
    return listy >= 2 or sentences == 0 or (digits > 0.08 and sentences < 2)


def strip_header(text: str, chunk: dict | None = None) -> str:
    """Drop a contextual chunk header before quoting a chunk in prose.

    Contract C1: headers look like `name_en | name_ar | city, country | site | section: ` and end at the first ': '.
    Older page chunks use `Page title: `. A project fact chunk ("Project: X. Site: ...") is not a header."""
    t = text or ""
    head, sep, rest = t.partition(": ")
    if not sep or len(head) > 240 or "\n" in head or not rest.strip():
        return t
    if " | " in head or (chunk or {}).get("entity_type") == "page":
        return rest
    return t


@dataclass
class Hit:
    chunk: dict
    score: float  # fused RRF score (+ boosts)
    bm25: float
    cosine: float | None


class Embedder:
    """ONNX embeddings on CPU (no torch). Prefers the lean loader (backend/app/embedder.py) on the baked model files;
    falls back to fastembed (which can download the model) when they are not present. `ok` is False if neither works."""

    def __init__(self, cache_dir: str | None = None, prefer_lite: bool = True):
        self.model = None
        self.backend = None
        threads = int(os.environ.get("EMBED_THREADS", "2") or 2)
        if prefer_lite:
            try:
                from .embedder import LiteEmbedder, find_model_dir
                d = find_model_dir(cache_dir)
                if d:
                    self.model, self.backend = LiteEmbedder(d, threads), "onnx"
            except Exception as e:  # pragma: no cover - environment dependent
                log.warning("lean ONNX loader failed (%s); trying fastembed", type(e).__name__)
        if self.model is None:
            try:
                from fastembed import TextEmbedding  # noqa: WPS433
                kw = {"model_name": EMBED_MODEL, "threads": threads}
                if cache_dir:
                    kw["cache_dir"] = cache_dir
                self.model, self.backend = TextEmbedding(**kw), "fastembed"
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
        page_types = {pg["id"]: (pg.get("page_type") or "").lower() for pg in store.pages}
        self._page_types = page_types
        self._demote = np.array([
            (c.get("entity_type") == "page" and page_types.get(c.get("entity_id") or "", "") in DEMOTE_PAGE_TYPES)
            or is_index_like(c.get("text") or "") for c in self.chunks], dtype=bool)
        self.vecs: np.ndarray | None = None
        self.embedder = None
        self.mode = "bm25"
        # ok | stale (index built for another dataset version, or ids mismatch) | bm25_only (no index / no model / off)
        self.index_state = "bm25_only"
        if embeddings != "off" and self.chunks:
            self._load_vectors(index_dir, cache_dir, embedder)

    def _load_vectors(self, index_dir, cache_dir, embedder):
        ids_path = os.path.join(index_dir or "", "ids.json")
        vec_path = os.path.join(index_dir or "", "embeddings.npy")
        meta_path = os.path.join(index_dir or "", "meta.json")
        if not (index_dir and os.path.exists(ids_path) and os.path.exists(vec_path)) and embedder is None:
            log.warning("no embedding index at %s; BM25-only", index_dir)
            return
        if embedder is None and os.path.exists(meta_path):
            # The index is built outside the image and COPYed in; a different dataset version means stale vectors.
            try:
                with open(meta_path, encoding="utf-8") as f:
                    built_for = (json.load(f) or {}).get("dataset_version")
            except (OSError, ValueError):
                built_for = None
            if built_for and built_for != self.store.version:
                log.warning("embedding index is for dataset %s, not %s; BM25-only", built_for, self.store.version)
                self.index_state = "stale"
                return
        if not (embedder is not None and not os.path.exists(vec_path)):
            with open(ids_path, encoding="utf-8") as f:
                ids = json.load(f)
            pos = {cid: i for i, cid in enumerate(ids)}
            if any(c["id"] not in pos for c in self.chunks):
                log.warning("embedding index is stale (ids mismatch); BM25-only")
                self.index_state = "stale"
                return
        emb = embedder or Embedder(cache_dir)
        if not emb.ok:
            return
        if embedder is not None and not os.path.exists(vec_path):
            vecs = emb.embed([c.get("text") or "" for c in self.chunks])
        else:
            # Memory-mapped: the vectors stay in the page cache instead of a private copy per process.
            vecs_all = np.load(vec_path, mmap_mode="r")
            order = [pos[c["id"]] for c in self.chunks]
            vecs = vecs_all if order == list(range(len(order))) and vecs_all.shape[0] == len(order) \
                else np.ascontiguousarray(vecs_all[order])
        self.vecs = vecs if vecs.dtype == np.float32 else vecs.astype(np.float32)
        self.embedder = emb
        self.mode = "hybrid"
        self.index_state = "ok"

    def warm(self) -> None:
        """One embed() at startup so the first user query does not pay the ONNX session warm-up."""
        if self.embedder is not None:
            try:
                self.embedder.embed(["warm up"])
            except Exception as e:  # pragma: no cover
                log.warning("embedding warm-up failed: %s", type(e).__name__)

    # ------------------------------------------------------------------
    def search(self, query: str, entity_ids: list[str] | None = None, top_k: int = TOP_K,
               filter_fn=None, demote_index: bool = False) -> list[Hit]:
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
        if demote_index:  # explanation wanted: content pages before sitemaps / result lists
            fused[self._demote] *= DEMOTE_FACTOR
        cand = [i for i in np.argsort(-fused) if fused[i] > 0][:top_k]
        return [Hit(self.chunks[i], float(fused[i]), float(bm[i]), float(cos[i]) if cos is not None else None)
                for i in cand]

    def is_editorial(self, chunk: dict) -> bool:
        """A blog post, guide, terms or legal page (by page type, or by its URL when the type is missing)."""
        if chunk.get("entity_type") != "page":
            return False
        pt = getattr(self, "_page_types", {}).get(chunk.get("entity_id") or "", "")
        return pt in EDITORIAL_PAGE_TYPES or bool(_EDITORIAL_URL.search(chunk.get("source_url") or ""))

    def relevance_floor(self, query: str, hit: Hit) -> bool:
        """The stricter test for an editorial best hit on a property question: cosine >= PROPERTY_FLOOR_COS AND
        specific-term coverage of that hit >= PROPERTY_FLOOR_COVERAGE. With no embeddings (BM25-only) the cosine
        cannot be shown, so the floor fails and the question goes to the structured data."""
        spec = specific_terms(query)
        toks = set(tokenize(hit.chunk.get("text") or ""))
        coverage = sum(1 for t in spec if t in toks or stem(t) in toks) / len(spec) if spec else 0.0
        return hit.cosine is not None and hit.cosine >= PROPERTY_FLOOR_COS and coverage >= PROPERTY_FLOOR_COVERAGE

    def gate(self, query: str, hits: list[Hit], entity_ids: list[str] | None = None,
             property_intent: bool = False) -> bool:
        """Calibrated retrieval gate. True = enough evidence to answer; False -> no_data template (or, for a property
        question, a reroute to the structured data in chat.py). With `property_intent`, a best hit that is an
        editorial page must also pass relevance_floor()."""
        if not hits:
            return False
        if entity_ids and any(h.chunk.get("entity_id") in set(entity_ids) for h in hits):
            return True
        if property_intent and self.is_editorial(hits[0].chunk) and not self.relevance_floor(query, hits[0]):
            return False
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
