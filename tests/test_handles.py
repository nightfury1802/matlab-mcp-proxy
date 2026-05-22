"""
Tests for kb/sim_handles.py — context handles for simulation results.
Run: pytest tests/test_handles.py -v
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest
from kb.sim_handles import SimHandleStore

SIM_OUTPUT_LARGE = """Simulation complete.

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

Final torque: 107.63 Nm at t=0.45 s. Efficiency: 97.2%.
"""

SIM_OUTPUT_SMALL = "ans =\n\n   42.0\n"

SIM_OUTPUT_2 = """Simulation complete.

torque =

   95.2100

speed =

   5235.9

Final torque: 95.21 Nm at t=0.45 s.
"""


@pytest.fixture
def store(tmp_path):
    return SimHandleStore(store_dir=str(tmp_path))


class TestSimHandleStore:
    def test_store_returns_handle_id(self, store):
        handle_id, summary = store.store(SIM_OUTPUT_LARGE)
        assert handle_id.startswith("SimHandle#")
        assert int(handle_id.split("#")[1]) >= 0

    def test_summary_contains_key_signals(self, store):
        _, summary = store.store(SIM_OUTPUT_LARGE)
        assert "107.63" in summary or "torque" in summary.lower()

    def test_summary_is_compact(self, store):
        _, summary = store.store(SIM_OUTPUT_LARGE)
        assert len(summary) < 300, f"Summary too long: {len(summary)} chars"

    def test_expand_returns_full_output(self, store):
        handle_id, _ = store.store(SIM_OUTPUT_LARGE)
        assert store.expand(handle_id) == SIM_OUTPUT_LARGE

    def test_expand_unknown_handle_returns_none(self, store):
        assert store.expand("SimHandle#999") is None

    def test_multiple_handles_independent(self, store):
        h1, _ = store.store(SIM_OUTPUT_LARGE)
        h2, _ = store.store(SIM_OUTPUT_2)
        assert h1 != h2
        assert store.expand(h1) == SIM_OUTPUT_LARGE
        assert store.expand(h2) == SIM_OUTPUT_2

    def test_small_output_not_stored(self, store):
        """Outputs below MIN_SIZE_CHARS should not create a handle."""
        handle_id, result = store.store(SIM_OUTPUT_SMALL)
        assert handle_id == ""
        assert result == SIM_OUTPUT_SMALL

    def test_format_for_context_is_compact(self, store):
        handle_id, summary = store.store(SIM_OUTPUT_LARGE, metadata={"model": "PMSM_FOC"})
        formatted = store.format_for_context(handle_id, summary)
        assert "SimHandle#" in formatted
        assert len(formatted) < 400

    def test_persists_across_instances(self, tmp_path):
        s1 = SimHandleStore(store_dir=str(tmp_path))
        handle_id, _ = s1.store(SIM_OUTPUT_LARGE)
        s2 = SimHandleStore(store_dir=str(tmp_path))
        assert s2.expand(handle_id) == SIM_OUTPUT_LARGE

    def test_metadata_appears_in_summary(self, store):
        _, summary = store.store(SIM_OUTPUT_LARGE, metadata={"model": "PMSM_FOC", "t_stop": "0.5"})
        assert "PMSM_FOC" in summary or "model" in summary.lower()

class TestHandleTiming:
    def test_store_and_format_under_50ms(self, store):
        """Handle creation should be negligible compared to simulation time."""
        times = []
        for i in range(10):
            t0 = time.perf_counter()
            handle_id, summary = store.store(SIM_OUTPUT_LARGE, metadata={"run": str(i)})
            _ = store.format_for_context(handle_id, summary)
            times.append((time.perf_counter() - t0) * 1000)
        avg_ms = sum(times) / len(times)
        print(f"\nHandle store+format avg: {avg_ms:.2f}ms")
        assert avg_ms < 50, f"Handle creation too slow: {avg_ms:.2f}ms"

    def test_token_reduction(self, store):
        """Verify the actual token reduction is significant."""
        handle_id, summary = store.store(SIM_OUTPUT_LARGE)
        formatted = store.format_for_context(handle_id, summary)
        reduction = 1 - len(formatted) / len(SIM_OUTPUT_LARGE)
        print(f"\nToken reduction: {reduction*100:.0f}% ({len(SIM_OUTPUT_LARGE)}→{len(formatted)} chars)")
        assert reduction > 0.70, f"Insufficient reduction: {reduction*100:.0f}%"
