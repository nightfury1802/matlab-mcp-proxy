import pytest


@pytest.fixture(autouse=True)
def _suppress_kb_staleness(monkeypatch, request):
    """Preset _kb_staleness_warned=True for tests that don't cover that feature.

    TestKBStaleness manages its own reset_kb_flag autouse fixture and must
    not be patched here.  Without this, TestKBStaleness's teardown leaves the
    flag False, causing the next text-content test to see the real
    pending_errors.jsonl and prepend a warning that breaks startswith() asserts.
    """
    if "TestKBStaleness" not in request.node.nodeid:
        monkeypatch.setattr("proxy._kb_staleness_warned", True)
