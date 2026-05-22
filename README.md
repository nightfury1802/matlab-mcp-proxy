# matlab-mcp-proxy

A transparent MCP stdio proxy that compresses verbose MATLAB®, Simulink®, and Simscape® tool responses before they reach your AI agent's context window — saving 48–85% on every tool call, with a semantic Error→Fix oracle and context handles for simulation results.

---

## Architecture

```
Claude Code
     │  tool_result (MCP JSON-RPC)
     ▼
┌─────────────────────────────── proxy.py ───────────────────────────────────┐
│                                                                             │
│  1. strip_html()          Remove MATLAB IDE hyperlinks                      │
│                                                                             │
│  2. router.classify()     Detect output type — 11 types:                   │
│     ┌────────────────────────────────────────────────────────┐             │
│     │ WHOS  ERROR  WARNING  TEST_RUN  BUILD  SIM_RESULT      │             │
│     │ PROGRESS  STRUCT  ARRAY  MODEL_QUERY  PLAIN            │             │
│     └────────────────────────────────────────────────────────┘             │
│                                                                             │
│  3. type-specific pipeline  14 compression rules per type:                 │
│     R01 repeated warnings    R08 progress lines (DOE sweeps)                │
│     R02 deep stack traces    R09 test runner output                         │
│     R03 whos tables          R10 struct field display                       │
│     R04 large arrays         R11 sim error boilerplate                      │
│     R05 block paths          R12 redundant Caused-By                        │
│     R06 algebraic loop lists R13 init-condition var lists                   │
│     R07 build output         R14 model_read block paths                     │
│                                                                             │
│  4. Error→Fix Oracle  (ERROR / WARNING only)                                │
│     kb/error_oracle.py  BAAI/bge-small-en-v1.5  384-dim  threshold 0.79   │
│     → prepends  [ORACLE (score=0.84): fix description...]                  │
│     → 19 PMSM FOC + Simscape seeds (grows with every debugging session)    │
│                                                                             │
│  5. Context Handles  (SIM_RESULT > 300 chars)                               │
│     kb/sim_handles.py                                                       │
│     → replaces 600-char signal dump with  [SimHandle#N] torque=... iq=...  │
│     → full output stored in kb_store/handles/  •  expand on request        │
└─────────────────────────────────────────────────────────────────────────────┘
     │  compressed tool_result
     ▼
Claude Code  ←──── matlab-mcp-proxy ────►  matlab-mcp-core-server  ────►  MATLAB R2025a
                   (compresses + enriches)  (unchanged protocol)
```

---

## Results

### Quarter-car active suspension (Simscape Foundation, PD controller)

Built twice — once via `evaluate_matlab_code`, once entirely via `model_edit` from the Simulink Agentic Toolkit — identical results.

| Metric | Passive | Active | Improvement |
|---|---|---|---|
| Peak chassis velocity | 0.120 m/s | 0.046 m/s | **61.7% lower** |
| Settling time | 2.665 s | 1.761 s | **33.9% faster** |

### PMSM FOC model build session (19 oracle seeds, 9-pt DOE)

Measured during programmatic construction of `PMSM_FOC_Proxy_Test.slx` using Simulink MCP:

| Proxy feature | Firings | Chars saved | Tokens saved |
|---|---|---|---|
| whos compression (R03) | 12× | 8,220 | ~2,055 |
| Warning dedup (R01) | 9× | 28,620 | ~7,155 |
| Sim result handles | 6× | 2,130 | ~532 |
| Struct compression (R10) | 7× | 1,120 | ~280 |
| DOE progress lines (R08) | 2× | 1,240 | ~310 |
| Build output (R07) | 3× | 1,080 | ~270 |
| **Total** | **48 firings** | **42,410** | **~10,600** |
| Oracle hints | 15 firings | — | ~30 min debugging saved |
| **Session reduction** | | | **82%** |

---

## Token compression by output type

| Output type | Reduction |
|---|---|
| `whos` variable table | **74%** |
| Repeated solver warnings | **59–71%** |
| Large array auto-display | **85%** |
| Simulink build log | **56%** |
| DOE progress loop (55 pts) | **79%** |
| Test runner output | **62%** |
| Algebraic loop block list | **63%** |
| `model_read` block paths | **36%** |
| Deep call stack | **40%** |
| Struct field display | **32–52%** |
| Simulation result (context handle) | **71–95%** |
| **Session average** | **48–82%** |

---

## The 14 compression rules

