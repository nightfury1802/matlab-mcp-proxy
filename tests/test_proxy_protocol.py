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
