# Python MCP Server — Pure Python MATLAB Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pure Python MCP server that replaces `matlab-mcp-core-server` (binary) by connecting directly to MATLAB's official Python Engine API — no binary download, no ports, no external network, fully auditable source.

**Architecture:** A single `server/matlab_mcp.py` entry point implements the MCP JSON-RPC stdio protocol, dispatches tool calls to `server/engine_bridge.py` (manages the `matlab.engine` session), and pipes every response through the existing `router.py → compressor.py → oracle → handles` pipeline already in this repo. The current `proxy.py` continues to work for users who have the binary; the Python server is an additional standalone mode added under `server/`.

**Tech Stack:** Python 3.9+, `matlab.engine` (ships with MATLAB R2014b+, no install beyond MATLAB), `asyncio`, `pytest` with `unittest.mock` for engine mocking. Zero new pip dependencies for the server itself.

---

## Context: what already exists and is reused

```
matlab-mcp-proxy/
  proxy.py           ← existing proxy (wraps binary) — UNCHANGED
  compressor.py      ← 14 compression rules — REUSED AS-IS
  router.py          ← 11-type classifier — REUSED AS-IS
  kb/
    error_oracle.py  ← oracle KB — REUSED AS-IS
    sim_handles.py   ← context handles — REUSED AS-IS
    auto_learn.py    ← session-end learning — REUSED AS-IS
```

Everything under `server/` is new. It imports from the parent package (`router`, `compressor`, `kb.*`) so all proxy features are available without copying code.

---

## File Structure

```
server/
  __init__.py              — package marker
  matlab_mcp.py            — MCP stdio loop, CLI entry point (~160 lines)
  engine_bridge.py         — matlab.engine session manager (~120 lines)
  tools/
    __init__.py
    matlab_tools.py        — evaluate_matlab_code, run_matlab_file,
                              detect_toolboxes, check_matlab_code (~130 lines)
    simulink_tools.py      — model_overview, model_read, model_query_params,
                              model_resolve_params, model_edit, model_test (~200 lines)
  tests/
    __init__.py
    test_engine_bridge.py  — engine session management tests
    test_matlab_tools.py   — core MATLAB tool tests (mocked engine)
    test_simulink_tools.py — Simulink tool tests (mocked engine)
    test_mcp_protocol.py   — MCP JSON-RPC protocol tests (no engine needed)
```

---

## How `matlab.engine` works (read before starting)

```python
import matlab.engine
import io

# Option A — start a new MATLAB session
eng = matlab.engine.start_matlab()

# Option B — attach to an already-running shared MATLAB session (better for orgs)
eng = matlab.engine.connect_matlab()   # connects to the first shared session

# Capture stdout (critical — without this, output goes to terminal not Python)
out = io.StringIO()
err = io.StringIO()
eng.eval("a = 1 + 1", nargout=0, stdout=out, stderr=err)
print(out.getvalue())   # '2\n' in MATLAB's display format

# Run a .m file
eng.run("/full/path/to/script.m", nargout=0, stdout=out, stderr=err)

# Set working directory
eng.cd("/path/to/project", nargout=0)

# Share the session so connect_matlab() can find it
matlab.engine.shareEngine()
```

**Install `matlab.engine` once per machine:**
```bash
cd /Applications/MATLAB_R2025a.app/extern/engines/python
python3 setup.py install
```

---

## MCP Protocol overview (read before starting)

Claude Code communicates via JSON-RPC 2.0 over stdin/stdout. Three message types matter:

```json
// 1. Initialize (Claude sends first)
{"jsonrpc":"2.0","id":1,"method":"initialize",
 "params":{"protocolVersion":"2024-11-05","capabilities":{}}}

// Server responds:
{"jsonrpc":"2.0","id":1,"result":{
  "protocolVersion":"2024-11-05",
  "capabilities":{"tools":{}},
  "serverInfo":{"name":"matlab-mcp-python","version":"1.0.0"}}}

// 2. List tools
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}

// Server responds with array of tool definitions (see Task 3)

// 3. Call a tool
{"jsonrpc":"2.0","id":3,"method":"tools/call",
 "params":{"name":"evaluate_matlab_code","arguments":{"code":"a=1+1"}}}

// Server responds:
{"jsonrpc":"2.0","id":3,"result":{
  "content":[{"type":"text","text":"a = 2"}]}}
```

Messages are **newline-delimited** (one JSON object per line). The existing `proxy.py` already handles Content-Length framing — the Python server uses simpler newline-delimited format since Claude Code supports both.

---

## Task 1: Install `matlab.engine` and project scaffold

**Files:**
- Create: `server/__init__.py`
- Create: `server/tools/__init__.py`
- Create: `server/tests/__init__.py`
- Modify: `.gitignore` (add `*.egg-info/`)

- [ ] **Step 1: Install `matlab.engine` for the system Python**

```bash
cd /Applications/MATLAB_R2025a.app/extern/engines/python
python3 setup.py install --user
```

Verify:
```bash
python3 -c "import matlab.engine; print('OK')"
```
Expected: `OK`

- [ ] **Step 2: Create the package scaffold**

```bash
mkdir -p /Users/soorajkrishnan/simscape-agent/matlab-mcp-proxy/server/tools
mkdir -p /Users/soorajkrishnan/simscape-agent/matlab-mcp-proxy/server/tests
touch /Users/soorajkrishnan/simscape-agent/matlab-mcp-proxy/server/__init__.py
touch /Users/soorajkrishnan/simscape-agent/matlab-mcp-proxy/server/tools/__init__.py
touch /Users/soorajkrishnan/simscape-agent/matlab-mcp-proxy/server/tests/__init__.py
```

- [ ] **Step 3: Add egg-info to .gitignore**

In the repo root `.gitignore`, add:
```
*.egg-info/
dist/
build/
```

- [ ] **Step 4: Commit scaffold**

```bash
git add server/ .gitignore
git commit -m "feat(server): scaffold pure Python MCP server package"
```

---

## Task 2: Engine Bridge

