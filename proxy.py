#!/usr/bin/env python3
"""
matlab-mcp-proxy — transparent MCP stdio proxy with output compression.

Handles both wire formats automatically:
  - Newline-delimited JSON  (matlab-mcp-server, old binary)
  - Content-Length framing  (matlab-mcp-core-server, SATK binary)

Claude → proxy → upstream MCP server
         (compress tool_result text only, never touch requests)

Usage:
  python3 proxy.py --upstream /path/to/server [server-args...]
  python3 proxy.py --bypass --upstream /path/to/server [...]
"""
import sys, os, json, asyncio, argparse, logging, time
import os as _os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compressor import compress
import re as _re

_RESULT_FLOAT_RE = _re.compile(
    r'(?:=\s*|:\s*)(-?\d*\.\d+(?:[eE][+-]?\d+)?|-?\d+\.\d*(?:[eE][+-]?\d+)?)',
    _re.MULTILINE
)

def _extract_result_floats(text: str) -> list:
    """Extract floats that appear after = or : (result-context values only)."""
    return _RESULT_FLOAT_RE.findall(text)

def _floats_preserved(original: str, compressed: str):
    """Return None if all floats are preserved, or the offending float string if corruption detected.

    Catches value corruption (0.0847 -> 0.847) while allowing deliberate removal.
    Every value present in compressed must have existed in original.
    """
    comp_floats = _extract_result_floats(compressed)
    if not comp_floats:
        return None
    orig_floats = _extract_result_floats(original)
    orig_vals = []
    for f in orig_floats:
        try:
            orig_vals.append(float(f))
        except ValueError:
            pass
    for cf in comp_floats:
        if cf in original:
            continue  # exact string match — fast path
        try:
            cv = float(cf)
        except ValueError:
            continue
        tol = max(abs(cv) * 1e-9, 1e-15)
        if not any(abs(ov - cv) <= tol for ov in orig_vals):
            return cf  # return the offending value
    return None

log = logging.getLogger("matlab-proxy")

_TESTED_VERSION_PREFIXES = ("0.",)  # tested against 0.x; update when upgrading binary

def _check_protocol_version(msg: dict) -> None:
    """Warn if upstream MCP server reports a version outside the tested range."""
    try:
        server_info = msg.get("result", {}).get("serverInfo", {})
        if not server_info:
            return
        version = server_info.get("version", "")
        if version and not any(version.startswith(p) for p in _TESTED_VERSION_PREFIXES):
            log.warning(
                f"MCP server version '{version}' is outside tested range "
                f"{_TESTED_VERSION_PREFIXES} — compression rules may be unsafe. "
                f"Consider running with --bypass until rules are re-validated."
            )
    except Exception:
        pass

_kb_staleness_warned = False

def _get_pending_path() -> str:
    return _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'kb_store', 'pending_errors.jsonl')

def _check_kb_staleness() -> "str | None":
    """Return a one-line warning if pending_errors.jsonl has >10 unprocessed entries.

    Called once per proxy session on the first tool result. Stays silent after that.
    """
    global _kb_staleness_warned
    if _kb_staleness_warned:
        return None
    _kb_staleness_warned = True  # set early, even if we error out
    try:
        path = _get_pending_path()
        with open(path) as f:
            count = sum(1 for _ in f)
        if count > 10:
            return (
                f"[proxy-kb] WARNING: {count} unseen errors in pending_errors.jsonl — "
                f"run `python3 kb/auto_learn.py` to drain (runs auto at session end)\n"
            )
    except Exception:
        pass
    return None

_oracle = None
_handle_store = None
_pending_methods: dict = {}  # request_id → method name, tracks in-flight requests

def _get_handle_store():
    global _handle_store
    if _handle_store is None:
        from kb.sim_handles import SimHandleStore
        store = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'kb_store')
        _handle_store = SimHandleStore(store_dir=store)
    return _handle_store

def _get_oracle():
    global _oracle
    if _oracle is None:
        from kb.error_oracle import ErrorOracle
        store = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'kb_store')
        _oracle = ErrorOracle(store_dir=store)
    return _oracle


# ── oracle auto-logging ───────────────────────────────────────────────────────

def _log_unseen_error(error_text: str) -> None:
    """Log errors the oracle didn't recognise to kb_store/pending_errors.jsonl.
    Claude reads this file after fixing an error and calls kb/learn.py to teach
    the oracle — making KB growth automatic without manual intervention.
    """
    try:
        store = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'kb_store')
        path  = _os.path.join(store, 'pending_errors.jsonl')
        entry = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "error": error_text.strip()[:800]})
        with open(path, 'a') as f:
            f.write(entry + '\n')
    except Exception:
        pass   # never crash the proxy over logging


# ── compression ──────────────────────────────────────────────────────────────

from router import route, OutputType as _OutputType
# Module-level import: startup failure is intentional — broken router crashes the proxy loudly.
# The startup self-test (selftest.py, Task 3) is the safety net that catches this first.


