"""
kb/error_oracle.py — Error→Fix semantic knowledge base.

Architecture:
  - Errors and fixes stored as JSON + numpy vector matrix.
  - On query, embeds error text and does dot-product similarity against all stored vecs.
  - If cosine similarity > THRESHOLD (0.82), returns the matching fix.
  - New pairs learned via learn(error, fix), appended to both stores.

Storage (in kb_store/):
  errors.json  — list of {id, error, fix, learned_at} dicts
  errors.npy   — numpy float32 array of shape (N, 384)

Both files written atomically via temp-file-then-rename.
"""
from __future__ import annotations
import json, os, time
from pathlib import Path
import numpy as np

THRESHOLD = 0.82
DIM       = 384


class ErrorOracle:
    """
    Semantic error→fix knowledge base backed by on-disk vector store.

    Usage:
        oracle = ErrorOracle(store_dir="kb_store/")
        oracle.learn("Derivative of state is not finite", "Set abs tol to 1e-6")
        result = oracle.query("State derivative X is infinite")
        if result:
            fix, score = result
    """

    def __init__(self, store_dir: str = "kb_store"):
        self._dir = Path(store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._json_path = self._dir / "errors.json"
        self._npy_path  = self._dir / "errors.npy"
        self._entries: list[dict] = self._load_json()
        self._vectors: np.ndarray | None = self._load_vectors()

    # ── Public API ─────────────────────────────────────────────────────────────

    def learn(self, error: str, fix: str) -> None:
        """Add a new error→fix pair to the knowledge base."""
        from kb.embedder import embed
        vec = embed(self._normalise(error))
        entry = {
            "id": len(self._entries),
            "error": error,
            "fix": fix,
            "learned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._entries.append(entry)
        self._vectors = vec.reshape(1, DIM) if self._vectors is None \
                        else np.vstack([self._vectors, vec])
        self._save()

    def query(self, error_text: str) -> tuple[str, float] | None:
        """
        Query for the best-matching fix.
        Returns (fix_text, similarity_score) or None if no match above threshold.
        """
        if self._vectors is None or not self._entries:
            return None
        from kb.embedder import embed
        q = embed(self._normalise(error_text))
        scores = self._vectors @ q      # dot product = cosine similarity (unit vecs)
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        if best_score < THRESHOLD:
            return None
        return self._entries[best_idx]["fix"], best_score

    def format_hint(self, error_text: str) -> str | None:
        """
        Returns a compact [ORACLE (score=X.XX): fix] hint string,
        or None if no match above threshold.
        """
        result = self.query(error_text)
        if result is None:
            return None
        fix, score = result
        short_fix = fix[:120] + "..." if len(fix) > 120 else fix
        return f"[ORACLE (score={score:.2f}): {short_fix}]"

    def size(self) -> int:
        return len(self._entries)

    def list_all(self) -> list[dict]:
        return list(self._entries)

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load_json(self) -> list[dict]:
        if not self._json_path.exists():
            return []
        with open(self._json_path) as f:
            return json.load(f)

    def _load_vectors(self) -> np.ndarray | None:
        if not self._entries:
            return None
        if self._npy_path.exists():
            return np.load(str(self._npy_path))
        # Rebuild from stored errors (migration path for JSON-only stores)
        from kb.embedder import embed_batch
        texts = [self._normalise(e["error"]) for e in self._entries]
        return embed_batch(texts)

    def _save(self) -> None:
        # Atomic JSON write
        tmp = self._json_path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(self._entries, f, indent=2)
        tmp.rename(self._json_path)
        # Atomic numpy write
        tmp_npy = self._npy_path.with_suffix(".tmp.npy")
        np.save(str(tmp_npy), self._vectors)
        os.rename(str(tmp_npy), str(self._npy_path))

    @staticmethod
    def _normalise(text: str) -> str:
        """Strip specific block paths and numbers for more robust matching."""
        import re
        text = re.sub(r"'[^']{3,}'", "BLOCK_PATH", text)
        text = re.sub(r'\b\d+\.\d+e[+-]\d+\b', 'N', text)
        text = re.sub(r'\b\d+\.\d+\b', 'N', text)
        return text.strip()
