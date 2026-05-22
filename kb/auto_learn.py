#!/usr/bin/env python3
"""
kb/auto_learn.py — Session-end oracle auto-learning (Option B).

Runs automatically via the Claude Code Stop hook at the end of every session.
For each MATLAB error the oracle didn't recognise during the session:
  1. Finds it in the most recent session log
  2. Checks whether a subsequent MATLAB call succeeded (validates the fix worked)
  3. Extracts Claude's explanation/fix from the assistant message after the error
  4. Calls oracle.learn(error, fix) to grow the KB permanently

Setup (already configured in ~/.claude/settings.json Stop hook):
  python3 /path/to/matlab-mcp-proxy/kb/auto_learn.py

Run manually after any session:
  python3 kb/auto_learn.py
  python3 kb/auto_learn.py --dry-run   # preview without writing to KB
"""
from __future__ import annotations
import json, os, re, sys, glob, argparse
from pathlib import Path

PROXY_ROOT  = Path(__file__).parent.parent
STORE_DIR   = PROXY_ROOT / 'kb_store'
PENDING_FILE = STORE_DIR / 'pending_errors.jsonl'

# Claude Code session logs for this project
SESSION_DIR = Path.home() / '.claude' / 'projects' / '-Users-soorajkrishnan-simscape-agent'


# ── session log helpers ────────────────────────────────────────────────────────

def latest_session_log() -> Path | None:
    """Return the most recently modified .jsonl session log."""
    logs = sorted(SESSION_DIR.glob('*.jsonl'), key=os.path.getmtime, reverse=True)
    return logs[0] if logs else None


def load_session(path: Path) -> list[dict]:
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def extract_tool_result_text(entry: dict) -> str:
    """Pull text from a 'user' session entry that contains a tool_result."""
    content = entry.get('message', {}).get('content', [])
    for c in content:
        if isinstance(c, dict) and c.get('type') == 'tool_result':
            rc = c.get('content', '')
            if isinstance(rc, str):
                return rc
            if isinstance(rc, list):
                for ic in rc:
                    if isinstance(ic, dict) and ic.get('type') == 'text':
                        return ic.get('text', '')
    return ''


def extract_assistant_text(entry: dict) -> str:
    """Pull the first meaningful text block from an assistant entry."""
    content = entry.get('message', {}).get('content', [])
    for c in content:
        if isinstance(c, dict) and c.get('type') == 'text':
            text = c.get('text', '').strip()
            if len(text) > 30:
                return text
    return ''


def is_matlab_tool_result(entry: dict) -> bool:
    """True if this user entry contains a MATLAB/Simulink tool_result."""
    content = entry.get('message', {}).get('content', [])
    for c in content:
        if isinstance(c, dict) and c.get('type') == 'tool_result':
            return True
    return False


def has_error(text: str) -> bool:
    return bool(re.search(
        r'^(Error|Warning|matlab error|failed to|Error using|Error in)[\s:]',
        text, re.MULTILINE | re.IGNORECASE
    ))


# ── pending error matching ─────────────────────────────────────────────────────

def normalise(text: str) -> str:
    """Normalise for fuzzy matching: lowercase, collapse whitespace, strip paths/numbers."""
    t = text.lower()
    t = re.sub(r"'[^']{3,}'", 'PATH', t)          # strip quoted paths
    t = re.sub(r'\b[\d.e+\-]+\b', 'N', t)          # strip numbers
    t = re.sub(r'\s+', ' ', t)
    return t.strip()[:200]


