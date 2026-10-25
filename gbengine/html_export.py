"""게임북을 HTML 파일 하나로 내보내기.

스크립트, 설정, 그림을 모두 파일 안에 넣습니다. 받은 사람은 브라우저로 열기만 하면
플레이할 수 있고(휴대폰 포함), 저장은 그 브라우저(localStorage)에 됩니다.
게임 화면은 gbengine/web/player.js (web_player/ 에서 빌드한 웹 플레이어)를 씁니다.
"""

from __future__ import annotations

import base64
import html
import json
import os
import time

from .lint import lint_project
from .script import script_files

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".webp": "image/webp", ".bmp": "image/bmp", ".svg": "image/svg+xml", ".avif": "image/avif",
}

TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="GameBook Studio">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div id="app"></div>
<script>window.GB_DATA = {data};</script>
<script>{js}</script>
</body>
</html>
"""


def _script_safe(s: str) -> str:
    """<script> 안에 넣어도 안전하게."""
    return (s.replace("</script", "<\\/script").replace("</SCRIPT", "<\\/SCRIPT")
            .replace("<!--", "<\\!--").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def collect(project):
    """내보낼 데이터: 설정, 스크립트(파일 이름 순), 그림(data URI)."""
    scripts = []
    for path in script_files(project.script_dir):
        rel = os.path.relpath(path, project.script_dir).replace(os.sep, "/")
        with open(path, "r", encoding="utf-8-sig") as f:
            scripts.append({"path": rel, "text": f.read()})
    images = {}
    for root, dirs, files in os.walk(project.image_dir):
        dirs.sort()
        for name in sorted(files):
            ext = os.path.splitext(name)[1].lower()
            if ext not in MIME:
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, project.image_dir).replace(os.sep, "/")
            with open(full, "rb") as f:
                images[rel] = f"data:{MIME[ext]};base64," + base64.b64encode(f.read()).decode("ascii")
    return {
        "config": project.config,
        "scripts": scripts,
        "images": images,
        "exportedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def default_output(project) -> str:
    return os.path.join(project.path, "dist", f"{project.name}.html")


def export_html(project, out_path=None) -> str:
    """HTML 파일을 만들고 경로를 돌려줍니다."""
    out_path = out_path or default_output(project)
    with open(os.path.join(WEB_DIR, "player.js"), encoding="utf-8") as f:
        js = f.read()
    with open(os.path.join(WEB_DIR, "player.css"), encoding="utf-8") as f:
        css = f.read()
    data = collect(project)
    page = TEMPLATE.format(
        title=html.escape(str(project.config.get("title") or project.name)),
        css=css.replace("</style", "<\\/style"),
        data=_script_safe(json.dumps(data, ensure_ascii=False)),
        js=_script_safe(js),
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = out_path + ".tmp~"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)
    os.replace(tmp, out_path)
    return out_path


def check_before_export(project):
    """내보내기 전에 검사. (오류 수, 요약) 을 돌려줍니다."""
    report = lint_project(project)
    return len(report.errors), report.summary()