**Files:**
- Create: `server/engine_bridge.py`
- Create: `server/tests/test_engine_bridge.py`

### `server/engine_bridge.py`

```python
"""
server/engine_bridge.py — matlab.engine session manager.

Manages a single persistent MATLAB session for the lifetime of the server.
Supports two modes:
  - 'new'      : start a fresh MATLAB process (default)
  - 'existing' : attach to a running shared MATLAB session (connect_matlab)

Usage:
    bridge = EngineBridge(mode='existing', matlab_root=None)
    bridge.start()
    output, error = bridge.eval("a = 1+1")
    bridge.cd("/path/to/project")
    bridge.stop()
"""
from __future__ import annotations
import io, sys, os
from typing import Literal


class EngineBridge:
    def __init__(self,
                 mode: Literal['new', 'existing'] = 'new',
                 matlab_root: str | None = None,
                 startup_options: str = ''):
        self.mode            = mode
        self.matlab_root     = matlab_root
        self.startup_options = startup_options
        self._eng            = None

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start or attach to a MATLAB session."""
        if self.matlab_root:
            _add_engine_to_path(self.matlab_root)
        import matlab.engine
        if self.mode == 'existing':
            self._eng = matlab.engine.connect_matlab()
        else:
            opts = self.startup_options or ''
            self._eng = matlab.engine.start_matlab(opts)

    def stop(self) -> None:
        if self._eng is not None:
            try:
                self._eng.quit()
            except Exception:
                pass
            self._eng = None

    # ── execution ──────────────────────────────────────────────────────────────

    def eval(self, code: str) -> tuple[str, str]:
        """
        Run a string of MATLAB code.
        Returns (stdout_text, stderr_text).
        Raises RuntimeError if MATLAB raises an exception.
        """
        self._require_session()
        out, err = io.StringIO(), io.StringIO()
        try:
            self._eng.eval(code, nargout=0, stdout=out, stderr=err)
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc
        return out.getvalue(), err.getvalue()

    def run_file(self, path: str) -> tuple[str, str]:
        """Run a .m file by absolute path."""
        self._require_session()
        # MATLAB's run() requires the file to be on the path or CWD
        folder = os.path.dirname(os.path.abspath(path))
        fname  = os.path.splitext(os.path.basename(path))[0]
        out, err = io.StringIO(), io.StringIO()
        try:
            self._eng.eval(f"addpath('{folder}'); {fname}", nargout=0,
                           stdout=out, stderr=err)
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc
        return out.getvalue(), err.getvalue()

    def cd(self, path: str) -> None:
        """Set MATLAB working directory."""
        self._require_session()
        self._eng.cd(path, nargout=0)

    def is_alive(self) -> bool:
        return self._eng is not None

    # ── internal ───────────────────────────────────────────────────────────────

    def _require_session(self) -> None:
        if self._eng is None:
            raise RuntimeError("MATLAB session not started. Call bridge.start() first.")


def _add_engine_to_path(matlab_root: str) -> None:
    """Add the matlab.engine package from a non-default MATLAB installation."""
    engine_path = os.path.join(matlab_root, 'extern', 'engines', 'python')
    if engine_path not in sys.path:
        sys.path.insert(0, engine_path)
```

- [ ] **Step 1: Write failing tests**

Create `server/tests/test_engine_bridge.py`:

```python
"""Tests for EngineBridge — all run with a mocked matlab.engine (no MATLAB needed)."""
import sys, os, pytest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from server.engine_bridge import EngineBridge


@pytest.fixture
def mock_engine_module():
    """Patch matlab.engine at the import level inside engine_bridge."""
    eng_instance = MagicMock()
    eng_instance.eval.return_value = None   # nargout=0
    eng_instance.cd.return_value = None
    module = MagicMock()
    module.start_matlab.return_value = eng_instance
    module.connect_matlab.return_value = eng_instance
    with patch.dict('sys.modules', {'matlab': MagicMock(), 'matlab.engine': module}):
        yield module, eng_instance


class TestEngineBridgeStart:
    def test_start_new_mode(self, mock_engine_module):
        mod, eng = mock_engine_module
        bridge = EngineBridge(mode='new')
        bridge.start()
        mod.start_matlab.assert_called_once()
        assert bridge.is_alive()

    def test_start_existing_mode(self, mock_engine_module):
        mod, eng = mock_engine_module
        bridge = EngineBridge(mode='existing')
        bridge.start()
        mod.connect_matlab.assert_called_once()
        assert bridge.is_alive()

    def test_not_alive_before_start(self):
        bridge = EngineBridge()
        assert not bridge.is_alive()


class TestEngineBridgeEval:
    def test_eval_returns_stdout(self, mock_engine_module):
        mod, eng = mock_engine_module
        def fake_eval(code, nargout, stdout, stderr):
            stdout.write("ans = 2\n")
        eng.eval.side_effect = fake_eval
        bridge = EngineBridge(); bridge.start()
        out, err = bridge.eval("1 + 1")
        assert "ans = 2" in out

    def test_eval_raises_runtime_error_on_matlab_exception(self, mock_engine_module):
        mod, eng = mock_engine_module
        eng.eval.side_effect = Exception("Undefined function 'foo'")
        bridge = EngineBridge(); bridge.start()
        with pytest.raises(RuntimeError, match="Undefined function"):
            bridge.eval("foo()")

    def test_eval_without_start_raises(self):
        bridge = EngineBridge()
        with pytest.raises(RuntimeError, match="not started"):
            bridge.eval("a = 1")

    def test_cd_sets_working_directory(self, mock_engine_module):
        mod, eng = mock_engine_module
        bridge = EngineBridge(); bridge.start()
        bridge.cd("/tmp/work")
        eng.cd.assert_called_once_with("/tmp/work", nargout=0)

    def test_run_file_calls_eval_with_addpath(self, mock_engine_module):
        mod, eng = mock_engine_module
        bridge = EngineBridge(); bridge.start()
        bridge.run_file("/some/path/myscript.m")
        call_args = eng.eval.call_args[0][0]
        assert "addpath" in call_args
        assert "myscript" in call_args

    def test_stop_calls_quit(self, mock_engine_module):
        mod, eng = mock_engine_module
        bridge = EngineBridge(); bridge.start()
        bridge.stop()
        eng.quit.assert_called_once()
        assert not bridge.is_alive()
```

