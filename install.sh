#!/usr/bin/env bash
# install.sh — patches ~/.claude.json (Claude Code's MCP config) to enable/disable proxy.
#
# Requires matlab-mcp-core-server v0.10.0+ (github.com/matlab/matlab-mcp-core-server).
# v0.10.0 introduced --matlab-session-mode=auto (now the default) which starts MATLAB
# automatically if no session is found, fixing the 30-second attach-window issue (#62).
# The old --initialize-matlab-on-startup=true / --matlab-session-mode=existing workaround
# is no longer needed.
#
# NOTE — macOS 26 (Sequoia 2026) codesigning:
#   The upstream binary must be ad-hoc re-signed after download on macOS 26+.
#   This script does it automatically if MATLAB_MCP_SERVER is set to the binary path.
#   Run: codesign --force --deep --sign - /path/to/matlab-mcp-core-server
#
# CONFIG FILE: ~/.claude.json  (NOT claude_desktop_config.json — that's Claude Desktop)
#
# Architecture:
#   matlab   → proxy → core-server (auto mode — starts MATLAB on first tool call)
#   simulink → proxy → core-server --matlab-session-mode=existing (attaches to same session)
#   Both share the same MATLAB session.
#
#   Note: simulink still needs --matlab-session-mode=existing to attach to the matlab
#   server's session rather than start an independent one. v0.10.0's benefit: existing
#   mode now starts MATLAB as a fallback if the attach poll times out, so the server
#   never permanently fails even if timing is off.
#
# Usage:
#   bash install.sh             # enable proxy, compression active
#   bash install.sh --bypass    # enable proxy, bypass (no compression, for debugging)
#   bash install.sh --uninstall # restore direct connections (no proxy)
#
# After any change: restart Claude Code for it to take effect.
set -euo pipefail

PROXY_DIR="$(cd "$(dirname "$0")" && pwd)"
PROXY_PATH="$PROXY_DIR/proxy.py"
CONFIG="$HOME/.claude.json"

# Auto-detect upstream MCP binary (override with: UPSTREAM=/path/to/binary ./install.sh)
if [ -z "${UPSTREAM:-}" ]; then
    UPSTREAM=$(command -v matlab-mcp-core-server 2>/dev/null || true)
    if [ -z "$UPSTREAM" ] && [ -x "$HOME/.local/bin/matlab-mcp-core-server" ]; then
        UPSTREAM="$HOME/.local/bin/matlab-mcp-core-server"
    fi
    if [ -z "$UPSTREAM" ]; then
        echo "ERROR: matlab-mcp-core-server not found in PATH or ~/.local/bin."
        echo "  Install via: npm install -g @mathworks/matlab-mcp-server"
        echo "  Or set: UPSTREAM=/path/to/matlab-mcp-core-server $0"
        exit 1
    fi
fi
echo "Using upstream binary: $UPSTREAM"

# Auto-detect MATLAB root (override with: MATLAB_ROOT=/Applications/MATLAB_Rxxxx.app ./install.sh)
if [ -z "${MATLAB_ROOT:-}" ]; then
    MATLAB_ROOT=$(ls -d /Applications/MATLAB_R*.app 2>/dev/null | sort -rV | head -1 || true)
    if [ -z "$MATLAB_ROOT" ]; then
        echo "ERROR: MATLAB not found in /Applications/MATLAB_R*.app"
        echo "  Or set: MATLAB_ROOT=/Applications/MATLAB_R2025a.app $0"
        exit 1
    fi
fi
echo "Using MATLAB root: $MATLAB_ROOT"

# Auto-detect toolkit and workdir relative to proxy location
if [ -z "${TOOLKIT:-}" ]; then
    TOOLKIT="$(cd "$PROXY_DIR/.." && pwd)/simulink-agentic-toolkit"
fi
if [ -z "${WORKDIR:-}" ]; then
    WORKDIR="$(cd "$PROXY_DIR/.." && pwd)/work"
fi

BYPASS=false
UNINSTALL=false
for arg in "$@"; do
    case "$arg" in
        --bypass)    BYPASS=true    ;;
        --uninstall) UNINSTALL=true ;;
        --help|-h)
            grep '^#' "$0" | grep -v '!/usr/bin' | sed 's/^# //' | sed 's/^#//'
            exit 0 ;;
    esac
done

[ -f "$CONFIG" ] || { echo "ERROR: $CONFIG not found"; exit 1; }
[ -f "$PROXY_PATH" ] || [ "$UNINSTALL" = true ] || { echo "ERROR: proxy.py not found"; exit 1; }

cp "$CONFIG" "${CONFIG}.bak"
echo "Backed up → ${CONFIG}.bak"

if [ "$UNINSTALL" = true ]; then
    python3 - "$CONFIG" "$UPSTREAM" "$TOOLKIT" "$WORKDIR" "$MATLAB_ROOT" << 'PYEOF'
import sys, json
cfg, upstream, toolkit, workdir, mroot = sys.argv[1:]
with open(cfg) as f: d = json.load(f)
d['mcpServers']['matlab'] = {
    "command": upstream,
    "args": ["--initial-working-folder", workdir, "--matlab-root", mroot],
    "env": {}, "type": "stdio"
}
d['mcpServers']['simulink'] = {
    "command": upstream,
    "args": ["--matlab-session-mode=existing",
             f"--extension-file={toolkit}/tools/tools.json"],
    "env": {}, "type": "stdio"
}
with open(cfg, 'w') as f: json.dump(d, f, indent=2)
print("Uninstalled proxy — direct connections restored in ~/.claude.json")
PYEOF
else
    python3 - "$CONFIG" "$PROXY_PATH" "$UPSTREAM" "$TOOLKIT" "$WORKDIR" "$MATLAB_ROOT" "$BYPASS" << 'PYEOF'
import sys, json
cfg, proxy, upstream, toolkit, workdir, mroot, bypass = sys.argv[1:]
with open(cfg) as f: d = json.load(f)

def entry(extra):
    args = [proxy]
    if bypass == "true": args.append("--bypass")
    return {"command": "python3", "args": args + ["--upstream", upstream] + extra,
            "env": {}, "type": "stdio"}

d['mcpServers']['matlab'] = entry([
    "--initial-working-folder", workdir,
    "--matlab-root", mroot,
])
d['mcpServers']['simulink'] = entry([
    "--matlab-session-mode=existing",       # attach to matlab server's session (not start a new one)
    f"--extension-file={toolkit}/tools/tools.json"
])
with open(cfg, 'w') as f: json.dump(d, f, indent=2)
mode = "BYPASS (no compression)" if bypass == "true" else "compression ACTIVE"
print(f"Proxy installed in ~/.claude.json — mode: {mode}")
PYEOF
fi

echo ""
echo "─────────────────────────────────────────────────────────────"
echo " Restart Claude Code for changes to take effect"
echo " MATLAB will start automatically (auto session mode)"
echo " Verify: /mcp — both 'matlab' and 'simulink' should connect"
echo "─────────────────────────────────────────────────────────────"
