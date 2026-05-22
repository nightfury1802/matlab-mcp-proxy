"""
Seed the live oracle with PMSM FOC error→fix pairs.
Run once: python3 tests/pmsm_foc/seed_oracle.py
"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from kb.error_oracle import ErrorOracle

SEEDS_FILE = os.path.join(os.path.dirname(__file__), 'pmsm_error_seeds.json')
STORE_DIR  = os.path.join(os.path.dirname(__file__), '../../kb_store')

def main():
    oracle = ErrorOracle(store_dir=STORE_DIR)
    before = oracle.size()
    with open(SEEDS_FILE) as f:
        seeds = json.load(f)
    t0 = time.perf_counter()
    for seed in seeds:
        oracle.learn(seed['error'], seed['fix'])
    elapsed = (time.perf_counter() - t0) * 1000
    after = oracle.size()
    print(f"Seeded {after - before} new pairs in {elapsed:.0f}ms. Total KB size: {after}")
    print(f"Avg per pair: {elapsed / max(after - before, 1):.0f}ms")
    print("\nVerification queries:")
    queries = [
        ("Derivative of state 'Motor/id' is not finite. Singularity.", "Rs > 0"),
        ("Algebraic loop detected involving 'FOC/CurrentLoop/Integrator'.", "Unit Delay"),
        ("Variable 'PMSM/omega_r' could not be initialized. Target value = 0.", "priority"),
        ("simulation failed because of a step-size-too-small error at time 0.0001", "ode15s"),
    ]
    for q, expected_keyword in queries:
        result = oracle.query(q)
        if result:
            fix, score = result
            status = "✓" if expected_keyword in fix else "✗"
            print(f"  {status} score={score:.3f}: {q[:50]}")
        else:
            print(f"  ✗ NO MATCH: {q[:50]}")

if __name__ == '__main__':
    main()