def load_pending() -> list[dict]:
    if not PENDING_FILE.exists():
        return []
    entries = []
    with open(PENDING_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


# ── main learning logic ────────────────────────────────────────────────────────

def find_fix_in_session(pending_error: str, session: list[dict]) -> str | None:
    """
    Search session log for:
    1. A tool_result containing text similar to pending_error (oracle didn't know it)
    2. Followed by an assistant message explaining the fix
    3. Followed by a successful MATLAB tool_result (no error) — validates fix worked

    Returns the fix description text, or None if not found / fix didn't work.
    """
    norm_error = normalise(pending_error)

    for i, entry in enumerate(session):
        if entry.get('type') != 'user':
            continue
        result_text = extract_tool_result_text(entry)
        if not result_text:
            continue
        # Must look like the pending error (but NOT have an oracle hint — those were matched)
        if result_text.startswith('[ORACLE'):
            continue
        if not has_error(result_text):
            continue
        # Fuzzy match against pending error
        if norm_error not in normalise(result_text) and normalise(result_text) not in norm_error:
            # Try shorter key match (first 80 chars of normalised)
            if norm_error[:80] not in normalise(result_text)[:200]:
                continue

        # Found the error in the session. Now look ahead for:
        # 1. Assistant text (the fix explanation)
        # 2. A successful MATLAB tool_result (validates fix)
        fix_text = None
        validated = False

        for j in range(i + 1, min(i + 12, len(session))):
            next_entry = session[j]
            etype = next_entry.get('type')

            if etype == 'assistant' and fix_text is None:
                text = extract_assistant_text(next_entry)
                if text:
                    # Keep only the first 600 chars, avoid huge explanations
                    fix_text = text[:600]

            elif etype == 'user' and is_matlab_tool_result(next_entry):
                result = extract_tool_result_text(next_entry)
                if result and not has_error(result) and not result.startswith('[ORACLE'):
                    validated = True
                    break
                elif has_error(result):
                    # Another error — fix didn't work, keep looking
                    fix_text = None

        if fix_text and validated:
            return fix_text

    return None


def run(dry_run: bool = False) -> None:
    pending = load_pending()
    if not pending:
        print("[auto_learn] No pending errors to process.")
        return

    log_path = latest_session_log()
    if not log_path:
        print("[auto_learn] No session log found.")
        return

    print(f"[auto_learn] Processing {len(pending)} pending error(s) from session log: {log_path.name}")
    session = load_session(log_path)

    sys.path.insert(0, str(PROXY_ROOT))
    from kb.error_oracle import ErrorOracle
    oracle = ErrorOracle(store_dir=str(STORE_DIR))

    learned, skipped, no_fix = 0, 0, 0

    for item in pending:
        error_text = item.get('error', '').strip()
        if not error_text:
            continue

        # Skip if already in oracle (might have been manually added)
        existing = oracle.query(error_text)
        if existing and existing[1] > 0.88:
            print(f"  [skip] Already in KB (score={existing[1]:.2f}): {error_text[:60]}...")
            skipped += 1
            continue

        fix = find_fix_in_session(error_text, session)
        if not fix:
            print(f"  [no fix] Could not find validated fix for: {error_text[:70]}...")
            no_fix += 1
            continue

        print(f"  [learn] {error_text[:60]}...")
        print(f"    fix: {fix[:80]}...")
        if not dry_run:
            oracle.learn(error_text, fix)
        learned += 1

    print(f"\n[auto_learn] Done — learned: {learned}  skipped: {skipped}  no fix found: {no_fix}")
    print(f"[auto_learn] Oracle KB size: {oracle.size()}")

    # Clear processed entries (keep ones we couldn't fix for next session)
    if not dry_run and (learned + skipped) > 0:
        remaining = []
        processed_norms = set()
        for item in pending:
            e = item.get('error', '')
            existing = oracle.query(e)
            if existing and existing[1] > 0.79:
                processed_norms.add(normalise(e)[:80])
            else:
                remaining.append(json.dumps(item))
        with open(PENDING_FILE, 'w') as f:
            f.write('\n'.join(remaining) + ('\n' if remaining else ''))
        print(f"[auto_learn] Cleared {len(pending) - len(remaining)} processed entries from pending_errors.jsonl")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Auto-learn oracle from session log')
    parser.add_argument('--dry-run', action='store_true', help='Preview without writing to KB')
    args = parser.parse_args()
    run(dry_run=args.dry_run)
