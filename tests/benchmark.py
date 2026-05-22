"""
tests/benchmark.py — Proxy v2 performance benchmark

Measures and logs all improvements introduced in proxy-improvements-v2:
  1. Mode routing overhead (classify + route)
  2. Oracle query latency (warm)
  3. Handle creation + token reduction
  4. End-to-end _compress_response() on each output type

Run: python3 tests/benchmark.py
Output: printed performance report + BENCHMARK_RESULTS.md written to tests/
"""
import sys, os, time, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ── Helpers ────────────────────────────────────────────────────────────────────

def timeit(fn, n=100):
    """Run fn n times, return (avg_ms, min_ms, max_ms)."""
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return sum(times)/len(times), min(times), max(times)

def reduction(original: str, compressed: str) -> float:
    return 1 - len(compressed) / len(original) if original else 0

SEP = "=" * 65

# ── Test fixtures ──────────────────────────────────────────────────────────────

WHOS_OUTPUT = """\
  Name            Size              Bytes  Class

  omega_r         1x1                   8  double
  tout            1000x1             8000  double
  torque          1000x1             8000  double
  params          1x1                1024  struct
  LUT_id          51x51x5         5297832  double
  LUT_iq          51x51x5         5297832  double
"""

ERROR_OUTPUT = """\
An error occurred while running the simulation and the simulation was terminated:

Derivative of state 'PMSM_FOC_Proxy_Test/PMSM/id' is not finite. \
At time 0.001 s, the derivative is Inf. Singularity likely.

Error in sim (line 847)
  out = sim(MODEL);
Error in run_pmsm_foc_sim (line 32)
  out2 = sim(MODEL, 'StopTime', '0.01');
Error in run_tests (line 10)
  run_pmsm_foc_sim;
Error in test_runner (line 5)
  run_tests;
"""

WARNING_OUTPUT = (
    "Warning: Matrix is close to singular or badly scaled. "
    "Results may be inaccurate. RCOND = 2.3e-17.\n"
    "> In solve (line 10)\n"
) * 5

SIM_RESULT_OUTPUT = """\
Simulation complete.

torque =

   107.6300

speed =

   6283.2

id =

   -12.3400

iq =

   85.6700

Vd =

   -45.2300

Vq =

   215.8900

Final torque: 107.63 Nm at t=0.45 s.
"""

DOE_OUTPUT = "\n".join(
    f"DOE point {k:3d}/15: omega={[1000,2000,3000,4500,6000][k//3]:4d} rpm, "
    f"Tref={[50,80,107][k%3]:3d} Nm -> T={[50,80,107][k%3]*0.98:.2f} Nm [PASS]"
    for k in range(15)
) + "\n"

BUILD_OUTPUT = """\
### Starting serial model reference simulation build.
### Starting build procedure for: PMSM_FOC_Proxy_Test
### Successful completion of build procedure for: PMSM_FOC_Proxy_Test
### Starting build procedure for: PMSM_FOC_CurrentControl
### Successful completion of build procedure for: PMSM_FOC_CurrentControl
Build complete. Duration: 0h 0m 8s
"""

FIXTURES = {
    "WHOS":       WHOS_OUTPUT,
    "ERROR":      ERROR_OUTPUT,
    "WARNING x5": WARNING_OUTPUT,
    "SIM_RESULT": SIM_RESULT_OUTPUT,
    "DOE (15pt)": DOE_OUTPUT,
    "BUILD":      BUILD_OUTPUT,
}

# ── Benchmarks ─────────────────────────────────────────────────────────────────

def bench_routing(results: dict):
    """B1: Mode routing overhead."""
    print(f"\nB1: Mode Routing")
    print(f"  {'Output type':<15} {'classify':>10} {'route':>10} {'reduction':>10}")
    print(f"  {'-'*50}")
    from router import classify, route
    for name, text in FIXTURES.items():
        c_avg, c_min, _ = timeit(lambda t=text: classify(t), n=500)
        r_avg, r_min, _ = timeit(lambda t=text: route(t), n=200)
        compressed, _ = route(text)
        red = reduction(text, compressed)
        print(f"  {name:<15} {c_avg:>8.3f}ms {r_avg:>8.3f}ms {red*100:>8.1f}%")
        results[f"routing_{name}_classify_ms"] = round(c_avg, 4)
        results[f"routing_{name}_route_ms"] = round(r_avg, 4)
        results[f"routing_{name}_reduction_pct"] = round(red * 100, 1)


def bench_oracle(results: dict):
    """B2: Oracle query latency."""
    print(f"\nB2: Oracle Query Latency")
    from kb.error_oracle import ErrorOracle
    oracle = ErrorOracle(store_dir=os.path.join(os.path.dirname(__file__), '../kb_store'))

    if oracle.size() == 0:
        print("  Oracle is empty — run: python3 tests/pmsm_foc/seed_oracle.py")
        results["oracle_size"] = 0
        return

    # Warm up (first embed loads model into memory)
    print(f"  Oracle size: {oracle.size()} entries")
    print(f"  Warming up embedder...")
    oracle.query("warm up")

    queries = [
        ("Derivative not finite",    "Derivative of state 'Motor/id' is not finite"),
        ("Algebraic loop",           "Algebraic loop detected in FOC subsystem"),
        ("Init var failed",          "Variable omega could not be initialized"),
        ("Step size too small",      "simulation failed step-size-too-small error"),
        ("No match (Python error)",  "Python ImportError: No module named numpy"),
    ]
    print(f"  {'Query':<30} {'latency':>10} {'score':>8} {'match':>8}")
    print(f"  {'-'*60}")
    for label, q in queries:
        avg_ms, _, _ = timeit(lambda q=q: oracle.query(q), n=10)
        result = oracle.query(q)
        score_str = f"{result[1]:.3f}" if result else "—"
        match_str = "Y" if result else "N"
        print(f"  {label:<30} {avg_ms:>8.1f}ms {score_str:>8} {match_str:>8}")
        results[f"oracle_query_{label}_ms"] = round(avg_ms, 2)
        results[f"oracle_query_{label}_score"] = result[1] if result else 0
    results["oracle_size"] = oracle.size()


