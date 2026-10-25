"""게임 진행 로직 (화면과 분리되어 있어 테스트하기 쉽습니다).

한 "페이지"는 단락 하나를 실행한 결과입니다: 이미지, 본문, 선택지.
저장 파일과 '뒤로 가기'는 페이지에 들어서기 직전의 상태(스냅샷)를 기록하고,
필요할 때 그 단락을 다시 실행해서 같은 페이지를 만들어 냅니다.
"""

from __future__ import annotations

import copy
import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

from .expr import EvalContext, ExprError
from .script import Choice, End, Goto, If, Image, SetVar, Story, Text

MAX_GOTO_CHAIN = 200
MAX_HISTORY = 200
SAVE_SLOTS = 10

_INTERP_RE = re.compile(r"\{\{|\}\}|\{(\w+)\}")


class RuntimeScriptError(Exception):
    """스크립트 실행 중 오류 (위치 정보 포함)."""

    def __init__(self, message: str, loc=None):
        super().__init__(f"{loc}  {message}" if loc else message)
        self.loc = loc
        self.message = message


@dataclass
class Snapshot:
    """페이지에 들어서기 직전의 상태."""
    label: str
    variables: dict
    visited: dict
    seed: int

    def to_json(self):
        return {"label": self.label, "variables": self.variables,
                "visited": self.visited, "seed": self.seed}

    @staticmethod
    def from_json(d):
        return Snapshot(d["label"], dict(d["variables"]), dict(d["visited"]), int(d["seed"]))


@dataclass
class PageChoice:
    text: str
    target: str
    enabled: bool = True
    node: Optional[Choice] = None   # None 이면 '계속' 버튼 (goto 로 생긴 것)


@dataclass
class Page:
    label: str
    image: Optional[str] = None                 # 프로젝트 images 폴더 기준 경로
    paragraphs: List[str] = field(default_factory=list)
    choices: List[PageChoice] = field(default_factory=list)
    ending: Optional[str] = None                # 엔딩이면 제목 ("" 가능)
    dead_end: bool = False                      # 갈 곳이 없는 단락
    labels_passed: List[str] = field(default_factory=list)  # goto 로 지나온 단락들

    @property
    def is_ending(self):
        return self.ending is not None


class _Stop(Exception):
    pass


class _Ctx:
    def __init__(self, engine: "Engine", variables: dict, visited: dict, rng):
        self.engine = engine
        self.variables = variables
        self.visited = visited
        self.rng = rng
        self.page: Optional[Page] = None
        self.goto: Optional[str] = None
        self.eval_ctx = EvalContext(variables, visited, rng)

    def eval(self, expr, loc):
        try:
            return expr.eval(self.eval_ctx)
        except ExprError as e:
            raise RuntimeScriptError(str(e), loc) from None


def interpolate(text: str, variables: dict) -> str:
    def repl(m):
        tok = m.group(0)
        if tok == "{{":
            return "{"
        if tok == "}}":
            return "}"
        value = variables.get(m.group(1), 0)
        if value is True:
            return "참"
        if value is False:
            return "거짓"
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return str(value)
    return _INTERP_RE.sub(repl, text)


