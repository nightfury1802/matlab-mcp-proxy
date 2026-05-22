"""
Tests for kb/error_oracle.py — error→fix semantic KB.
Run: pytest tests/test_oracle.py -v
NOTE: First run warms up the bge-small model (~1s). Subsequent tests are fast.
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest
from kb.error_oracle import ErrorOracle

@pytest.fixture
def tmp_store(tmp_path):
    return str(tmp_path)

@pytest.fixture
def seeded_oracle(tmp_store):
    oracle = ErrorOracle(store_dir=tmp_store)
    oracle.learn(
        "Derivative of state 'Motor/id' is not finite. Singularity likely.",
        "Set absolute tolerance to 1e-6 and verify Rs > 0 and Ld > 0 in motor parameters."
    )
    oracle.learn(
        "Algebraic loop detected involving block 'FOC/CurrentLoop/Integrator'.",
        "Insert a Unit Delay or Memory block in the algebraic loop feedback path."
    )
    oracle.learn(
        "Variable 'Motor/omega' could not be initialized. Target value = 0, priority = high.",
        "Change omega initialization priority to 'none' or add an angular velocity source IC block."
    )
    return oracle

class TestErrorOracle:
    def test_query_exact_match(self, seeded_oracle):
        result = seeded_oracle.query("Derivative of state 'Motor/id' is not finite.")
        assert result is not None
        fix, score = result
        assert "Rs > 0" in fix
        assert score > 0.90

    def test_query_paraphrased_match(self, seeded_oracle):
        result = seeded_oracle.query(
            "State derivative X is infinite — possible singularity in the model."
        )
        assert result is not None
        fix, score = result
        assert score > 0.82

    def test_query_wrong_domain_no_match(self, seeded_oracle):
        result = seeded_oracle.query("Python ImportError: No module named numpy")
        if result is not None:
            _, score = result
            assert score < 0.82

    def test_query_empty_store(self, tmp_store):
        oracle = ErrorOracle(store_dir=tmp_store)
        assert oracle.query("some error") is None

    def test_learn_increases_store_size(self, tmp_store):
        oracle = ErrorOracle(store_dir=tmp_store)
        assert oracle.size() == 0
        oracle.learn("error A", "fix A")
        assert oracle.size() == 1
        oracle.learn("error B", "fix B")
        assert oracle.size() == 2

    def test_learn_persists_to_disk(self, tmp_store):
        oracle1 = ErrorOracle(store_dir=tmp_store)
        oracle1.learn(
            "Rate Transition block inserted automatically for 'Motor/id'.",
            "Add explicit Rate Transition block between continuous and discrete subsystems."
        )
        oracle2 = ErrorOracle(store_dir=tmp_store)
        result = oracle2.query("Rate Transition inserted automatically")
        assert result is not None
        fix, score = result
        assert "Rate Transition" in fix
        assert score > 0.85

    def test_algebraic_loop_match(self, seeded_oracle):
        result = seeded_oracle.query(
            "An algebraic loop exists in 'FOC/CurrentController' subsystem."
        )
        assert result is not None
        fix, _ = result
        assert "Unit Delay" in fix

    def test_format_hint_structure(self, seeded_oracle):
        hint = seeded_oracle.format_hint(
            "Derivative of state 'Motor/iq' is not finite."
        )
        assert hint is not None
        assert hint.startswith("[ORACLE")
        assert "score=" in hint

    def test_format_hint_none_when_no_match(self, tmp_store):
        oracle = ErrorOracle(store_dir=tmp_store)
        assert oracle.format_hint("totally unrelated text") is None

class TestOracleTiming:
    """Measure oracle query latency for performance logging."""

    def test_query_latency_with_warm_model(self, seeded_oracle):
        """After warm-up, each query should complete in under 2 seconds."""
        # Warm up
        seeded_oracle.query("warm up call")
        # Measure
        times = []
        for _ in range(5):
            t0 = time.perf_counter()
            seeded_oracle.query("Derivative of state is not finite")
            times.append((time.perf_counter() - t0) * 1000)
        avg_ms = sum(times) / len(times)
        print(f"\nOracle query avg latency (warm): {avg_ms:.1f}ms")
        assert avg_ms < 2000, f"Oracle query too slow: {avg_ms:.1f}ms"
