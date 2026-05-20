# matlab-mcp-proxy

A transparent MCP stdio proxy that compresses verbose MATLAB®, Simulink®, and Simscape® tool responses before they reach your AI agent's context window — saving 48–85% of tokens on typical engineering simulation output.

```
Claude Code  ←──── matlab-mcp-proxy ────►  matlab-mcp-core-server  ────►  MATLAB R2025a
                   (compresses responses)    (unchanged protocol)
```

## Why

MATLAB MCP output is formatted for humans, not language models. A single `whos` call returns a 1,800-character aligned table. Repeated solver warnings can fire 100+ times per simulation step. A Simulink build log repeats `### Starting build procedure for:` for every referenced model. None of that is useful to an LLM — it's token waste.

This proxy sits between Claude Code and `matlab-mcp-core-server` and applies 14 domain-specific compression rules to every tool response before it reaches the model.

## Results

Validated on a real Simscape quarter-car active suspension model (2-DOF, Simscape Foundation library, PD controller):

| Output type | Reduction |
|---|---|
| `whos` variable table | **74%** |
| Repeated solver warnings | **59–71%** |
| Large array auto-display | **85%** |
| Simulink build log | **56%** |
| DOE progress loop (55 pts) | **79%** |
| Test runner output | **62%** |
| Algebraic loop block list | **63%** |
| Deep call stack | **40%** |
| Struct field display | **32%** |
| **Session average** | **48–66%** |

## How it works

The proxy is a Python asyncio process. It:
1. Receives MCP JSON-RPC messages from Claude (Content-Length framing or newline-delimited)
2. Forwards requests to the upstream `matlab-mcp-core-server` **unchanged**
3. Intercepts `tool_result` responses and applies 14 text compression rules to `content[].text`
4. Re-serialises with updated Content-Length and returns to Claude

Requests are never touched. The compressor is conservative — if no rule matches, text passes through byte-for-byte.

## The 14 compression rules

| Rule | What it compresses | Reduction |
|---|---|---|
| R01 | Repeated identical warnings (RCOND, Rate Transition, etc.) | ~59% |
| R02 | Deep MATLAB call stack traces (>3 frames) | ~40% |
| R03 | `whos` variable tables | ~74% |
| R04 | Large numeric array auto-display | ~85% |
| R05 | Long Simulink block paths in quoted strings | varies |
| R06 | Algebraic loop block lists (>3 blocks) | ~63% |
| R07 | Simulink `### Starting/Successful build` output | ~56% |
| R08 | Repeated `fprintf` progress lines (DOE sweeps, loops) | ~79% |
| R09 | Test runner pass/fail output | ~62% |
| R10 | MATLAB struct field display | ~32% |
| R11 | "An error occurred while running the simulation…" boilerplate | always |
| R12 | Redundant `Caused by:` block (same error as main) | ~58% |
| R13 | Simscape init-condition variable lists | varies |
| R14 | Unquoted block paths in `model_read` / `model_overview` output | ~36% |

## Installation

