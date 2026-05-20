#!/usr/bin/env bash
# install.sh — patches ~/.claude.json (Claude Code's MCP config) to enable/disable proxy.
#
# ROOT CAUSE & FIX (discovered 2026-05-20):
#   matlab-mcp-core-server --matlab-session-mode=existing retries for 30 seconds
#   waiting for the MATLAB Connector on the port written by the matlab server.
#   Without --initialize-matlab-on-startup=true, MATLAB starts lazily (on first
#   tool call) and the 30s window expires before MATLAB is ready → attach fails.
#   Adding --initialize-matlab-on-startup=true starts MATLAB eagerly (~15-20s),
#   within the 30s discovery window → shared session connects reliably.
#
# CONFIG FILE: ~/.claude.json  (NOT claude_desktop_config.json — that's Claude Desktop)
#
# Architecture:
#   matlab   → proxy → core-server --initialize-matlab-on-startup=true (starts MATLAB)
#   simulink → proxy → core-server --matlab-session-mode=existing      (attaches, 30s window)
#   Both share the same MATLAB session via connector.securePort.
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

UPSTREAM="/Users/soorajkrishnan/.local/bin/matlab-mcp-core-server"
TOOLKIT="/Users/soorajkrishnan/simscape-agent/simulink-agentic-toolkit"
WORKDIR="/Users/soorajkrishnan/simscape-agent/work"
MATLAB_ROOT="/Applications/MATLAB_R2025a.app"

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
    "args": ["--initial-working-folder", workdir, "--matlab-root", mroot,
             "--initialize-matlab-on-startup=true"],
    "env": {}, "type": "stdio"
}
d['mcpServers']['simulink'] = {
    "command": upstream,
    "args": [f"--matlab-session-mode=existing",
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
    "--initialize-matlab-on-startup=true"   # start MATLAB eagerly for simulink attach
])
d['mcpServers']['simulink'] = entry([
    "--matlab-session-mode=existing",       # attaches within 30s discovery window
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
echo " MATLAB will start automatically (~15-20s after launch)"
echo " simulink server attaches within 30s discovery window"
echo " Verify: /mcp — both 'matlab' and 'simulink' should connect"
echo "─────────────────────────────────────────────────────────────"
