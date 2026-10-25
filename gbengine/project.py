"""프로젝트 폴더 구조와 설정(game.json), 새 프로젝트 만들기, 배포 파일 만들기.

    내프로젝트/
        game.json       제목, 시작 단락, 창 크기 등 설정
        script/         .gb 스크립트 (여러 파일로 나눠도 됨)
        images/         이미지 (PNG, GIF / Pillow 가 있으면 JPG 등도)
        saves/          저장 파일 (자동 생성)
"""

from __future__ import annotations

import json
import os
import re
import time
import zipfile

from . import __version__
from .script import load_story

DEFAULT_CONFIG = {
    "title": "제목 없는 게임북",
    "author": "",
    "start": "start",
    "window": [1024, 760],
    "font": "",                 # 비우면 고딕(나눔고딕), "serif" 면 명조(나눔명조), 또는 글꼴 파일 경로
    "font_size": 15,
    "show_locked_choices": False,  # true 면 조건이 안 맞는 선택지도 흐리게 보여 줌
    "title_image": "",          # 타이틀 화면 이미지 (images 폴더 기준)
    "theme": "paper",           # paper | night
}

NEW_SCRIPT = '''# {title}
# 이 파일을 텍스트 편집기로 열어 이야기를 쓰세요. 저장할 때는 UTF-8 로 저장합니다.
# 문법은 README.md 를 참고하세요.

default 열쇠 = false

label start:
    "당신은 낯선 방에서 눈을 떴다. 문이 하나, 창문이 하나 있다."
    choice "문을 열어 본다" -> 문
    choice "창밖을 내다본다" -> 창문

label 창문:
    "창틀 아래에서 작은 열쇠를 발견했다."
    set 열쇠 = true
    choice "문으로 간다" -> 문

label 문:
    if 열쇠:
        "열쇠가 딱 맞는다. 문이 열린다."
        end "탈출"
    "문은 잠겨 있다."
    choice "방을 둘러본다" -> 창문
'''


class Project:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.config = dict(DEFAULT_CONFIG)
        self.config_error = None
        cfg = os.path.join(self.path, "game.json")
        if os.path.exists(cfg):
            try:
                with open(cfg, "r", encoding="utf-8-sig") as f:
                    self.config.update(json.load(f))
            except (OSError, ValueError) as e:
                self.config_error = f"game.json 을 읽지 못했습니다: {e}"

    @property
    def name(self):
        return os.path.basename(self.path)

    @property
    def title(self):
        return self.config.get("title") or self.name

    @property
    def script_dir(self):
        return os.path.join(self.path, "script")

    @property
    def image_dir(self):
        return os.path.join(self.path, "images")

    @property
    def save_dir(self):
        return os.path.join(self.path, "saves")

    def load_story(self, overrides=None):
        return load_story(self.script_dir, overrides)

    def image_path(self, rel):
        return os.path.join(self.image_dir, *rel.replace("\\", "/").split("/"))

    def script_mtimes(self):
        """스크립트 폴더의 파일 변경 감지용."""
        result = {}
        for root, _dirs, files in os.walk(self.script_dir):
            for f in files:
                p = os.path.join(root, f)
                try:
                    result[p] = os.path.getmtime(p)
                except OSError:
                    pass
        return result


def is_project(path: str) -> bool:
    return os.path.isfile(os.path.join(path, "game.json")) or os.path.isdir(os.path.join(path, "script"))


def list_projects(projects_dir: str):
    if not os.path.isdir(projects_dir):
        return []
    found = []
    for name in sorted(os.listdir(projects_dir)):
        p = os.path.join(projects_dir, name)
        if os.path.isdir(p) and is_project(p):
            found.append(Project(p))
    return found


