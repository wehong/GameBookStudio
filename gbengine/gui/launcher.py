"""런처 (pygame): 프로젝트 목록, 편집기로 열기, 실행, 검사, HTML 내보내기, 배포 파일 만들기.

Ren'Py 런처처럼 스크립트는 외부 편집기(VS Code 등)로 고치고, 게임은 개발 모드로 띄워서
저장할 때마다 바로 반영되는 것을 확인합니다.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pygame

from .. import __version__
from .. import editors
from ..lint import lint_project
from ..project import Project, build_distribution, create_project, delete_project, list_projects
from .base import App, Dialog, InputDialog, ListDialog, Screen, blit_text, draw_rect, fit_text, mod_down, wrap

ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL_DIR = os.path.dirname(ENGINE_DIR)
PROJECTS_DIR = os.path.join(TOOL_DIR, "projects")
DIST_DIR = os.path.join(TOOL_DIR, "dist")

BASE_SIZE = (960, 640)


def main_script(project: Project):
    """편집기로 처음 열 스크립트 파일."""
    files = []
    for root, _dirs, names in os.walk(project.script_dir):
        for n in sorted(names):
            if n.endswith(".gb"):
                files.append(os.path.join(root, n))
    for want in ("script.gb", "main.gb", "start.gb"):
        for f in files:
            if os.path.basename(f) == want:
                return f
    return files[0] if files else None


class Launcher(Screen):
    def __init__(self, app):
        super().__init__(app)
        self.projects = []
        self.current = None
        self.reports = {}        # 경로 → (스크립트 시각, 검사 결과 또는 예외)
        self.games = {}          # 경로 → 실행 중인 게임 (Popen)
        self.list_scroll = 0
        self.busy = None         # 오래 걸리는 작업 이름
        self.refresh()

    # ================================================================ 목록
    def refresh(self):
        keep = self.current.path if self.current else None
        os.makedirs(PROJECTS_DIR, exist_ok=True)
        self.projects = list_projects(PROJECTS_DIR)
        self.current = next((p for p in self.projects if p.path == keep), self.projects[0] if self.projects else None)
        self.app.invalidate()

    def select(self, p):
        self.current = Project(p.path)
        self.app.invalidate()

    def report(self, p):
        sig = (tuple(sorted(p.script_mtimes().items())), self._mtime(os.path.join(p.path, "game.json")))
        cached = self.reports.get(p.path)
        if cached is None or cached[0] != sig:
            try:
                rep = lint_project(Project(p.path))
            except Exception as e:  # noqa: BLE001  검사가 실패해도 런처는 계속
                rep = e
            cached = (sig, rep)
            self.reports[p.path] = cached
        return cached[1]

    @staticmethod
    def _mtime(path):
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0

    _ticks = 0

    def tick(self):
        self._ticks += 1
        if self._ticks % 4 == 0:        # 2초마다: 스크립트가 바뀌었으면 요약을 다시 계산
            self.app.invalidate()

    def on_focus(self):
        self.refresh()

    # ================================================================ 동작
    def edit(self):
        p = self.current
        if not p:
            return
        f = main_script(p)
        if not f:
            os.makedirs(p.script_dir, exist_ok=True)
            f = os.path.join(p.script_dir, "script.gb")
            with open(f, "w", encoding="utf-8") as fp:
                fp.write("label start:\n    \"이야기를 여기에 쓰세요.\"\n    end\n")
        self.open_file(f, 1)

    def open_file(self, path, line=1):
        name = editors.open_in_editor(path, line, self.current.path if self.current else None)
        self.app.toast(f"{name}(으)로 열었습니다")

    def run_game(self):
        p = self.current
        if not p:
            return
        proc = self.games.get(p.path)
        if proc is not None and proc.poll() is None:
            self.app.toast("게임 창이 이미 열려 있습니다 · 스크립트를 저장하면 바로 반영됩니다", 3000)
            return
        cmd = [sys.executable, "-m", "gbengine", "run", p.path, "--dev"]
        try:
            self.games[p.path] = subprocess.Popen(cmd, cwd=TOOL_DIR)
            self.app.toast("게임을 개발 모드로 실행합니다")
        except OSError as e:
            self.app.push(Dialog(self.app, "실행할 수 없습니다", str(e)))

    def lint_dialog(self):
        p = self.current
        if not p:
            return
        rep = self.report(p)
        if isinstance(rep, Exception):
            self.app.push(Dialog(self.app, "검사 실패", str(rep)))
            return
        t = self.app.t
        color = {"오류": t["error"], "경고": t["warning"], "참고": t["info"]}
        items = [(f"[{i.level}] {i.message}", str(i.loc) if i.loc else "",
                  (i.loc.file, i.loc.line) if i.loc and getattr(i.loc, "line", 0) else None, color[i.level])
                 for i in rep.issues] or [("문제가 발견되지 않았습니다. 잘 하셨어요!", "", None, None)]
        self.app.push(ListDialog(self.app, f"검사 결과 - {p.title}", items,
                                 lambda v: v and self.open_file(*v),
                                 body=rep.summary() + "\n항목을 누르면 편집기에서 그 줄이 열립니다.", rows=10))

    def config(self):
        if self.current:
            self.open_file(os.path.join(self.current.path, "game.json"), 1)

    def guide(self):
        from .player import open_guide
        open_guide()

    def open_folder(self, path):
        os.makedirs(path, exist_ok=True)
        editors.open_path(path)

    # ---------------------------------------------------------------- HTML
    def export_html(self):
        p = self.current
        if not p:
            return
        from ..html_export import check_before_export, default_output
        n_err, _summary = check_before_export(Project(p.path))
        out = default_output(p)
        body = (f"한 파일짜리 HTML 게임을 만듭니다. 그림도 파일 안에 들어가서 이 파일 하나만 보내면 "
                f"누구나 브라우저(휴대폰 포함)에서 플레이할 수 있어요.\n\n저장 위치: {out}")
        if n_err:
            body = f"검사에서 오류 {n_err}개가 발견되었습니다. 내보낸 게임에서도 오류 화면이 나옵니다.\n\n" + body
        self.app.push(Dialog(self.app, "HTML 로 내보내기", body, [("취소", None), ("내보내기", True, True)],
                             lambda ok: ok and self._export_html(p, out)))

    def _export_html(self, p, out):
        from ..html_export import export_html
        self.busy = "HTML 로 내보내는 중…"

        def done(r):
            self.busy = None
            if isinstance(r, Exception):
                self.app.push(Dialog(self.app, "내보내기 실패", str(r)))
                return
            size = os.path.getsize(out) / 1024 / 1024
            self.app.push(Dialog(self.app, "내보내기 완료", f"HTML 파일을 만들었습니다. ({size:.1f} MB)\n\n{out}",
                                 [("폴더 열기", "dir"), ("닫기", None), ("브라우저로 열기", "open", True)],
                                 lambda v: (editors.open_url(out) if v == "open" else
                                            editors.open_path(os.path.dirname(out)) if v == "dir" else None)))
        self.app.background(lambda: export_html(Project(p.path), out), done)

    # ---------------------------------------------------------------- 배포
    def build(self):
        p = self.current
        if not p:
            return
        rep = self.report(p)
        n_err = 0 if isinstance(rep, Exception) else len(rep.errors)
        body = ("Python 과 pygame-ce 가 설치된 컴퓨터에서 실행할 수 있는 zip 파일을 만듭니다. "
                "(엔진·글꼴·게임이 함께 들어갑니다)\n\n저장 위치: " + DIST_DIR)
        if n_err:
            body = f"검사에서 오류 {n_err}개가 발견되었습니다.\n\n" + body
        self.app.push(Dialog(self.app, "배포 파일 만들기", body, [("취소", None), ("만들기", True, True)],
                             lambda ok: ok and self._build(p)))

    def _build(self, p):
        self.busy = "배포 파일을 만드는 중…"

        def done(r):
            self.busy = None
            if isinstance(r, Exception):
                self.app.push(Dialog(self.app, "실패", f"배포 파일을 만들지 못했습니다.\n{r}"))
                return
            self.app.push(Dialog(self.app, "완료", f"배포 파일을 만들었습니다.\n\n{r}",
                                 [("닫기", None), ("폴더 열기", True, True)],
                                 lambda v: v and self.open_folder(DIST_DIR)))
        self.app.background(lambda: build_distribution(Project(p.path), ENGINE_DIR, DIST_DIR), done)

    # ---------------------------------------------------------------- 새 프로젝트
    def new_project(self):
        def done(v):
            if not v:
                return
            try:
                p = create_project(PROJECTS_DIR, v["folder"], v["title"].strip())
            except (ValueError, OSError) as e:
                self.app.push(Dialog(self.app, "만들 수 없습니다", str(e),
                                     on_done=lambda _v: self.new_project()))
                return
            self.current = p
            self.refresh()
            self.app.push(Dialog(self.app, "프로젝트를 만들었습니다",
                                 f"'{p.title}' 프로젝트를 만들었습니다. 편집기로 스크립트를 열까요?",
                                 [("나중에", None), ("스크립트 편집하기", True, True)], lambda ok: ok and self.edit()))
        self.app.push(InputDialog(self.app, "새 프로젝트", [
            ("folder", "폴더 이름", "영문·숫자를 권장합니다. 예) my_gamebook", ""),
            ("title", "게임 제목", "예) 잊혀진 등대", ""),
        ], ok="만들기", on_done=done))

    # ---------------------------------------------------------------- 프로그램 정보
    def about(self):
        import platform
        try:
            sdl = ".".join(str(n) for n in pygame.get_sdl_version())
        except Exception:  # noqa: BLE001
            sdl = "?"
        body = (f"버전 {__version__}\n\n"
                "텍스트 스크립트로 분기형 게임북을 만들고 플레이하는 도구입니다.\n\n"
                f"Python {platform.python_version()} · pygame-ce {pygame.version.ver} · SDL {sdl}\n"
                f"운영체제: {platform.system()} {platform.release()}\n"
                f"설치 위치: {TOOL_DIR}\n\n"
                "한글 글꼴: 나눔고딕 · 나눔명조 (NAVER, SIL Open Font License 1.1)")
        self.app.push(Dialog(self.app, "GameBook Studio", body, [("닫기", None, True)]))

    # ---------------------------------------------------------------- 삭제
    def delete_dialog(self):
        p = self.current
        if not p:
            return
        proc = self.games.get(p.path)
        if proc is not None and proc.poll() is None:
            self.app.push(Dialog(self.app, "삭제할 수 없습니다",
                                 "이 프로젝트의 게임 창이 열려 있습니다. 게임 창을 닫은 뒤 다시 시도해 주세요."))
            return
        n_scripts = len([f for f in p.script_mtimes() if f.endswith(".gb")])
        n_images = sum(len(fs) for _r, _d, fs in os.walk(p.image_dir)) if os.path.isdir(p.image_dir) else 0
        body = (f"'{p.title}' 프로젝트를 삭제할까요?\n\n"
                f"폴더: {p.path}\n스크립트 {n_scripts}개, 이미지 {n_images}개, 저장 파일이 함께 지워집니다.\n\n"
                "휴지통을 거치지 않고 바로 지워지며, 되돌릴 수 없습니다.")
        self.app.push(Dialog(self.app, "프로젝트 삭제", body, [("취소", None, True), ("삭제", "del")],
                             lambda v: v == "del" and self._delete(p)))

    def _delete(self, p):
        try:
            delete_project(Project(p.path))
        except OSError as e:
            self.app.push(Dialog(self.app, "삭제하지 못했습니다",
                                 f"{e}\n\n다른 프로그램(편집기 등)이 이 폴더의 파일을 쓰고 있으면 지워지지 않을 수 있습니다."))
            self.refresh()
            return
        self.reports.pop(p.path, None)
        self.games.pop(p.path, None)
        idx = next((i for i, q in enumerate(self.projects) if q.path == p.path), 0)
        self.current = None
        self.refresh()
        if self.projects:
            self.current = self.projects[min(idx, len(self.projects) - 1)]
        self.app.toast(f"'{p.title}' 프로젝트를 삭제했습니다", 3000)

    # ---------------------------------------------------------------- 편집기 설정
    def editor_dialog(self):
        cur = editors.current_editor()[0]
        items = [(name, "사용 중" if eid == cur else "", eid, None) for eid, name, _exe in editors.detect()]
        items.append(("운영체제 기본 프로그램 (.gb 파일에 연결된 프로그램)", "사용 중" if cur == "system" else "", "system", None))
        items.append(("직접 지정…", "사용 중" if cur == "custom" else "", "custom", None))

        def done(eid):
            if not eid:
                return
            s = editors.load_settings()
            if eid == "custom":
                def got(v):
                    if v and v["cmd"].strip():
                        s.update(editor="custom", editor_command=v["cmd"].strip())
                        editors.save_settings(s)
                        self.app.toast("편집기를 바꿨습니다")
                self.app.push(InputDialog(self.app, "편집기 명령 직접 지정", [
                    ("cmd", "실행 명령", "{file} 파일, {line} 줄 번호, {project} 프로젝트 폴더로 바뀝니다.",
                     s.get("editor_command", "") or "code -g {file}:{line}")], on_done=got))
                return
            s["editor"] = eid
            editors.save_settings(s)
            self.app.toast("편집기를 바꿨습니다")
        self.app.push(ListDialog(self.app, "스크립트 편집기 고르기", items, done,
                                 body="스크립트를 열 때 쓸 편집기입니다. 줄 번호로 바로 이동하려면 "
                                      "VS Code 를 추천합니다.", rows=min(8, max(4, len(items)))))

    def install_vscode(self):
        self.busy = "VS Code 확장을 설치하는 중…"

        def done(r):
            self.busy = None
            ok, msg = r if isinstance(r, tuple) else (False, str(r))
            self.app.push(Dialog(self.app, "설치 완료" if ok else "설치하지 못했습니다", msg,
                                 [("확인", True, True)] if ok else
                                 [("폴더 열기", "dir"), ("확인", None, True)],
                                 lambda v: v == "dir" and editors.open_path(os.path.join(TOOL_DIR, "editor_support"))))
        self.app.background(editors.install_vscode_extension, done)

    # ================================================================ 그리기
    def draw(self, surf):
        app, t, u = self.app, self.app.t, self.app.u
        W, H = surf.get_size()
        surf.fill(t["desk"])
        m = int(18 * u)
        lw = int(260 * u)
        self.draw_left(surf, pygame.Rect(m, m, lw, H - m * 2))
        right = pygame.Rect(m * 2 + lw, m, W - lw - m * 3, H - m * 2)
        draw_rect(surf, t["page"], right, 6 * u)
        self.draw_right(surf, right)
        if self.busy:
            f = app.font(14, bold=True)
            img = app.fonts.render(f, self.busy, t["accent_ink"])
            r = img.get_rect(center=(W // 2, H // 2)).inflate(int(40 * u), int(24 * u))
            draw_rect(surf, t["dim"], surf.get_rect())
            draw_rect(surf, t["accent"], r, 6 * u)
            surf.blit(img, img.get_rect(center=r.center))
            self.hits.clear()
            self.hit(surf.get_rect(), lambda: None, hover=False)

    def small_button(self, surf, rect, text, fn, font, primary=False, align="center", danger=False):
        app, t, u = self.app, self.app.t, self.app.u
        hov = rect.collidepoint(app.mouse)
        if danger:
            bg = t["error"] if hov else t["choice"]
            ink = t["accent_ink"] if hov else t["error"]
        elif primary:
            bg = t["accent"]
            ink = t["accent_ink"]
        else:
            bg = t["hover"] if hov else t["choice"]
            ink = t["ink"]
        draw_rect(surf, bg, rect, 4 * u)
        if primary and hov:
            draw_rect(surf, (255, 255, 255, 30), rect, 4 * u)
        text = fit_text(font, text, rect.w - int(16 * u))
        if align == "center":
            blit_text(surf, app.fonts, font, text, ink, rect.center, "center")
        else:
            blit_text(surf, app.fonts, font, text, ink, (rect.x + int(14 * u), rect.centery), "midleft")
        self.hit(rect, fn)

    def draw_left(self, surf, R):
        app, t, u = self.app, self.app.t, self.app.u
        hf, lf, f = app.font(17, bold=True), app.font(11), app.font(13.5)
        y = R.y
        blit_text(surf, app.fonts, hf, "GameBook Studio", t["page"], (R.x, y))
        y += hf.get_linesize()
        y += int(14 * u)
        blit_text(surf, app.fonts, lf, "프로젝트", t["status_fg"], (R.x, y))
        y += lf.get_linesize() + int(4 * u)
        bh = int(34 * u)
        list_r = pygame.Rect(R.x, y, R.w, R.bottom - y - bh * 2 - int(16 * u))
        draw_rect(surf, t["page"], list_r, 4 * u)
        self.list_rect = list_r
        rh = int(36 * u)
        self.list_rows = max(1, list_r.h // rh)
        self.list_scroll = max(0, min(self.list_scroll, len(self.projects) - self.list_rows))
        surf.set_clip(list_r)
        for i, p in enumerate(self.projects[self.list_scroll:self.list_scroll + self.list_rows + 1]):
            r = pygame.Rect(list_r.x, list_r.y + i * rh, list_r.w, rh)
            sel = self.current is not None and p.path == self.current.path
            if sel:
                draw_rect(surf, t["accent"], r, 4 * u)
            elif r.collidepoint(app.mouse):
                draw_rect(surf, t["choice"], r, 4 * u)
            blit_text(surf, app.fonts, f, fit_text(f, p.title, r.w - int(24 * u)),
                      t["accent_ink"] if sel else t["ink"], (r.x + int(12 * u), r.centery), "midleft")
            self.hit(r.clip(list_r), lambda p=p: self.select(p))
        if not self.projects:
            for k, line in enumerate(wrap(app.font(12), "프로젝트가 없습니다. 아래 [+ 새 프로젝트]로 시작해 보세요.",
                                          list_r.w - int(24 * u))):
                blit_text(surf, app.fonts, app.font(12), line, t["muted"],
                          (list_r.x + int(12 * u), list_r.y + int(12 * u) + k * app.font(12).get_linesize()))
        surf.set_clip(None)
        bf = app.font(12.5)
        y = list_r.bottom + int(8 * u)
        half = (R.w - int(8 * u)) // 2
        self.small_button(surf, pygame.Rect(R.x, y, half, bh), "＋ 새 프로젝트", self.new_project, bf)
        if self.current:
            self.small_button(surf, pygame.Rect(R.right - half, y, half, bh), "삭제", self.delete_dialog, bf,
                              danger=True)
        y += bh + int(8 * u)
        self.small_button(surf, pygame.Rect(R.x, y, half, bh), "projects 폴더", lambda: self.open_folder(PROJECTS_DIR), bf)
        self.small_button(surf, pygame.Rect(R.right - half, y, half, bh), "새로 고침", self.refresh, bf)

    def draw_right(self, surf, R):
        app, t, u = self.app, self.app.t, self.app.u
        p = self.current
        pad = int(30 * u)
        x, w = R.x + pad, R.w - pad * 2
        if p is None:
            f = app.font(14)
            blit_text(surf, app.fonts, f, "projects 폴더에 프로젝트가 없습니다.", t["muted"], R.center, "center")
            return
        tf, sf, f = app.font(23, bold=True), app.font(11), app.font(12.5)
        y = R.y + int(24 * u)
        blit_text(surf, app.fonts, tf, fit_text(tf, p.title, w), t["ink"], (x, y))
        y += tf.get_linesize()
        blit_text(surf, app.fonts, sf, fit_text(sf, p.path, w), t["muted"], (x, y))
        y += sf.get_linesize() + int(8 * u)
        rep = self.report(p)
        if isinstance(rep, Exception):
            summary, color = f"검사 실패: {rep}", t["error"]
        else:
            summary = rep.summary()
            color = t["error"] if rep.errors else (t["warning"] if rep.warnings else t["muted"])
        r = blit_text(surf, app.fonts, f, fit_text(f, summary, w), color, (x, y))
        self.hit(r, self.lint_dialog)
        y += f.get_linesize() + int(20 * u)

        # 큰 실행 버튼
        bf = app.font(15.5, bold=True)
        bh = int(48 * u)
        bw = min(int(210 * u), w)
        self.small_button(surf, pygame.Rect(x, y, bw, bh), "▶  실행하기", self.run_game, bf, primary=True)
        y += bh + int(10 * u)
        ed_name = editors.current_editor()[1]
        hint = (f"[스크립트 편집하기]로 편집기({ed_name})에서 스크립트를 열고, 게임 창을 띄워 둔 채 저장하면 바로 반영됩니다. "
                "게임 창의 오류 위치를 누르거나 F4 를 누르면 편집기의 그 줄이 열립니다.")
        hf = app.font(11.5)
        for line in wrap(hf, hint, w):
            blit_text(surf, app.fonts, hf, line, t["muted"], (x, y))
            y += hf.get_linesize()
        y += int(18 * u)

        groups = [
            ("작업", [("스크립트 편집하기", self.edit),
                      ("스크립트 검사", self.lint_dialog),
                      ("설정 (game.json)", self.config),
                      ("HTML 로 내보내기", self.export_html),
                      ("배포 파일 만들기", self.build)]),
            ("열기", [("스크립트 폴더", lambda: self.open_folder(p.script_dir)),
                      ("이미지 폴더", lambda: self.open_folder(p.image_dir)),
                      ("프로젝트 폴더", lambda: self.open_folder(p.path)),
                      ("배포 폴더", lambda: self.open_folder(DIST_DIR))]),
            ("도움", [("문법 가이드", self.guide),
                      ("편집기 고르기", self.editor_dialog),
                      ("VS Code 확장 설치", self.install_vscode),
                      ("프로그램 정보", self.about)]),
        ]
        gap = int(14 * u)
        cw = (w - gap * (len(groups) - 1)) // len(groups)
        gf, btf = app.font(11.5, bold=True), app.font(12.5)
        rowh = int(34 * u)
        for gi, (title, items) in enumerate(groups):
            cx = x + gi * (cw + gap)
            yy = y
            blit_text(surf, app.fonts, gf, title, t["muted"], (cx, yy))
            yy += gf.get_linesize() + int(4 * u)
            for text, fn in items:
                if yy + rowh > R.bottom - int(36 * u):
                    break
                self.small_button(surf, pygame.Rect(cx, yy, cw, rowh), text, fn, btf, align="left")
                yy += rowh + int(5 * u)

        # 아래: 편집기 정보
        ff = app.font(11)
        blit_text(surf, app.fonts, ff, fit_text(ff, f"스크립트 편집기: {ed_name}   ·   F5 실행 · Ctrl+E 편집 · Ctrl+N 새 프로젝트",
                                                 w), t["muted"], (x, R.bottom - int(16 * u)), "bottomleft")

    # ================================================================ 입력
    def on_wheel(self, dy, pos):
        if getattr(self, "list_rect", None) and self.list_rect.collidepoint(pos):
            step = int(round(dy * 2)) or (1 if dy > 0 else -1)
            self.list_scroll = max(0, self.list_scroll - step)

    def on_key(self, e):
        k = e.key
        if mod_down(e):
            if k == pygame.K_e:
                return self.edit()
            if k == pygame.K_n:
                return self.new_project()
            if k == pygame.K_r:
                return self.run_game()
            if k == pygame.K_t:
                self.app.theme_name = "night" if self.app.theme_name == "paper" else "paper"
                return
            if k == pygame.K_q:
                return self.on_quit()
            return
        if k == pygame.K_F5:
            return self.run_game()
        if k == pygame.K_F1:
            return self.guide()
        if k == pygame.K_F7:
            return self.lint_dialog()
        if k == pygame.K_F11:
            return self.app.display.toggle_fullscreen()
        if k in (pygame.K_UP, pygame.K_DOWN) and self.projects:
            i = next((n for n, p in enumerate(self.projects) if self.current and p.path == self.current.path), 0)
            i = max(0, min(len(self.projects) - 1, i + (1 if k == pygame.K_DOWN else -1)))
            self.select(self.projects[i])
            rows = getattr(self, "list_rows", 10)
            if i < self.list_scroll:
                self.list_scroll = i
            elif i >= self.list_scroll + rows:
                self.list_scroll = i - rows + 1
        elif k == pygame.K_DELETE:
            self.delete_dialog()
        elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.edit()

    def on_quit(self):
        self.app.running = False


def main(argv=None):
    app = App("GameBook Studio", BASE_SIZE, min_size=(640, 460))
    app.run(Launcher(app))


if __name__ == "__main__":
    main()
