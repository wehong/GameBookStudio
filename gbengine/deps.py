"""pygame-ce 가 설치되어 있는지 확인하고, 없으면 설치 방법을 알려 줍니다 (또는 바로 설치)."""

from __future__ import annotations

import subprocess
import sys

INSTALL_CMD = [sys.executable, "-m", "pip", "install", "--upgrade", "pygame-ce"]


def _have_pygame():
    try:
        import pygame  # noqa: F401
        return True
    except ImportError:
        return False


def require_pygame():
    if _have_pygame():
        return
    cmd = " ".join(INSTALL_CMD[1:]).replace("-m pip", "python -m pip", 1)
    msg = ("GameBook Studio 의 화면은 pygame-ce 로 그립니다. 아직 설치되어 있지 않습니다.\n"
           f"    {cmd}\n"
           "로 설치한 뒤 다시 실행해 주세요.")
    if sys.stdin and sys.stdin.isatty():
        print(msg)
        try:
            ans = input("지금 설치할까요? [Y/n] ").strip().lower()
        except EOFError:
            ans = "n"
        if ans in ("", "y", "yes", "ㅛ", "예", "네"):
            r = subprocess.call(INSTALL_CMD)
            if r != 0:   # 시스템 Python(Linux) 등에서 막혀 있으면 사용자 영역에
                r = subprocess.call(INSTALL_CMD + ["--user"])
            if r == 0:
                import importlib
                importlib.invalidate_caches()
                if _have_pygame():
                    return
        sys.exit(1)
    sys.exit(msg)
