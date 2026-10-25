"""외부 편집기 연동 (Ren'Py 처럼 스크립트는 VS Code 같은 편집기로 고칩니다).

- 설치된 편집기를 찾아서 파일을 원하는 줄로 엽니다.
- VS Code 용 게임북 스크립트 확장(구문 강조, 들여쓰기, 문장 조각)을 설치합니다.
- 설정은 사용자 폴더의 .gamebook_studio.json 에 저장합니다.
"""

from __future__ import annotations

import glob
import json
import os
import shlex
import shutil
import subprocess
import sys
import webbrowser
import zipfile

SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".gamebook_studio.json")
TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VSCODE_EXT_DIR = os.path.join(TOOL_DIR, "editor_support", "vscode-gamebook")

WIN = sys.platform.startswith("win")
MAC = sys.platform == "darwin"


# ------------------------------------------------------------------ 설정

def load_settings() -> dict:
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(s: dict):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ------------------------------------------------------------------ 열기

def open_path(path: str):
    """파일이나 폴더를 운영체제 기본 프로그램으로 엽니다."""
    if WIN:
        os.startfile(path)  # noqa
    elif MAC:
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_url(path_or_url: str):
    if "://" not in path_or_url:
        path_or_url = "file://" + os.path.abspath(path_or_url).replace("\\", "/").replace(" ", "%20")
    webbrowser.open(path_or_url)


def _first(*paths):
    for p in paths:
        for hit in glob.glob(os.path.expandvars(os.path.expanduser(p))):
            if os.path.exists(hit):
                return hit
    return None


