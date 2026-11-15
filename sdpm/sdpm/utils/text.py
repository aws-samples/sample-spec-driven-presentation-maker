# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Text utilities: styled text parsing and spacing normalization."""
import re


def is_fullwidth(char):
    """全角文字判定（CJK + CJK記号のみ。Latin拡張・一般句読点はhalfwidth扱い）"""
    cp = ord(char)
    return (0x2E80 <= cp <= 0x9FFF    # CJK部首・漢字・かな・カタカナ・注音等
            or 0xF900 <= cp <= 0xFAFF  # CJK互換漢字
            or 0xFE30 <= cp <= 0xFE4F  # CJK互換形
            or 0xFF01 <= cp <= 0xFF60  # 全角英数・記号
            or 0xFFE0 <= cp <= 0xFFE6  # 全角通貨等
            or 0x20000 <= cp <= 0x2FA1F)  # CJK拡張


def is_cjk_punctuation(char):
    """CJK punctuation and full-width symbols (、。・「」／（）：〜 …): characters that
    take no space next to half-width text. Letter-like marks (々 〆 〇 ー) are not
    punctuation."""
    cp = ord(char)
    if char in '々〆〇':
        return False
    return (0x3000 <= cp <= 0x303F       # CJK記号・句読点（、。「」〜 など）
            or cp == 0x30FB              # 中黒（・）
            or 0xFE30 <= cp <= 0xFE4F    # CJK互換形
            or 0xFF01 <= cp <= 0xFF0F    # ！＂＃＄％＆＇（）＊＋，－．／
            or 0xFF1A <= cp <= 0xFF20    # ：；＜＝＞？＠
            or 0xFF3B <= cp <= 0xFF40    # ［＼］＾＿｀
            or 0xFF5B <= cp <= 0xFF65    # ｛｜｝～ と半角の句読点（｡｢｣､･）
            or 0xFFE0 <= cp <= 0xFFE6)   # 全角通貨等


# Half-width punctuation that attaches to the word before it (「例: 説明」, 「完了!」):
# no space between a CJK letter and one of these.
ASCII_TRAILING_PUNCTUATION = frozenset(':;,.!?')
_OPEN_BRACKETS = frozenset('([{<')
_CLOSE_BRACKETS = frozenset(')]}>')
_QUOTES = frozenset('"\'`')


def _is_halfwidth(c):
    """Latin-script text that takes a space next to CJK letters: printable ASCII and
    non-ASCII Latin letters (é ü ñ ...) with their combining marks."""
    cp = ord(c)
    return (0x21 <= cp <= 0x7E
            or (0xC0 <= cp <= 0x24F and cp not in (0xD7, 0xF7))  # Latin-1 letters, Latin Extended-A/B
            or 0x0300 <= cp <= 0x036F                             # combining diacritical marks
            or 0x1E00 <= cp <= 0x1EFF)                            # Latin Extended Additional


def _is_wide(c):
    """CJK letters (kanji, kana, full-width alphanumerics), not CJK punctuation."""
    return is_fullwidth(c) and not is_cjk_punctuation(c)


def _quote_roles(text):
    """Map the index of each quote character to 'open' or 'close'.

    A ``'`` between two Latin letters or digits is an apostrophe (It's, O'Reilly) and is
    not a quote. Each quote character pairs up with itself in order of appearance."""
    roles, seen = {}, {}
    for i, ch in enumerate(text):
        if ch not in _QUOTES:
            continue
        if (ch == "'" and 0 < i < len(text) - 1
                and _is_halfwidth(text[i - 1]) and text[i - 1].isalnum()
                and _is_halfwidth(text[i + 1]) and text[i + 1].isalnum()):
            continue
        roles[i] = 'open' if seen.get(ch, 0) % 2 == 0 else 'close'
        seen[ch] = seen.get(ch, 0) + 1
    return roles


def spacing_points(text):
    """Indices ``i`` after which a half-width space goes between ``text[i]`` and ``text[i + 1]``.

    A space goes between a CJK letter and Latin text, either way round. Brackets and quotes
    take it on their outside only: none after an opening one, none before a closing one.
    None goes next to Japanese punctuation, and none before half-width ``: ; , . ! ?``
    following a CJK letter. The rule only looks at the two characters and the quote
    pairing, so applying it again adds nothing."""
    roles = _quote_roles(text)
    points = []
    for i in range(len(text) - 1):
        a, b = text[i], text[i + 1]
        if _is_halfwidth(a) and _is_wide(b):
            if a not in _OPEN_BRACKETS and roles.get(i) != 'open':
                points.append(i)
        elif _is_wide(a) and _is_halfwidth(b):
            if (b not in _CLOSE_BRACKETS and roles.get(i + 1) != 'close'
                    and b not in ASCII_TRAILING_PUNCTUATION):
                points.append(i)
    return points