- [ ] **Step 2: Run to verify fail**

```bash
cd /Users/soorajkrishnan/simscape-agent/matlab-mcp-proxy
pytest server/tests/test_engine_bridge.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'server.engine_bridge'`

- [ ] **Step 3: Write `server/engine_bridge.py`** (code shown above)

- [ ] **Step 4: Run tests**

```bash
pytest server/tests/test_engine_bridge.py -v
```
Expected: 7/7 pass

- [ ] **Step 5: Commit**

```bash
git add server/engine_bridge.py server/tests/test_engine_bridge.py
git commit -m "feat(server): EngineBridge — matlab.engine session manager, 7 tests"
```

---

## Task 3: Core MATLAB Tools

**Files:**
- Create: `server/tools/matlab_tools.py`
- Create: `server/tests/test_matlab_tools.py`

### `server/tools/matlab_tools.py`

```python
"""
server/tools/matlab_tools.py — Core MATLAB tool implementations.

Each function takes an EngineBridge + the tool's argument dict and returns
a (text_output, is_error) tuple. The MCP server layer wraps these into
proper JSON-RPC responses.
"""
from __future__ import annotations
import os
from server.engine_bridge import EngineBridge


TOOL_DEFINITIONS = [
    {
        "name": "evaluate_matlab_code",
        "description": "Evaluate a string of MATLAB code in the current session. "
                       "Returns command window output.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code":         {"type": "string", "description": "MATLAB code to evaluate"},
                "project_path": {"type": "string", "description": "Optional working directory"}
            },
            "required": ["code"]
        }
    },
    {
        "name": "run_matlab_file",
        "description": "Run a MATLAB .m script file. Returns command window output.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path":         {"type": "string", "description": "Absolute path to .m file"},
                "project_path": {"type": "string", "description": "Optional working directory"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "detect_matlab_toolboxes",
        "description": "List all installed MATLAB toolboxes and their versions.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "check_matlab_code",
        "description": "Run mlint static analysis on a .m file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to .m file"}
            },
            "required": ["path"]
        }
    },
]


def evaluate_matlab_code(bridge: EngineBridge, args: dict) -> tuple[str, bool]:
    code         = args["code"]
    project_path = args.get("project_path")
    if project_path:
        bridge.cd(project_path)
    try:
        out, err = bridge.eval(code)
        text = (out + err).strip() or "(no output)"
        return text, False
    except RuntimeError as exc:
        return f"matlab error: {exc}", True


def run_matlab_file(bridge: EngineBridge, args: dict) -> tuple[str, bool]:
    path         = args["path"]
    project_path = args.get("project_path")
    if project_path:
        bridge.cd(project_path)
    if not os.path.exists(path):
        return f"File not found: {path}", True
    try:
        out, err = bridge.run_file(path)
        text = (out + err).strip() or "(no output)"
        return text, False
    except RuntimeError as exc:
        return f"matlab error: {exc}", True


def detect_matlab_toolboxes(bridge: EngineBridge, args: dict) -> tuple[str, bool]:
    try:
        out, _ = bridge.eval(
            "v = ver; for i=1:length(v), "
            "fprintf('%s — %s\\n', v(i).Name, v(i).Version); end"
        )
        return out.strip() or "(no toolboxes found)", False
    except RuntimeError as exc:
        return f"matlab error: {exc}", True


def check_matlab_code(bridge: EngineBridge, args: dict) -> tuple[str, bool]:
    path = args["path"]
    if not os.path.exists(path):
        return f"File not found: {path}", True
    try:
        code = f"info = checkcode('{path}', '-struct'); "             "if isempty(info), disp('No issues found.'); "             "else, for i=1:length(info), "             "fprintf('Line %d: %s\\n', info(i).line, info(i).message); end, end"
        out, _ = bridge.eval(code)
        return out.strip() or "No issues found.", False
    except RuntimeError as exc:
        return f"matlab error: {exc}", True


TOOL_HANDLERS = {
    "evaluate_matlab_code":  evaluate_matlab_code,
    "run_matlab_file":       run_matlab_file,
    "detect_matlab_toolboxes": detect_matlab_toolboxes,
    "check_matlab_code":     check_matlab_code,
}
```

- [ ] **Step 1: Write failing tests**

Create `server/tests/test_matlab_tools.py`:

```python
"""Tests for core MATLAB tools — mocked EngineBridge, no MATLAB needed."""
import sys, os, pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from server.tools.matlab_tools import (
    evaluate_matlab_code, run_matlab_file,
    detect_matlab_toolboxes, check_matlab_code, TOOL_DEFINITIONS
)


@pytest.fixture
def bridge():
    b = MagicMock()
    b.eval.return_value = ("ans = 2\n", "")
    b.run_file.return_value = ("Script complete.\n", "")
    return b


class TestEvaluateMatlabCode:
    def test_returns_stdout(self, bridge):
        out, is_err = evaluate_matlab_code(bridge, {"code": "1+1"})
        assert "ans = 2" in out
        assert not is_err

    def test_sets_project_path(self, bridge):
        evaluate_matlab_code(bridge, {"code": "1+1", "project_path": "/tmp"})
        bridge.cd.assert_called_once_with("/tmp")

    def test_returns_error_on_exception(self, bridge):
        bridge.eval.side_effect = RuntimeError("Undefined function 'foo'")
        out, is_err = evaluate_matlab_code(bridge, {"code": "foo()"})
        assert is_err
        assert "Undefined function" in out

    def test_no_output_returns_placeholder(self, bridge):
        bridge.eval.return_value = ("", "")
        out, is_err = evaluate_matlab_code(bridge, {"code": "a=1;"})
        assert out == "(no output)"
        assert not is_err


class TestRunMatlabFile:
    def test_runs_existing_file(self, bridge, tmp_path):
        f = tmp_path / "test.m"
        f.write_text("disp('hello')")
        out, is_err = run_matlab_file(bridge, {"path": str(f)})
        assert "Script complete" in out
        assert not is_err

    def test_missing_file_returns_error(self, bridge):
        out, is_err = run_matlab_file(bridge, {"path": "/nonexistent/file.m"})
        assert is_err
        assert "not found" in out


class TestDetectToolboxes:
    def test_returns_toolbox_list(self, bridge):
        bridge.eval.return_value = ("MATLAB — 25.1\nSimulink — 25.1\n", "")
        out, is_err = detect_matlab_toolboxes(bridge, {})
        assert "MATLAB" in out
        assert not is_err


class TestToolDefinitions:
    def test_all_tools_have_required_fields(self):
        for t in TOOL_DEFINITIONS:
            assert "name" in t
            assert "description" in t
            assert "inputSchema" in t

    def test_four_tools_defined(self):
        assert len(TOOL_DEFINITIONS) == 4
```

