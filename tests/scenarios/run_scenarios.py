#!/usr/bin/env python3
"""
Dry-run scenario harness: shows what compression would produce on each .m file's
source code. For live output testing, run each .m via Claude Code with the proxy
active and compare what Claude sees vs what MATLAB actually produced.

Usage:
  python3 run_scenarios.py                  # all scenarios
  python3 run_scenarios.py --scenario whos  # one scenario by name fragment
"""
import sys, os, argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from compressor import compress, ratio

SCENARIOS_DIR = os.path.dirname(os.path.abspath(__file__))


def load_scenarios() -> list:
    """Returns list of (name, content) pairs for all .m files, sorted."""
    result = []
    for fname in sorted(os.listdir(SCENARIOS_DIR)):
        if fname.endswith('.m'):
            path = os.path.join(SCENARIOS_DIR, fname)
            with open(path) as f:
                result.append((fname, f.read()))
    return result


def print_scenario(name: str, content: str) -> None:
    SEP = "═" * 70
    compressed = compress(content)
    print(f"\n{SEP}")
    print(f"SCENARIO: {name}")
    print(f"{SEP}")
    print(f"── SOURCE ({len(content)} chars) ──")
    print(content[:500] + ("..." if len(content) > 500 else ""))
    print(f"── COMPRESSOR OUTPUT ({len(compressed)} chars) ──")
    print(compressed[:500] + ("..." if len(compressed) > 500 else ""))
    print(f"── REDUCTION: {ratio(content, compressed)}")
    print()
    print("NOTE: To test live, ask Claude to run this .m file via run_matlab_file.")
    print("      The proxy compresses the MCP tool_result before Claude sees it.")


def main() -> None:
    parser = argparse.ArgumentParser(description="MATLAB MCP proxy scenario dry-run")
    parser.add_argument("--scenario", help="Filter by scenario name fragment")
    args = parser.parse_args()

    scenarios = load_scenarios()
    if args.scenario:
        scenarios = [(n, c) for n, c in scenarios if args.scenario in n]

    if not scenarios:
        print(f"No scenarios found matching '{args.scenario}'")
        sys.exit(1)

    print(f"Found {len(scenarios)} scenario(s) in {SCENARIOS_DIR}")
    print("These are MATLAB source files — compression acts on MATLAB *output*, not source.")
    print("Run live tests by asking Claude to execute each .m with the proxy active.\n")

    for name, content in scenarios:
        print_scenario(name, content)


if __name__ == "__main__":
    main()
