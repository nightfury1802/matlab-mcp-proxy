"""
MATLAB/Simulink/Simscape MCP output compressor — v2.
Conservative: unrecognized patterns pass through unchanged.
Only compresses outputs, never inputs.
"""
import re


# ── helpers ──────────────────────────────────────────────────────────────────

def _norm_nums(s):
    """Replace numbers with N, then collapse whitespace."""
    return re.sub(r'\s+', ' ', re.sub(r'[\d.e+\-]+', 'N', s)).strip()

def _norm_warning_key(line):
    """Warning key: normalize quoted block paths AND numbers."""
    line = re.sub(r"'[^']*'", "'PATH'", line)  # block paths → PATH
    return _norm_nums(line)


# ── RULE 1: Deduplicate repeated warnings ────────────────────────────────────
def compress_repeated_warnings(text: str) -> str:
    """
    Group warnings with same semantic key (path + number agnostic).
    First occurrence kept, annotated with count. Middle stack frames collapsed.
    """
    blocks = re.split(r'(?=^Warning:)', text, flags=re.MULTILINE)

    counts = {}
    for block in blocks:
        if not block:  # skip empty strings from split
            continue
        if block.startswith('Warning:'):
            key = _norm_warning_key(block.split('\n')[0])
            counts[key] = counts.get(key, 0) + 1

    seen = set()
    out = []
    for block in blocks:
        if not block:  # skip empty strings from split
            continue
        if not block.startswith('Warning:'):
            out.append(block)
            continue
        key = _norm_warning_key(block.split('\n')[0])
        # Separate the warning lines from any trailing non-warning content.
        # A warning block ends after the last "> In" line (plus blank separator).
        # Everything after is tail content to be preserved.
        block_lines = block.split('\n')
        last_warn_idx = 0
        for idx, line in enumerate(block_lines):
            if line.startswith('Warning:') or re.match(r'^[>\s]+In ', line):
                last_warn_idx = idx
        # Advance past any blank lines immediately after the last warn line
        warn_end = last_warn_idx + 1
        while warn_end < len(block_lines) and not block_lines[warn_end].strip():
            warn_end += 1
        warn_part = '\n'.join(block_lines[:warn_end])
        tail_part = '\n'.join(block_lines[warn_end:]) if warn_end < len(block_lines) else ''

        if key in seen:
            # Still preserve any trailing non-warning content
            if tail_part:
                out.append(tail_part)
            continue
        seen.add(key)
        n = counts[key]
        b = warn_part.rstrip()
        # Compress > In ... stack inside warning
        in_lines = [l for l in b.split('\n') if re.match(r'^[>\s]+In ', l)]
        if len(in_lines) > 2:
            first_in = in_lines[0]
            last_in  = in_lines[-1]
            # rebuild block with compressed stack
            non_in = [l for l in b.split('\n') if not re.match(r'^[>\s]+In ', l)]
            b = '\n'.join(non_in) + f'\n{first_in}\n  ... [{len(in_lines)-2} frames]\n{last_in}'
        suffix = f'  [×{n}]\n' if n > 1 else '\n'
        out.append(b + suffix)
        if tail_part:
            out.append(tail_part)

    return ''.join(out)


# ── RULE 2: Compress deep stack traces ───────────────────────────────────────
def compress_stack_trace(text: str) -> str:
    """
    Collapse middle 'Error in' frames when stack depth > 3.
    Approach: find the span from frame[1] start to frame[-1] start,
    replace entirely with a single annotation line.
    """
    error_in_pat = re.compile(r'^Error in \S+.*\(line \d+\)', re.MULTILINE)
    frames = list(error_in_pat.finditer(text))

    if len(frames) <= 3:
        return text
    # Safety: if first frame is not near the top, something's off — pass through
    if frames[0].start() > len(text) // 2:
        return text

    n_middle = len(frames) - 2
    # Span to remove: from end of frame[0]'s code line to start of last frame
    # We'll cut from right after frame[0] line ends to just before frame[-1]
    frame0_end = frames[0].end()
    # Advance past the optional indented code line after frame 0
    rest = text[frame0_end:]
    m = re.match(r'\n\s{4}[^\n]+', rest)
    cut_start = frame0_end + (len(m.group(0)) if m else 0)
    cut_end   = frames[-1].start()

    annotation = f'\n  ... [{n_middle} intermediate frames omitted]\n'
    return text[:cut_start] + annotation + text[cut_end:]