- [ ] **Step 2: Run to verify fail**

```bash
pytest server/tests/test_matlab_tools.py -v 2>&1 | head -15
```

- [ ] **Step 3: Write `server/tools/matlab_tools.py`** (code shown above)

- [ ] **Step 4: Run tests**

```bash
pytest server/tests/test_matlab_tools.py -v
```
Expected: 10/10 pass

- [ ] **Step 5: Commit**

```bash
git add server/tools/matlab_tools.py server/tests/test_matlab_tools.py
git commit -m "feat(server): core MATLAB tools — evaluate, run_file, toolboxes, check_code"
```

---

## Task 4: Simulink Tools

**Files:**
- Create: `server/tools/simulink_tools.py`
- Create: `server/tests/test_simulink_tools.py`

The Simulink tools work by calling the Simulink Agentic Toolkit's MATLAB functions via `eng.eval()`. The toolkit must be on MATLAB's path (same as the current setup).

### `server/tools/simulink_tools.py`

```python
"""
server/tools/simulink_tools.py — Simulink/Simscape tool implementations.

These tools mirror the Simulink Agentic Toolkit (SATK) tools from tools.json.
They call SATK MATLAB functions via the engine bridge.
The SATK must be initialised on the MATLAB path:
  bridge.eval("run('/path/to/simulink-agentic-toolkit/satk_initialize.p')")
"""
from __future__ import annotations
import json
from server.engine_bridge import EngineBridge


TOOL_DEFINITIONS = [
    {
        "name": "model_overview",
        "description": "Get a structural overview of a Simulink model.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model":  {"type": "string"},
                "scope":  {"type": "string", "default": "root"},
                "detail": {"type": "string", "enum": ["summary","full"], "default": "summary"}
            },
            "required": ["model"]
        }
    },
    {
        "name": "model_read",
        "description": "Read block parameters in a Simulink model scope.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "scope": {"type": "string", "default": "root"},
                "depth": {"type": "integer", "default": 1}
            },
            "required": ["model"]
        }
    },
    {
        "name": "model_query_params",
        "description": "Query specific parameters from blocks in a model.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model":   {"type": "string"},
                "targets": {"type": "array", "items": {"type": "string"}},
                "params":  {"type": "array", "items": {"type": "string"}},
                "compile": {"type": "boolean", "default": False}
            },
            "required": ["model", "targets", "params"]
        }
    },
    {
        "name": "model_resolve_params",
        "description": "Resolve parameter expressions to their values.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model":       {"type": "string"},
                "expressions": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["model", "expressions"]
        }
    },
    {
        "name": "model_edit",
        "description": "Programmatically edit a Simulink model (add/connect/configure blocks).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model":      {"type": "string"},
                "scope":      {"type": "string", "default": "root"},
                "operations": {"type": "array", "items": {"type": "object"}}
            },
            "required": ["model", "scope", "operations"]
        }
    },
    {
        "name": "model_test",
        "description": "Run Gherkin-based tests against a Simulink model.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model":        {"type": "string"},
                "gherkin_file": {"type": "string"},
                "scenarios":    {"type": "array", "items": {"type": "string"}},
                "verbose":      {"type": "boolean", "default": False},
                "draft_mode":   {"type": "boolean", "default": False}
            },
            "required": ["model", "gherkin_file"]
        }
    },
]


def _call_satk(bridge: EngineBridge, func: str, args_json: str) -> tuple[str, bool]:
    """Call a SATK function: satk_func(args_json) → returns JSON string → decode."""
    code = f"result = {func}('{_escape(args_json)}'); disp(result);"
    try:
        out, err = bridge.eval(code)
        return (out + err).strip(), False
    except RuntimeError as exc:
        return f"matlab error: {exc}", True


def _escape(s: str) -> str:
    return s.replace("'", "''")


def model_overview(bridge: EngineBridge, args: dict) -> tuple[str, bool]:
    payload = json.dumps({
        "model": args["model"],
        "scope": args.get("scope", "root"),
        "detail": args.get("detail", "summary")
    })
    return _call_satk(bridge, "satk_model_overview", payload)


def model_read(bridge: EngineBridge, args: dict) -> tuple[str, bool]:
    payload = json.dumps({
        "model": args["model"],
        "scope": args.get("scope", "root"),
        "depth": args.get("depth", 1)
    })
    return _call_satk(bridge, "satk_model_read", payload)


def model_query_params(bridge: EngineBridge, args: dict) -> tuple[str, bool]:
    payload = json.dumps({
        "model":   args["model"],
        "targets": args.get("targets", []),
        "params":  args.get("params", []),
        "compile": args.get("compile", False)
    })
    return _call_satk(bridge, "satk_model_query_params", payload)


def model_resolve_params(bridge: EngineBridge, args: dict) -> tuple[str, bool]:
    payload = json.dumps({
        "model":       args["model"],
        "expressions": args.get("expressions", [])
    })
    return _call_satk(bridge, "satk_model_resolve_params", payload)


def model_edit(bridge: EngineBridge, args: dict) -> tuple[str, bool]:
    payload = json.dumps({
        "model":      args["model"],
        "scope":      args.get("scope", "root"),
        "operations": args.get("operations", [])
    })
    return _call_satk(bridge, "satk_model_edit", payload)


def model_test(bridge: EngineBridge, args: dict) -> tuple[str, bool]:
    payload = json.dumps({
        "model":        args["model"],
        "gherkin_file": args["gherkin_file"],
        "scenarios":    args.get("scenarios", []),
        "verbose":      args.get("verbose", False),
        "draft_mode":   args.get("draft_mode", False)
    })
    return _call_satk(bridge, "satk_model_test", payload)


TOOL_HANDLERS = {
    "model_overview":       model_overview,
    "model_read":           model_read,
    "model_query_params":   model_query_params,
    "model_resolve_params": model_resolve_params,
    "model_edit":           model_edit,
    "model_test":           model_test,
}
```