def _compress_response(msg: dict, bypass: bool) -> dict:
    """Compress text in tool_result messages. Requests pass through unchanged."""
    if bypass:
        return msg
    try:
        content = msg.get("result", {}).get("content", [])
        if not isinstance(content, list):
            return msg
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "text":
                log.debug(f"Skipping non-text content item type={item.get('type')!r} — passing through unchanged")
                continue
            original = item["text"]
            compressed, otype = route(original)

            # Float integrity check — run BEFORE prepending oracle hints
            # (oracle hints contain score=0.XX floats not in original, which would falsely trigger)
            if compressed != original:
                corrupted_float = _floats_preserved(original, compressed)
                if corrupted_float is not None:
                    log.warning(
                        f"Float integrity check failed — value {corrupted_float!r} in compressed "
                        f"not found in original ({len(original)} chars). Check compressor rules."
                    )
                    compressed = original
                else:
                    pct = (1 - len(compressed) / len(original)) * 100
                    log.debug(f"Compressed {len(original)}→{len(compressed)} chars ({pct:.0f}%)")
                    # Stats counter
                    import os
                    stats_file = os.path.expanduser("~/.hermes/logs/proxy_compression_stats.txt")
                    with open(stats_file, "a") as sf:
                        sf.write(f"{len(original)} {len(compressed)}\n")

            # Only augment with oracle/handle data after float check passes
            if otype in (_OutputType.ERROR, _OutputType.WARNING):
                oracle = _get_oracle()
                hint = oracle.format_hint(original)
                if hint:
                    compressed = hint + "\n" + compressed
                else:
                    # No match — log for auto-learning after fix is found
                    _log_unseen_error(original)
            elif otype == _OutputType.SIM_RESULT and len(original) > 300:
                hs = _get_handle_store()
                handle_id, summary = hs.store(original)
                if handle_id:
                    compressed = hs.format_for_context(handle_id, summary)
            # Inject KB staleness note (once per proxy session, first text content item)
            staleness_note = _check_kb_staleness()
            if staleness_note:
                compressed = staleness_note + compressed
            item["text"] = compressed
    except (KeyError, TypeError, AttributeError):
        pass
    return msg


# ── message framing ───────────────────────────────────────────────────────────

class _Frame:
    """Detected wire format for one message."""
    __slots__ = ("kind", "cl_sep")

    def __init__(self, kind, cl_sep=b""):
        self.kind   = kind      # "cl" | "nl"
        self.cl_sep = cl_sep    # separator line between header and body


async def _read_message(reader: asyncio.StreamReader):
    """
    Read one complete MCP message.
    Returns (frame, payload_bytes) or (None, None) on EOF.
    Supports Content-Length framing and newline-delimited JSON.
    """
    try:
        line = await reader.readline()
    except Exception:
        return None, None
    if not line:
        return None, None

    if line.lower().startswith(b"content-length:"):
        try:
            n = int(line.split(b":", 1)[1].strip())
        except ValueError:
            return _Frame("nl"), line
        # Drain ALL header lines (servers may send Content-Type etc.) until blank separator
        while True:
            sep = await reader.readline()
            if sep in (b"\r\n", b"\n", b""):
                break
        try:
            body = await reader.readexactly(n)
        except asyncio.IncompleteReadError as e:
            body = e.partial
        return _Frame("cl"), body
    else:
        return _Frame("nl"), line


def _serialize(frame: _Frame, payload: bytes) -> bytes:
    """Serialize payload back to wire format matching the detected framing."""
    if frame.kind == "cl":
        sep  = frame.cl_sep if frame.cl_sep else b"\r\n"
        header = f"Content-Length: {len(payload)}\r\n".encode()
        return header + sep + payload
    else:
        return payload if payload.endswith(b"\n") else payload + b"\n"


# ── oracle MCP resource helpers ──────────────────────────────────────────────

def _augment_resources_list(msg: dict) -> dict:
    """Inject oracle resource entries into a resources/list MCP response."""
    try:
        result = msg.get("result", {})
        resources = result.get("resources")
        if not isinstance(resources, list):
            return msg
        oracle = _get_oracle()
        entries = oracle.list_all()
        if not entries:
            return msg
        oracle_resources = [
            {
                "uri": "oracle://errors/recent",
                "name": f"Error Oracle — {len(entries)} known fixes",
                "description": (
                    "Known MATLAB/Simscape errors with verified fixes. "
                    "Read oracle://errors/recent for all, or "
                    "oracle://errors/query/<url-encoded-error-text> for nearest-match lookup."
                ),
                "mimeType": "text/plain",
            }
        ]
        msg["result"]["resources"] = resources + oracle_resources
    except Exception:
        pass
    return msg


