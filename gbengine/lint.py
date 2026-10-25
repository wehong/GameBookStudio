"""스크립트 검사기.

끊긴 링크, 도달할 수 없는 단락, 막다른 단락, 빠진 이미지, 쓰이지 않는 변수 등을 찾아 줍니다.
명령줄에서: python -m gbengine lint <프로젝트 폴더>
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional

from .script import Choice, Default, End, Goto, If, Image, Loc, SetVar, Story, Text, walk

ERROR, WARNING, INFO = "오류", "경고", "참고"
_LEVEL_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}
_INTERP_RE = re.compile(r"(?<!\{)\{(\w+)\}")

# 게임 창(pygame-ce)과 HTML 내보내기(브라우저) 모두에서 보이는 형식
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


@dataclass
class Issue:
    level: str
    loc: Optional[Loc]
    message: str

    def __str__(self):
        where = f"{self.loc}  " if self.loc else ""
        return f"[{self.level}] {where}{self.message}"


@dataclass
class Report:
    issues: List[Issue]
    stats: dict

    @property
    def errors(self):
        return [i for i in self.issues if i.level == ERROR]

    @property
    def warnings(self):
        return [i for i in self.issues if i.level == WARNING]

    def summary(self):
        s = self.stats
        return (f"단락 {s['labels']}개 · 선택지 {s['choices']}개 · 엔딩 {s['endings']}개 · "
                f"본문 {s['chars']:,}자 · 오류 {len(self.errors)}개 · 경고 {len(self.warnings)}개")


def _exits(body) -> bool:
    return any(isinstance(n, (Choice, Goto, End)) for n in walk(body))


def _guaranteed_exit(body) -> bool:
    for n in body:
        if isinstance(n, (Goto, End)):
            return True
        if isinstance(n, Choice) and n.cond is None:
            return True
        if isinstance(n, If) and n.branches[-1][0] is None \
                and all(_guaranteed_exit(sub) for _c, sub in n.branches):
            return True
    return False


def _targets(body):
    for n in walk(body):
        if isinstance(n, (Choice, Goto)) and n.target:
            yield n


def _image_check(issues, image_dir: str, rel: str, loc: Optional[Loc], what="이미지"):
    path = os.path.join(image_dir, *rel.replace("\\", "/").split("/"))
    ext = os.path.splitext(rel)[1].lower()
    if not os.path.isfile(path):
        # 대소문자만 다른 파일이 있는지 (Windows 에선 열리지만 다른 OS 에선 안 열림)
        folder, base = os.path.split(path)
        if os.path.isdir(folder):
            for f in os.listdir(folder):
                if f.lower() == base.lower():
                    issues.append(Issue(WARNING, loc,
                        f"{what} '{rel}' 의 대소문자가 실제 파일 '{f}' 과(와) 다릅니다. "
                        "Windows 외의 운영체제에서는 열리지 않습니다."))
                    return
        issues.append(Issue(ERROR, loc, f"{what} 파일 '{rel}' 이(가) images 폴더에 없습니다."))
        return
    if ext not in IMAGE_EXT:
        issues.append(Issue(ERROR, loc, f"'{rel}' 은(는) 지원하지 않는 이미지 형식입니다. "
                                        "(PNG, JPG, GIF, WEBP, BMP 를 쓸 수 있습니다)"))


def lint(story: Story, start: str = "start", image_dir: Optional[str] = None,
         title_image: str = "") -> Report:
    issues: List[Issue] = [Issue(ERROR, e.loc, e.message) for e in story.errors]
    labels = story.labels

    # --- 시작 단락
    if labels and start not in labels:
        issues.append(Issue(ERROR, None,
            f"시작 단락 '{start}' 이(가) 없습니다. game.json 의 \"start\" 를 확인하거나 label {start}: 을 만들어 주세요."))

    # --- 링크와 출구
    for label in labels.values():
        for n in _targets(label.body):
            if n.target not in labels:
                kind = "선택지" if isinstance(n, Choice) else "goto"
                issues.append(Issue(ERROR, n.loc, f"{kind}가 가리키는 단락 '{n.target}' 이(가) 없습니다."))
            elif n.target == label.name and isinstance(n, Goto):
                issues.append(Issue(ERROR, n.loc, f"단락 '{label.name}' 이(가) 자기 자신으로 goto 합니다 (무한 반복)."))
        if not _exits(label.body):
            issues.append(Issue(WARNING, label.loc,
                f"단락 '{label.name}' 에 선택지·goto·end 가 없어 막다른 곳이 됩니다."))
        elif not _guaranteed_exit(label.body):
            issues.append(Issue(WARNING, label.loc,
                f"단락 '{label.name}' 은(는) 조건에 따라 선택지가 하나도 없을 수 있습니다. "
                "조건 없는 선택지나 else 를 두는 것을 권장합니다."))

    # --- 도달 가능성
    seen = None
    if start in labels:
        seen, stack = {start}, [start]
        while stack:
            for n in _targets(labels[stack.pop()].body):
                if n.target in labels and n.target not in seen:
                    seen.add(n.target)
                    stack.append(n.target)
        for name, label in labels.items():
            if name not in seen:
                issues.append(Issue(WARNING, label.loc,
                    f"단락 '{name}' 은(는) 시작 단락에서 갈 수 있는 길이 없습니다."))

    # --- 변수
    assigned, used = {}, {}
    for d in story.defaults:
        assigned.setdefault(d.name, d.loc)
        for v in d.expr.names:
            used.setdefault(v, d.loc)
    for label in labels.values():
        for n in walk(label.body):
            exprs = []
            if isinstance(n, SetVar):
                assigned.setdefault(n.name, n.loc)
                exprs.append(n.expr)
                if n.op != "=":
                    used.setdefault(n.name, n.loc)
            elif isinstance(n, If):
                exprs += [c for c, _ in n.branches if c is not None]
            elif isinstance(n, Choice):
                if n.cond:
                    exprs.append(n.cond)
                for v in _INTERP_RE.findall(n.text):
                    used.setdefault(v, n.loc)
            elif isinstance(n, Text):
                for v in _INTERP_RE.findall(n.text):
                    used.setdefault(v, n.loc)
            for e in exprs:
                for v in e.names:
                    used.setdefault(v, n.loc)
                for lab in e.labels:
                    if lab not in labels:
                        issues.append(Issue(ERROR, n.loc, f"visited(\"{lab}\") 의 단락 '{lab}' 이(가) 없습니다."))
    for v, loc in used.items():
        if v not in assigned:
            issues.append(Issue(WARNING, loc,
                f"변수 '{v}' 에 값을 넣는 곳(default/set)이 없습니다. 오타가 아닌지 확인해 주세요. (값은 0 으로 취급)"))
    for v, loc in assigned.items():
        if v not in used:
            issues.append(Issue(INFO, loc, f"변수 '{v}' 은(는) 값만 넣고 어디에서도 쓰지 않습니다."))

    # --- 이미지
    if image_dir:
        for label in labels.values():
            for n in walk(label.body):
                if isinstance(n, Image) and n.path:
                    _image_check(issues, image_dir, n.path, n.loc)
        if title_image:
            _image_check(issues, image_dir, title_image, None, what="타이틀 이미지")

    # --- 통계
    stats = {"labels": len(labels), "choices": 0, "endings": 0, "chars": 0}
    for label in labels.values():
        for n in walk(label.body):
            if isinstance(n, Choice):
                stats["choices"] += 1
            elif isinstance(n, End):
                stats["endings"] += 1
            elif isinstance(n, Text):
                stats["chars"] += len(n.text)

    def sort_key(i: Issue):
        return (_LEVEL_ORDER[i.level], i.loc.file if i.loc else "", i.loc.line if i.loc else 0)
    issues.sort(key=sort_key)
    report = Report(issues, stats)
    report.unreachable = set(labels) - seen if seen is not None else set()
    report.ending_labels = {name for name, label in labels.items()
                            if any(isinstance(n, End) for n in walk(label.body))}
    return report


def lint_project(project, overrides=None, story=None) -> Report:
    """프로젝트 검사. overrides 는 저장하지 않은 편집 내용 {경로: 내용}."""
    story = story or project.load_story(overrides)
    report = lint(story, project.config.get("start", "start"), project.image_dir,
                  project.config.get("title_image", ""))
    report.story = story
    if project.config_error:
        report.issues.insert(0, Issue(ERROR, None, project.config_error))
    return report