def _which(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def detect():
    """설치된 편집기 목록: [(id, 이름, 실행 파일)]"""
    found = []
    code = _which("code") or _first(
        "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
        "~/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
        "%LOCALAPPDATA%/Programs/Microsoft VS Code/bin/code.cmd",
        "%PROGRAMFILES%/Microsoft VS Code/bin/code.cmd",
        "/snap/bin/code", "/usr/share/code/bin/code")
    if code:
        found.append(("vscode", "Visual Studio Code", code))
    codium = _which("codium") or _first("/Applications/VSCodium.app/Contents/Resources/app/bin/codium")
    if codium:
        found.append(("codium", "VSCodium", codium))
    cursor = _which("cursor") or _first("/Applications/Cursor.app/Contents/Resources/app/bin/cursor")
    if cursor:
        found.append(("cursor", "Cursor", cursor))
    subl = _which("subl") or _first("/Applications/Sublime Text.app/Contents/SharedSupport/bin/subl",
                                    "%PROGRAMFILES%/Sublime Text*/subl.exe")
    if subl:
        found.append(("sublime", "Sublime Text", subl))
    npp = _first("%PROGRAMFILES%/Notepad++/notepad++.exe", "%PROGRAMFILES(X86)%/Notepad++/notepad++.exe") if WIN else None
    if npp:
        found.append(("notepadpp", "Notepad++", npp))
    for exe, name in (("kate", "Kate"), ("gedit", "gedit"), ("gnome-text-editor", "GNOME 텍스트 편집기"),
                      ("mousepad", "Mousepad"), ("xed", "Xed")):
        if not WIN and not MAC and shutil.which(exe):
            found.append((exe, name, shutil.which(exe)))
    if MAC:
        found.append(("textedit", "텍스트 편집기 (TextEdit)", "open"))
    return found


VSCODE_LIKE = ("vscode", "codium", "cursor")


def current_editor():
    """설정된 편집기 (id, 이름, 실행 파일). 설정이 없으면 VS Code 계열을 먼저 고름."""
    s = load_settings()
    want = s.get("editor", "auto")
    if want == "custom" and s.get("editor_command"):
        return ("custom", "직접 지정", s["editor_command"])
    if want == "system":
        return ("system", "운영체제 기본 프로그램", None)
    found = detect()
    for e in found:
        if e[0] == want:
            return e
    for e in found:
        if e[0] in VSCODE_LIKE + ("sublime",):
            return e
    return ("system", "운영체제 기본 프로그램", None)


def _run(cmd):
    if WIN:
        subprocess.Popen(subprocess.list2cmdline(cmd), shell=True)
    else:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_in_editor(path: str, line: int = 0, project_dir: str | None = None):
    """편집기로 파일을 열고 가능하면 line 줄로 이동. 쓴 편집기 이름을 돌려줌."""
    eid, name, exe = current_editor()
    line = max(1, int(line or 1))
    try:
        if eid in VSCODE_LIKE:
            cmd = [exe]
            if project_dir:
                cmd.append(project_dir)
            _run(cmd + ["-g", f"{path}:{line}"])
        elif eid == "sublime":
            _run([exe, f"{path}:{line}"])
        elif eid == "notepadpp":
            _run([exe, f"-n{line}", path])
        elif eid == "kate":
            _run([exe, "-l", str(line), path])
        elif eid in ("gedit", "xed", "mousepad", "gnome-text-editor"):
            _run([exe, f"+{line}", path])
        elif eid == "textedit":
            subprocess.Popen(["open", "-e", path])
        elif eid == "custom":
            cmd = [part.replace("{file}", path).replace("{line}", str(line)).replace("{project}", project_dir or "")
                   for part in shlex.split(exe, posix=not WIN)]
            _run(cmd)
        else:
            open_path(path)
    except OSError:
        open_path(path)
        return "운영체제 기본 프로그램"
    return name


# ------------------------------------------------------------------ VS Code 확장

def _vsix(ext_dir: str, out: str):
    """확장 폴더를 .vsix 파일로 묶습니다."""
    with open(os.path.join(ext_dir, "package.json"), encoding="utf-8") as f:
        pkg = json.load(f)
    manifest = f"""<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
  <Metadata>
    <Identity Language="en-US" Id="{pkg['name']}" Version="{pkg['version']}" Publisher="{pkg['publisher']}"/>
    <DisplayName>{pkg['displayName']}</DisplayName>
    <Description xml:space="preserve">{pkg.get('description', '')}</Description>
    <Categories>Programming Languages</Categories>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{pkg['engines']['vscode']}"/>
    </Properties>
  </Metadata>
  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/>
  </Assets>
</PackageManifest>
"""
    types = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension=".json" ContentType="application/json"/><Default Extension=".vsixmanifest" ContentType="text/xml"/>
<Default Extension=".md" ContentType="text/markdown"/>
</Types>
"""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("extension.vsixmanifest", manifest)
        z.writestr("[Content_Types].xml", types)
        for root, _dirs, files in os.walk(ext_dir):
            for name in files:
                full = os.path.join(root, name)
                z.write(full, "extension/" + os.path.relpath(full, ext_dir).replace(os.sep, "/"))
    return out


def install_vscode_extension():
    """VS Code(또는 VSCodium/Cursor)에 게임북 스크립트 확장을 설치. (성공 여부, 설명)"""
    editors = [e for e in detect() if e[0] in VSCODE_LIKE]
    vsix = os.path.join(TOOL_DIR, "editor_support", "gamebook-script.vsix")
    try:
        _vsix(VSCODE_EXT_DIR, vsix)
    except OSError as e:
        return False, f"확장 파일을 만들지 못했습니다: {e}"
    if not editors:
        return False, ("VS Code 를 찾지 못했습니다.\n\nVS Code 를 설치한 뒤 다시 누르거나, VS Code 의 확장 화면에서 "
                       f"'… → VSIX에서 설치'로 이 파일을 고르세요:\n{vsix}")
    done = []
    for eid, name, exe in editors:
        try:
            cmd = [exe, "--install-extension", vsix, "--force"]
            r = subprocess.run(subprocess.list2cmdline(cmd) if WIN else cmd, shell=WIN, capture_output=True,
                               text=True, timeout=120)
            if r.returncode == 0:
                done.append(name)
        except (OSError, subprocess.SubprocessError):
            pass
    if done:
        return True, (f"{', '.join(done)} 에 게임북 스크립트 확장을 설치했습니다.\n"
                      "편집기를 다시 열면 .gb 파일에 색이 입혀지고, 'label', 'choice' 같은 단어를 치면 "
                      "문장 틀(조각)을 넣을 수 있습니다.")
    return False, ("설치 명령이 실패했습니다. VS Code 의 확장 화면에서 '… → VSIX에서 설치'로 이 파일을 고르세요:\n" + vsix)
