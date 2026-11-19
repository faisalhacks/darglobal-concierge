"""Build-time helper: install the compact SentencePiece tokenizer next to the ONNX model (backend/app/embedder.py).

  python backend/scripts/prepare_tokenizer.py <model_snapshot_dir> <sentencepiece.bpe.model> [check.txt ...]

Writes <dir>/sentencepiece.bpe.model and <dir>/sp_to_hf.npy (SentencePiece id -> tokenizer.json id, unknown -> 3),
then checks that both tokenizers give identical ids on built-in strings and on every line of the optional check
files. Exits 1 on any mismatch, so a Docker build cannot ship a tokenizer that changes the vectors.
Standalone on purpose (stdlib + numpy + tokenizers + sentencepiece): it runs in the model-download build stage.
"""
from __future__ import annotations

import json
import os
import shutil
import sys

import numpy as np
import sentencepiece as spm
from tokenizers import Tokenizer

SAMPLES = ["How do Wasalt auctions work?", "كيف تعمل مزادات وصلت؟", "مَا هِيَ المَشَارِيعُ فِي دُبَيّ؟",
           "Tell me عن المشاريع في دبي", "7&8 Albert Hall Mansions, Overlooking Hyde Park, London", "", "  x  ",
           "Da Vinci Tower, Interiors By Pagani | Dubai, United Arab Emirates | DarGlobal | Overview: " * 6,
           "شقة غرفتين للبيع في الرياض أقل من 1000000 ريال", "Price from: 2,766,120 SAR. Status: Ready to Move-in."]


def main(argv: list[str]) -> int:
    model_dir, sp_src, checks = argv[0], argv[1], argv[2:]
    shutil.copyfile(sp_src, os.path.join(model_dir, "sentencepiece.bpe.model"))
    sp = spm.SentencePieceProcessor(model_file=os.path.join(model_dir, "sentencepiece.bpe.model"))
    hf = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
    vocab = hf.get_vocab()
    table = np.array([vocab.get(sp.id_to_piece(i), 3) for i in range(sp.get_piece_size())], dtype=np.int32)
    np.save(os.path.join(model_dir, "sp_to_hf.npy"), table)
    with open(os.path.join(model_dir, "tokenizer_config.json"), encoding="utf-8") as f:
        tcfg = json.load(f)
    max_len = min(v for v in (tcfg.get("model_max_length"), tcfg.get("max_length")) if v)
    hf.enable_truncation(max_length=max_len)
    texts = list(SAMPLES)
    for path in checks:
        with open(path, encoding="utf-8") as f:
            texts += [ln.rstrip("\n") for ln in f]
    bad = 0
    for t in texts:
        a = hf.encode(t).ids
        b = [0] + table[np.asarray(sp.encode(t), dtype=np.int64)].tolist()[: max_len - 2] + [2]
        if a != b:
            bad += 1
            print("tokenizer mismatch:", t[:60], file=sys.stderr)
    print(f"compact tokenizer: {len(texts)} strings checked, {bad} mismatches")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
