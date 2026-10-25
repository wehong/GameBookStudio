"""게임북 스크립트(.gb) 파서.

문법 요약 (자세한 설명은 README.md):

    # 주석
    default 금화 = 10

    label start:
        image "forest.png"
        "본문 한 문단."
        \"\"\"
        여러 줄로 된
        본문.
        \"\"\"
        set 금화 += 5
        if 횃불:
            "횃불이 일렁인다."
        elif 금화 > 3:
            "..."
        else:
            "..."
        choice "동굴로 들어간다" if 횃불 -> 동굴
        choice "오두막을 뒤진다" -> 오두막:
            set 용기 += 1
        goto 다른단락
        end "엔딩 제목"
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import SCRIPT_EXT
from .expr import Expr, ExprError

NAME_RE = re.compile(r"^\w+$")            # 단락 이름: 한글, 영문, 숫자, _ (예: 동굴, cave_2, 147)
SET_RE = re.compile(r"^(\w+)\s*(\+=|-=|=)\s*(.+)$")


# ---------------------------------------------------------------- 구문 노드

@dataclass
class Loc:
    file: str
    line: int

    def __str__(self):
        return f"{os.path.basename(self.file)}:{self.line}"


@dataclass
class Text:
    text: str
    loc: Loc


@dataclass
class Image:
    path: Optional[str]  # None = 이미지 없음
    loc: Loc


@dataclass
class SetVar:
    name: str
    op: str  # "=", "+=", "-="
    expr: Expr
    loc: Loc


@dataclass
class If:
    branches: List[Tuple[Optional[Expr], list]]  # (조건, 본문). else의 조건은 None
    loc: Loc


@dataclass
class Choice:
    text: str
    cond: Optional[Expr]
    target: str
    body: list
    loc: Loc
    uid: str = ""  # 저장 파일에서 선택지를 가리키는 식별자 ("단락#순번")


@dataclass
class Goto:
    target: str
    loc: Loc


@dataclass
class End:
    title: str
    loc: Loc


@dataclass
class Label:
    name: str
    body: list
    loc: Loc


@dataclass
class Default:
    name: str
    expr: Expr
    loc: Loc


@dataclass
class ScriptError:
    loc: Loc
    message: str

    def __str__(self):
        return f"{self.loc}  {self.message}"


@dataclass
class Story:
    labels: dict = field(default_factory=dict)      # 이름 -> Label
    defaults: list = field(default_factory=list)    # [Default]
    errors: list = field(default_factory=list)      # [ScriptError]
    files: list = field(default_factory=list)       # 읽은 스크립트 파일 경로

    def choices_by_uid(self) -> dict:
        found = {}
        for label in self.labels.values():
            for node in walk(label.body):
                if isinstance(node, Choice):
                    found[node.uid] = node
        return found


def walk(body):
    """본문의 모든 문장을 (if 안쪽까지) 차례로 돌려줍니다."""
    for node in body:
        yield node
        if isinstance(node, If):
            for _cond, sub in node.branches:
                yield from walk(sub)
        elif isinstance(node, Choice):
            yield from walk(node.body)


# ---------------------------------------------------------------- 줄 단위 전처리

@dataclass
class _Line:
    indent: int
    text: str           # 주석을 지운 내용
    lineno: int
    block_text: Optional[str] = None  # 세 따옴표 본문이면 그 내용


def _strip_comment(s: str) -> str:
    quote = None
    i = 0
    while i < len(s):
        c = s[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "#":
            return s[:i].rstrip()
        i += 1
    return s.rstrip()


def _dedent_block(lines: List[str]) -> str:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    indents = [len(l) - len(l.lstrip(" ")) for l in lines if l.strip()]
    cut = min(indents) if indents else 0
    return "\n".join(l[cut:].rstrip() for l in lines)


def _logical_lines(source: str, filename: str, errors: list) -> List[_Line]:
    raw = source.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4).split("\n")
    out: List[_Line] = []
    i = 0
    while i < len(raw):
        line = raw[i]
        stripped = line.strip()
        lineno = i + 1
        indent = len(line) - len(line.lstrip(" "))
        i += 1
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith('"""'):
            rest = stripped[3:]
            if '"""' in rest:  # """한 줄"""
                text, after = rest.split('"""', 1)
                if after.strip() and not after.strip().startswith("#"):
                    errors.append(ScriptError(Loc(filename, lineno), '닫는 """ 뒤에 다른 내용이 있습니다.'))
                out.append(_Line(indent, '"""', lineno, text.strip()))
                continue
            body = [rest] if rest.strip() else []
            closed = False
            while i < len(raw):
                l2 = raw[i]
                i += 1
                if '"""' in l2:
                    before = l2.split('"""', 1)[0]
                    if before.strip():
                        body.append(before)
                    closed = True
                    break
                body.append(l2)
            if not closed:
                errors.append(ScriptError(Loc(filename, lineno), '여러 줄 본문을 닫는 """ 가 없습니다.'))
            out.append(_Line(indent, '"""', lineno, _dedent_block(body)))
            continue
        out.append(_Line(indent, _strip_comment(stripped), lineno))
    return out


