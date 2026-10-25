"""가이드 문서용 작은 마크다운 파서와 HTML 변환기.

지원: 제목(#~####), 문단, 코드 블록(```), 표, 목록(-, 1.), 인용(>), 구분선(---),
인라인 `코드`, **굵게**, [링크](주소)
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import List

from .syntax import tokenize

INLINE_RE = re.compile(r"`([^`]+)`|\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)]+)\)")


@dataclass
class Block:
    kind: str                 # heading, para, code, table, list, quote, hr
    text: str = ""
    level: int = 0            # 제목 단계 / 목록 들여쓰기 단계
    lang: str = ""
    rows: List[List[str]] = field(default_factory=list)
    items: List[tuple] = field(default_factory=list)   # 목록: (단계, 번호 or None, 글)
    anchor: str = ""


def inline(text: str):
    """[(글, 스타일 집합, 링크)] 로 나눕니다. 스타일: code, bold"""
    out = []
    pos = 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], frozenset(), None))
        if m.group(1) is not None:
            out.append((m.group(1), frozenset({"code"}), None))
        elif m.group(2) is not None:
            for t, st, link in inline(m.group(2)):
                out.append((t, st | {"bold"}, link))
        else:
            out.append((m.group(3), frozenset({"link"}), m.group(4)))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], frozenset(), None))
    return out


def plain(text: str) -> str:
    return "".join(t for t, _s, _l in inline(text))


def slug(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", plain(text)).strip().lower()
    return re.sub(r"\s", "-", s)


def _split_row(line: str) -> List[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    cells, buf, in_code = [], [], False
    i = 0
    while i < len(line):
        c = line[i]
        if c == "`":
            in_code = not in_code
        if c == "\\" and i + 1 < len(line) and line[i + 1] == "|":
            buf.append("|")
            i += 2
            continue
        if c == "|" and not in_code:
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(c)
        i += 1
    cells.append("".join(buf).strip())
    return cells


LIST_RE = re.compile(r"^(\s*)(?:([-*])|(\d+)\.)\s+(.*)$")


def parse(source: str) -> List[Block]:
    lines = source.replace("\r\n", "\n").split("\n")
    blocks: List[Block] = []
    i = 0
    used_anchors = set()
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        if s.startswith("```"):
            lang = s[3:].strip()
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1
            blocks.append(Block("code", "\n".join(body), lang=lang))
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            text = m.group(2).strip()
            a = slug(text) or f"h{len(blocks)}"
            base, k = a, 2
            while a in used_anchors:
                a, k = f"{base}-{k}", k + 1
            used_anchors.add(a)
            blocks.append(Block("heading", text, level=len(m.group(1)), anchor=a))
            i += 1
            continue
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-{2,}", lines[i + 1].strip()):
            rows = [_split_row(s)]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i]))
                i += 1
            blocks.append(Block("table", rows=rows))
            continue
        if re.match(r"^(-{3,}|\*{3,})$", s):
            blocks.append(Block("hr"))
            i += 1
            continue
        if s.startswith(">"):
            body = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                body.append(lines[i].strip()[1:].strip())
                i += 1
            blocks.append(Block("quote", " ".join(body)))
            continue
        if LIST_RE.match(line):
            items = []
            while i < len(lines):
                lm = LIST_RE.match(lines[i])
                if lm:
                    level = len(lm.group(1).expandtabs(4)) // 2
                    items.append([min(level, 3), lm.group(3), lm.group(4).strip()])
                    i += 1
                elif lines[i].strip() and lines[i].startswith("  ") and items:
                    items[-1][2] += " " + lines[i].strip()
                    i += 1
                else:
                    break
            blocks.append(Block("list", items=[tuple(x) for x in items]))
            continue
        body = []
        while i < len(lines):
            t = lines[i].strip()
            if not t or t.startswith(("```", "#", "|", ">")) or LIST_RE.match(lines[i]) \
                    or re.match(r"^(-{3,}|\*{3,})$", t):
                break
            body.append(t)
            i += 1
        blocks.append(Block("para", " ".join(body)))
    return blocks


def headings(blocks: List[Block], max_level=3):
    return [b for b in blocks if b.kind == "heading" and b.level <= max_level]


# ---------------------------------------------------------------- HTML

def _inline_html(text: str, anchors: set) -> str:
    out = []
    for t, st, link in inline(text):
        h = html.escape(t)
        if "code" in st:
            h = f"<code>{h}</code>"
        if "bold" in st:
            h = f"<strong>{h}</strong>"
        if link is not None:
            href = link
            if link.startswith("#") and link[1:] not in anchors:
                href = "#" + slug(link[1:])
            h = f'<a href="{html.escape(href)}">{h}</a>'
        out.append(h)
    return "".join(out)


def highlight_html(code: str) -> str:
    lines = code.split("\n")
    out = []
    for line, spans in zip(lines, tokenize(code)):
        spans = sorted(spans)
        # interp 은 string 안에 겹쳐 있으므로, 경계를 모아서 가장 안쪽 종류를 씀
        bounds = sorted({0, len(line)} | {s for s, _e, _k in spans} | {e for _s, e, _k in spans})
        buf = []
        for a, b in zip(bounds, bounds[1:]):
            kind = None
            for s, e, k in spans:
                if s <= a and b <= e:
                    kind = k if (kind is None or k == "interp") else kind
            piece = html.escape(line[a:b])
            buf.append(f'<span class="t-{kind}">{piece}</span>' if kind else piece)
        out.append("".join(buf))
    return "\n".join(out)


HTML_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  --bg: #f4ecda; --page: #fbf7ee; --ink: #2f2721; --muted: #85766a; --rule: #e2d5bb;
  --accent: #8e3b28; --code-bg: #f1e8d4; --side: #efe5cf;
  --t-keyword: #8e3b28; --t-labeldef: #1f5f8b; --t-target: #1f5f8b; --t-variable: #6b4c9a;
  --t-string: #4b6b26; --t-interp: #b0571f; --t-comment: #9a8f80; --t-number: #7a4fa0;
  --t-const: #7a4fa0; --t-func: #0f6d6a; --t-arrow: #8e3b28;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #15171b; --page: #1c1f24; --ink: #e2ddd2; --muted: #8d939c; --rule: #2e333a;
    --accent: #e0a65e; --code-bg: #23272e; --side: #181b20;
    --t-keyword: #e8946f; --t-labeldef: #7fb6e0; --t-target: #7fb6e0; --t-variable: #c3a5ef;
    --t-string: #a9c97d; --t-interp: #f0b072; --t-comment: #7b828c; --t-number: #c3a5ef;
    --t-const: #c3a5ef; --t-func: #6fd0c8; --t-arrow: #e8946f;
  }}
}}
* {{ box-sizing: border-box; }}
html {{ scroll-padding-top: 16px; }}
body {{ margin: 0; background: var(--bg); color: var(--ink);
  font: 16px/1.75 "Pretendard", "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR", "Noto Sans CJK KR", sans-serif; }}
.wrap {{ display: flex; max-width: 1180px; margin: 0 auto; }}
nav {{ position: sticky; top: 0; align-self: flex-start; width: 260px; flex: none; height: 100vh;
  overflow-y: auto; padding: 28px 18px 40px 24px; font-size: 14px; line-height: 1.5; }}
nav .brand {{ font-weight: 700; font-size: 15px; margin-bottom: 14px; color: var(--accent); }}
nav a {{ display: block; color: var(--muted); text-decoration: none; padding: 3px 8px; border-radius: 6px; }}
nav a:hover {{ background: var(--side); color: var(--ink); }}
nav a.l3 {{ padding-left: 22px; font-size: 13px; }}
main {{ flex: 1; min-width: 0; background: var(--page); padding: 48px 56px 96px;
  border-left: 1px solid var(--rule); border-right: 1px solid var(--rule); }}
h1 {{ font-size: 32px; line-height: 1.3; margin: 0 0 8px; }}
h2 {{ font-size: 23px; margin: 56px 0 12px; padding-top: 18px; border-top: 1px solid var(--rule); }}
h3 {{ font-size: 18px; margin: 32px 0 8px; }}
h4 {{ font-size: 16px; margin: 24px 0 6px; color: var(--muted); }}
p {{ margin: 10px 0; }}
a {{ color: var(--accent); }}
code {{ font-family: "D2Coding", "Consolas", "Menlo", "Noto Sans Mono CJK KR", monospace; font-size: 0.9em;
  background: var(--code-bg); padding: 1px 5px; border-radius: 4px; }}
pre {{ background: var(--code-bg); padding: 14px 18px; border-radius: 8px; overflow-x: auto;
  line-height: 1.6; font-size: 14.5px; margin: 14px 0; border: 1px solid var(--rule); }}
pre code {{ background: none; padding: 0; font-size: inherit; }}
table {{ border-collapse: collapse; margin: 14px 0; width: 100%; font-size: 15px; }}
th, td {{ border-bottom: 1px solid var(--rule); padding: 7px 10px; text-align: left; vertical-align: top; }}
th {{ font-weight: 700; border-bottom-width: 2px; }}
blockquote {{ margin: 14px 0; padding: 10px 16px; border-left: 3px solid var(--accent);
  background: var(--code-bg); border-radius: 0 8px 8px 0; color: var(--ink); }}
hr {{ border: 0; border-top: 1px solid var(--rule); margin: 32px 0; }}
ul, ol {{ padding-left: 24px; }}
li {{ margin: 3px 0; }}
.t-keyword, .t-arrow {{ color: var(--t-keyword); font-weight: 700; }}
.t-labeldef {{ color: var(--t-labeldef); font-weight: 700; }}
.t-target {{ color: var(--t-target); }}
.t-variable {{ color: var(--t-variable); }}
.t-string {{ color: var(--t-string); }}
.t-interp {{ color: var(--t-interp); font-weight: 700; }}
.t-comment {{ color: var(--t-comment); font-style: italic; }}
.t-number, .t-const {{ color: var(--t-number); }}
.t-func {{ color: var(--t-func); }}
@media (max-width: 860px) {{
  .wrap {{ display: block; }}
  nav {{ position: static; width: auto; height: auto; padding: 20px 16px 8px; }}
  nav a.l3 {{ display: none; }}
  main {{ padding: 28px 16px 64px; border: 0; }}
  h1 {{ font-size: 26px; }}
}}
</style>
</head>
<body>
<div class="wrap">
<nav><div class="brand">{title}</div>
{toc}
</nav>
<main>
{body}
</main>
</div>
</body>
</html>
"""