- [ ] **Step 1: Write failing tests**

Create `server/tests/test_simulink_tools.py`:

```python
"""Tests for Simulink tools — mocked EngineBridge, no MATLAB needed."""
import sys, os, json, pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from server.tools.simulink_tools import (
    model_overview, model_edit, model_read,
    model_query_params, TOOL_DEFINITIONS
)


@pytest.fixture
def bridge():
    b = MagicMock()
    b.eval.return_value = ("status: ok\n", "")
    return b


class TestModelOverview:
    def test_calls_satk_function(self, bridge):
        model_overview(bridge, {"model": "myModel"})
        call_code = bridge.eval.call_args[0][0]
        assert "satk_model_overview" in call_code
        assert "myModel" in call_code

    def test_default_scope_is_root(self, bridge):
        model_overview(bridge, {"model": "myModel"})
        call_code = bridge.eval.call_args[0][0]
        assert "root" in call_code

    def test_returns_output(self, bridge):
        bridge.eval.return_value = ("blk_0 myModel [5|0/0]\n", "")
        out, is_err = model_overview(bridge, {"model": "myModel"})
        assert "blk_0" in out
        assert not is_err


class TestModelEdit:
    def test_passes_operations_json(self, bridge):
        ops = [{"op": "add_block", "type": "simulink/Sources/Constant", "name": "C"}]
        model_edit(bridge, {"model": "myModel", "scope": "root", "operations": ops})
        call_code = bridge.eval.call_args[0][0]
        assert "satk_model_edit" in call_code
        assert "add_block" in call_code

    def test_returns_error_on_matlab_exception(self, bridge):
        bridge.eval.side_effect = RuntimeError("Block not found")
        out, is_err = model_edit(bridge, {"model": "M", "scope": "root", "operations": []})
        assert is_err
        assert "Block not found" in out


class TestToolDefinitions:
    def test_six_tools_defined(self):
        assert len(TOOL_DEFINITIONS) == 6

    def test_all_have_required_fields(self):
        for t in TOOL_DEFINITIONS:
            assert "name" in t
            assert "description" in t
            assert "inputSchema" in t
```

- [ ] **Step 2: Run to verify fail**

```bash
pytest server/tests/test_simulink_tools.py -v 2>&1 | head -10
```

- [ ] **Step 3: Write `server/tools/simulink_tools.py`** (code shown above)

- [ ] **Step 4: Run tests**

```bash
pytest server/tests/test_simulink_tools.py -v
```
Expected: 8/8 pass

- [ ] **Step 5: Commit**

```bash
git add server/tools/simulink_tools.py server/tests/test_simulink_tools.py
git commit -m "feat(server): Simulink tools — model_overview/read/query/resolve/edit/test via SATK"
```

---

## Task 5: MCP Protocol Layer + Response Pipeline

**Files:**
- Create: `server/matlab_mcp.py`
- Create: `server/tests/test_mcp_protocol.py`

This is the main entry point. It reads MCP JSON-RPC from stdin, dispatches to tools, pipes responses through the existing compression pipeline, and writes to stdout.

### `server/matlab_mcp.py`

