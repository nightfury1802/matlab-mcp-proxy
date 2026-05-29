"""
Unit tests for proxy.py _compress_response() intercept logic.
No subprocess required — tests the compression intercept in isolation.
Run: pytest tests/test_proxy_protocol.py -v
"""
import sys, os
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from proxy import _compress_response

WHOS_TEXT = (
    "  Name            Size              Bytes  Class\n\n"
    "  omega_r         1x1                   8  double\n"
    "  tout            1000x1             8000  double\n"
    "  params          1x1                1024  struct\n"
)


def make_tool_result(text: str) -> dict:
    return {"id": "1", "result": {"content": [{"type": "text", "text": text}]}}


class TestCompressResponse:
    def test_compresses_tool_result_text(self):
        msg = make_tool_result(WHOS_TEXT)
        out = _compress_response(msg, bypass=False)
        text = out["result"]["content"][0]["text"]
        assert text.startswith("whos:")
        assert len(text) < len(WHOS_TEXT)

    def test_bypass_returns_unchanged(self):
        msg = make_tool_result(WHOS_TEXT)
        out = _compress_response(msg, bypass=True)
        assert out["result"]["content"][0]["text"] == WHOS_TEXT

    def test_does_not_modify_request_messages(self):
        """Tool calls (requests) must never be touched."""
        request = {
            "method": "tools/call",
            "params": {
                "name": "evaluate_matlab_code",
                "arguments": {"code": "whos"},
            },
        }
        out = _compress_response(request, bypass=False)
        assert out == request

    def test_does_not_modify_non_text_content(self):
        msg = {"id": "1", "result": {"content": [{"type": "image", "data": "abc"}]}}
        out = _compress_response(msg, bypass=False)
        assert out == msg

    def test_handles_malformed_result_none_gracefully(self):
        msg = {"id": "1", "result": None}
        out = _compress_response(msg, bypass=False)
        assert out == msg

    def test_handles_missing_result_gracefully(self):
        msg = {"method": "initialize", "params": {}}
        out = _compress_response(msg, bypass=False)
        assert out == msg

    def test_handles_content_not_a_list(self):
        msg = {"id": "1", "result": {"content": "not a list"}}
        out = _compress_response(msg, bypass=False)
        assert out == msg

    def test_preserves_numerical_result_after_compression(self):
        text = (
            "Warning: Matrix singular. RCOND=1e-17.\n> In solve (line 1)\n" * 5
            + "\nans =\n\n   107.6300\n"
        )
        msg = make_tool_result(text)
        out = _compress_response(msg, bypass=False)
        compressed = out["result"]["content"][0]["text"]
        assert "107.6300" in compressed

    def test_empty_content_list_passthrough(self):
        msg = {"id": "1", "result": {"content": []}}
        out = _compress_response(msg, bypass=False)
        assert out == msg

    def test_multiple_text_items_all_compressed(self):
        """All text items in content list should be compressed."""
        whos2 = WHOS_TEXT + "  speed           1000x1             8000  double\n"
        msg = {
            "id": "1",
            "result": {
                "content": [
                    {"type": "text", "text": WHOS_TEXT},
                    {"type": "text", "text": whos2},
                ]
            },
        }
        out = _compress_response(msg, bypass=False)
        items = out["result"]["content"]
        assert items[0]["text"].startswith("whos:")
        assert items[1]["text"].startswith("whos:")


class TestFloatPreservation:
    def test_fallback_when_leading_zero_eaten(self):
        """Regression: compressor must not eat leading zeros from result floats."""
        from proxy import _floats_preserved
        assert _floats_preserved("lambda_ds =\n\n   0.0847\n", "lambda_ds =\n\n   0.847\n") is not None

    def test_pass_when_floats_unchanged(self):
        from proxy import _floats_preserved
        assert _floats_preserved("ans =\n\n   107.6300\n", "ans =\n\n   107.6300\n") is None

    def test_pass_when_floats_legitimately_removed(self):
        """Deliberate removal (whos table compression) must not trigger fallback."""
        from proxy import _floats_preserved
        original = (
            "  Name         Size    Bytes  Class\n"
            "  omega_r      1x1        8  double\n"
            "  lambda_ds    1x1        8  double\n"
            "\nFinal torque = 107.63 Nm\n"
        )
        compressed = "whos: omega_r[1x1,dbl] lambda_ds[1x1,dbl]\nFinal torque = 107.63 Nm\n"
        assert _floats_preserved(original, compressed) is None

    def test_compress_response_falls_back_on_corrupted_float(self, monkeypatch):
        """_compress_response must return original text when float integrity check fails."""
        import proxy as px
        from router import OutputType
        monkeypatch.setattr("proxy.route", lambda text: ("corrupted = 0.847\n", OutputType.SIM_RESULT))
        msg = {"id": "1", "result": {"content": [{"type": "text", "text": "actual = 0.0847\n"}]}}
        out = px._compress_response(msg, bypass=False)
        assert out["result"]["content"][0]["text"] == "actual = 0.0847\n"