def normalize_spacing(text):
    """半角と全角の間に半角スペースを挿入（括弧・引用符の内側、日本語の約物の隣、CJK 直後の半角 : ; , . ! ? は除外）"""
    out, last = [], 0
    for i in spacing_points(text):
        out.append(text[last:i + 1])
        out.append(' ')
        last = i + 1
    out.append(text[last:])
    return ''.join(out)


def _flatten_nested_styles(text):
    """Flatten nested {{attrs:...}} notation into comma-separated attrs form.

    Agents sometimes emit nested styled text (issue #123):

        {{bold:{{#FF0000:X}}}}      ->  {{bold,#FF0000:X}}
        {{bold:a{{#FF0000:b}}c}}    ->  {{bold:a}}{{bold,#FF0000:b}}{{bold:c}}

    The regex-based parser cannot handle nesting (``[^}]`` excludes the inner
    ``}}``), which leaked raw tag text onto slides. This pre-pass rewrites
    nested tags into the canonical comma-separated form. Merge order is
    ``outer,inner`` — the parser applies attrs last-wins, so inner attributes
    take priority naturally (boolean attrs like bold cannot be negated).

    Guarantees:
    - Non-nested input is returned byte-identical (tags copied verbatim).
    - Tag starts trigger only on a ``{{`` two-char sequence; bare ``{`` / ``}``
      (e.g. in highlight_code output) pass through untouched.
    - link tags are opaque: never flattened, never merged.
    - Unbalanced input falls back to the original text, so the parser behaves
      exactly as it did before this pre-pass existed.
    - Idempotent: flattened output contains no nested tags.
    """
    if '{{' not in text:
        return text
    try:
        out = []
        i = 0
        while i < len(text):
            if text.startswith('{{', i):
                scanned = _scan_styled_tag(text, i)
                if scanned is not None:
                    end, attrs, parts, has_nest = scanned
                    out.append(_emit_flat_tag(attrs, parts) if has_nest else text[i:end])
                    i = end
                    continue
            out.append(text[i])
            i += 1
        return ''.join(out)
    except RecursionError:
        # Pathologically deep nesting (adversarial input): fall back to the
        # original text, consistent with the unbalanced-input guarantee.
        return text


def _is_link_attrs(attrs):
    return 'link' in [a.strip() for a in attrs.split(',')]


def _scan_styled_tag(text, start):
    """Scan one ``{{attrs:body}}`` tag at ``start`` (must point at ``{{``).

    Returns ``(end_index, attrs, parts, has_nest)`` where parts is a list of
    ``('plain', str)`` / ``('tag', attrs, parts, has_nest)`` items, or None
    if no well-formed tag starts here.
    """
    m = re.match(r'\{\{([^:}]+):', text[start:])
    if not m:
        return None
    attrs = m.group(1)
    j = start + m.end()
    if _is_link_attrs(attrs):
        # Link content cannot contain '}' (mirrors the link regex): opaque.
        close = text.find('}}', j)
        if close == -1:
            return None
        return (close + 2, attrs, [('plain', text[j:close])], False)
    parts = []
    buf = []
    has_nest = False
    while j < len(text):
        if text.startswith('\\}', j):
            buf.append('\\}')
            j += 2
        elif text.startswith('}}', j):
            if buf:
                parts.append(('plain', ''.join(buf)))
            return (j + 2, attrs, parts, has_nest)
        elif text[j] == '}':
            return None  # unescaped single '}' — malformed, fall back
        elif text.startswith('{{', j):
            inner = _scan_styled_tag(text, j)
            if inner is None:
                buf.append(text[j])
                j += 1
                continue
            in_end, in_attrs, in_parts, in_nest = inner
            if _is_link_attrs(in_attrs):
                buf.append(text[j:in_end])  # nested links stay verbatim
            else:
                if buf:
                    parts.append(('plain', ''.join(buf)))
                    buf = []
                parts.append(('tag', in_attrs, in_parts, in_nest))
                has_nest = True
            j = in_end
        else:
            buf.append(text[j])
            j += 1
    return None  # ran out of text before '}}'