```python
#!/usr/bin/env python3
"""
server/matlab_mcp.py — Pure Python MCP server for MATLAB.

Replaces matlab-mcp-core-server (binary) using matlab.engine directly.
All proxy features (compression, oracle, handles) are applied inline.

Usage:
  python3 server/matlab_mcp.py --mode new --working-folder /path/to/work
  python3 server/matlab_mcp.py --mode existing   # attach to running MATLAB
  python3 server/matlab_mcp.py --bypass           # disable compression

Configure in ~/.claude.json:
  {
    "mcpServers": {
      "matlab": {
        "command": "python3",
        "args": ["/path/to/matlab-mcp-proxy/server/matlab_mcp.py",
                 "--mode", "existing",
                 "--working-folder", "/your/work/folder"]
      }
    }
  }
"""
import sys, os, json, argparse, logging, time

# Ensure proxy root is on path so we can import router, compressor, kb.*
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from server.engine_bridge import EngineBridge
from server.tools.matlab_tools   import TOOL_DEFINITIONS as MATLAB_TOOLS,   TOOL_HANDLERS as MATLAB_HANDLERS
from server.tools.simulink_tools import TOOL_DEFINITIONS as SIMULINK_TOOLS, TOOL_HANDLERS as SIMULINK_HANDLERS

log = logging.getLogger("matlab-mcp-python")

ALL_TOOLS    = MATLAB_TOOLS + SIMULINK_TOOLS
ALL_HANDLERS = {**MATLAB_HANDLERS, **SIMULINK_HANDLERS}

# ── lazy proxy pipeline ────────────────────────────────────────────────────────

_oracle       = None
_handle_store = None

def _get_oracle():
    global _oracle
    if _oracle is None:
        from kb.error_oracle import ErrorOracle
        _oracle = ErrorOracle(store_dir=os.path.join(_ROOT, 'kb_store'))
    return _oracle

def _get_handle_store():
    global _handle_store
    if _handle_store is None:
        from kb.sim_handles import SimHandleStore
        _handle_store = SimHandleStore(store_dir=os.path.join(_ROOT, 'kb_store'))
    return _handle_store

def _apply_pipeline(text: str, bypass: bool) -> str:
    """Apply router → compress → oracle → handles pipeline to tool output."""
    if bypass or not text.strip():
        return text
    try:
        from router import route, OutputType
        compressed, otype = route(text)
        if otype in (OutputType.ERROR, OutputType.WARNING):
            hint = _get_oracle().format_hint(text)
            if hint:
                compressed = hint + "\n" + compressed
            else:
                _log_unseen_error(text)
        elif otype == OutputType.SIM_RESULT and len(text) > 300:
            hs = _get_handle_store()
            handle_id, summary = hs.store(text)
            if handle_id:
                compressed = hs.format_for_context(handle_id, summary)
        return compressed
    except Exception:
        return text

def _log_unseen_error(text: str) -> None:
    try:
        path = os.path.join(_ROOT, 'kb_store', 'pending_errors.jsonl')
        entry = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "error": text.strip()[:800]})
        with open(path, 'a') as f:
            f.write(entry + '\n')
    except Exception:
        pass

# ── MCP message I/O ────────────────────────────────────────────────────────────

def _read_message() -> dict | None:
    """Read one newline-delimited JSON-RPC message from stdin."""
    try:
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line.strip())
    except (json.JSONDecodeError, EOFError):
        return None

def _write_message(msg: dict) -> None:
    """Write one JSON-RPC message to stdout (newline-delimited)."""
    sys.stdout.write(json.dumps(msg) + '\n')
    sys.stdout.flush()

def _error_response(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

def _success_response(req_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}

# ── request handlers ───────────────────────────────────────────────────────────

def handle_initialize(req: dict) -> dict:
    return _success_response(req.get("id"), {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "matlab-mcp-python", "version": "1.0.0"}
    })

def handle_tools_list(req: dict) -> dict:
    return _success_response(req.get("id"), {"tools": ALL_TOOLS})

def handle_tools_call(req: dict, bridge: EngineBridge, bypass: bool) -> dict:
    params    = req.get("params", {})
    tool_name = params.get("name", "")
    args      = params.get("arguments", {})
    req_id    = req.get("id")

    handler = ALL_HANDLERS.get(tool_name)
    if not handler:
        return _error_response(req_id, -32601, f"Unknown tool: {tool_name}")

    if not bridge.is_alive():
        return _error_response(req_id, -32603, "MATLAB session not available")

    try:
        text, is_error = handler(bridge, args)
    except Exception as exc:
        return _error_response(req_id, -32603, str(exc))

    processed = _apply_pipeline(text, bypass)

    return _success_response(req_id, {
        "content": [{"type": "text", "text": processed}],
        "isError": is_error
    })

# ── main loop ──────────────────────────────────────────────────────────────────

def run(bridge: EngineBridge, bypass: bool) -> None:
    bridge.start()
    log.info("MATLAB session ready")

    DISPATCH = {
        "initialize":   lambda r: handle_initialize(r),
        "tools/list":   lambda r: handle_tools_list(r),
        "tools/call":   lambda r: handle_tools_call(r, bridge, bypass),
        # notifications (no response needed)
        "notifications/initialized": None,
    }

    while True:
        msg = _read_message()
        if msg is None:
            break
        method = msg.get("method", "")
        handler = DISPATCH.get(method)
        if handler is None:
            continue   # notification — no response
        response = handler(msg)
        if response:
            _write_message(response)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pure Python MATLAB MCP server")
    parser.add_argument("--mode", choices=["new", "existing"], default="new",
                        help="'new' = start MATLAB; 'existing' = attach to running session")
    parser.add_argument("--working-folder", default=None,
                        help="Set MATLAB working directory on startup")
    parser.add_argument("--matlab-root", default=None,
                        help="Path to MATLAB installation (if not default)")
    parser.add_argument("--satk-path", default=None,
                        help="Path to Simulink Agentic Toolkit (optional)")
    parser.add_argument("--bypass", action="store_true",
                        help="Disable compression pipeline")
    parser.add_argument("--log-level", default="WARNING",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level),
                        stream=sys.stderr,
                        format="[matlab-mcp-py] %(levelname)s %(message)s")

    bridge = EngineBridge(mode=args.mode, matlab_root=args.matlab_root)

    # Post-start init: set working folder + load SATK if provided
    original_start = bridge.start

    def patched_start():
        original_start()
        if args.working_folder:
            bridge.cd(args.working_folder)
        if args.satk_path:
            bridge.eval(f"run('{args.satk_path}/satk_initialize.p')")

    bridge.start = patched_start

    try:
        run(bridge, args.bypass)
    finally:
        bridge.stop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 1: Write failing tests for MCP protocol layer**

Create `server/tests/test_mcp_protocol.py`:

```python
"""Tests for MCP protocol handling — no engine, no MATLAB needed."""
import sys, os, json, pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from server.matlab_mcp import (
    handle_initialize, handle_tools_list, handle_tools_call,
    _apply_pipeline, _success_response, _error_response
)


@pytest.fixture
def mock_bridge():
    b = MagicMock()
    b.is_alive.return_value = True
    return b


class TestJsonRpcHelpers:
    def test_success_response_structure(self):
        r = _success_response(42, {"tools": []})
        assert r["jsonrpc"] == "2.0"
        assert r["id"] == 42
        assert "result" in r

    def test_error_response_structure(self):
        r = _error_response(1, -32601, "Not found")
        assert r["jsonrpc"] == "2.0"
        assert r["error"]["code"] == -32601
        assert "Not found" in r["error"]["message"]


class TestHandleInitialize:
    def test_returns_protocol_version(self):
        req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        resp = handle_initialize(req)
        assert resp["result"]["protocolVersion"] == "2024-11-05"
        assert resp["result"]["serverInfo"]["name"] == "matlab-mcp-python"