# ── RULE 3: Compact whos table ───────────────────────────────────────────────
def compress_whos(text: str) -> str:
    if 'Bytes' not in text or 'Class' not in text:
        return text
    lines = text.split('\n')
    header_idx = next((i for i, l in enumerate(lines) if re.search(r'Bytes\s+Class', l)), None)
    if header_idx is None:
        return text

    SHORT = {'double':'dbl','single':'sng','logical':'bool','char':'str',
             'struct':'struct','cell':'cell','int32':'i32','uint8':'u8','int16':'i16'}
    vars_info = []
    table_end = header_idx
    for i, line in enumerate(lines[header_idx+1:], header_idx+1):
        m = re.match(r'\s+(\w+)\s+([\dx]+)\s+(\d+)\s+(\w+)', line)
        if m:
            n, sz, _, cls = m.groups()
            vars_info.append(f'{n}[{sz},{SHORT.get(cls,cls)}]')
            table_end = i

    if not vars_info:
        return text

    pre  = '\n'.join(lines[:max(0, header_idx-1)]).strip()
    post = '\n'.join(lines[table_end+1:]).strip()
    whos_line = 'whos: ' + '  '.join(vars_info)
    return '\n'.join(p for p in [pre, whos_line, post] if p) + '\n'


# ── RULE 4: Truncate large numeric arrays ────────────────────────────────────
def compress_large_arrays(text: str) -> str:
    pattern = re.compile(
        r'^(\w+)\s*=\s*\n\n((?:\s+[\d.e+\-]+\n){3,})'
        r'(?:\n\((\d+) more rows.*?\)\n)?',
        re.MULTILINE
    )
    def replacer(m):
        name   = m.group(1)
        rows   = m.group(2)
        more   = int(m.group(3)) if m.group(3) else 0
        vals   = re.findall(r'[\d.e+\-]+', rows)
        total  = len(vals) + more
        first, last = vals[0], vals[-1]
        return f'{name} = [{total}x1: first={first}, last={last}]\n'
    return pattern.sub(replacer, text)


# ── RULE 5: Compress block paths in quoted strings ───────────────────────────
def compress_block_paths(text: str) -> str:
    """'model/A/B/C/D/Block' → 'model/.../C/Block' when depth > 3"""
    def shorten(m):
        path = m.group(1)
        parts = path.split('/')
        if len(parts) > 4:
            return f"'{parts[0]}/.../{parts[-2]}/{parts[-1]}'"
        return m.group(0)
    return re.compile(r"'([\w][\w/]+(?:/[\w]+){3,})'").sub(shorten, text)


# ── RULE 6: Compress Simulink block lists in warnings ────────────────────────
def compress_block_lists(text: str) -> str:
    """
    Long indented block-path lists inside warnings/errors → compressed.
    e.g. 5-line block list → 'Blocks(5): MTPA_Lookup, ..., FeedForward'
    """
    pattern = re.compile(
        r'(The following blocks? (?:are|is) involved:\n)'
        r'((?:  [\w/]+\n){3,})',
        re.MULTILINE
    )
    def compress_list(m):
        header = m.group(1)
        block_lines = [l.strip() for l in m.group(2).strip().split('\n') if l.strip()]
        names = [b.split('/')[-1] for b in block_lines]
        n = len(names)
        if n <= 3:
            return m.group(0)
        summary = f'  Blocks({n}): {names[0]}, ..., {names[-1]}\n'
        return header + summary
    return pattern.sub(compress_list, text)