def _emit_flat_tag(attrs, parts):
    """Emit flattened tags for a scanned nested tag."""
    out = []
    for part in parts:
        if part[0] == 'plain':
            # Split on newlines so each line carries a complete tag (mirrors
            # _expand_styled_newlines; avoids emitting an empty {{attrs:}}
            # which the parser would leak as literal text).
            lines = part[1].split('\n')
            tagged = [f'{{{{{attrs}:{line}}}}}' if line else '' for line in lines]
            out.append('\n'.join(tagged))
        else:
            _, in_attrs, in_parts, _ = part
            out.append(_emit_flat_tag(attrs + ',' + in_attrs, in_parts))
    return ''.join(out)


def parse_styled_text(text, auto_spacing=True):
    """Parse {{attrs:text}} syntax into styled segments.

    Supported attrs (comma-separated):
    - bold
    - italic
    - #RRGGBB (color)
    - NNpt (font size)
    - link:URL (hyperlink)

    Args:
        auto_spacing: Insert half-width spaces between CJK and Latin text
            (typography for AI-authored decks). Pass False to preserve the
            source text verbatim (e.g. decks imported from existing PPTX).
    """
    text = _flatten_nested_styles(text)
    link_pattern = r'\{\{(?:(\d+pt),)?link:([^}]+)\}\}'
    segments = []
    kinds = []
    last_end = 0

    def add_plain(part):
        segs, ks = _parse_non_link_raw(part)
        segments.extend(segs)
        kinds.extend(ks)

    for match in re.finditer(link_pattern, text):
        if match.start() > last_end:
            add_plain(text[last_end:match.start()])

        size_attr = match.group(1)  # e.g. "14pt" or None
        content = match.group(2)
        # Split URL:text — find the separator colon (not part of ://)
        # Try splitting at ":http" or ":/" boundary first
        split_idx = -1
        for sep in [':https://', ':http://', ':/', ':']:
            idx = content.find(sep, 8)  # skip initial protocol
            if idx > 0:
                split_idx = idx
                break
        if split_idx > 0:
            url = re.sub(r'[\x00-\x1f]', '', content[:split_idx])
            link_text = content[split_idx+1:]
            seg = {"text": link_text, "link": url}
        else:
            seg = {"text": content, "link": content}
        if size_attr:
            try:
                seg["fontSize"] = int(size_attr[:-2])
            except ValueError:
                pass
        segments.append(seg)
        kinds.append('text')

        last_end = match.end()

    if last_end < len(text):
        add_plain(text[last_end:])

    if not segments:
        return [{"text": text}]
    if auto_spacing:
        _space_segments(segments, kinds)
    return segments


def _space_segments(segments, kinds):
    """Insert CJK↔Latin spaces into ``segments`` in place, computed over their joined text so a
    paragraph gets the same spaces whatever its styling. A space at a boundary goes at the end
    of the segment before it. ``kinds[i]`` is ``'text'``; ``'verbatim'`` (no space inside it,
    its edges are spaced, e.g. ``font=`` runs); or ``'break'`` (no space inside or at its
    edges, e.g. superscript and subscript runs)."""
    owner, start = [], []
    for idx, seg in enumerate(segments):
        start.append(len(owner))
        owner.extend([idx] * len(seg["text"]))
    joined = "".join(seg["text"] for seg in segments)
    inserts = {}
    for p in spacing_points(joined):
        a, b = owner[p], owner[p + 1]
        if kinds[a] == 'break' or kinds[b] == 'break':
            continue
        if a == b and kinds[a] == 'verbatim':
            continue
        inserts.setdefault(a, []).append(p - start[a] + 1)
    for idx, cuts in inserts.items():
        t = segments[idx]["text"]
        for cut in sorted(cuts, reverse=True):
            t = t[:cut] + ' ' + t[cut:]
        segments[idx]["text"] = t


def _parse_non_link_styles(text, auto_spacing=True):
    """Parse non-link styled text."""
    segments, kinds = _parse_non_link_raw(text)
    if auto_spacing:
        _space_segments(segments, kinds)
    return segments


