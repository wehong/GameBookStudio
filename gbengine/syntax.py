"""스크립트 구문 강조용 토크나이저 (화면과 무관, 에디터와 도움말이 함께 사용).

tokenize(source) 는 줄마다 (시작 열, 끝 열, 종류) 목록을 돌려줍니다.
종류: keyword, labeldef, target, variable, string, interp, comment, number, const, func, arrow
"""

from __future__ import annotations

import re
from typing import List, Tuple

STATEMENT_KEYWORDS = {"label", "default", "set", "if", "elif", "else", "choice",
                      "goto", "end", "image"}
INLINE_KEYWORDS = {"if", "and", "or", "not"}
CONSTS = {"true", "false", "True", "False", "none", "None", "참", "거짓", "없음"}
FUNCS = {"visited", "random"}

WORD_RE = re.compile(r"\w+")
NUMBER_RE = re.compile(r"\d+(\.\d+)?$")
INTERP_RE = re.compile(r"\{\{|\}\}|\{\w+\}")

Span = Tuple[int, int, str]


def _string_spans(line: str, start: int, end: int, out: List[Span]):
    out.append((start, end, "string"))
    for m in INTERP_RE.finditer(line, start, end):
        if len(m.group(0)) > 2:
            out.append((m.start(), m.end(), "interp"))


def _find_quote_end(line: str, i: int, quote: str) -> int:
    """i 는 여는 따옴표 다음 위치. 닫는 따옴표 다음 위치(없으면 줄 끝)를 돌려줌."""
    while i < len(line):
        c = line[i]
        if c == "\\":
            i += 2
            continue
        if c == quote:
            return i + 1
        i += 1
    return len(line)


def tokenize_line(line: str, in_block: bool) -> Tuple[List[Span], bool]:
    spans: List[Span] = []
    i = 0
    n = len(line)
    if in_block:
        k = line.find('"""')
        if k < 0:
            _string_spans(line, 0, n, spans)
            return spans, True
        _string_spans(line, 0, k + 3, spans)
        i = k + 3
        in_block = False

    first_word = None     # 문장 첫 단어
    expect = None         # 다음 단어의 종류 (labeldef / target / variable)
    while i < n:
        c = line[i]
        if c.isspace():
            i += 1
            continue
        if c == "#":
            spans.append((i, n, "comment"))
            break
        if line.startswith('"""', i):
            k = line.find('"""', i + 3)
            if k < 0:
                _string_spans(line, i, n, spans)
                return spans, True
            _string_spans(line, i, k + 3, spans)
            i = k + 3
            first_word = first_word or '"'
            continue
        if c in "\"'":
            e = _find_quote_end(line, i + 1, c)
            _string_spans(line, i, e, spans)
            i = e
            first_word = first_word or '"'
            continue
        if line.startswith("->", i):
            spans.append((i, i + 2, "arrow"))
            i += 2
            expect = "target"
            continue
        m = WORD_RE.match(line, i)
        if m:
            w = m.group(0)
            s, e = m.start(), m.end()
            if expect:
                spans.append((s, e, expect))
                expect = None
            elif first_word is None and w in STATEMENT_KEYWORDS:
                spans.append((s, e, "keyword"))
                expect = {"label": "labeldef", "goto": "target", "set": "variable",
                          "default": "variable"}.get(w)
            elif w in INLINE_KEYWORDS:
                spans.append((s, e, "keyword"))
            elif w in CONSTS:
                spans.append((s, e, "const"))
            elif w in FUNCS and line[e:e + 1] == "(":
                spans.append((s, e, "func"))
            elif NUMBER_RE.match(w):
                spans.append((s, e, "number"))
            if first_word is None:
                first_word = w
            i = e
            continue
        i += 1
    return spans, in_block


def tokenize(source: str) -> List[List[Span]]:
    result = []
    in_block = False
    for line in source.split("\n"):
        spans, in_block = tokenize_line(line, in_block)
        result.append(spans)
    return result


LABEL_LINE_RE = re.compile(r"^label\s+(\w+)\s*:")


def label_at_line(lines: List[str], lineno: int):
    """lineno(1부터) 줄이 속한 단락 이름. 없으면 None."""
    for i in range(min(lineno, len(lines)) - 1, -1, -1):
        m = LABEL_LINE_RE.match(lines[i])
        if m:
            return m.group(1)
    return None