class TestHandleToolsList:
    def test_returns_all_tools(self):
        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        resp = handle_tools_list(req)
        tools = resp["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "evaluate_matlab_code" in names
        assert "model_edit" in names
        assert len(tools) == 10   # 4 matlab + 6 simulink


class TestHandleToolsCall:
    def test_unknown_tool_returns_error(self, mock_bridge):
        req = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
               "params": {"name": "nonexistent_tool", "arguments": {}}}
        resp = handle_tools_call(req, mock_bridge, bypass=True)
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    def test_dead_session_returns_error(self):
        bridge = MagicMock()
        bridge.is_alive.return_value = False
        req = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
               "params": {"name": "evaluate_matlab_code", "arguments": {"code": "1"}}}
        resp = handle_tools_call(req, bridge, bypass=True)
        assert "error" in resp
        assert "not available" in resp["error"]["message"]

    def test_successful_tool_call(self, mock_bridge):
        from unittest.mock import patch as p
        with p('server.tools.matlab_tools.evaluate_matlab_code', return_value=("ans = 2\n", False)):
            req = {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                   "params": {"name": "evaluate_matlab_code",
                              "arguments": {"code": "1+1"}}}
            resp = handle_tools_call(req, mock_bridge, bypass=True)
        assert "result" in resp
        assert resp["result"]["content"][0]["type"] == "text"
        assert "ans = 2" in resp["result"]["content"][0]["text"]

    def test_bypass_skips_pipeline(self, mock_bridge):
        from unittest.mock import patch as p
        big_text = "torque =\n\n   107.63\n\n" * 30   # >300 chars, SIM_RESULT
        with p('server.tools.matlab_tools.evaluate_matlab_code', return_value=(big_text, False)):
            req = {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                   "params": {"name": "evaluate_matlab_code",
                              "arguments": {"code": "sim('M')"}}}
            resp = handle_tools_call(req, mock_bridge, bypass=True)
        # bypass=True means output passes through unchanged (not compressed to SimHandle)
        assert big_text in resp["result"]["content"][0]["text"]


class TestApplyPipeline:
    def test_bypass_returns_original(self):
        result = _apply_pipeline("Warning: singular matrix.", bypass=True)
        assert result == "Warning: singular matrix."

    def test_empty_text_passthrough(self):
        result = _apply_pipeline("", bypass=False)
        assert result == ""
```

- [ ] **Step 2: Run to verify fail**

```bash
pytest server/tests/test_mcp_protocol.py -v 2>&1 | head -15
```

- [ ] **Step 3: Write `server/matlab_mcp.py`** (code shown above)

- [ ] **Step 4: Run all server tests**

```bash
pytest server/tests/ -v
```
Expected: all pass (25+ tests)

- [ ] **Step 5: Commit**

```bash
git add server/matlab_mcp.py server/tests/test_mcp_protocol.py
git commit -m "feat(server): MCP stdio loop, dispatch, pipeline integration — full server working"
```

---

## Task 6: Integration test with real MATLAB

This task requires MATLAB to be running. Mark these tests with `@pytest.mark.integration` so they only run when explicitly requested.

**Files:**
- Create: `server/tests/test_integration.py`

```python
"""
Integration tests — require actual MATLAB (matlab.engine must be installed).
Run: pytest server/tests/test_integration.py -v -m integration
"""
import sys, os, pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def live_bridge():
    """Start a real MATLAB session for the entire test module."""
    from server.engine_bridge import EngineBridge
    bridge = EngineBridge(mode='new')
    bridge.start()
    yield bridge
    bridge.stop()


class TestLiveMATLAB:
    def test_eval_simple_expression(self, live_bridge):
        out, err = live_bridge.eval("a = 1 + 1; fprintf('%d\\n', a)")
        assert "2" in out

    def test_eval_whos_gets_compressed(self, live_bridge):
        """whos output must be compressed to one line by the pipeline."""
        from server.tools.matlab_tools import evaluate_matlab_code
        from server.matlab_mcp import _apply_pipeline
        live_bridge.eval("x = zeros(100,1); y = 'hello';")
        raw, _ = evaluate_matlab_code(live_bridge, {"code": "whos"})
        compressed = _apply_pipeline(raw, bypass=False)
        # Compressed whos is a single line starting with "whos:"
        assert compressed.startswith("whos:") or "whos:" in compressed
        assert len(compressed) < len(raw)

    def test_eval_error_gets_oracle_lookup(self, live_bridge):
        """A known Simscape error should get an oracle hint prepended."""
        from server.tools.matlab_tools import evaluate_matlab_code
        from server.matlab_mcp import _apply_pipeline
        # Force a known error
        raw, _ = evaluate_matlab_code(live_bridge, {
            "code": "warning('on','all'); A=[1 2;2 4]; b=[1;1]; x=A\\b;"
        })
        compressed = _apply_pipeline(raw, bypass=False)
        # Either oracle hint or warning dedup
        assert "[ORACLE" in compressed or "[×" in compressed or "singular" in compressed.lower()

    def test_sim_result_gets_handle(self, live_bridge):
        """A multi-signal simulation result should become a SimHandle."""
        from server.tools.matlab_tools import evaluate_matlab_code
        from server.matlab_mcp import _apply_pipeline
        code = "\n".join([
            "fprintf('Simulation complete.\\n')",
            "for sig = {'torque','speed','id','iq','Vd','Vq','flux_d','flux_q','T1','T2','T3'}",
            "  fprintf('%s =\\n\\n   %.4f\\n\\n', sig{1}, rand*100);",
            "end",
            "fprintf('Final torque: 50.00 Nm\\n')"
        ])
        raw, _ = evaluate_matlab_code(live_bridge, {"code": code})
        compressed = _apply_pipeline(raw, bypass=False)
        assert "SimHandle#" in compressed
        assert len(compressed) < len(raw)