### Requirements
- Python 3.9+
- `matlab-mcp-core-server` installed ([matlab/matlab-mcp-core-server](https://github.com/matlab/matlab-mcp-core-server))
- Simulink Agentic Toolkit (for `model_edit`, `model_overview` etc.) — optional

### 1. Clone

```bash
git clone https://github.com/nightfury1802/matlab-mcp-proxy.git
cd matlab-mcp-proxy
```

### 2. Apply to Claude Code config

```bash
bash install.sh
```

This patches `~/.claude.json` (Claude Code's MCP config) to wrap both the `matlab` and `simulink` servers through the proxy. A backup is created at `~/.claude.json.bak`.

```bash
bash install.sh --bypass     # proxy running, compression disabled (for debugging)
bash install.sh --uninstall  # restore direct connections
```

### 3. Restart Claude Code

MATLAB starts automatically on first tool call (~15–20s). The simulink server attaches within a 30-second discovery window.

## Configuration

After running `install.sh`, `~/.claude.json` looks like this:

```json
{
  "mcpServers": {
    "matlab": {
      "command": "python3",
      "args": [
        "/path/to/matlab-mcp-proxy/proxy.py",
        "--upstream", "/path/to/matlab-mcp-core-server",
        "--initial-working-folder", "/your/work/folder",
        "--matlab-root", "/Applications/MATLAB_R2025a.app",
        "--initialize-matlab-on-startup=true"
      ],
      "env": {}, "type": "stdio"
    },
    "simulink": {
      "command": "python3",
      "args": [
        "/path/to/matlab-mcp-proxy/proxy.py",
        "--upstream", "/path/to/matlab-mcp-core-server",
        "--matlab-session-mode=existing",
        "--extension-file=/path/to/simulink-agentic-toolkit/tools/tools.json"
      ],
      "env": {}, "type": "stdio"
    }
  }
}
```

> **Important:** `~/.claude.json` is the config for Claude Code CLI / VS Code extension.  
> `~/Library/Application Support/Claude/claude_desktop_config.json` is for Claude Desktop — a different app.

## Wire format

`matlab-mcp-core-server` uses **Content-Length framing** (LSP/JSON-RPC style), not newline-delimited JSON. The proxy auto-detects this — no configuration needed.

## The simulink session attach problem

`--matlab-session-mode=existing` polls for a running MATLAB session for 30 seconds at startup. Without `--initialize-matlab-on-startup=true` on the matlab server, MATLAB starts lazily (only on the first tool call) and the 30-second window expires before MATLAB is ready.

The fix — `--initialize-matlab-on-startup=true` — makes MATLAB start at Claude Code launch (~15–20s), within the discovery window.

This is tracked upstream at [matlab/matlab-mcp-core-server#62](https://github.com/matlab/matlab-mcp-core-server/issues/62).

## Reverting

```bash
bash install.sh --uninstall
# restart Claude Code
```

Or manually restore `~/.claude.json`:

```python
import json
d = json.load(open('/Users/your-user/.claude.json'))
core = '/path/to/matlab-mcp-core-server'
toolkit = '/path/to/simulink-agentic-toolkit'
d['mcpServers']['matlab'] = {
    "command": core,
    "args": ["--initial-working-folder", "...", "--matlab-root", "...",
             "--initialize-matlab-on-startup=true"],
    "env": {}, "type": "stdio"
}
d['mcpServers']['simulink'] = {
    "command": core,
    "args": ["--matlab-session-mode=existing",
             f"--extension-file={toolkit}/tools/tools.json"],
    "env": {}, "type": "stdio"
}
json.dump(d, open('/Users/your-user/.claude.json', 'w'), indent=2)
```

## Testing

```bash
# Unit tests (no MATLAB needed)
cd matlab-mcp-proxy
pytest tests/test_compressor.py tests/test_proxy_protocol.py -v
# 37 tests, ~0.02s

# Live test: quarter-car active suspension
# See tests/quarter_car_suspension/
```

The `tests/quarter_car_suspension/` folder contains a validated Simscape quarter-car active suspension model (`QCarV2.slx`) built entirely via `model_edit` and simulated via `evaluate_matlab_code`. Results: 61.7% lower peak chassis velocity, 33.9% faster settling with active PD control vs passive.

## When to disable compression

- You need raw numerical output to debug a result
- An error message looks truncated and you need full context
- You see `]` characters leaking in tool output (proxy parsing bug — file an issue)

Use `bash install.sh --bypass` to keep the proxy running but skip all compression rules.

## Files

```
proxy.py          — MCP stdio proxy (asyncio, stdlib only, ~210 lines)
compressor.py     — 14 compression rules (~380 lines)
install.sh        — patches ~/.claude.json for matlab + simulink
tests/
  test_compressor.py       — 27 unit tests, one per rule
  test_proxy_protocol.py   — 10 protocol tests (Content-Length, bypass, etc.)
  quarter_car_suspension/  — live Simscape validation test
docs/
  index.html               — full HTML documentation (self-contained, offline-ready)
```

## Compared to other MCP proxies

| Project | Compresses | Domain rules |
|---|---|---|
| [mcp-compressor](https://github.com/atlassian-labs/mcp-compressor) | Tool descriptions/schemas | None |
| [mcp-rtk](https://github.com/ThomasTartrau/mcp-rtk) | Tool results (GitLab, Grafana) | GitLab / Grafana JSON |
| **matlab-mcp-proxy** | Tool results | **MATLAB / Simulink / Simscape** |

## License

MIT

---

*Built with Claude Code. Validated on MATLAB R2025a, Simulink, Simscape Foundation library.*