def _parse_non_link_raw(text):
    """Parse non-link styled text into segments (text as written) and their spacing kinds."""
    pattern = r'\{\{([^:}]+):((?:\\}|[^}])+)\}\}'
    segments = []
    kinds = []
    last_end = 0

    for match in re.finditer(pattern, text):
        if match.start() > last_end:
            segments.append({"text": text[last_end:match.start()]})
            kinds.append('text')

        raw_attrs = match.group(1)
        inner_text = match.group(2).replace('\\}', '}')
        # Handle LLM mistake: {{bold:#FFFFFF:text}} → treat #RRGGBB as attr
        # Split inner_text on ":" and pull leading #RRGGBB tokens into attrs
        while re.match(r'^#[0-9A-Fa-f]{6}:', inner_text):
            color_token = inner_text[:7]
            raw_attrs += ',' + color_token
            inner_text = inner_text[8:]  # skip "#RRGGBB:"
        attrs = raw_attrs.split(',')
        has_font = any(a.startswith('font=') for a in attrs)
        segment = {"text": inner_text}

        for attr in attrs:
            attr = attr.strip()
            if attr == "bold":
                segment["bold"] = True
            elif attr == "italic":
                segment["italic"] = True
            elif attr == "underline":
                segment["underline"] = True
            elif attr.startswith("#") and len(attr) == 7:
                segment["color"] = attr
            elif attr.endswith("pt"):
                try:
                    segment["fontSize"] = int(attr[:-2])
                except ValueError:
                    pass
            elif attr.startswith("font="):
                segment["fontName"] = attr[5:]
            elif attr.startswith("baseline="):
                # Sub/superscript offset in 1000ths of a percent (OOXML raw).
                # Renderers auto-shrink offset runs, so dropping this made
                # e.g. an 80pt "01" render full-size and wrap.
                try:
                    segment["baseline"] = int(attr[9:])
                except ValueError:
                    pass
            elif attr.startswith("highlight=#"):
                # Text highlight (marker) color — a:highlight
                segment["highlight"] = attr[10:]

        segments.append(segment)
        kinds.append('break' if segment.get("baseline") else 'verbatim' if has_font else 'text')
        last_end = match.end()

    if last_end < len(text):
        segments.append({"text": text[last_end:]})
        kinds.append('text')

    return segments, kinds


def _expand_styled_newlines(text):
    """Expand \\n inside styled tags so each line gets its own complete tag."""
    # Flatten nesting first: builders call this before splitting on newlines,
    # and the expand regex below (``[^}]``) cannot see through nested tags —
    # without this, split("\n") would cut a nested tag in half (issue #123).
    text = _flatten_nested_styles(text)
    def expand_match(m):
        attrs = m.group(1)
        content = m.group(2)
        if '\n' not in content:
            return m.group(0)
        lines = content.split('\n')
        return '\n'.join(f'{{{{{attrs}:{line}}}}}' for line in lines)

    text = re.sub(r'\{\{([^:}]+):([^}]*\n[^}]*)\}\}', expand_match, text)
    return text


def highlight_code(code: str, language: str, theme: str = "dark") -> str:
    """Apply syntax highlighting to code and return styled text with {{#color:text}} syntax."""
    import re
    from pygments import lex
    from pygments.lexers import get_lexer_by_name
    from pygments.token import Token
    from sdpm.engine.builder.constants import CODE_COLORS

    colors = CODE_COLORS.get(theme, CODE_COLORS["dark"])

    TOKEN_MAP = {
        Token.Keyword: "keyword", Token.Keyword.Constant: "boolean",
        Token.Keyword.Declaration: "keyword", Token.Keyword.Namespace: "keyword",
        Token.Keyword.Reserved: "keyword", Token.Keyword.Type: "class",
        Token.Name.Class: "class", Token.Name.Function: "function",
        Token.Name.Decorator: "decorator", Token.Name.Builtin: "function",
        Token.Literal.String: "string", Token.Literal.String.Single: "string",
        Token.Literal.String.Double: "string", Token.Literal.String.Backtick: "string",
        Token.Literal.String.Doc: "comment",
        Token.Literal.Number: "number", Token.Literal.Number.Integer: "number",
        Token.Literal.Number.Float: "number",
        Token.Comment: "comment", Token.Comment.Single: "comment",
        Token.Comment.Multiline: "comment",
        Token.Operator: "operator", Token.Punctuation: "variable",
        Token.Name.Other: "property",
    }

    try:
        lexer = get_lexer_by_name(language)
    except Exception:
        lexer = get_lexer_by_name("text")

    result = []
    for token_type, value in lex(code, lexer):
        if not value:
            continue
        color_key = None
        for t_type in token_type.split():
            if t_type in TOKEN_MAP:
                color_key = TOKEN_MAP[t_type]
                break
        if color_key and color_key in colors:
            color = colors[color_key]
        else:
            color = colors.get("variable", "#d6deeb")
        parts = re.split(r'([{}\n])', value)
        for part in parts:
            if part in '{}':
                result.append(part)
            elif part == '\n':
                result.append('\n')
            elif part:
                result.append(f"{{{{{color}:{part}}}}}")
    return "".join(result)