class TestKBStaleness:
    @pytest.fixture(autouse=True)
    def reset_kb_flag(self):
        import proxy as px
        px._kb_staleness_warned = False
        yield
        px._kb_staleness_warned = False

    def test_staleness_warning_fires_when_over_10_entries(self, tmp_path, monkeypatch):
        """Staleness note injected into first tool result when >10 pending errors."""
        import proxy as px
        fake_pending = tmp_path / "pending_errors.jsonl"
        fake_pending.write_text("\n".join([f'{{"error":"err{i}"}}' for i in range(11)]) + "\n")
        monkeypatch.setattr("proxy._get_pending_path", lambda: str(fake_pending))
        note = px._check_kb_staleness()
        assert note is not None
        assert "11" in note
        assert "pending_errors.jsonl" in note

    def test_staleness_warning_fires_only_once(self, tmp_path, monkeypatch):
        """After first call, _check_kb_staleness returns None."""
        import proxy as px
        fake_pending = tmp_path / "pending_errors.jsonl"
        fake_pending.write_text("\n".join([f'{{"error":"err{i}"}}' for i in range(11)]) + "\n")
        monkeypatch.setattr("proxy._get_pending_path", lambda: str(fake_pending))
        px._check_kb_staleness()  # first call fires
        note2 = px._check_kb_staleness()  # second call must be None
        assert note2 is None

    def test_no_staleness_warning_under_10_entries(self, tmp_path, monkeypatch):
        """No warning when pending_errors.jsonl has <=10 entries."""
        import proxy as px
        fake_pending = tmp_path / "pending_errors.jsonl"
        fake_pending.write_text("\n".join([f'{{"error":"err{i}"}}' for i in range(5)]) + "\n")
        monkeypatch.setattr("proxy._get_pending_path", lambda: str(fake_pending))
        note = px._check_kb_staleness()
        assert note is None

    def test_staleness_note_prepended_to_compressed_output(self, tmp_path, monkeypatch):
        """_compress_response prepends staleness note to first text result."""
        import proxy as px
        fake_pending = tmp_path / "pending_errors.jsonl"
        fake_pending.write_text("\n".join([f'{{"error":"err{i}"}}' for i in range(11)]) + "\n")
        monkeypatch.setattr("proxy._get_pending_path", lambda: str(fake_pending))
        msg = make_tool_result(WHOS_TEXT)
        out = px._compress_response(msg, bypass=False)
        text = out["result"]["content"][0]["text"]
        assert text.startswith("[proxy-kb] WARNING:")
        assert "pending_errors.jsonl" in text

    def test_staleness_note_not_injected_on_bypass(self, tmp_path, monkeypatch):
        """bypass=True skips staleness check entirely."""
        import proxy as px
        fake_pending = tmp_path / "pending_errors.jsonl"
        fake_pending.write_text("\n".join([f'{{"error":"err{i}"}}' for i in range(11)]) + "\n")
        monkeypatch.setattr("proxy._get_pending_path", lambda: str(fake_pending))
        msg = make_tool_result(WHOS_TEXT)
        out = px._compress_response(msg, bypass=True)
        text = out["result"]["content"][0]["text"]
        assert "[proxy-kb]" not in text


class TestProtocolVersionGuard:
    def test_image_content_type_passes_through_unchanged(self):
        """type:image must never be touched by compressor."""
        msg = {
            "id": "1",
            "result": {
                "content": [
                    {"type": "image", "data": "iVBORw0KGgoAAAANSUhEUgA", "mimeType": "image/png"}
                ]
            }
        }
        out = _compress_response(msg, bypass=False)
        assert out["result"]["content"][0]["data"] == "iVBORw0KGgoAAAANSUhEUgA"

    def test_chunk_content_type_passes_through_unchanged(self):
        msg = {
            "id": "1",
            "result": {
                "content": [{"type": "chunk", "text": "partial output"}]
            }
        }
        out = _compress_response(msg, bypass=False)
        assert out["result"]["content"][0]["text"] == "partial output"

    def test_mixed_content_only_compresses_text(self):
        """When content has text + image, only text items should be compressed."""
        whos = (
            "  Name      Size    Bytes  Class\n"
            "  x         1x1        8  double\n"
        )
        msg = {
            "id": "1",
            "result": {
                "content": [
                    {"type": "text", "text": whos},
                    {"type": "image", "data": "abc123", "mimeType": "image/png"},
                ]
            }
        }
        out = _compress_response(msg, bypass=False)
        assert out["result"]["content"][0]["text"].startswith("whos:")
        assert out["result"]["content"][1]["data"] == "abc123"

    def test_version_check_logs_warning_for_unknown_version(self, caplog):
        import logging
        import proxy as px
        msg = {
            "jsonrpc": "2.0", "id": 1,
            "result": {
                "protocolVersion": "3.0.0",
                "serverInfo": {"name": "matlab-mcp-core-server", "version": "3.0.0"},
            }
        }
        with caplog.at_level(logging.WARNING, logger="matlab-proxy"):
            px._check_protocol_version(msg)
        assert any("outside tested range" in r.message for r in caplog.records)

    def test_version_check_silent_for_known_version(self, caplog):
        import logging
        import proxy as px
        msg = {
            "jsonrpc": "2.0", "id": 1,
            "result": {
                "serverInfo": {"name": "matlab-mcp-core-server", "version": "0.12.1"},
            }
        }
        with caplog.at_level(logging.WARNING, logger="matlab-proxy"):
            px._check_protocol_version(msg)
        assert not any("outside tested range" in r.message for r in caplog.records)