def to_html(source: str, title: str = "문서") -> str:
    blocks = parse(source)
    anchors = {b.anchor for b in blocks if b.kind == "heading"}
    body, toc = [], []
    for b in blocks:
        if b.kind == "heading":
            body.append(f'<h{b.level} id="{b.anchor}">{_inline_html(b.text, anchors)}</h{b.level}>')
            if b.level in (2, 3):
                toc.append(f'<a class="l{b.level}" href="#{b.anchor}">{html.escape(plain(b.text))}</a>')
        elif b.kind == "para":
            body.append(f"<p>{_inline_html(b.text, anchors)}</p>")
        elif b.kind == "code":
            code = highlight_html(b.text) if b.lang in ("", "gb", "gamebook") else html.escape(b.text)
            body.append(f"<pre><code>{code}</code></pre>")
        elif b.kind == "table":
            rows = ["<tr>" + "".join(f"<th>{_inline_html(c, anchors)}</th>" for c in b.rows[0]) + "</tr>"]
            for r in b.rows[1:]:
                rows.append("<tr>" + "".join(f"<td>{_inline_html(c, anchors)}</td>" for c in r) + "</tr>")
            body.append("<table>" + "".join(rows) + "</table>")
        elif b.kind == "list":
            ordered = b.items and b.items[0][1] is not None
            tag = "ol" if ordered else "ul"
            body.append(f"<{tag}>" + "".join(f"<li>{_inline_html(t, anchors)}</li>" for _l, _n, t in b.items)
                        + f"</{tag}>")
        elif b.kind == "quote":
            body.append(f"<blockquote>{_inline_html(b.text, anchors)}</blockquote>")
        elif b.kind == "hr":
            body.append("<hr>")
    return HTML_TEMPLATE.format(title=html.escape(title), toc="\n".join(toc), body="\n".join(body))
