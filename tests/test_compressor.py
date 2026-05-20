"""
Unit tests for compressor.py — one test class per rule.
Run: pytest tests/test_compressor.py -v
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from compressor import (
    compress,
    compress_repeated_warnings,
    compress_stack_trace,
    compress_whos,
    compress_large_arrays,
    compress_block_paths,
    compress_block_lists,
    compress_build_output,
    compress_progress_lines,
    compress_test_output,
    compress_struct_display,
    compress_sim_error_boilerplate,
    compress_caused_by,
    compress_init_cond_vars,
)


class TestRepeatedWarnings:
    def test_deduplicates_four_identical_warnings(self):
        text = (
            "Warning: Matrix is close to singular. RCOND = 2.3e-17.\n"
            "> In solve (line 10)\n"
        ) * 4
        out = compress_repeated_warnings(text)
        assert out.count("Warning: Matrix") == 1
        assert "[×4]" in out

    def test_keeps_different_warnings_separate(self):
        text = (
            "Warning: Matrix is close to singular. RCOND = 1e-17.\n> In solve (line 1)\n"
            "Warning: Step size too small.\n> In ode15s (line 5)\n"
        )
        out = compress_repeated_warnings(text)
        assert "Matrix" in out
        assert "Step size" in out

    def test_path_agnostic_dedup_for_rate_transition(self):
        """Block_d and Block_q should deduplicate — only block name differs."""
        text = (
            "Warning: 'model/Sub/Block_d' has sample time 0.0001 s. "
            "A Rate Transition block was automatically inserted.\n"
            "> In Simulink.compile (line 1)\n"
            "Warning: 'model/Sub/Block_q' has sample time 0.0001 s. "
            "A Rate Transition block was automatically inserted.\n"
            "> In Simulink.compile (line 1)\n"
        )
        out = compress_repeated_warnings(text)
        assert out.count("Rate Transition") == 1
        assert "[×2]" in out

    def test_passthrough_when_no_warnings(self):
        text = "ans =\n\n   107.63\n"
        assert compress_repeated_warnings(text) == text


class TestStackTrace:
    def test_compresses_six_frame_stack(self):
        text = (
            "Error using sim (line 847)\n\n"
            "Error in DriveUnit.run (line 112)\n"
            "        simOut = sim();\n\n"
            "Error in run_doe (line 78)\n"
            "        result = DriveUnit.run();\n\n"
            "Error in doe_sweep (line 45)\n"
            "        results = run_doe();\n\n"
            "Error in batch (line 23)\n"
            "        doe_sweep();\n\n"
            "Error in runtests (line 67)\n"
            "        run(suite);\n"
        )
        out = compress_stack_trace(text)
        assert "intermediate frames omitted" in out
        assert "Error in DriveUnit.run" in out
        assert "Error in runtests" in out
        assert "Error using sim" in out  # top-level error header must be preserved

    def test_passthrough_when_three_or_fewer_frames(self):
        text = (
            "Error using sim (line 1)\n"
            "Error in my_func (line 5)\n"
            "        foo();\n"
            "Error in test (line 10)\n"
        )
        assert compress_stack_trace(text) == text


class TestWhos:
    def test_compact_format(self):
        text = (
            "  Name            Size              Bytes  Class\n\n"
            "  omega_r         1x1                   8  double\n"
            "  tout            1000x1             8000  double\n"
            "  params          1x1                1024  struct\n"
        )
        out = compress_whos(text)
        assert out.startswith("whos:")
        assert "omega_r[1x1,dbl]" in out
        assert "tout[1000x1,dbl]" in out
        assert "params[1x1,struct]" in out
        assert "Name" not in out

    def test_passthrough_when_no_whos_header(self):
        text = "ans =\n\n   107.63\n"
        assert compress_whos(text) == text


class TestLargeArrays:
    def test_compresses_array_with_more_rows_annotation(self):
        rows = "".join(f"   {i}.0000\n" for i in range(20))
        text = f"torque =\n\n{rows}\n(980 more rows — truncated)\n"
        out = compress_large_arrays(text)
        assert "1000x1" in out
        assert "first=0" in out
        assert "last=19" in out
        assert "980 more" not in out
        assert len(out) < len(text) // 2  # should be dramatically shorter

    def test_passthrough_short_array(self):
        text = "x =\n\n   1\n   2\n"
        assert compress_large_arrays(text) == text


class TestBlockPaths:
    def test_shortens_five_level_path(self):
        text = "'model/SubA/SubB/SubC/Block' is not connected."
        out = compress_block_paths(text)
        assert "'model/.../SubC/Block'" in out

    def test_keeps_three_level_path(self):
        text = "'model/SubA/Block' is not connected."
        assert compress_block_paths(text) == text


class TestBlockLists:
    def test_compresses_five_block_list(self):
        text = (
            "The following blocks are involved:\n"
            "  model/Sub/BlockA\n"
            "  model/Sub/BlockB\n"
            "  model/Sub/BlockC\n"
            "  model/Sub/BlockD\n"
            "  model/Sub/BlockE\n"
        )
        out = compress_block_lists(text)
        assert "Blocks(5)" in out
        assert "BlockA" in out
        assert "BlockE" in out
        assert "BlockB" not in out

    def test_keeps_three_block_list(self):
        text = (
            "The following blocks are involved:\n"
            "  model/Sub/A\n"
            "  model/Sub/B\n"
            "  model/Sub/C\n"
        )
        assert compress_block_lists(text) == text


class TestBuildOutput:
    def test_collapses_starting_successful_pairs(self):
        text = (
            "### Starting serial model reference simulation build.\n"
            "### Starting build procedure for: ModelA\n"
            "### Successful completion of build procedure for: ModelA\n"
            "### Starting build procedure for: ModelB\n"
            "### Successful completion of build procedure for: ModelB\n"
            "Build duration: 0h 0m 12s\n"
        )
        out = compress_build_output(text)
        assert "### Built: ModelA, ModelB" in out
        assert "Starting build procedure" not in out
        assert "Successful completion" not in out
        assert "Build duration: 0h 0m 12s" in out


class TestProgressLines:
    def test_elides_middle_of_long_run(self):
        lines = [f"DOE point {i}/55: omega={i*100} rpm [PASS]" for i in range(1, 22)]
        text = "\n".join(lines) + "\n"
        out = compress_progress_lines(text)
        assert "DOE point 1/55" in out
        assert "DOE point 2/55" in out
        assert "lines omitted" in out
        assert "DOE point 21/55" in out
        assert "DOE point 10/55" not in out

    def test_keeps_short_run_intact(self):
        lines = [f"Step {i}" for i in range(4)]
        text = "\n".join(lines)
        assert compress_progress_lines(text) == text


class TestTestOutput:
    def test_compact_pass_fail(self):
        text = (
            "Running suite\n"
            "================\n"
            "Test Results:\n"
            "================\n"
            "   1. test_alpha ... Passed (1.2s)\n"
            "   2. test_beta  ... Passed (2.3s)\n"
            "   3. test_gamma ... Failed (5.1s)\n"
            "      Expected 100, got 88\n"
            "================\n"
            "Totals:\n"
            "   2 Passed, 1 Failed, 0 Incomplete\n"
            "Total duration: 8.6 seconds\n"
        )
        out = compress_test_output(text)
        assert "PASS (2): test_alpha, test_beta" in out
        assert "FAIL (1): test_gamma" in out
        assert "Expected 100, got 88" in out
        assert "Running suite" not in out


class TestStructDisplay:
    def test_inline_struct_fields(self):
        text = (
            "params = \n\n"
            "  struct with fields:\n\n"
            "         Ld: 2.1000e-04\n"
            "         Rs: 0.0182\n"
            "          p: 4\n"
        )
        out = compress_struct_display(text)
        assert "struct:" in out
        assert "Ld=2.1000e-04" in out
        assert "Rs=0.0182" in out
        assert "struct with fields:" not in out


class TestBoilerplate:
    def test_strips_an_error_occurred(self):
        text = (
            "Error using sim\n"
            "An error occurred while running the simulation and the simulation was terminated:\n\n"
            "Derivative of state is not finite.\n"
        )
        out = compress_sim_error_boilerplate(text)
        assert "An error occurred while" not in out
        assert "Derivative of state is not finite." in out


class TestCausedBy:
    def test_drops_redundant_caused_by(self):
        text = (
            "Error using sim\n"
            "Derivative of state 'X/id' is not finite. Singularity likely.\n\n"
            "Error in test (line 1)\n\n"
            "Caused by:\n"
            "    Error using Simulink.run\n"
            "    Derivative of state 'X/id' is not finite at time 0.003. Singularity.\n"
        )
        out = compress_caused_by(text)
        assert "Caused by:" not in out

    def test_keeps_informative_caused_by(self):
        text = (
            "Error using sim\n"
            "Model failed to compile.\n\n"
            "Caused by:\n"
            "    Error using codegen\n"
            "    Undefined function 'foo' for input type double.\n"
        )
        out = compress_caused_by(text)
        assert "Undefined function" in out


class TestInitCondVars:
    def test_compresses_long_variable_list(self):
        text = (
            "The following variables could not be initialized:\n"
            "  model/Sub/Motor/id: target value = 0, priority = low\n"
            "  model/Sub/Motor/iq: target value = 0, priority = low\n"
            "  model/Sub/Motor/omega: target value = 0, priority = high\n"
            "  model/Sub/Motor/Flux: target value = 0, priority = low\n"
        )
        out = compress_init_cond_vars(text)
        assert "4 total" in out

    def test_passthrough_short_list(self):
        text = (
            "The following variables could not be initialized:\n"
            "  model/Sub/id: target = 0\n"
            "  model/Sub/iq: target = 0\n"
        )
        assert compress_init_cond_vars(text) == text


class TestFullPipeline:
    def test_pipeline_preserves_result_value(self):
        text = (
            "Warning: Matrix singular. RCOND = 1e-17.\n> In solve (line 1)\n" * 5
            + "\nans =\n\n   107.6300\n"
        )
        out = compress(text)
        assert "107.6300" in out

    def test_pipeline_passthrough_on_clean_output(self):
        text = "Simulation complete. Torque = 107.63 Nm at t = 0.45 s.\n"
        assert compress(text) == text

    def test_pipeline_never_modifies_empty_string(self):
        assert compress("") == ""
