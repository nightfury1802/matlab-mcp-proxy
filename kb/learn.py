#!/usr/bin/env python3
"""
kb/learn.py — Manually teach the oracle a new error→fix pair.

Use this when you want to add a fix immediately (Option A: manual).
For automatic learning at session end, see kb/auto_learn.py (Option B).

Usage:
    python3 kb/learn.py "exact MATLAB error text" "what fixed it"
    python3 kb/learn.py   (interactive prompts)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from kb.error_oracle import ErrorOracle

STORE = os.path.join(os.path.dirname(__file__), '..', 'kb_store')


def main():
    if len(sys.argv) == 3:
        error_text = sys.argv[1].strip()
        fix_text   = sys.argv[2].strip()
    elif len(sys.argv) == 1:
        print("=== Oracle: Add new error→fix pair ===")
        error_text = input("MATLAB error/warning text: ").strip()
        fix_text   = input("What fixed it:             ").strip()
    else:
        print("Usage: python3 kb/learn.py \"error text\" \"fix text\"")
        sys.exit(1)

    if not error_text or not fix_text:
        print("Both fields are required.")
        sys.exit(1)

    oracle = ErrorOracle(store_dir=STORE)
    before = oracle.size()

    existing = oracle.query(error_text)
    if existing and existing[1] > 0.92:
        fix, score = existing
        print(f"Near-duplicate already in KB (score={score:.2f}):\n  {fix[:100]}")
        if input("Add anyway? [y/N] ").strip().lower() != 'y':
            print("Skipped.")
            return

    oracle.learn(error_text, fix_text)
    print(f"Learned. KB: {before} → {oracle.size()} entries")


if __name__ == '__main__':
    main()