class TestOracleResources:
    @pytest.fixture(autouse=True)
    def seed_oracle(self, tmp_path, monkeypatch):
        """Seed an isolated oracle in tmp_path — never writes to production kb_store/."""
        from kb.error_oracle import ErrorOracle
        import proxy as px
        isolated = ErrorOracle(store_dir=str(tmp_path))
        isolated.learn(
            "Error using sim\nDerivative of state is not finite.",
            "Add Mechanical Rotational Reference block."
        )
        isolated.learn(
            "Error: Simscape initialization error. Algebraic loop detected.",
            "Add a Solver Configuration block with local solver enabled."
        )
        # Patch the module-level singleton so all proxy functions use this isolated oracle
        monkeypatch.setattr(px, "_oracle", isolated)
        yield isolated
        # monkeypatch auto-restores _oracle after each test

    def test_resources_list_augmented_with_oracle_entries(self):
        import proxy as px
        upstream_response = {
            "jsonrpc": "2.0", "id": 5,
            "result": {"resources": [{"uri": "matlab://workspace", "name": "Workspace"}]}
        }
        augmented = px._augment_resources_list(upstream_response)
        uris = [r["uri"] for r in augmented["result"]["resources"]]
        assert any(u.startswith("oracle://") for u in uris)

    def test_resources_list_unchanged_when_oracle_empty(self, monkeypatch):
        import proxy as px
        from kb.error_oracle import ErrorOracle
        # Override with a truly empty oracle (seed_oracle autouse already ran, this overrides it)
        class _EmptyOracle:
            def list_all(self): return []
        monkeypatch.setattr(px, "_oracle", _EmptyOracle())
        upstream_response = {
            "jsonrpc": "2.0", "id": 5,
            "result": {"resources": [{"uri": "matlab://workspace", "name": "Workspace"}]}
        }
        result = px._augment_resources_list(upstream_response)
        assert result == upstream_response

    def test_handle_oracle_read_recent_returns_kb_content(self):
        import proxy as px
        req = {
            "jsonrpc": "2.0", "id": 7,
            "method": "resources/read",
            "params": {"uri": "oracle://errors/recent"}
        }
        response = px._handle_oracle_read(req)
        assert response["id"] == 7
        assert "result" in response
        contents = response["result"]["contents"]
        assert len(contents) == 1
        text = contents[0]["text"]
        # Should contain oracle entries
        assert "Oracle KB" in text or "Mechanical Rotational Reference" in text

    def test_handle_oracle_read_query_returns_match(self):
        import proxy as px
        from urllib.parse import quote_plus
        query = quote_plus("Derivative of state is not finite")
        req = {
            "jsonrpc": "2.0", "id": 8,
            "method": "resources/read",
            "params": {"uri": f"oracle://errors/query/{query}"}
        }
        response = px._handle_oracle_read(req)
        assert response["id"] == 8
        text = response["result"]["contents"][0]["text"]
        # score= is unconditionally in the format string; also verify content is from a seeded entry
        assert "score=" in text
        assert "Mechanical Rotational Reference" in text or "Solver Configuration" in text or "match" in text.lower()

    def test_handle_oracle_read_graceful_no_match(self):
        import proxy as px
        from urllib.parse import quote_plus
        query = quote_plus("completely unknown error xyz123abc")
        req = {
            "jsonrpc": "2.0", "id": 9,
            "method": "resources/read",
            "params": {"uri": f"oracle://errors/query/{query}"}
        }
        response = px._handle_oracle_read(req)
        assert "result" in response
        assert isinstance(response["result"]["contents"], list)
        assert len(response["result"]["contents"]) == 1

    def test_handle_oracle_read_unknown_uri_returns_help(self):
        import proxy as px
        req = {
            "jsonrpc": "2.0", "id": 10,
            "method": "resources/read",
            "params": {"uri": "oracle://errors/unknown-path"}
        }
        response = px._handle_oracle_read(req)
        text = response["result"]["contents"][0]["text"]
        assert "oracle://errors/recent" in text
        assert "oracle://errors/query" in text
