# MATLAB MCP Proxy — Test Scenarios

Each `.m` file here is a real MATLAB script that exercises a specific compression rule.
Run them via Claude Code with the proxy active to test compression on real output.

## Live test procedure

1. Ensure proxy is active: `bash matlab-mcp-proxy/install.sh` then restart Claude Code
2. Ask Claude: `"Run the file matlab-mcp-proxy/tests/scenarios/test_whos.m"`
3. Claude calls `run_matlab_file` → matlab-mcp-server executes → proxy compresses → Claude sees result
4. Verify: does the compressed output convey all the same information as the raw output would?
5. To see raw output: ask Claude to run `bash matlab-mcp-proxy/install.sh --bypass` then restart and re-run

## Scenario index

| File | What MATLAB outputs | Rules tested | Expected reduction |
|------|--------------------|--------------|--------------------|
| `test_whos.m` | Variable table (whos) | R03 | ~74% |
| `test_repeated_warnings.m` | Repeated RCOND warnings × 10 | R01 | ~59% |
| `test_nested_error.m` | Deep 4-frame call stack error | R02 | ~40% |
| `test_doe_progress.m` | 15 fprintf progress lines | R08 | ~79% |
| `test_struct_display.m` | 21-field struct display | R10 | ~32% |
| `test_large_array.m` | Two 1000-row vector displays | R04 | ~85% |
| `test_simscape_error.m` | Simscape sim error with paths | R05, R11, R12 | ~50% |
| `test_build_output.m` | Simulink ### build output | R07 | ~56% |

## Pass criteria

For each scenario, the compressed output must satisfy ALL of these:

- **Meaning preserved:** all variable names, error messages, file:line references,
  and numerical values visible in the raw output are present in the compressed output
- **No hallucination:** the compressed output contains no information absent from raw
- **Shorter:** `len(compressed) < len(raw)` for all scenarios above except where noted
- **Passthrough on miss:** if the compressor fires no rules, output is byte-identical to input

## Dry-run (no MATLAB required)

```bash
cd /Users/soorajkrishnan/simscape-agent/matlab-mcp-proxy
python3 tests/scenarios/run_scenarios.py
```

This compresses the .m source files themselves (not real MATLAB output) to show
what the compressor would do with similarly-structured text. For real validation,
run live via Claude Code with the proxy active.
