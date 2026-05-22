"""
kb/sim_handles.py — Context handles for simulation results.

When a simulation result is large (>MIN_SIZE_CHARS), the proxy stores the full
output here and returns a compact handle + summary instead. Claude gets ~30 tokens
instead of ~800+, and can request the full output by asking 'expand SimHandle#N'.

Storage (in kb_store/handles/):
  index.json        — {handle_id: file_number} registry
  0000.json, ...    — full output + metadata per handle
"""
from __future__ import annotations
import json, os, re, time
from pathlib import Path


class SimHandleStore:
    """
    Store and retrieve simulation results via lightweight handles.

    Usage:
        store = SimHandleStore("kb_store/")
        handle_id, summary = store.store(full_sim_output, metadata={"model": "PMSM_FOC"})
        # proxy injects summary into Claude's context instead of full output
        full = store.expand(handle_id)   # on 'expand SimHandle#N' request
    """

    MIN_SIZE_CHARS = 50

    def __init__(self, store_dir: str = "kb_store"):
        self._dir = Path(store_dir) / "handles"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "index.json"
        self._index: dict[str, int] = self._load_index()

    # ── Public API ─────────────────────────────────────────────────────────────

    def store(self, full_output: str,
              metadata: dict | None = None) -> tuple[str, str]:
        """
        Store a simulation result. Returns (handle_id, summary).
        If output is below MIN_SIZE_CHARS, returns ("", full_output) — no handle.
        """
        if len(full_output) < self.MIN_SIZE_CHARS:
            return "", full_output

        handle_num = len(self._index)
        handle_id  = f"SimHandle#{handle_num}"
        summary    = self._extract_summary(full_output, metadata)

        record = {
            "handle_id":   handle_id,
            "created_at":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "metadata":    metadata or {},
            "summary":     summary,
            "full_output": full_output,
        }
        out_path = self._dir / f"{handle_num:04d}.json"
        with open(out_path, "w") as f:
            json.dump(record, f, indent=2)

        self._index[handle_id] = handle_num
        self._save_index()
        return handle_id, summary

    def expand(self, handle_id: str) -> str | None:
        """Return the full output for a handle, or None if not found."""
        if handle_id not in self._index:
            return None
        n = self._index[handle_id]
        path = self._dir / f"{n:04d}.json"
        if not path.exists():
            return None
        with open(path) as f:
            return json.load(f)["full_output"]

    def format_for_context(self, handle_id: str, summary: str) -> str:
        """Return a compact string for injection into Claude's context window."""
        return f"[{handle_id}] {summary}"

    # ── Internal ───────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_summary(text: str, metadata: dict | None = None) -> str:
        """Extract key signal values from simulation output for the summary."""
        # Match: signal_name =\n\n   value
        scalar_pat = re.compile(
            r'^(\w+)\s*=\s*\n\n\s+([\d.e+\-]+)\s*$',
            re.MULTILINE
        )
        signals: dict[str, str] = {}
        for m in scalar_pat.finditer(text):
            name, val = m.group(1), m.group(2)
            if name != 'ans':
                signals[name] = val

        # Also pick up "Final X: Y" inline patterns
        for m in re.finditer(r'Final (\w+):\s+([\d.]+)', text, re.IGNORECASE):
            signals.setdefault(m.group(1).lower(), m.group(2))

        if not signals:
            return text[:120].replace('\n', ' ').strip()

        parts = [f"{k}={v}" for k, v in list(signals.items())[:3]]
        summary = ", ".join(parts)

        if metadata:
            meta_str = ", ".join(f"{k}={v}" for k, v in metadata.items())
            summary = f"[{meta_str}] {summary}"

        return summary

    def _load_index(self) -> dict[str, int]:
        if self._index_path.exists():
            with open(self._index_path) as f:
                return json.load(f)
        return {}

    def _save_index(self) -> None:
        tmp = self._index_path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(self._index, f, indent=2)
        tmp.rename(self._index_path)