# ---------------------------------------------------------------- 문자열 읽기

def _read_string(s: str, pos: int = 0) -> Tuple[str, int]:
    """s[pos]의 따옴표로 시작하는 문자열을 읽어 (내용, 끝난 다음 위치)를 돌려줍니다."""
    quote = s[pos]
    if quote not in "\"'":
        raise ValueError("따옴표로 시작하는 문자열이 필요합니다.")
    buf = []
    i = pos + 1
    escapes = {"n": "\n", "t": "\t", "\\": "\\", '"': '"', "'": "'"}
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            buf.append(escapes.get(s[i + 1], "\\" + s[i + 1]))
            i += 2
            continue
        if c == quote:
            return "".join(buf), i + 1
        buf.append(c)
        i += 1
    raise ValueError("문자열을 닫는 따옴표가 없습니다.")


def _find_arrow(s: str) -> int:
    quote = None
    i = 0
    while i < len(s) - 1:
        c = s[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif s[i:i + 2] == "->":
            return i
        i += 1
    return -1


# ---------------------------------------------------------------- 파서

class _Parser:
    def __init__(self, filename: str, story: Story):
        self.filename = filename
        self.story = story
        self.lines: List[_Line] = []
        self.pos = 0

    def error(self, line: _Line, msg: str):
        self.story.errors.append(ScriptError(Loc(self.filename, line.lineno), msg))

    def loc(self, line: _Line) -> Loc:
        return Loc(self.filename, line.lineno)

    def expr(self, line: _Line, src: str) -> Optional[Expr]:
        try:
            return Expr(src)
        except ExprError as e:
            self.error(line, str(e))
            return None

    def parse(self, source: str):
        self.lines = _logical_lines(source, self.filename, self.story.errors)
        self.pos = 0
        while self.pos < len(self.lines):
            line = self.lines[self.pos]
            self.pos += 1
            if line.indent != 0:
                self.error(line, "최상위 문장은 들여쓰지 않아야 합니다. (label 또는 default)")
                self._skip_block(line.indent)
                continue
            text = line.text
            if line.block_text is None and (text.startswith("label ") or text.startswith("label:")):
                self._parse_label(line)
            elif line.block_text is None and text.startswith("default "):
                self._parse_default(line)
            else:
                self.error(line, "label 밖에는 label 과 default 만 쓸 수 있습니다.")
                self._skip_block(0)

    def _skip_block(self, indent: int):
        while self.pos < len(self.lines) and self.lines[self.pos].indent > indent:
            self.pos += 1

    def _parse_default(self, line: _Line):
        m = SET_RE.match(line.text[len("default "):].strip())
        if not m or m.group(2) != "=":
            self.error(line, "default 는 'default 이름 = 값' 형태로 써야 합니다.")
            return
        name = m.group(1)
        if not name.isidentifier():
            self.error(line, f"'{name}'은(는) 변수 이름으로 쓸 수 없습니다.")
            return
        e = self.expr(line, m.group(3))
        if e:
            self.story.defaults.append(Default(name, e, self.loc(line)))

    def _parse_label(self, line: _Line):
        head = line.text[len("label"):].strip()
        if not head.endswith(":"):
            self.error(line, "label 줄은 콜론(:)으로 끝나야 합니다. 예) label 동굴:")
            head = head.rstrip(":")
        name = head[:-1].strip() if head.endswith(":") else head
        if not NAME_RE.match(name):
            self.error(line, f"단락 이름 '{name}'이(가) 올바르지 않습니다. 한글, 영문, 숫자, _ 만 쓸 수 있습니다.")
            name = None
        body = self._parse_block(line, context="label")
        if not body:
            self.error(line, "단락에 내용이 없습니다. 아래 줄을 들여써서 내용을 적어 주세요.")
        if name is None:
            return
        if name in self.story.labels:
            prev = self.story.labels[name]
            self.error(line, f"단락 '{name}'이(가) 이미 {prev.loc}에 있습니다.")
            return
        label = Label(name, body, self.loc(line))
        n = 0
        for node in walk(body):
            if isinstance(node, Choice):
                node.uid = f"{name}#{n}"
                n += 1
        self.story.labels[name] = label

    def _parse_block(self, header: _Line, context: str) -> list:
        """header 아래의 들여쓴 줄들을 읽습니다. context: label | if | choice"""
        if self.pos >= len(self.lines) or self.lines[self.pos].indent <= header.indent:
            return []
        indent = self.lines[self.pos].indent
        body = []
        while self.pos < len(self.lines):
            line = self.lines[self.pos]
            if line.indent <= header.indent:
                break
            if line.indent != indent:
                self.error(line, "들여쓰기가 위 줄들과 맞지 않습니다.")
                self.pos += 1
                self._skip_block(line.indent)
                continue
            self.pos += 1
            node = self._parse_statement(line, body, context)
            if node is not None:
                body.append(node)
        return body

    def _parse_statement(self, line: _Line, body: list, context: str):
        loc = self.loc(line)
        text = line.text

        if line.block_text is not None:
            return Text(line.block_text, loc) if self._text_ok(line, context) else None

        if text[:1] in "\"'":
            try:
                value, end = _read_string(text)
            except ValueError as e:
                self.error(line, str(e))
                return None
            if text[end:].strip():
                self.error(line, "본문 문자열 뒤에 다른 내용이 있습니다.")
            return Text(value, loc) if self._text_ok(line, context) else None

        word, _, rest = text.partition(" ")
        word = word.rstrip(":") if word in ("else:",) else word
        rest = rest.strip()

        if word == "set":
            m = SET_RE.match(rest)
            if not m:
                self.error(line, "set 은 'set 이름 = 값', 'set 이름 += 값', 'set 이름 -= 값' 형태로 씁니다.")
                return None
            if not m.group(1).isidentifier():
                self.error(line, f"'{m.group(1)}'은(는) 변수 이름으로 쓸 수 없습니다.")
                return None
            e = self.expr(line, m.group(3))
            return e and SetVar(m.group(1), m.group(2), e, loc)

        if word == "if":
            return self._parse_if(line, context)

        if word in ("elif", "else"):
            prev = body[-1] if body else None
            if not isinstance(prev, If) or prev.branches[-1][0] is None:
                self.error(line, f"{word} 앞에 짝이 되는 if 가 없습니다.")
                self._parse_block(line, context)
                return None
            if word == "else":
                if text.replace(" ", "") != "else:":
                    self.error(line, "else 는 'else:' 로만 씁니다.")
                prev.branches.append((None, self._parse_block(line, context)))
            else:
                cond = self._cond_header(line, rest)
                prev.branches.append((cond, self._parse_block(line, context)))
            return None

        if word == "image":
            if context == "choice":
                self.error(line, "선택지 블록 안에서는 set 과 if 만 쓸 수 있습니다.")
                return None
            if rest in ("none", "None", "없음"):
                return Image(None, loc)
            try:
                value, end = _read_string(rest)
            except (ValueError, IndexError):
                self.error(line, '이미지는 image "파일이름.png" 형태로 씁니다.')
                return None
            return Image(value, loc)

        if word == "choice":
            if context == "choice":
                self.error(line, "선택지 블록 안에 다른 선택지를 둘 수 없습니다.")
                return None
            return self._parse_choice(line, rest)

        if word == "goto":
            if context == "choice":
                self.error(line, "선택지 블록 안에서는 set 과 if 만 쓸 수 있습니다. (이동할 곳은 -> 뒤에 씁니다)")
                return None
            if not NAME_RE.match(rest):
                self.error(line, "goto 뒤에는 단락 이름을 씁니다. 예) goto 동굴")
                return None
            return Goto(rest, loc)

        if word == "end":
            if context == "choice":
                self.error(line, "선택지 블록 안에서는 set 과 if 만 쓸 수 있습니다.")
                return None
            title = ""
            if rest:
                try:
                    title, endp = _read_string(rest)
                except (ValueError, IndexError):
                    self.error(line, '엔딩 제목은 따옴표로 감싸 주세요. 예) end "행복한 결말"')
            return End(title, loc)

        if word in ("label", "default"):
            self.error(line, f"{word} 는 들여쓰지 않고 맨 앞에 써야 합니다.")
            return None

        self.error(line, f"알 수 없는 문장입니다: {text}")
        return None

    def _text_ok(self, line: _Line, context: str) -> bool:
        if context == "choice":
            self.error(line, "선택지 블록 안에는 본문을 쓸 수 없습니다. 선택 후 보여 줄 내용은 이동할 단락에 적어 주세요.")
            return False
        return True

    def _cond_header(self, line: _Line, rest: str) -> Optional[Expr]:
        if not rest.endswith(":"):
            self.error(line, "조건 줄은 콜론(:)으로 끝나야 합니다.")
        else:
            rest = rest[:-1]
        return self.expr(line, rest)

    def _parse_if(self, line: _Line, context: str):
        cond = self._cond_header(line, line.text[2:].strip())
        body = self._parse_block(line, context)
        if not body:
            self.error(line, "if 아래에 들여쓴 내용이 없습니다.")
        return If([(cond, body)], self.loc(line))

    def _parse_choice(self, line: _Line, rest: str):
        loc = self.loc(line)
        if not rest[:1] in ("\"", "'"):
            self.error(line, '선택지는 choice "보여 줄 글" -> 단락이름 형태로 씁니다.')
            return None
        try:
            text, end = _read_string(rest)
        except ValueError as e:
            self.error(line, str(e))
            return None
        tail = rest[end:].strip()
        has_block = tail.endswith(":")
        if has_block:
            tail = tail[:-1].rstrip()
        arrow = _find_arrow(tail)
        if arrow < 0:
            self.error(line, '선택지에 이동할 단락이 없습니다. 예) choice "문을 연다" -> 방안')
            if has_block:
                self._parse_block(line, "choice")
            return None
        before, target = tail[:arrow].strip(), tail[arrow + 2:].strip()
        cond = None
        if before:
            if not before.startswith("if "):
                self.error(line, '선택지 조건은 if 로 시작해야 합니다. 예) choice "..." if 횃불 -> 동굴')
            else:
                cond = self.expr(line, before[3:])
        if not NAME_RE.match(target):
            self.error(line, f"이동할 단락 이름 '{target}'이(가) 올바르지 않습니다.")
            target = ""
        body = self._parse_block(line, "choice") if has_block else []
        if has_block and not body:
            self.error(line, "선택지 줄이 콜론(:)으로 끝났지만 아래에 들여쓴 내용이 없습니다.")
        return Choice(text, cond, target, body, loc)


# ---------------------------------------------------------------- 공개 함수

def parse_source(source: str, filename: str = "<script>", story: Optional[Story] = None) -> Story:
    story = story or Story()
    _Parser(filename, story).parse(source)
    return story


def script_files(script_dir: str) -> List[str]:
    found = []
    for root, dirs, files in os.walk(script_dir):
        dirs.sort()
        for f in sorted(files):
            if f.lower().endswith(SCRIPT_EXT):
                found.append(os.path.join(root, f))
    return found


def load_story(script_dir: str, overrides: Optional[dict] = None) -> Story:
    """폴더 안의 모든 .gb 파일을 읽어 하나의 이야기로 합칩니다.

    overrides: {파일 경로: 내용} - 에디터에서 아직 저장하지 않은 내용을 디스크 대신 사용
    """
    story = Story()
    overrides = {os.path.normcase(os.path.abspath(k)): v for k, v in (overrides or {}).items()}
    files = script_files(script_dir)
    if not files:
        story.errors.append(ScriptError(Loc(script_dir, 0), "스크립트(.gb) 파일이 하나도 없습니다."))
    for path in files:
        story.files.append(path)
        key = os.path.normcase(os.path.abspath(path))
        if key in overrides:
            parse_source(overrides[key], path, story)
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                source = f.read()
        except UnicodeDecodeError:
            story.errors.append(ScriptError(Loc(path, 0), "UTF-8 로 저장된 파일이 아닙니다. 편집기에서 UTF-8 로 다시 저장해 주세요."))
            continue
        except OSError as e:
            story.errors.append(ScriptError(Loc(path, 0), f"파일을 열 수 없습니다: {e}"))
            continue
        parse_source(source, path, story)
    return story