| Rule | What it compresses | Reduction |
|---|---|---|
| R01 | Repeated identical warnings (RCOND, Rate Transition, AlgLoop) | ~59% |
| R02 | Deep MATLAB call stack traces (>3 frames) | ~40% |
| R03 | `whos` variable tables | ~74% |
| R04 | Large numeric array auto-display | ~85% |
| R05 | Long Simulink block paths in quoted strings | varies |
| R06 | Algebraic loop block lists (>3 blocks) | ~63% |
| R07 | Simulink `### Starting/Successful build` output | ~56% |
| R08 | Repeated `fprintf` progress lines (DOE sweeps, loops) | ~79% |
| R09 | Test runner pass/fail output | ~62% |
| R10 | MATLAB struct field display | ~32–52% |
| R11 | "An error occurred while running the simulation…" boilerplate | always |
| R12 | Redundant `Caused by:` block (same error as main) | ~58% |
| R13 | Simscape init-condition variable lists | varies |
| R14 | Unquoted block paths in `model_read` / `model_overview` output | ~36% |

---

## Error→Fix Oracle

A local vector knowledge base that maps MATLAB/Simscape error messages to known fixes.
Uses **BAAI/bge-small-en-v1.5** (384-dim, ~22MB, CPU-only) via `sentence-transformers`.
Cosine similarity threshold: **0.79**. Fires only on ERROR and WARNING outputs (~7ms per query).

**Live-validated output:**
```
[ORACLE (score=0.84): Check motor impedance parameters: if Ld/Lq are in mH
but code expects H, scale by 1e-3. Also check simulation time step is not
larger than Ld/Rs.]
Warning: Matrix is singular to working precision.  [×5]
```

**Seed with 19 PMSM FOC + Simscape errors (included in repo):**
```bash
python3 tests/pmsm_foc/seed_oracle.py
```

**Add new errors after a debugging session:**
```python
from kb.error_oracle import ErrorOracle
oracle = ErrorOracle(store_dir='kb_store/')
oracle.learn(
    "Paste the exact MATLAB error text here",
    "What fixed it — solver settings, parameter values, block changes"
)
```

**Covered error types (19 seeds):**
- Non-finite state derivatives (PMSM singularity)
- Algebraic loops with current feedback
- Simscape variable initialization conflicts
- Rate Transition auto-insertion
- Singular matrix (RCOND warnings)
- Step-size-too-small solver failures
- Flux linkage initialization
- Undefined workspace variables
- Wrong PID parameter names (`InitialConditionForOutput` → `InitialConditionForIntegrator`)
- Electrical vs mechanical angular frequency bug (ω vs ωe = p×ω)
- Velocity source IC conflict with PMSM initial state
- Invalid Simulink block path when wiring
- set_param argument count errors
- simscape.addConnection port type mismatches

---

## Context Handles for Simulation Results

Simulation results > 300 chars are replaced with a compact `SimHandle#N` summary.
The full output is stored in `kb_store/handles/` and retrieved on request.

**Live-validated output (11-signal sim result, 2026-05-22):**
```
Before: torque=\n\n 107.6300\nspeed=\n\n 6283.2...(600+ chars across 11 signals)

After:  [SimHandle#0] torque=107.6300, speed=6283.2000, id=-12.3400
```

Ask Claude `expand SimHandle#0` to retrieve the full output.

---

## Performance benchmark (2026-05-22)

| Metric | Value | Notes |
|--------|-------|-------|
| `classify()` latency | < 0.04ms | Pure regex, no I/O |
| `route()` latency | < 0.09ms | Type-specific pipeline |
| Oracle warm query | ~7ms | Only for ERROR/WARNING types |
| Handle store | 0.59ms | Pure JSON/disk |
| Proxy overhead (non-oracle) | +0.01–0.09ms | Negligible vs MATLAB call time |
| Proxy overhead (ERROR path) | +16.7ms | Embedding cost — acceptable for debug |

Run the benchmark yourself: `python3 tests/benchmark.py`

### Live validation results (Simulink MCP, MATLAB R2025a, 2026-05-22)

| Test | Feature | Result |
|------|---------|--------|
| T1: `whos` table | R03 whos compression | ✅ one-line `whos: x[1x1,dbl]...` |
| T1: struct + whos together | R10 + WHOS pipeline | ✅ both compressed in one pass, 52% |
| T3: 5× singular warnings | R01 dedup + oracle | ✅ `Warning: ... [×5]` + `[ORACLE score=0.84]` |
| T5: 15-pt DOE progress | R08 progress compression | ✅ `[11 lines omitted]`, 71% |
| T2: 11-signal sim result | Context handle | ✅ `[SimHandle#0] torque=107.63...` |

---

## Installation

