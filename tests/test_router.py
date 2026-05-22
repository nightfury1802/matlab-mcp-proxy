"""
Tests for router.py — output type classification and pipeline dispatch.
Run: pytest tests/test_router.py -v
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from router import classify, route, OutputType

class TestClassify:
    def test_whos_output(self):
        text = "  Name   Size   Bytes  Class\n\n  x  1x1  8  double\n"
        assert classify(text) == OutputType.WHOS

    def test_error_output(self):
        text = "Error using sim (line 847)\nDerivative of state is not finite.\n"
        assert classify(text) == OutputType.ERROR

    def test_warning_output(self):
        text = "Warning: Matrix is close to singular. RCOND = 1.2e-17.\n> In solve\n"
        assert classify(text) == OutputType.WARNING

    def test_test_runner_output(self):
        text = "   1. test_alpha ... Passed\n   2. test_beta ... Failed\nTotals:\n   1 Passed\n"
        assert classify(text) == OutputType.TEST_RUN

    def test_build_output(self):
        text = "### Starting build procedure for: ModelA\n### Successful completion\n"
        assert classify(text) == OutputType.BUILD

    def test_simulation_result(self):
        text = "Simulation complete.\n\ntorque =\n\n   107.6300\n\nspeed =\n\n   6283.2\n"
        assert classify(text) == OutputType.SIM_RESULT

    def test_doe_progress(self):
        text = "DOE point  1/55: omega=1000 rpm, Tref=50 Nm -> T=49.82 Nm [PASS]\n"
        assert classify(text) == OutputType.PROGRESS

    def test_struct_display(self):
        text = "params = \n\n  struct with fields:\n\n    Ld: 2.1e-04\n"
        assert classify(text) == OutputType.STRUCT

    def test_large_array(self):
        rows = "\n".join(f"   {float(i)}" for i in range(10))
        text = f"torque =\n\n{rows}\n"
        assert classify(text) == OutputType.ARRAY

    def test_model_query(self):
        text = "Block: model/Sub1/Sub2/Block\nParam: Gain = 1.0\n"
        assert classify(text) == OutputType.MODEL_QUERY

    def test_plain_scalar(self):
        text = "ans =\n\n   107.6300\n"
        assert classify(text) == OutputType.PLAIN

    def test_empty_passthrough(self):
        text = ""
        assert classify(text) == OutputType.PLAIN

    def test_model_query_with_struct_value_not_misclassified(self):
        """model_read output with struct value must route to MODEL_QUERY, not STRUCT."""
        text = (
            "Block: ModelName/Subsystem/Motor\n"
            "result = \n\n"
            "  struct with fields:\n\n"
            "    Ld: 0.00021\n"
        )
        assert classify(text) == OutputType.MODEL_QUERY


class TestRoute:
    def test_route_returns_type(self):
        text = "Warning: Matrix is close to singular. RCOND = 1.2e-17.\n> In solve\n"
        compressed, otype = route(text)
        assert otype == OutputType.WARNING
        assert isinstance(compressed, str)

    def test_route_whos_compresses(self):
        text = "  Name   Size   Bytes  Class\n\n  x  1x1  8  double\n  y  1x1  8  double\n"
        compressed, otype = route(text)
        assert otype == OutputType.WHOS
        assert len(compressed) < len(text)

    def test_route_plain_passthrough(self):
        text = "ans =\n\n   107.6300\n"
        compressed, otype = route(text)
        assert otype == OutputType.PLAIN
        assert compressed == text

    def test_route_preserves_numerical_values(self):
        text = (
            "Warning: Matrix is close to singular. RCOND = 1.2e-17.\n> In solve\n" * 4
            + "\nans =\n\n   107.6300\n"
        )
        # warning classified first
        compressed, otype = route(text)
        assert "107.6300" in compressed

    def test_compress_delegates_to_route(self):
        """compress() must delegate to route() — not run its own pipeline."""
        from compressor import compress
        text = "  Name   Size   Bytes  Class\n\n  x  1x1  8  double\n"
        result = compress(text)
        assert result.startswith("whos:")


class TestTiming:
    """Verify routing is fast enough not to add meaningful proxy overhead."""

    def test_classify_under_1ms(self):
        text = "Error using sim (line 847)\nDerivative of state is not finite.\n"
        start = time.perf_counter()
        for _ in range(1000):
            classify(text)
        elapsed_ms = (time.perf_counter() - start) * 1000 / 1000
        assert elapsed_ms < 1.0, f"classify() averaged {elapsed_ms:.3f}ms — too slow"

    def test_route_under_5ms(self):
        """Full pipeline on a 2KB error output should complete in under 5ms."""
        text = (
            "An error occurred while running the simulation and the simulation was terminated:\n\n"
            "Derivative of state 'Motor/id' is not finite.\n\n"
            "Error in sim (line 847)\n"
            "  out = sim(MODEL);\n" * 8
        )
        start = time.perf_counter()
        for _ in range(200):
            route(text)
        elapsed_ms = (time.perf_counter() - start) * 1000 / 200
        assert elapsed_ms < 5.0, f"route() averaged {elapsed_ms:.3f}ms — too slow"