def _handle_oracle_read(req: dict) -> dict:
    """Handle oracle://errors/* resource reads directly without forwarding to upstream."""
    req_id = req.get("id")
    uri = req.get("params", {}).get("uri", "")

    def _make_response(text: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "contents": [{"uri": uri, "mimeType": "text/plain", "text": text}]
            }
        }

    try:
        oracle = _get_oracle()

        if uri == "oracle://errors/recent":
            entries = oracle.list_all()
            if not entries:
                return _make_response("Oracle KB is empty — no errors have been learned yet.")
            lines = [
                f"[{i}] {e.get('handle', e.get('error', ''))[:120]}\n    Fix: {e.get('fix', '')[:200]}"
                for i, e in enumerate(entries[-20:])
            ]
            return _make_response(
                f"Oracle KB — {len(entries)} entries (showing last 20):\n\n" + "\n\n".join(lines)
            )

        if "/query/" in uri:
            from urllib.parse import unquote_plus
            query = unquote_plus(uri.split("/query/", 1)[1])
            result = oracle.query(query)
            if result is None:
                return _make_response(
                    f"No match found for: {query[:200]!r}\n\n"
                    f"Try broader terms or check oracle://errors/recent."
                )
            fix, score = result
            return _make_response(f"Oracle match (score={score:.2f}):\n\n{fix}")

        return _make_response(
            "Oracle URI formats:\n"
            "  oracle://errors/recent          — list last 20 known fixes\n"
            "  oracle://errors/query/<encoded> — URL-encoded error text lookup"
        )
    except Exception as exc:
        return _make_response(f"Oracle error: {exc!r}")


# ── forwarding coroutines ─────────────────────────────────────────────────────

async def _forward_requests(stdin_reader: asyncio.StreamReader,
                             proc_stdin: asyncio.StreamWriter):
    """Claude → proxy → upstream: pass requests through, short-circuit oracle reads."""
    while True:
        frame, payload = await _read_message(stdin_reader)
        if frame is None:
            break
        try:
            req = json.loads(payload.decode())
            req_id = req.get("id")
            method = req.get("method", "")
            if req_id is not None:
                _pending_methods[req_id] = method
                # Evict oldest entry if dict grows too large (defensive: dropped responses)
                if len(_pending_methods) > 1000:
                    oldest = next(iter(_pending_methods))
                    _pending_methods.pop(oldest, None)
                    log.warning(
                        f"_pending_methods exceeded 1000 entries — evicted oldest ({oldest!r}). "
                        f"Upstream may be dropping responses."
                    )
            # Short-circuit oracle resource reads — handle locally
            if method == "resources/read":
                uri = req.get("params", {}).get("uri", "")
                if uri.startswith("oracle://"):
                    response = _handle_oracle_read(req)
                    out = json.dumps(response, separators=(",", ":")).encode()
                    sys.stdout.buffer.write(_serialize(frame, out))
                    sys.stdout.buffer.flush()
                    if req_id is not None:
                        _pending_methods.pop(req_id, None)
                    continue
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        proc_stdin.write(_serialize(frame, payload))
        await proc_stdin.drain()
    proc_stdin.close()


async def _forward_responses(proc_stdout: asyncio.StreamReader, bypass: bool):
    """upstream → proxy (compress + augment) → Claude stdout."""
    while True:
        frame, payload = await _read_message(proc_stdout)
        if frame is None:
            break
        try:
            msg     = json.loads(payload.decode())
            # Augment resources/list with oracle entries
            req_id  = msg.get("id")
            method  = _pending_methods.pop(req_id, "") if req_id is not None else ""
            if method == "resources/list":
                msg = _augment_resources_list(msg)
            _check_protocol_version(msg)          # warn if server version outside 0.x range
            msg         = _compress_response(msg, bypass)
            out_payload = json.dumps(msg, separators=(",", ":")).encode()
        except (json.JSONDecodeError, UnicodeDecodeError):
            out_payload = payload
        sys.stdout.buffer.write(_serialize(frame, out_payload))
        sys.stdout.buffer.flush()


# ── main ──────────────────────────────────────────────────────────────────────

async def run(upstream_cmd: list, bypass: bool) -> None:
    proc = await asyncio.create_subprocess_exec(
        *upstream_cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=sys.stderr,
    )
    loop = asyncio.get_event_loop()
    stdin_reader = asyncio.StreamReader()
    await loop.connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(stdin_reader),
        sys.stdin.buffer,
    )
    await asyncio.gather(
        _forward_requests(stdin_reader, proc.stdin),
        _forward_responses(proc.stdout, bypass),
    )
    await proc.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description="MATLAB MCP compression proxy")
    parser.add_argument("--bypass",    action="store_true",
                        help="Disable compression — raw passthrough")
    parser.add_argument("--upstream",  required=True,
                        help="Path to upstream MCP server binary")
    parser.add_argument("--log-level", default="WARNING",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args, upstream_args = parser.parse_known_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        stream=sys.stderr,
        format="[proxy] %(levelname)s %(message)s",
    )
    upstream_cmd = [args.upstream] + upstream_args
    log.info(f"upstream: {' '.join(upstream_cmd)}")
    log.info(f"compression: {'DISABLED' if args.bypass else 'ENABLED'}")
    if not args.bypass:
        import selftest
        selftest.run_startup_checks()   # exits 1 with diagnostics if broken
    asyncio.run(run(upstream_cmd, args.bypass))


if __name__ == "__main__":
    main()