```

- [ ] **Step 1: Run existing tests still pass**

```bash
pytest server/tests/ -v -m "not integration"
```
Expected: all pass

- [ ] **Step 2: Run integration tests with live MATLAB**

```bash
pytest server/tests/test_integration.py -v -m integration
```
Expected: 4/4 pass

- [ ] **Step 3: Commit**

```bash
git add server/tests/test_integration.py
git commit -m "test(server): integration tests against live MATLAB — compression/oracle/handles"
```

---

## Task 7: Configuration and Install

**Files:**
- Modify: `install.sh` — add `--python-server` option
- Create: `server/README.md` — standalone setup guide

- [ ] **Step 1: Add `--python-server` flag to `install.sh`**

Add this block to `install.sh` after the existing install logic:

```bash
if [[ "$1" == "--python-server" ]]; then
  echo "Installing matlab.engine Python package..."
  MATLAB_ROOT="${MATLAB_ROOT:-/Applications/MATLAB_R2025a.app}"
  cd "$MATLAB_ROOT/extern/engines/python" && python3 setup.py install --user
  echo "Done. Updating ~/.claude.json to use Python server..."
  python3 - <<'PYEOF'
import json, os, pathlib

claude_json = pathlib.Path.home() / '.claude.json'
proxy_root  = os.path.dirname(os.path.abspath(__file__))
work_folder = os.path.expanduser("~/Documents/MATLAB")

d = json.loads(claude_json.read_text()) if claude_json.exists() else {}
d.setdefault('mcpServers', {})
d['mcpServers']['matlab'] = {
    "command": "python3",
    "args": [
        f"{proxy_root}/server/matlab_mcp.py",
        "--mode", "existing",
        "--working-folder", work_folder
    ],
    "env": {}, "type": "stdio"
}
d['mcpServers']['simulink'] = {
    "command": "python3",
    "args": [
        f"{proxy_root}/server/matlab_mcp.py",
        "--mode", "existing",
        "--working-folder", work_folder,
        "--satk-path", f"{proxy_root}/../simulink-agentic-toolkit"
    ],
    "env": {}, "type": "stdio"
}
claude_json.write_text(json.dumps(d, indent=2))
print(f"Updated {claude_json}")
PYEOF
  echo "Restart Claude Code to activate."
  exit 0
fi
```

- [ ] **Step 2: Create `server/README.md`**

```markdown
# matlab-mcp-python — Pure Python MCP Server

Drop-in replacement for `matlab-mcp-core-server` (binary) using MATLAB's
official Python Engine API. No binary download, no external network, no ports.

## Requirements
- MATLAB R2014b or newer (matlab.engine ships with MATLAB)
- Python 3.9+

## Setup

### 1. Install matlab.engine (once per machine)
```bash
cd /Applications/MATLAB_R2025a.app/extern/engines/python
python3 setup.py install --user
```

### 2. Configure Claude Code
```bash
bash install.sh --python-server
# Restart Claude Code
```

Or manually edit `~/.claude.json`:
```json
{
  "mcpServers": {
    "matlab": {
      "command": "python3",
      "args": [
        "/path/to/matlab-mcp-proxy/server/matlab_mcp.py",
        "--mode", "existing",
        "--working-folder", "/your/work/folder"
      ]
    }
  }
}
```

### 3. Share your MATLAB session (once per MATLAB startup)
In MATLAB command window:
```matlab
matlab.engine.shareEngine
```
This lets the Python server attach without starting a new MATLAB instance.

## Session modes
| Flag | Behaviour |
|------|-----------|
| `--mode new` | Start a fresh MATLAB process (default) |
| `--mode existing` | Attach to a running shared MATLAB session |
| `--bypass` | Disable all compression (raw output) |

## How it differs from the binary
- No `--initialize-matlab-on-startup` flag needed
- No 30-second discovery window
- No localhost port exposure
- Fully auditable Python source
```

- [ ] **Step 3: Commit**

```bash
git add install.sh server/README.md
git commit -m "feat(server): --python-server install flag, server README with setup guide"
```

---

## Task 8: Final polish — docs update

**Files:**
- Modify: `README.md` — add "Python server" section
- Modify: `docs/index.html` — add section for Python server

- [ ] **Step 1: Add Python server section to root README**

In `README.md`, add after the Installation section:

```markdown
## Python server (no binary required)

For environments where installing the `matlab-mcp-core-server` binary isn't possible
(corporate IT restrictions, no binary approval), use the pure Python server instead.
It connects to MATLAB's official Python Engine API which ships with every MATLAB installation.

```bash
# One-time: install matlab.engine
cd /Applications/MATLAB_R2025a.app/extern/engines/python
python3 setup.py install --user

# Configure Claude Code to use the Python server
bash install.sh --python-server
```

See `server/README.md` for full setup details.
```

- [ ] **Step 2: Run full test suite one last time**

```bash
pytest server/tests/ -v -m "not integration"
pytest tests/test_compressor.py tests/test_proxy_protocol.py tests/test_router.py \
       tests/test_oracle.py tests/test_handles.py -v
```
Expected: all pass

- [ ] **Step 3: Final commit and push**

```bash
git add README.md docs/index.html
git commit -m "docs: add Python server section to README and HTML docs"
git push origin main
```

---

## Self-Review

### Spec coverage
| Requirement | Task |
|---|---|
| Pure Python, no binary | Task 5 — `matlab_mcp.py` uses only `matlab.engine` |
| `matlab.engine` bridge | Task 2 — `engine_bridge.py` |
| All 4 core MATLAB tools | Task 3 |
| All 6 Simulink tools | Task 4 |
| Compression pipeline reused | Task 5 — `_apply_pipeline()` |
| Oracle auto-logging reused | Task 5 — `_log_unseen_error()` |
| Context handles reused | Task 5 — `_get_handle_store()` |
| `--mode existing` (attach, no new port) | Task 5 + Task 7 |
| `--bypass` flag | Task 5 |
| `install.sh --python-server` | Task 7 |
| Integration tests with real MATLAB | Task 6 |
| IT-friendly: no binary, local only | Entire server design |

### No placeholders ✓

### Type consistency ✓
- `EngineBridge.eval()` → `tuple[str, str]` (out, err) — consistent Tasks 2→3→4
- Tool handlers `(bridge, args) → tuple[str, bool]` (text, is_error) — consistent Tasks 3→4→5
- `_apply_pipeline(text, bypass) → str` — consistent Task 5→tests