def create_project(projects_dir: str, folder_name: str, title: str) -> Project:
    folder_name = folder_name.strip()
    if not folder_name or re.search(r'[\\/:*?"<>|]', folder_name):
        raise ValueError("폴더 이름에 쓸 수 없는 글자가 있습니다.")
    path = os.path.join(projects_dir, folder_name)
    if os.path.exists(path):
        raise ValueError(f"'{folder_name}' 폴더가 이미 있습니다.")
    os.makedirs(os.path.join(path, "script"))
    os.makedirs(os.path.join(path, "images"))
    cfg = dict(DEFAULT_CONFIG, title=title or folder_name)
    with open(os.path.join(path, "game.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    with open(os.path.join(path, "script", "script.gb"), "w", encoding="utf-8") as f:
        f.write(NEW_SCRIPT.format(title=cfg["title"]))
    return Project(path)


PLAY_PY = '''"""{title} - 실행하려면: python play.py"""
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)

from gbengine.deps import require_pygame

require_pygame()          # pygame-ce 가 없으면 설치 방법을 알려 줌

from gbengine.gui.player import main

main([os.path.join(here, "game")] + sys.argv[1:])
'''

README_TXT = """{title}

실행 방법
  1) Python 3.9 이상을 설치합니다.  (https://www.python.org)
  2) pygame-ce 를 설치합니다. 터미널(명령 프롬프트)에서
         python -m pip install pygame-ce
     (macOS·Linux 에서는 python 대신 python3)
  3) 이 폴더에서
         python play.py
     를 실행합니다. Windows 에서는 play.py 를 더블클릭해도 됩니다.

  한글 글꼴(나눔고딕·나눔명조)이 함께 들어 있어서 어느 운영체제에서나 똑같이 보입니다.

조작
  숫자 1~9 / 마우스: 선택지 고르기    Backspace: 뒤로 가기
  Ctrl+S: 저장   Ctrl+O: 불러오기    Ctrl+ +/-: 글자 크기    Ctrl+T: 밤 테마
  F11: 전체 화면                      (macOS 에서는 Ctrl 대신 Cmd 도 됩니다)

GameBook Studio {version} 으로 만들었습니다.
"""

ENGINE_SKIP_DIRS = ("__pycache__",)


def build_distribution(project: Project, engine_dir: str, out_dir: str) -> str:
    """플레이어용 zip 파일을 만듭니다: play.py + gbengine/(엔진·화면·글꼴) + game/(프로젝트, 저장 파일 제외)."""
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M")
    base = f"{project.name}-{stamp}"
    out = os.path.join(out_dir, base + ".zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{base}/play.py", PLAY_PY.format(title=project.title))
        z.writestr(f"{base}/README.txt", README_TXT.format(title=project.title, version=__version__))
        for root, dirs, files in os.walk(engine_dir):
            dirs[:] = sorted(d for d in dirs if d not in ENGINE_SKIP_DIRS)
            rel_root = os.path.relpath(root, engine_dir)
            for f in sorted(files):
                if f.endswith((".pyc", ".pyo")):
                    continue
                rel = os.path.normpath(os.path.join(rel_root, f)).replace(os.sep, "/")
                z.write(os.path.join(root, f), f"{base}/gbengine/{rel}")
        for root, dirs, files in os.walk(project.path):
            rel_root = os.path.relpath(root, project.path)
            if rel_root.split(os.sep)[0] in ("saves", "__pycache__"):
                continue
            dirs.sort()
            for f in sorted(files):
                rel = os.path.normpath(os.path.join(rel_root, f))
                z.write(os.path.join(root, f), f"{base}/game/" + rel.replace(os.sep, "/"))
    return out


def delete_project(project: Project) -> None:
    """프로젝트 폴더를 통째로 지웁니다. 되돌릴 수 없습니다."""
    import shutil
    import stat
    path = os.path.abspath(project.path)
    if not os.path.isdir(path):
        raise OSError(f"폴더가 없습니다: {path}")

    def _retry(func, p, _exc):          # Windows 의 읽기 전용 파일도 지울 수 있게
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            raise
    shutil.rmtree(path, onerror=_retry)