### Requirements
- Python 3.9+
- `matlab-mcp-core-server` ([matlab/matlab-mcp-core-server](https://github.com/matlab/matlab-mcp-core-server))
- Simulink Agentic Toolkit — optional (for `model_edit`, `model_overview`)
- `pip install sentence-transformers` — optional, needed for oracle + handles only

### Quick start

```bash
git clone https://github.com/nightfury1802/matlab-mcp-proxy.git
cd matlab-mcp-proxy
bash install.sh
# Restart Claude Code
```

`install.sh` patches `~/.claude.json` to wrap both `matlab` and `simulink` servers through the proxy. A backup is created at `~/.claude.json.bak`.

```bash
bash install.sh --bypass     # proxy active, compression disabled (for debugging)
bash install.sh --uninstall  # restore direct connections
```

### Seed the oracle

```bash
python3 tests/pmsm_foc/seed_oracle.py   # loads 19 PMSM FOC + Simscape seeds
```

---

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

> **`~/.claude.json`** is the config for Claude Code CLI / VS Code extension.
> **`~/Library/Application Support/Claude/claude_desktop_config.json`** is for Claude Desktop.

---

## The simulink session attach problem

`--matlab-session-mode=existing` polls for a running MATLAB session for 30 seconds at startup. Without `--initialize-matlab-on-startup=true`, MATLAB starts lazily and the 30-second window expires before it's ready.

Fix: `--initialize-matlab-on-startup=true` makes MATLAB start at Claude Code launch (~15–20s), within the discovery window.

Tracked upstream at [matlab/matlab-mcp-core-server#62](https://github.com/matlab/matlab-mcp-core-server/issues/62).

---

## Testing

```bash
# All unit tests (no MATLAB needed)
pytest tests/test_compressor.py tests/test_proxy_protocol.py \
       tests/test_router.py tests/test_oracle.py tests/test_handles.py -v
# 79 tests

# End-to-end latency benchmark
python3 tests/benchmark.py

# PMSM FOC live test — paste PROMPT.md into Claude Code
# See tests/pmsm_foc/PROMPT.md
```

The `tests/quarter_car_suspension/` folder contains a validated Simscape quarter-car active suspension model (`QCarV2.slx`) built entirely via `model_edit`. 61.7% lower peak chassis velocity, 33.9% faster settling with active PD vs passive.

The `tests/pmsm_foc/` folder contains `PMSM_FOC_Proxy_Test.slx` — a PMSM (DQ0) with closed-loop PI current control, validated 9/9 DOE PASS at 0.0% torque error across 200–400 rad/s, 30–70 Nm.

---

## When to disable compression

- You need raw numerical output to debug a result
- An error message looks truncated and you need full context

Use `bash install.sh --bypass` to keep the proxy running but skip all compression rules.

---

## Files

```
proxy.py           — MCP stdio proxy (asyncio, stdlib only)
compressor.py      — 14 compression rules
router.py          — semantic mode router, 11 output types, HTML stripping
kb/
  embedder.py      — lazy-loaded BAAI/bge-small-en-v1.5 (384-dim)
  error_oracle.py  — Error→Fix vector KB, cosine similarity threshold 0.79
  sim_handles.py   — SimHandle#N context handle store
kb_store/          — persisted oracle vectors + sim handles (19 seeds)
install.sh         — patches ~/.claude.json for matlab + simulink
tests/
  test_compressor.py       — 27 rules tests
  test_proxy_protocol.py   — 10 protocol tests
  test_router.py           — 20 classification + timing tests
  test_oracle.py           — 10 oracle + latency tests
  test_handles.py          — 12 handle + reduction tests
  benchmark.py             — end-to-end latency benchmark
  pmsm_foc/
    PMSM_FOC_Proxy_Test.slx  — validated PMSM FOC model (reference)
    build_pmsm_foc.m         — build script (recreates model from scratch)
    PROMPT.md                — user prompt for Claude Code live testing
    pmsm_error_seeds.json    — 11 PMSM FOC error→fix seeds
    seed_oracle.py           — seeds oracle KB from JSON
  quarter_car_suspension/  — Simscape validation test
docs/
  index.html       — full HTML documentation
```

| Project | Compresses | Domain rules |
|---|---|---|
| [mcp-compressor](https://github.com/atlassian-labs/mcp-compressor) | Tool descriptions/schemas | None |
| [mcp-rtk](https://github.com/ThomasTartrau/mcp-rtk) | Tool results (GitLab, Grafana) | GitLab / Grafana JSON |
| **matlab-mcp-proxy** | Tool results | **MATLAB / Simulink / Simscape + semantic KB** |

MIT — Built with Claude Code. Validated on MATLAB R2025a.
