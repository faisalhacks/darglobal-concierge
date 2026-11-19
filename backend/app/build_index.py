"""Build the embedding index at image-build time.

Usage: python -m backend.app.build_index [--data data/concierge.sqlite] [--out data/index]
Writes <out>/embeddings.npy (float32, L2-normalised), <out>/ids.json, <out>/meta.json.
Exits 0 with a warning (BM25-only at runtime) if the embedding model cannot be loaded.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

import numpy as np

from .config import EMBED_MODEL
from .retrieval import Embedder
from .store import Store


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("DATA_PATH", "data/concierge.sqlite"))
    ap.add_argument("--out", default=os.environ.get("INDEX_DIR", "data/index"))
    ap.add_argument("--cache-dir", default=os.environ.get("EMBED_CACHE_DIR"))
    ap.add_argument("--batch", type=int, default=64)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    store = Store.load(a.data)
    if not store.chunks:
        logging.warning("no chunks found in %s; nothing to index", a.data)
        return 0
    emb = Embedder(a.cache_dir)
    if not emb.ok:
        logging.warning("embedding model unavailable; runtime will be BM25-only")
        return 0
    t0 = time.time()
    texts = [c.get("text") or "" for c in store.chunks]
    parts = [emb.embed(texts[i:i + a.batch]) for i in range(0, len(texts), a.batch)]
    vecs = np.concatenate(parts).astype(np.float32)
    os.makedirs(a.out, exist_ok=True)
    np.save(os.path.join(a.out, "embeddings.npy"), vecs)
    with open(os.path.join(a.out, "ids.json"), "w", encoding="utf-8") as f:
        json.dump([c["id"] for c in store.chunks], f)
    with open(os.path.join(a.out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"model": EMBED_MODEL, "dim": int(vecs.shape[1]), "n": int(vecs.shape[0]),
                   "dataset_version": store.version, "built_s": round(time.time() - t0, 1)}, f)
    logging.info("indexed %d chunks (dim %d) in %.1fs -> %s", vecs.shape[0], vecs.shape[1], time.time() - t0, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
