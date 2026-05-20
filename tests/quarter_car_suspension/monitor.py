#!/usr/bin/env python3
"""
Token savings monitor for the Quarter-Car suspension test.
Records each MCP tool_result, applies compression, reports savings.
Usage: from monitor import record; record("step_name", raw_text)
"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from compressor import compress, ratio

LOG_FILE = os.path.join(os.path.dirname(__file__), "savings_log.json")
_log = []


def record(step: str, raw: str) -> str:
    compressed = compress(raw)
    raw_chars   = len(raw)
    comp_chars  = len(compressed)
    saved       = raw_chars - comp_chars
    pct         = saved / raw_chars * 100 if raw_chars else 0

    entry = {
        "step":      step,
        "raw_chars": raw_chars,
        "cmp_chars": comp_chars,
        "saved":     saved,
        "pct":       round(pct, 1),
        "ts":        time.time(),
    }
    _log.append(entry)
    _persist()

    bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
    print(f"\n{'─'*60}")
    print(f"  STEP: {step}")
    print(f"  Raw:        {raw_chars:>6} chars")
    print(f"  Compressed: {comp_chars:>6} chars")
    print(f"  Saved:      {saved:>6} chars  [{bar}] {pct:.0f}%")
    if compressed != raw:
        print(f"\n  ── Compressed preview ──")
        print("  " + "\n  ".join(compressed[:400].split("\n")[:8]))
        if len(compressed) > 400:
            print(f"  ... ({comp_chars} chars total)")
    return compressed


def summary():
    if not _log:
        print("No steps recorded.")
        return
    total_raw  = sum(e["raw_chars"] for e in _log)
    total_comp = sum(e["cmp_chars"] for e in _log)
    total_saved = total_raw - total_comp
    overall_pct = total_saved / total_raw * 100 if total_raw else 0

    print(f"\n{'═'*60}")
    print(f"  QUARTER-CAR TEST — TOKEN SAVINGS SUMMARY")
    print(f"{'═'*60}")
    print(f"  {'Step':<30} {'Raw':>7} {'Saved':>7} {'%':>5}")
    print(f"  {'─'*50}")
    for e in _log:
        print(f"  {e['step']:<30} {e['raw_chars']:>7} {e['saved']:>7} {e['pct']:>4.0f}%")
    print(f"  {'─'*50}")
    print(f"  {'TOTAL':<30} {total_raw:>7} {total_saved:>7} {overall_pct:>4.0f}%")
    print(f"{'═'*60}")
    print(f"  Est. tokens saved (÷4): ~{total_saved//4:,}")
    print(f"  Est. cost saved @ $3/Mtok: ${total_saved/4/1e6*3:.4f}")


def _persist():
    with open(LOG_FILE, "w") as f:
        json.dump(_log, f, indent=2)


if __name__ == "__main__":
    # Print summary of existing log if present
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            _log = json.load(f)
        summary()
    else:
        print("No log yet. Run the test first.")