# ── RULE 7: Compress Simulink build/compilation output ───────────────────────
def compress_build_output(text: str) -> str:
    if '### Starting' not in text:
        return text
    lines = text.split('\n')
    built, out = [], []
    for line in lines:
        m = re.match(r'### Starting build procedure for: (.+)', line)
        if m:
            built.append(m.group(1).strip())
        elif re.match(r'### Successful completion', line) or re.match(r'### Starting serial', line):
            pass
        else:
            out.append(line)
    result = []
    if built:
        result.append(f'### Built: {", ".join(built)}')
    result.extend(out)
    return '\n'.join(result)


# ── RULE 8: Compress repeated fprintf progress lines ─────────────────────────
def compress_progress_lines(text: str) -> str:
    """
    Runs of 5+ structurally identical lines → head + ellipsis + tail.
    Uses whitespace-collapsed normalization to handle alignment padding.
    """
    lines = text.split('\n')

    def normalize(line):
        # Collapse whitespace BEFORE replacing numbers — fixes "  1/" vs " 10/"
        collapsed = re.sub(r'\s+', ' ', line.strip())
        return re.sub(r'[\d.]+', 'N', collapsed)

    result = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            result.append(lines[i])
            i += 1
            continue
        norm = normalize(lines[i])
        run  = [lines[i]]
        j    = i + 1
        while j < len(lines) and lines[j].strip() and normalize(lines[j]) == norm:
            run.append(lines[j])
            j += 1
        if len(run) >= 5:
            head, tail = 2, 2
            result.extend(run[:head])
            result.append(f'  ... [{len(run) - head - tail} lines omitted]')
            result.extend(run[-tail:])
        else:
            result.extend(run)
        i = j
    return '\n'.join(result)


# ── RULE 9: Compact test runner output ───────────────────────────────────────
def compress_test_output(text: str) -> str:
    if 'Totals:' not in text and 'Passed' not in text:
        return text
    lines = text.split('\n')
    passed, failed, fail_details, totals = [], [], [], []

    for i, line in enumerate(lines):
        if re.match(r'\s+\d+\. .+ \.\.\. Passed', line):
            m = re.match(r'\s+\d+\. (.+?) \.\.\.', line)
            if m: passed.append(m.group(1).strip())
        elif re.match(r'\s+\d+\. .+ \.\.\. Failed', line):
            m = re.match(r'\s+\d+\. (.+?) \.\.\.', line)
            if m: failed.append(m.group(1).strip())
            if i+1 < len(lines) and lines[i+1].strip() and not re.match(r'\s+\d+\.', lines[i+1]):
                fail_details.append('  ' + lines[i+1].strip())
        elif re.match(r'\s+\d+ Passed', line) or 'Total duration' in line:
            totals.append(line.strip())

    out = []
    if passed: out.append(f'PASS ({len(passed)}): {", ".join(passed)}')
    if failed: out.append(f'FAIL ({len(failed)}): {", ".join(failed)}')
    out.extend(fail_details)
    out.extend(totals)
    return '\n'.join(out) if out else text


# ── RULE 10: Compact struct display ──────────────────────────────────────────
def compress_struct_display(text: str) -> str:
    if 'struct with fields:' not in text:
        return text
    pattern = re.compile(
        r'(\w+)\s*=\s*\n\n\s+struct with fields:\n\n((?:\s+\w+:.*\n)+)',
        re.MULTILINE
    )
    def replacer(m):
        name   = m.group(1)
        fields = re.findall(r'\s+(\w+):\s+(.+)', m.group(2))
        parts  = [f'{f}={v.strip()[:18]}' for f, v in fields]
        return f'{name} = {{struct: {", ".join(parts)}}}\n'
    return pattern.sub(replacer, text)


# ── RULE 11: Strip "An error occurred" boilerplate ───────────────────────────
def compress_sim_error_boilerplate(text: str) -> str:
    return re.sub(
        r'An error occurred while running the simulation and the simulation was terminated:\n\n',
        '', text
    )


