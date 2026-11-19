"""Lean ONNX embedder: the same model, tokenizer settings and pooling as fastembed 0.4.2's
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (qdrant ONNX export), without fastembed itself.

Pooling note (measured, not assumed): fastembed 0.4.2 registers this model under OnnxTextEmbedding, which takes the
first-token (CLS) vector and L2-normalises it; it does NOT mean-pool, although the model was trained for mean pooling.
The shipped index was built that way, so this loader reproduces CLS pooling exactly. Switching to mean pooling means
rebuilding the index and re-running E1; `pooling="mean"` is provided for that experiment only.

Why: fastembed's loader roughly doubled resident memory over a bare ONNX Runtime session in our container
(measured: +520 MB vs +245 MB for the same model file), and it pulls Pillow, huggingface_hub, loguru, etc. into the
runtime image. Vectors are numerically the same as fastembed's (checked by backend/tests/test_embedder.py when the
model is available locally), so an index built with either loads with the other.
"""
from __future__ import annotations

import glob
import json
import logging
import os

import numpy as np

log = logging.getLogger("concierge.embedder")

HF_DIR = "models--qdrant--paraphrase-multilingual-MiniLM-L12-v2-onnx-Q"
MODEL_FILE = "model_optimized.onnx"
# Optional compact tokenizer (written at image build by backend/scripts/prepare_tokenizer.py): the model's own
# SentencePiece file plus a SentencePiece-id -> model-id table. It yields the same ids as tokenizer.json (checked on all
# 2,519 dataset chunks + test strings at build time) but uses ~15 MB instead of ~280 MB of resident memory.
SP_MODEL = "sentencepiece.bpe.model"
SP_MAP = "sp_to_hf.npy"


class SPTokenizer:
    """XLM-R style: <s>=0 + mapped pieces (truncated) + </s>=2, padded with pad_id; matches tokenizer.json here."""

    def __init__(self, model_dir: str, max_len: int, pad_id: int):
        import sentencepiece as spm
        self.sp = spm.SentencePieceProcessor(model_file=os.path.join(model_dir, SP_MODEL))
        self.map = np.load(os.path.join(model_dir, SP_MAP))
        self.max_len, self.pad_id = max_len, pad_id

    def encode_ids(self, texts: list[str]) -> tuple[np.ndarray, np.ndarray]:
        rows = [[0] + self.map[np.asarray(self.sp.encode(t), dtype=np.int64)].tolist()[: self.max_len - 2] + [2]
                for t in texts]
        n = max(len(r) for r in rows)
        ids = np.full((len(rows), n), self.pad_id, dtype=np.int64)
        mask = np.zeros((len(rows), n), dtype=np.int64)
        for i, r in enumerate(rows):
            ids[i, :len(r)] = r
            mask[i, :len(r)] = 1
        return ids, mask


def find_model_dir(cache_dir: str | None) -> str | None:
    roots = [r for r in (cache_dir, os.environ.get("FASTEMBED_CACHE_PATH"),
                         os.path.join(os.environ.get("TMP") or os.environ.get("TEMP") or "/tmp", "fastembed_cache"),
                         "/tmp/fastembed_cache") if r]
    for root in roots:
        for snap in sorted(glob.glob(os.path.join(root, HF_DIR, "snapshots", "*"))):
            if all(os.path.exists(os.path.join(snap, f)) for f in
                   (MODEL_FILE, "tokenizer.json", "tokenizer_config.json", "config.json")):
                return snap
    return None


class LiteEmbedder:
    def __init__(self, model_dir: str, threads: int | None = None, pooling: str = "cls"):
        self.pooling = pooling
        import onnxruntime as ort

        with open(os.path.join(model_dir, "config.json"), encoding="utf-8") as f:
            config = json.load(f)
        with open(os.path.join(model_dir, "tokenizer_config.json"), encoding="utf-8") as f:
            tcfg = json.load(f)
        max_len = min(v for v in (tcfg.get("model_max_length"), tcfg.get("max_length")) if v)
        self.sp_tok = None
        if os.path.exists(os.path.join(model_dir, SP_MODEL)) and os.path.exists(os.path.join(model_dir, SP_MAP)):
            try:
                self.sp_tok = SPTokenizer(model_dir, max_len, config.get("pad_token_id", 0))
            except Exception as e:  # pragma: no cover - environment dependent
                log.warning("compact tokenizer unavailable (%s); using tokenizer.json", type(e).__name__)
        self.tokenizer = None if self.sp_tok else self._hf_tokenizer(model_dir, config, tcfg, max_len)
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if threads:
            so.intra_op_num_threads = threads
            so.inter_op_num_threads = 1
        # No arena / memory pattern: the arena keeps the peak of every batch resident forever (measured +90 MB).
        so.enable_cpu_mem_arena = False
        so.enable_mem_pattern = False
        self.session = ort.InferenceSession(os.path.join(model_dir, MODEL_FILE), so,
                                            providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}


    @staticmethod
    def _hf_tokenizer(model_dir, config, tcfg, max_len):
        from tokenizers import AddedToken, Tokenizer
        tok = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        tok.enable_truncation(max_length=max_len)
        tok.enable_padding(pad_id=config.get("pad_token_id", 0), pad_token=tcfg["pad_token"])
        special = os.path.join(model_dir, "special_tokens_map.json")
        if os.path.exists(special):
            with open(special, encoding="utf-8") as f:
                for t in json.load(f).values():
                    if isinstance(t, str):
                        tok.add_special_tokens([t])
                    elif isinstance(t, dict):
                        tok.add_special_tokens([AddedToken(**t)])
        return tok

    def encode_ids(self, texts: list[str]) -> tuple[np.ndarray, np.ndarray]:
        if self.sp_tok is not None:
            return self.sp_tok.encode_ids(texts)
        enc = self.tokenizer.encode_batch(texts)
        return (np.array([e.ids for e in enc], dtype=np.int64), np.array([e.attention_mask for e in enc], dtype=np.int64))

    def embed(self, texts: list[str], batch_size: int = 32):
        for i in range(0, len(texts), batch_size):
            ids, mask = self.encode_ids(texts[i:i + batch_size])
            feed = {"input_ids": ids}
            if "attention_mask" in self.inputs:
                feed["attention_mask"] = mask
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            out = self.session.run(None, feed)[0]
            if self.pooling == "mean":
                m = mask[..., None].astype(np.float32)
                pooled = (out * m).sum(axis=1) / np.maximum(m.sum(axis=1), 1e-9)
            else:  # fastembed 0.4.2 behaviour for this model
                pooled = out[:, 0]
            norms = np.linalg.norm(pooled, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            yield from (pooled / norms).astype(np.float32)