class Engine:
    def __init__(self, story: Story, start: str = "start", show_locked_choices: bool = False):
        self.story = story
        self.start = start
        self.show_locked_choices = show_locked_choices

    # ------------------------------------------------------------ 새 게임
    def new_game(self, seed: Optional[int] = None) -> Snapshot:
        seed = seed if seed is not None else random.randrange(2 ** 31)
        variables: dict = {}
        ctx = _Ctx(self, variables, {}, random.Random(seed))
        for d in self.story.defaults:
            variables[d.name] = ctx.eval(d.expr, d.loc)
        return Snapshot(self.start, variables, {}, ctx.rng.randrange(2 ** 31))

    # ------------------------------------------------------------ 페이지 실행
    def run_page(self, entry: Snapshot):
        """스냅샷에서 시작해 페이지를 만듭니다. (페이지, 페이지를 다 읽은 뒤의 상태)를 돌려줍니다."""
        variables = copy.deepcopy(entry.variables)
        visited = dict(entry.visited)
        rng = random.Random(entry.seed)
        ctx = _Ctx(self, variables, visited, rng)

        label_name = entry.label
        passed = []
        for _ in range(MAX_GOTO_CHAIN):
            label = self.story.labels.get(label_name)
            if label is None:
                raise RuntimeScriptError(f"단락 '{label_name}'을(를) 찾을 수 없습니다.")
            passed.append(label_name)
            visited[label_name] = visited.get(label_name, 0) + 1
            page = Page(label_name)
            ctx.page = page
            ctx.goto = None
            try:
                self._exec(label.body, ctx)
            except _Stop:
                pass
            if ctx.goto is not None:
                if page.paragraphs or page.image:
                    page.choices = [PageChoice("계속", ctx.goto)]
                    break
                label_name = ctx.goto      # 보여 줄 내용이 없으면 바로 넘어감
                continue
            break
        else:
            raise RuntimeScriptError(
                f"goto 가 {MAX_GOTO_CHAIN}번 넘게 이어졌습니다. 단락끼리 서로 goto 하는 무한 반복인지 확인해 주세요.")

        page.labels_passed = passed
        if not page.is_ending and not page.choices:
            page.dead_end = True
        elif not page.is_ending and not any(c.enabled for c in page.choices):
            page.dead_end = True

        after = Snapshot(page.label, variables, visited, rng.randrange(2 ** 31))
        return page, after

    def _exec(self, body, ctx: _Ctx):
        for node in body:
            if isinstance(node, Text):
                ctx.page.paragraphs.append(interpolate(node.text, ctx.variables))
            elif isinstance(node, Image):
                ctx.page.image = node.path
            elif isinstance(node, SetVar):
                self._set(node, ctx)
            elif isinstance(node, If):
                for cond, sub in node.branches:
                    if cond is None or ctx.eval(cond, node.loc):
                        self._exec(sub, ctx)
                        break
            elif isinstance(node, Choice):
                ok = node.cond is None or bool(ctx.eval(node.cond, node.loc))
                if ok or self.show_locked_choices:
                    ctx.page.choices.append(PageChoice(
                        interpolate(node.text, ctx.variables), node.target, ok, node))
            elif isinstance(node, Goto):
                ctx.goto = node.target
                raise _Stop()
            elif isinstance(node, End):
                ctx.page.ending = node.title
                ctx.page.choices = []
                raise _Stop()

    def _set(self, node: SetVar, ctx: _Ctx):
        value = ctx.eval(node.expr, node.loc)
        if node.op == "=":
            ctx.variables[node.name] = value
            return
        old = ctx.variables.get(node.name, 0)
        try:
            ctx.variables[node.name] = old + value if node.op == "+=" else old - value
        except TypeError:
            raise RuntimeScriptError(
                f"'{node.name}'({old!r})에 {value!r}을(를) 더하거나 뺄 수 없습니다.", node.loc) from None

    # ------------------------------------------------------------ 선택
    def choose(self, after: Snapshot, choice: PageChoice) -> Snapshot:
        """선택지를 고른 뒤 다음 페이지의 시작 상태를 돌려줍니다."""
        if not choice.enabled:
            raise RuntimeScriptError("선택할 수 없는 선택지입니다.")
        variables = copy.deepcopy(after.variables)
        visited = dict(after.visited)
        rng = random.Random(after.seed)
        if choice.node is not None and choice.node.body:
            ctx = _Ctx(self, variables, visited, rng)
            ctx.page = Page(after.label)
            self._exec(choice.node.body, ctx)
        return Snapshot(choice.target, variables, visited, rng.randrange(2 ** 31))


# ---------------------------------------------------------------- 진행 상황 (뒤로 가기 포함)

class Session:
    """현재 페이지와 지나온 페이지 기록을 관리합니다."""

    def __init__(self, engine: Engine):
        self.engine = engine
        self.history: List[Snapshot] = []    # 지나온 페이지들의 시작 상태
        self.entry: Optional[Snapshot] = None
        self.page: Optional[Page] = None
        self.after: Optional[Snapshot] = None

    def start(self, seed: Optional[int] = None):
        self.history = []
        self._enter(self.engine.new_game(seed))

    def _enter(self, entry: Snapshot):
        page, after = self.engine.run_page(entry)
        self.entry, self.page, self.after = entry, page, after

    def choose(self, index: int):
        choice = self.page.choices[index]
        nxt = self.engine.choose(self.after, choice)
        prev = self.entry
        self._enter(nxt)
        self.history.append(prev)
        del self.history[:-MAX_HISTORY]

    def start_at(self, label: str, seed: Optional[int] = None):
        """새 게임을 시작하되 지정한 단락에서 출발합니다 (변수는 default 값)."""
        self.history = []
        entry = self.engine.new_game(seed)
        entry.label = label
        self._enter(entry)

    def jump(self, label: str):
        """개발용: 현재 변수를 유지한 채 다른 단락으로 이동."""
        base = self.after or self.engine.new_game()
        nxt = Snapshot(label, copy.deepcopy(base.variables), dict(base.visited), base.seed)
        prev = self.entry
        self._enter(nxt)
        if prev:
            self.history.append(prev)

    def can_go_back(self):
        return bool(self.history)

    def back(self):
        if self.history:
            self._enter(self.history.pop())

    def reload(self, engine: Engine):
        """스크립트를 다시 읽은 뒤 현재 페이지를 다시 실행합니다."""
        self.engine = engine
        if self.entry is not None:
            self._enter(self.entry)

    # ------------------------------------------------------------ 저장 / 불러오기
    def to_json(self):
        return {"entry": self.entry.to_json(),
                "history": [h.to_json() for h in self.history[-50:]]}

    def load_json(self, data):
        self.history = [Snapshot.from_json(h) for h in data.get("history", [])]
        self._enter(Snapshot.from_json(data["entry"]))


def save_path(save_dir: str, slot: int) -> str:
    return os.path.join(save_dir, f"slot{slot:02d}.json")


def write_save(save_dir: str, slot: int, session: Session):
    os.makedirs(save_dir, exist_ok=True)
    excerpt = ""
    if session.page and session.page.paragraphs:
        excerpt = session.page.paragraphs[0].replace("\n", " ")[:60]
    data = {
        "format": 1,
        "time": time.strftime("%Y-%m-%d %H:%M"),
        "label": session.entry.label,
        "excerpt": excerpt,
        "session": session.to_json(),
    }
    tmp = save_path(save_dir, slot) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, save_path(save_dir, slot))


def read_save(save_dir: str, slot: int) -> Optional[dict]:
    p = save_path(save_dir, slot)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