# ── RULE 12: Deduplicate "Caused by:" when it repeats the main error ─────────
def compress_caused_by(text: str) -> str:
    # "Caused by:" may be preceded by blank line — match both forms
    m = re.search(r'\n{1,2}Caused by:\n', text)
    if not m:
        return text
    main  = text[:m.start()]
    caused = text[m.end():]
    caused_core_lines = [l for l in caused.split('\n')
                         if l.strip() and not re.match(r'\s*Error using', l)]
    if caused_core_lines:
        core_full = caused_core_lines[0].strip()
        # Strip trailing "at time X" / "at t=X" clauses before comparing
        core_trimmed = re.sub(r'\s+at time[\s\d.e+\-]+.*', '', core_full, flags=re.IGNORECASE)
        # Use only the first sentence (up to first period) to allow "at time X" suffix
        core_sentence = core_trimmed.split('.')[0]
        core_norm = _norm_nums(core_sentence)
        if len(core_norm) > 20 and core_norm in _norm_nums(main):
            return main.rstrip() + '\n'
    return text


# ── RULE 13: Compress Simscape init-condition variable lists ─────────────────
def compress_init_cond_vars(text: str) -> str:
    """
    Long 'could not be initialized:' lists → compact summary.
    """
    pattern = re.compile(
        r'(The following variables? could not be initialized:\n)'
        r'((?:  [\w/]+:[^\n]+\n){3,})',
        re.MULTILINE
    )
    def compress_vars(m):
        header = m.group(1)
        var_lines = [l.strip() for l in m.group(2).strip().split('\n') if l.strip()]
        # Extract var name (last path segment) and its metadata
        summaries = []
        for vl in var_lines:
            path_m = re.match(r'([\w/]+):\s+(.+)', vl)
            if path_m:
                vname = path_m.group(1).split('/')[-1]
                meta  = path_m.group(2)
                summaries.append(f'{vname}({meta})')
        if len(summaries) > 3:
            return header + f'  {"; ".join(summaries[:2])}; ... [{len(summaries)} total]\n'
        return m.group(0)
    return pattern.sub(compress_vars, text)


# ── RULE 14: Compress unquoted block paths in simulink model_read output ─────
def compress_model_read_paths(text: str) -> str:
    """
    model_read / model_overview emit unquoted block paths:
      Block: model/Sub1/Sub2/Sub3/block
    Shorten deep paths the same way R05 does for quoted ones.
    """
    if 'Block:' not in text:
        return text

    text = re.sub(
        r'(?m)^(Block:\s+)([\w][\w/]{20,})',
        lambda m: m.group(1) + _shorten(m.group(2)),
        text
    )
    return text


def _shorten(path: str) -> str:
    parts = path.split('/')
    if len(parts) > 4:
        return f"{parts[0]}/.../{parts[-2]}/{parts[-1]}"
    return path


# ── PIPELINE ─────────────────────────────────────────────────────────────────
RULES = [
    ("sim_error_boilerplate", compress_sim_error_boilerplate),
    ("repeated_warnings",     compress_repeated_warnings),
    ("block_lists",           compress_block_lists),
    ("init_cond_vars",        compress_init_cond_vars),
    ("stack_trace",           compress_stack_trace),
    ("whos",                  compress_whos),
    ("large_arrays",          compress_large_arrays),
    ("block_paths",           compress_block_paths),
    ("build_output",          compress_build_output),
    ("progress_lines",        compress_progress_lines),
    ("test_output",           compress_test_output),
    ("struct_display",        compress_struct_display),
    ("caused_by",             compress_caused_by),
    ("model_read_paths",      compress_model_read_paths),
]

def compress(text: str) -> str:
    """Entry point. Routes to type-specific pipeline via router.py."""
    from router import route
    compressed, _ = route(text)
    return compressed

def ratio(original: str, compressed: str) -> str:
    o, c = len(original), len(compressed)
    pct = (1 - c/o) * 100 if o else 0
    return f"{o}→{c} chars ({pct:.0f}% reduction)"
