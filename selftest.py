"""
selftest.py — Startup correctness checks for the compression pipeline.

Run via proxy.py main() on startup (skipped in --bypass mode).
Exits 1 with a clear diagnostic if any check fails.
Usage: python3 selftest.py   (also callable as a module)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_CHECKS = [
    # (name, input_text, must_contain, must_not_contain)
    (
        "whos_compression",
        (
            "  Name            Size              Bytes  Class\n\n"
            "  omega_r         1x1                   8  double\n"
            "  lambda_ds       1x1                   8  double\n"
        ),
        ["whos:", "omega_r[1x1,dbl]", "lambda_ds[1x1,dbl]"],
        ["Name            Size"],
    ),
    (
        "float_value_preservation",
        (
            "Warning: Singular matrix. RCOND = 1e-17.\n"
            "> In solve (line 1)\n"
        ) * 3 + "\nlambda_ds =\n\n   0.0847\n",
        ["0.0847"],
        [],
    ),
    (
        "stack_trace_compression",
        (
            "Error using sim (line 847)\n\n"
            "Error in DriveUnit.run (line 112)\n"
            "        simOut = sim();\n\n"
            "Error in run_doe (line 78)\n"
            "        result = DriveUnit.run();\n\n"
            "Error in doe_sweep (line 45)\n"
            "        doe_sweep();\n\n"
            "Error in runtests (line 67)\n"
            "        run(suite);\n"
        ),
        ["Error using sim", "intermediate frames omitted", "Error in runtests"],
        [],
    ),
]


def run_startup_checks() -> None:
    """Run 3 known-output checks. Calls sys.exit(1) with diagnostics if any fail."""
    from router import route

    failures = []
    for name, text, must_contain, must_not_contain in _CHECKS:
        try:
            compressed, _ = route(text)
        except Exception as exc:
            failures.append(f"  FAIL [{name}]: route() raised {exc!r}")
            continue
        for expected in must_contain:
            if expected not in compressed:
                failures.append(
                    f"  FAIL [{name}]: expected {expected!r} in output\n"
                    f"    got: {compressed[:300]!r}"
                )
        for forbidden in must_not_contain:
            if forbidden in compressed:
                failures.append(f"  FAIL [{name}]: {forbidden!r} must not appear in output")

    if failures:
        sys.stderr.write("[proxy] STARTUP SELF-TEST FAILED — compression pipeline is broken:\n")
        for f in failures:
            sys.stderr.write(f + "\n")
        sys.stderr.write(
            "[proxy] Run 'python3 -m pytest tests/test_compressor.py -v' for details.\n"
            "[proxy] To bypass compression and start anyway: use --bypass flag.\n"
        )
        sys.exit(1)


if __name__ == "__main__":
    run_startup_checks()
    print("Self-test: all 3 checks PASSED", file=sys.stderr)