def bench_handles(results: dict):
    """B3: Context handle creation and token reduction."""
    print(f"\nB3: Context Handle Performance")
    import tempfile
    from kb.sim_handles import SimHandleStore

    with tempfile.TemporaryDirectory() as tmp:
        store = SimHandleStore(store_dir=tmp)

        # Latency
        avg_ms, min_ms, _ = timeit(
            lambda: store.store(SIM_RESULT_OUTPUT, {"model": "PMSM_FOC"}), n=100
        )
        print(f"  store() avg latency:    {avg_ms:.3f}ms (min {min_ms:.3f}ms)")

        handle_id, summary = store.store(SIM_RESULT_OUTPUT, {"model": "PMSM_FOC_Proxy_Test"})
        formatted = store.format_for_context(handle_id, summary)

        red = reduction(SIM_RESULT_OUTPUT, formatted)
        print(f"  Token reduction:        {red*100:.1f}%  ({len(SIM_RESULT_OUTPUT)} → {len(formatted)} chars)")
        print(f"  Handle output:          {formatted[:80]}...")

        expand_avg, _, _ = timeit(lambda: store.expand(handle_id), n=200)
        print(f"  expand() avg latency:   {expand_avg:.3f}ms")

        results["handle_store_ms"]    = round(avg_ms, 4)
        results["handle_expand_ms"]   = round(expand_avg, 4)
        results["handle_reduction_pct"] = round(red * 100, 1)
        results["handle_input_chars"] = len(SIM_RESULT_OUTPUT)
        results["handle_output_chars"] = len(formatted)


def bench_proxy_e2e(results: dict):
    """B4: End-to-end _compress_response() on mock MCP messages."""
    print(f"\nB4: End-to-End _compress_response() Latency")
    from proxy import _compress_response

    def make_msg(text):
        return {"id": "1", "result": {"content": [{"type": "text", "text": text}]}}

    print(f"  {'Type':<20} {'bypass=False':>14} {'bypass=True':>12} {'overhead':>10}")
    print(f"  {'-'*60}")

    type_fixtures = [
        ("WHOS",    WHOS_OUTPUT),
        ("ERROR",   ERROR_OUTPUT[:500]),
        ("WARNING", WARNING_OUTPUT),
        ("DOE",     DOE_OUTPUT),
        ("BUILD",   BUILD_OUTPUT),
    ]
    for name, text in type_fixtures:
        msg = make_msg(text)
        # bypass=False (full pipeline)
        active_avg, _, _ = timeit(lambda m=msg: _compress_response(m.copy(), bypass=False), n=50)
        # bypass=True (raw passthrough)
        bypass_avg, _, _ = timeit(lambda m=msg: _compress_response(m.copy(), bypass=True), n=200)
        overhead = active_avg - bypass_avg
        print(f"  {name:<20} {active_avg:>12.3f}ms {bypass_avg:>10.3f}ms {overhead:>+9.3f}ms")
        results[f"e2e_{name}_active_ms"]  = round(active_avg, 4)
        results[f"e2e_{name}_bypass_ms"]  = round(bypass_avg, 4)
        results[f"e2e_{name}_overhead_ms"] = round(overhead, 4)


def write_report(results: dict):
    """Write BENCHMARK_RESULTS.md alongside this file."""
    out_path = os.path.join(os.path.dirname(__file__), 'BENCHMARK_RESULTS.md')
    lines = [
        "# Proxy v2 Benchmark Results\n",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}\n",
        "Branch: proxy-improvements-v2\n",
        "\n## Raw Metrics\n",
        "```json\n",
        json.dumps(results, indent=2),
        "\n```\n",
        "\n## Summary\n",
        f"- Oracle KB size: {results.get('oracle_size', '?')} entries\n",
        f"- Handle token reduction: {results.get('handle_reduction_pct', '?')}%\n",
        f"- Handle creation latency: {results.get('handle_store_ms', '?')}ms\n",
        f"- Oracle warm query latency: {results.get('oracle_query_Derivative not finite_ms', '?')}ms\n",
    ]
    # Best routing reduction
    reductions = {k.replace("routing_", "").replace("_reduction_pct", ""): v
                  for k, v in results.items() if k.endswith("_reduction_pct")}
    if reductions:
        best = max(reductions, key=reductions.get)
        lines.append(f"- Best routing reduction: {reductions[best]:.1f}% ({best})\n")
    with open(out_path, "w") as f:
        f.writelines(lines)
    print(f"\nResults written to {out_path}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print(SEP)
    print("MATLAB MCP Proxy v2 — Performance Benchmark")
    print(SEP)

    results = {}
    bench_routing(results)
    bench_oracle(results)
    bench_handles(results)
    bench_proxy_e2e(results)
    write_report(results)

    print(f"\n{SEP}")
    print("SUMMARY")
    print(SEP)
    print(f"  Oracle KB entries:       {results.get('oracle_size', 0)}")
    print(f"  Handle reduction:        {results.get('handle_reduction_pct', '?')}%")
    print(f"  Handle latency:          {results.get('handle_store_ms', '?')}ms")
    if 'oracle_query_Derivative not finite_ms' in results:
        print(f"  Oracle query (warm):     {results['oracle_query_Derivative not finite_ms']}ms")
    print(SEP)

if __name__ == "__main__":
    main()
