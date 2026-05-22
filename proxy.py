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
import sys, os, json, asyncio, argparse, logging
import os as _os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compressor import compress

log = logging.getLogger("matlab-proxy")

_oracle = None
_handle_store = None

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


# ── compression ──────────────────────────────────────────────────────────────

def _compress_response(msg: dict, bypass: bool) -> dict:
    """Compress text in tool_result messages. Requests pass through unchanged."""
    if bypass:
        return msg
    try:
        from router import route, OutputType
        content = msg.get("result", {}).get("content", [])
        if not isinstance(content, list):
            return msg
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                original = item["text"]
                compressed, otype = route(original)
                # Append oracle hint for errors/warnings
                if otype in (OutputType.ERROR, OutputType.WARNING):
                    oracle = _get_oracle()
                    hint = oracle.format_hint(original)
                    if hint:
                        compressed = hint + "\n" + compressed
                elif otype == OutputType.SIM_RESULT and len(original) > 300:
                    hs = _get_handle_store()
                    handle_id, summary = hs.store(original)
                    if handle_id:
                        compressed = hs.format_for_context(handle_id, summary)
                if compressed != original:
                    pct = (1 - len(compressed) / len(original)) * 100
                    log.debug(f"Compressed {len(original)}→{len(compressed)} chars ({pct:.0f}%)")
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


# ── forwarding coroutines ─────────────────────────────────────────────────────

async def _forward_requests(stdin_reader: asyncio.StreamReader,
                             proc_stdin: asyncio.StreamWriter):
    """Claude → proxy → upstream: pass requests through unchanged."""
    while True:
        frame, payload = await _read_message(stdin_reader)
        if frame is None:
            break
        proc_stdin.write(_serialize(frame, payload))
        await proc_stdin.drain()
    proc_stdin.close()


async def _forward_responses(proc_stdout: asyncio.StreamReader, bypass: bool):
    """upstream → proxy (compress) → Claude stdout."""
    while True:
        frame, payload = await _read_message(proc_stdout)
        if frame is None:
            break
        try:
            msg         = json.loads(payload.decode())
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
    asyncio.run(run(upstream_cmd, args.bypass))


if __name__ == "__main__":
    main()
