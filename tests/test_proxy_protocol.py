"""
Unit tests for proxy.py _compress_response() intercept logic.
No subprocess required — tests the compression intercept in isolation.
Run: pytest tests/test_proxy_protocol.py -v
"""
import sys, os
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
