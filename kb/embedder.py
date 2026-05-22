"""
kb/embedder.py — Shared sentence-transformer embedder (lazy-loaded singleton).

Uses BAAI/bge-small-en-v1.5: 384-dim, ~130MB, CPU-only, no GPU needed.
Model downloads once to ~/.cache/huggingface/hub/ on first use (~5s).
Subsequent calls use the cached model (~50ms to load into memory).
"""
from __future__ import annotations
import numpy as np
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_model: "SentenceTransformer | None" = None
MODEL_NAME = "BAAI/bge-small-en-v1.5"


def _get_model() -> "SentenceTransformer":
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed(text: str) -> np.ndarray:
    """Embed a single text string → float32 numpy array of shape (384,)."""
    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.astype(np.float32)


def embed_batch(texts: list[str]) -> np.ndarray:
    """Embed a list of strings → float32 array of shape (N, 384)."""
    model = _get_model()
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=32)
    return vecs.astype(np.float32)
