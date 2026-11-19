"""The lean ONNX loader must reproduce fastembed's vectors (the shipped index was built with fastembed 0.4.2).
Skipped when the model files are not on this machine (CI without the model cache)."""
import os

import numpy as np
import pytest

from backend.app.embedder import LiteEmbedder, find_model_dir
from backend.app.retrieval import is_index_like, stem, strip_header

TEXTS = ["How do Wasalt auctions work?", "كيف تعمل مزادات وصلت؟", "Da Vinci Tower, Interiors By Pagani | Dubai | DarGlobal",
         "", "شقة غرفتين للبيع في الرياض أقل من 1000000 ريال " * 20]


@pytest.fixture(scope="module")
def model_dir():
    d = find_model_dir(os.environ.get("EMBED_CACHE_DIR"))
    if not d:
        pytest.skip("embedding model not available locally")
    return d


def test_lite_matches_fastembed(model_dir):
    fe = pytest.importorskip("fastembed")
    ref = fe.TextEmbedding(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                           cache_dir=os.path.dirname(os.path.dirname(os.path.dirname(model_dir))))
    a = np.array(list(LiteEmbedder(model_dir, threads=1).embed(TEXTS)))
    b = np.array(list(ref.embed(TEXTS)))
    b = b / np.linalg.norm(b, axis=1, keepdims=True)
    assert a.shape == (len(TEXTS), 384) and float((a * b).sum(1).min()) > 0.9999


def test_compact_tokenizer_matches_tokenizer_json(model_dir):
    lite = LiteEmbedder(model_dir, threads=1)
    if lite.sp_tok is None:
        pytest.skip("compact tokenizer not installed next to the model")
    hf = LiteEmbedder._hf_tokenizer(model_dir, {"pad_token_id": 1}, {"pad_token": "<pad>"}, 128)
    for t in TEXTS:
        ids, _ = lite.sp_tok.encode_ids([t])
        assert ids[0].tolist() == hf.encode(t).ids


def test_retrieval_helpers():
    assert strip_header("A | B | Dubai | DarGlobal | Overview: Body text.") == "Body text."
    assert strip_header("Project: X. Site: Wasalt.", {"entity_type": "project"}) == "Project: X. Site: Wasalt."
    assert strip_header("Terms and Conditions: Article 1.", {"entity_type": "page"}) == "Article 1."
    assert stem("auctions") == "auction" and stem("properties") == "property" and stem("access") == "access"
    assert is_index_like("## Auction (14) Riyadh Started on: 16 Nov Ends on: x View Details & Bid")
    assert not is_index_like("Wasalt Auctions is a feature where assets are sold through timed auctions. Bidders compete.")
