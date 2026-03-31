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


def normalize_spacing(text):
    """半角と全角の間に半角スペースを挿入（括弧内側は除外）"""
    open_br = set('([{「『（【〔《〈')
    close_br = set(')]}」』）】〕》〉')
    quotes = set('"\'`')

    def is_ascii(c):
        return '\x21' <= c <= '\x7e'

    def is_wide(c):
        return is_fullwidth(c) and c not in open_br and c not in close_br

    quote_positions = {q: [] for q in quotes}
    for i, ch in enumerate(text):
        if ch in quotes:
            quote_positions[ch].append(i)

    def is_opening_quote(pos, ch):
        if ch not in quotes:
            return False
        positions = quote_positions[ch]
        idx = positions.index(pos)
        return idx % 2 == 0

    def is_closing_quote(pos, ch):
        if ch not in quotes:
            return False
        positions = quote_positions[ch]
        idx = positions.index(pos)
        return idx % 2 == 1

    result = []
    for i, ch in enumerate(text):
        result.append(ch)
        if i + 1 >= len(text):
            continue

        next_ch = text[i + 1]

        if is_closing_quote(i, ch) and next_ch not in open_br and not is_opening_quote(i + 1, next_ch):
            result.append(' ')
        elif is_opening_quote(i + 1, next_ch) and ch not in open_br and not is_opening_quote(i, ch):
            result.append(' ')
        elif is_ascii(ch) and is_wide(next_ch) and ch not in open_br and not is_opening_quote(i, ch):
            result.append(' ')
        elif is_wide(ch) and is_ascii(next_ch) and next_ch not in close_br and not is_closing_quote(i + 1, next_ch):
            result.append(' ')

    return ''.join(result)


def parse_styled_text(text):
    """Parse {{attrs:text}} syntax into styled segments.

    Supported attrs (comma-separated):
    - bold
    - italic
    - #RRGGBB (color)
    - NNpt (font size)
    - link:URL (hyperlink)
    """
    link_pattern = r'\{\{(?:(\d+pt),)?link:([^}]+)\}\}'
    segments = []
    last_end = 0

    for match in re.finditer(link_pattern, text):
        if match.start() > last_end:
            plain_part = text[last_end:match.start()]
            segments.extend(_parse_non_link_styles(plain_part))

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

        last_end = match.end()

    if last_end < len(text):
        segments.extend(_parse_non_link_styles(text[last_end:]))

    return segments if segments else [{"text": text}]


def _parse_non_link_styles(text):
    """Parse non-link styled text."""
    pattern = r'\{\{([^:}]+):((?:\\}|[^}])+)\}\}'
    segments = []
    last_end = 0

    for match in re.finditer(pattern, text):
        if match.start() > last_end:
            plain_text = normalize_spacing(text[last_end:match.start()])
            segments.append({"text": plain_text})

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
        inner_text = inner_text if has_font else normalize_spacing(inner_text)
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

        segments.append(segment)
        last_end = match.end()

    if last_end < len(text):
        plain_text = normalize_spacing(text[last_end:])
        segments.append({"text": plain_text})

    for i in range(len(segments) - 1):
        cur_text = segments[i]["text"]
        nxt_text = segments[i + 1]["text"]
        if not cur_text or not nxt_text:
            continue
        last_ch, first_ch = cur_text[-1], nxt_text[0]

        def is_ascii(c: str) -> bool:
            return '\x21' <= c <= '\x7e'

        def is_wide(c: str) -> bool:
            return is_fullwidth(c)

        if (is_ascii(last_ch) and is_wide(first_ch)) or (is_wide(last_ch) and is_ascii(first_ch)):
            segments[i]["text"] = cur_text + ' '

    return segments


def _expand_styled_newlines(text):
    """Expand \\n inside styled tags so each line gets its own complete tag."""
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
    from sdpm.builder.constants import CODE_COLORS

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
