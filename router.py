"""
router.py — Output type classifier and pipeline dispatcher.

Replaces the blind sequential pipeline in compressor.py with intent-first routing.
Each OutputType gets exactly the rules relevant to it — no false positives.
"""
import re
from enum import Enum, auto
from compressor import (
    compress_whos, compress_repeated_warnings, compress_stack_trace,
    compress_large_arrays, compress_block_paths, compress_block_lists,
    compress_build_output, compress_progress_lines, compress_test_output,
    compress_struct_display, compress_sim_error_boilerplate, compress_caused_by,
    compress_init_cond_vars, compress_model_read_paths,
)


class OutputType(Enum):
    WHOS        = auto()
    ERROR       = auto()
    WARNING     = auto()
    TEST_RUN    = auto()
    BUILD       = auto()
    SIM_RESULT  = auto()
    PROGRESS    = auto()
    STRUCT      = auto()
    ARRAY       = auto()
    MODEL_QUERY = auto()
    PLAIN       = auto()


def _has(text: str, pattern: str, flags: int = 0) -> bool:
    return bool(re.search(pattern, text, flags))


def classify(text: str) -> OutputType:
    """Classify MATLAB MCP output into one of 11 output types."""
    if not text.strip():
        return OutputType.PLAIN
    if _has(text, r'Bytes\s+Class', re.IGNORECASE):
        return OutputType.WHOS
    if _has(text, r'^Error using|^Error in ', re.MULTILINE):
        return OutputType.ERROR
    if _has(text, r'^Warning:', re.MULTILINE):
        return OutputType.WARNING
    if _has(text, r'Totals:|^\s+\d+\. .+\.\.\. (Passed|Failed)', re.MULTILINE):
        return OutputType.TEST_RUN
    if _has(text, r'### Starting build procedure|### Successful completion', re.MULTILINE):
        return OutputType.BUILD
    if _has(text, r'^Block:\s+\w', re.MULTILINE) or _has(text, r'^Param:\s+', re.MULTILINE):
        return OutputType.MODEL_QUERY
    if _has(text, r'struct with fields:', re.IGNORECASE):
        return OutputType.STRUCT
    if _has(text, r'DOE point\s+\d+/\d+|^\s*\d+/\d+:', re.MULTILINE):
        return OutputType.PROGRESS
    if _has(text, r'^\w+ =\n\n(\s+[\d.e+\-]+\n){3,}', re.MULTILINE):
        return OutputType.ARRAY
    if _has(text, r'Simulation complete|Final torque|Final speed', re.MULTILINE):
        return OutputType.SIM_RESULT
    return OutputType.PLAIN


_PIPELINES: dict[OutputType, list] = {
    OutputType.WHOS:        [compress_struct_display, compress_whos],  # struct may precede whos in same output
    OutputType.ERROR:       [compress_sim_error_boilerplate, compress_block_lists,
                             compress_init_cond_vars, compress_stack_trace,
                             compress_caused_by, compress_block_paths],
    OutputType.WARNING:     [compress_repeated_warnings, compress_block_lists,
                             compress_block_paths],
    OutputType.TEST_RUN:    [compress_test_output],
    OutputType.BUILD:       [compress_build_output],
    OutputType.SIM_RESULT:  [compress_struct_display],           # arrays handled by ARRAY
    OutputType.PROGRESS:    [compress_progress_lines],
    OutputType.STRUCT:      [compress_struct_display],
    OutputType.ARRAY:       [compress_large_arrays, compress_struct_display],  # add struct
    OutputType.MODEL_QUERY: [compress_model_read_paths, compress_block_paths],
    OutputType.PLAIN:       [],
}


_HTML_TAG = re.compile(r'<[^>]+>')


def _strip_html(text: str) -> str:
    """Remove HTML tags injected by MATLAB's rich-text command window output."""
    return _HTML_TAG.sub('', text)


def route(text: str) -> tuple[str, OutputType]:
    """
    Classify text and apply the matching pipeline.
    Returns (compressed_text, output_type).
    OutputType is returned so the proxy can dispatch to KB lookups.
    """
    text = _strip_html(text)
    otype = classify(text)
    result = text
    for rule in _PIPELINES[otype]:
        result = rule(result)
    return result, otype
