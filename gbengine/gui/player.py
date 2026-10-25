"""게임 창 (pygame, Ren'Py 처럼 직접 그림).

실행:  python -m gbengine run <프로젝트 폴더> [--dev] [--start 단락]

--dev(개발 모드): 스크립트를 저장하면 자동으로 다시 읽고, 오류 위치를 누르거나 F4 를 누르면
편집기의 그 줄이 열립니다. F2 변수, F5 다시 읽기, F6 단락으로 이동, F7 검사, F1 가이드.
"""

from __future__ import annotations

import os
import time

import pygame

from .. import __version__
from ..editors import open_in_editor, open_url
from ..lint import lint_project
from ..project import Project
from ..runtime import SAVE_SLOTS, Engine, RuntimeScriptError, Session, read_save, write_save
from ..script import ScriptError
from .base import (App, Dialog, ImageCache, ListDialog, Screen, blit_text, draw_rect, fit_text, mod_down,
                   wrap)

GUIDE_HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "docs", "script_guide.html")


def error_items(errors):
    out = []
    for e in errors:
        if isinstance(e, (ScriptError, RuntimeScriptError)):
            loc = e.loc if getattr(e, "loc", None) and getattr(e.loc, "line", 0) else None
            out.append((loc, e.message))
        else:
            out.append((None, str(e)))
    return sorted(out, key=lambda x: (0, x[0].file, x[0].line) if x[0] else (1, "", 0))


def open_guide():
    """문법 가이드를 브라우저로 엽니다. 가이드가 없으면(배포판) False."""
    src = os.path.join(os.path.dirname(GUIDE_HTML), "script_guide.md")
    try:
        if not os.path.exists(GUIDE_HTML) or (os.path.exists(src) and
                                               os.path.getmtime(src) > os.path.getmtime(GUIDE_HTML)):
            from ..markdown_lite import to_html
            with open(src, encoding="utf-8") as f:
                html = to_html(f.read(), "게임북 스크립트 가이드")
            with open(GUIDE_HTML, "w", encoding="utf-8") as f:
                f.write(html)
    except OSError:
        return False
    open_url(GUIDE_HTML)
    return True


class Player(Screen):
    def __init__(self, app, project: Project, dev=False, start_at=None):
        super().__init__(app)
        self.project = project
        self.dev = dev
        self.images = ImageCache()
        self.story = None
        self.engine = None
        self.session = None
        self.mode = "title"            # title | play | error
        self.errors = []
        self.error_title = ""
        self.font_delta = 0
        self.scroll = 0
        self.max_scroll = 0
        self.show_vars = False
        self.mtimes = None
        self.latest = None
        self.reload(initial=True)
        if start_at:
            self.start_at(start_at)

    # ================================================================ 읽기
    @property
    def cfg(self):
        return self.project.config

    def signature(self):
        sig = dict(self.project.script_mtimes())
        for p in (os.path.join(self.project.path, "game.json"),):
            try:
                sig[p] = os.path.getmtime(p)
            except OSError:
                pass
        return sig

    def reload(self, initial=False):
        self.project = Project(self.project.path)
        self.story = self.project.load_story()
        self.mtimes = self.signature()
        self.images.clear()
        self.app.base_size = tuple(int(x) for x in (self.cfg.get("window") or [1024, 760])[:2])
        if not getattr(self.app, "theme_by_user", False):
            self.app.theme_name = "night" if self.cfg.get("theme") == "night" else "paper"
        self.app.display.set_title(self.project.title + ("  [개발 모드]" if self.dev else ""))
        errors = list(self.story.errors)
        start = self.cfg.get("start", "start")
        if not errors and start not in self.story.labels:
            errors = [f"시작 단락 '{start}' 이(가) 없습니다. (game.json 의 \"start\" 확인)"]
        if self.project.config_error:
            errors.insert(0, self.project.config_error)
        if errors:
            self.engine = None
            self.show_error("스크립트에 오류가 있습니다", errors)
            return
        self.engine = Engine(self.story, start, bool(self.cfg.get("show_locked_choices")))
        if self.session is not None and self.mode in ("play", "error") and self.session.entry:
            try:
                self.session.reload(self.engine)
                self.mode = "play"
            except RuntimeScriptError as e:
                self.show_error("실행 중 오류", [e])
                return
        elif self.mode == "error" or initial:
            self.mode = "title"
        self.latest = self.latest_slot()
        if not initial:
            self.app.toast("스크립트를 다시 읽었습니다")
        self.app.invalidate()

    def tick(self):
        if self.dev and self.signature() != self.mtimes:
            self.reload()

    def on_focus(self):
        self.latest = self.latest_slot()

    # ================================================================ 진행
    def new_game(self):
        if self.engine is None:
            return
        self.session = Session(self.engine)
        try:
            self.session.start()
            self.mode = "play"
        except RuntimeScriptError as e:
            return self.show_error("실행 중 오류", [e])
        self.scroll = 0

    def start_at(self, label):
        if self.engine is None:
            return
        if label not in self.story.labels:
            self.app.toast(f"단락 '{label}' 이(가) 없습니다")
            return
        self.session = Session(self.engine)
        try:
            self.session.start_at(label)
            self.mode = "play"
        except RuntimeScriptError as e:
            return self.show_error("실행 중 오류", [e])
        self.scroll = 0
        self.app.toast(f"'{label}' 단락부터 시작합니다")

    def show_title(self):
        if self.engine is not None:
            self.mode = "title"
            self.latest = self.latest_slot()

    def end_actions(self):
        acts = [("처음부터 다시 하기", self.new_game), ("타이틀로 돌아가기", self.show_title)]
        if self.session and self.session.can_go_back():
            acts.insert(0, ("뒤로 가기", self.back))
        return acts

    def pick(self, i):
        if self.mode != "play" or not self.session:
            return
        page = self.session.page
        if page.is_ending or page.dead_end:
            acts = self.end_actions()
            if 0 <= i < len(acts):
                acts[i][1]()
            return
        if not (0 <= i < len(page.choices)) or not page.choices[i].enabled:
            return
        try:
            self.session.choose(i)
        except RuntimeScriptError as e:
            return self.show_error("실행 중 오류", [e])
        self.scroll = 0

    def back(self):
        if self.mode == "error" and self.session and self.session.can_go_back():
            self.mode = "play"
        if self.mode == "play" and self.session and self.session.can_go_back():
            try:
                self.session.back()
            except RuntimeScriptError as e:
                return self.show_error("실행 중 오류", [e])
            self.scroll = 0

    def show_error(self, title, errors):
        self.mode = "error"
        self.error_title = title
        self.errors = error_items(errors)
        self.app.invalidate()

    # ================================================================ 저장
    def latest_slot(self):
        best, best_time = None, ""
        for slot in range(1, SAVE_SLOTS + 1):
            d = read_save(self.project.save_dir, slot)
            if d and d.get("time", "") > best_time:
                best, best_time = slot, d.get("time", "")
        return best

    def load_slot(self, slot):
        data = read_save(self.project.save_dir, slot)
        if not data or self.engine is None:
            return
        s = Session(self.engine)
        try:
            s.load_json(data["session"])
        except (RuntimeScriptError, KeyError, TypeError, ValueError) as e:
            self.app.push(Dialog(self.app, "불러오기 실패",
                                 f"저장 파일을 불러올 수 없습니다. 스크립트가 바뀌어 단락이 없어졌을 수 있습니다.\n\n{e}"))
            return
        self.session = s
        self.mode = "play"
        self.scroll = 0
        self.app.toast(f"슬롯 {slot}에서 불러왔습니다")

    def slot_dialog(self, kind):
        if self.engine is None:
            return
        if kind == "save" and (self.mode != "play" or not self.session):
            self.app.toast("게임 중에만 저장할 수 있습니다")
            return
        items = []
        for slot in range(1, SAVE_SLOTS + 1):
            d = read_save(self.project.save_dir, slot)
            text = f"{slot}.  [{d.get('label', '')}] {d.get('excerpt', '')}" if d else f"{slot}.  — 비어 있음 —"
            enabled = bool(d) or kind == "save"
            items.append((text, d.get("time", "") if d else "", slot if enabled else None,
                          None if enabled else self.app.t["locked"]))

        def done(slot):
            if not slot:
                return
            if kind == "save":
                write_save(self.project.save_dir, slot, self.session)
                self.latest = slot
                self.app.toast(f"슬롯 {slot}에 저장했습니다")
            else:
                self.load_slot(slot)
        self.app.push(ListDialog(self.app, "저장할 칸을 고르세요" if kind == "save" else "불러올 칸을 고르세요",
                                 items, done, rows=SAVE_SLOTS))

    # ================================================================ 개발 도구
    def open_source(self, file, line):
        name = open_in_editor(file, line, self.project.path)
        self.app.toast(f"{name}(으)로 열었습니다")

    def open_in_editor(self):
        if self.mode == "error":
            loc = next((l for l, _m in self.errors if l), None)
            if loc:
                self.open_source(loc.file, loc.line)
        elif self.mode == "play" and self.session and self.story:
            label = self.story.labels.get(self.session.page.label)
            if label:
                self.open_source(label.loc.file, label.loc.line)

    def jump_dialog(self):
        if self.engine is None:
            return
        items = [(n, str(l.loc), n, None) for n, l in self.story.labels.items()]

        def done(name):
            if not name:
                return
            if self.session is None:
                self.session = Session(self.engine)
            try:
                self.session.jump(name)
                self.mode = "play"
                self.scroll = 0
            except RuntimeScriptError as e:
                self.show_error("실행 중 오류", [e])
        self.app.push(ListDialog(self.app, "단락으로 이동 (변수는 유지됩니다)", items, done, filter=True,
                                 placeholder="단락 이름"))

    def lint_dialog(self):
        report = lint_project(self.project)
        t = self.app.t
        color = {"오류": t["error"], "경고": t["warning"], "참고": t["info"]}
        items = [(f"[{i.level}] {i.message}", str(i.loc) if i.loc else "", (i.loc.file, i.loc.line) if i.loc and i.loc.line else None,
                  color[i.level]) for i in report.issues] or [("문제가 없습니다.", "", None, None)]
        self.app.push(ListDialog(self.app, "검사 결과", items,
                                 lambda v: v and self.open_source(*v), body=report.summary(), rows=10))

    # ================================================================ 그리기
    def fs(self, delta=0):
        """본문 글자 크기 (화소)."""
        return (int(self.cfg.get("font_size", 15)) + self.font_delta + delta) * 1.3

    def body_kind(self):
        f = str(self.cfg.get("font", "") or "")
        if f in ("serif", "명조"):
            return "serif"
        if f in ("", "sans", "고딕"):
            return "sans"
        p = f if os.path.isabs(f) else os.path.join(self.project.path, f)
        return p if os.path.isfile(p) else "serif"

    def draw(self, surf):
        app, t, u = self.app, self.app.t, self.app.u
        W, H = surf.get_size()
        surf.fill(t["desk"])
        status_h = int(26 * u)
        margin = int(20 * u)
        pw = min(int(900 * u), W - int(32 * u))
        self.page = pygame.Rect((W - pw) // 2, margin, pw, H - status_h - margin * 2)
        draw_rect(surf, t["page"], self.page)
        pygame.draw.rect(surf, t["rule"], self.page, max(1, int(u)))
        if self.mode == "title":
            self.draw_title(surf)
        elif self.mode == "error":
            self.draw_error(surf)
        else:
            self.draw_play(surf)
        self.draw_status(surf, pygame.Rect(0, H - status_h, W, status_h))
        if self.show_vars:
            self.draw_vars(surf)

    def button(self, surf, rect, text, fn, font, enabled=True, center=False, num=None):
        app, t, u = self.app, self.app.t, self.app.u
        hov = enabled and rect.collidepoint(app.mouse)
        draw_rect(surf, t["hover"] if hov else t["choice"], rect, 3 * u)
        x = rect.x + int(14 * u)
        if num:
            blit_text(surf, app.fonts, font, num, t["muted"], (x, rect.y + int(9 * u)))
            x += font.size("9. ")[0] + int(4 * u)
        lines = wrap(font, text, rect.right - int(14 * u) - x)
        y = rect.y + int(9 * u)
        for line in lines:
            if center:
                blit_text(surf, app.fonts, font, line, t["ink"] if enabled else t["locked"], (rect.centerx, y), "midtop")
            else:
                blit_text(surf, app.fonts, font, line, t["ink"] if enabled else t["locked"], (x, y))
            y += font.get_linesize()
        if enabled:
            self.hit(rect, fn)

    def button_height(self, font, text, width, num=False):
        u = self.app.u
        inner = width - int(28 * u) - (font.size("9. ")[0] + int(4 * u) if num else 0)
        return len(wrap(font, text, inner)) * font.get_linesize() + int(18 * u)

    def image(self, rel, max_w, max_h):
        if not rel:
            return None
        return self.images.get(self.project.image_path(rel), max_w, max_h, max_scale=self.app.u)

    def draw_title(self, surf):
        app, t, u = self.app, self.app.t, self.app.u
        P = self.page
        col = pygame.Rect(0, 0, min(P.w - int(80 * u), int(700 * u)), 0)
        kind = self.body_kind()
        title_f = app.fonts.get(kind, self.fs(15) * u / 1.0 * 1, bold=True)
        img = self.image(self.cfg.get("title_image"), col.w, int(P.h * 0.38))
        title_lines = wrap(title_f, self.project.title, col.w)
        author_f = app.fonts.get(kind, self.fs() * u)
        menu_f = app.fonts.get("sans", self.fs() * u)
        items = [("새로 시작하기", self.new_game)]
        if self.latest:
            items.append(("이어하기", lambda s=self.latest: self.load_slot(s)))
        items += [("불러오기", lambda: self.slot_dialog("load")), ("끝내기", self.on_quit)]
        bh = menu_f.get_linesize() + int(18 * u)
        total = (img.get_height() + int(18 * u) if img else 0) + len(title_lines) * title_f.get_linesize() \
            + (author_f.get_linesize() + int(6 * u) if self.cfg.get("author") else 0) + int(44 * u) \
            + len(items) * (bh + int(8 * u))
        y = P.y + max(int(20 * u), (P.h - total) // 2)
        if img:
            surf.blit(img, img.get_rect(midtop=(P.centerx, y)))
            y += img.get_height() + int(18 * u)
        for line in title_lines:
            blit_text(surf, app.fonts, title_f, line, t["ink"], (P.centerx, y), "midtop")
            y += title_f.get_linesize()
        if self.cfg.get("author"):
            y += int(6 * u)
            blit_text(surf, app.fonts, author_f, self.cfg["author"], t["muted"], (P.centerx, y), "midtop")
            y += author_f.get_linesize()
        y += int(22 * u)
        pygame.draw.line(surf, t["rule"], (P.centerx - int(60 * u), y), (P.centerx + int(60 * u), y), max(1, int(u)))
        y += int(22 * u)
        bw = min(int(300 * u), col.w)
        for i, (text, fn) in enumerate(items):
            r = pygame.Rect(P.centerx - bw // 2, y, bw, bh)
            self.button(surf, r, text, fn, menu_f, center=True)
            y += bh + int(8 * u)
        self.title_items = items

    def draw_play(self, surf):
        app, t, u = self.app, self.app.t, self.app.u
        P = self.page
        page = self.session.page
        pad = int(44 * u)
        tw = P.w - pad * 2
        kind = self.body_kind()
        body = app.fonts.get(kind, self.fs() * u)
        # 선택지 (아래에 고정)
        if page.is_ending or page.dead_end:
            entries = [(text, True) for text, _ in self.end_actions()]
        else:
            entries = [(c.text, c.enabled) for c in page.choices]
        heights = [self.button_height(body, text, tw, num=True) for text, _ in entries]
        gap = int(6 * u)
        choices_h = sum(heights) + gap * max(0, len(heights) - 1)
        bottom = P.bottom - int(26 * u)
        cy = bottom - choices_h
        rule_y = cy - int(14 * u)
        pygame.draw.line(surf, t["rule"], (P.x + pad, rule_y), (P.right - pad, rule_y), max(1, int(u)))
        for i, ((text, enabled), h) in enumerate(zip(entries, heights)):
            r = pygame.Rect(P.x + pad, cy, tw, h)
            self.button(surf, r, text, (lambda i=i: self.pick(i)), body, enabled=enabled,
                        num=f"{i + 1}." if i < 9 else None)
            cy += h + gap
        # 본문 (위, 넘치면 굴리기)
        area = pygame.Rect(P.x, P.y + int(30 * u), P.w, rule_y - int(12 * u) - (P.y + int(30 * u)))
        self.text_area = area
        blocks = []          # (종류, 값, 높이)
        img = self.image(page.image, tw, int(P.h * 0.42)) if page.image else None
        if page.image and img is None:
            small = app.font(12)
            blocks.append(("err", f"[이미지를 열 수 없음: {page.image}]", small.get_linesize() + int(10 * u)))
        elif img:
            blocks.append(("img", img, img.get_height() + int(18 * u)))
        ls = int(body.get_linesize() * 1.25)
        para_gap = int(body.get_linesize() * 0.6)
        for para in page.paragraphs:
            lines = wrap(body, para, tw)
            blocks.append(("para", lines, len(lines) * ls + para_gap))
        if page.is_ending:
            bf = app.fonts.get(kind, self.fs(3) * u, bold=True)
            blocks.append(("ending", (bf, f"— {page.ending} —" if page.ending else "— 끝 —"), bf.get_linesize() + para_gap * 2))
        elif page.dead_end:
            nf = app.fonts.get("sans", self.fs(-2) * u)
            msg = ("※ 막다른 단락입니다: 보여 줄 선택지가 없습니다. (개발 모드에서만 보이는 안내)"
                   if self.dev else "이야기가 여기서 멈췄습니다.")
            lines = wrap(nf, msg, tw)
            blocks.append(("note", (nf, lines), len(lines) * nf.get_linesize() + para_gap))
        content_h = sum(b[2] for b in blocks)
        self.max_scroll = max(0, content_h - area.h)
        self.scroll = max(0, min(self.scroll, self.max_scroll))
        surf.set_clip(area)
        y = area.y - self.scroll
        for kind_, val, h in blocks:
            if kind_ == "img":
                surf.blit(val, val.get_rect(midtop=(P.centerx, y)))
            elif kind_ == "err":
                blit_text(surf, app.fonts, app.font(12), val, t["error"], (P.x + pad, y))
            elif kind_ == "para":
                yy = y
                for line in val:
                    blit_text(surf, app.fonts, body, line, t["ink"], (P.x + pad, yy))
                    yy += ls
            elif kind_ == "ending":
                blit_text(surf, app.fonts, val[0], val[1], t["accent"], (P.centerx, y + para_gap), "midtop")
            elif kind_ == "note":
                yy = y
                for line in val[1]:
                    blit_text(surf, app.fonts, val[0], line, t["muted"], (P.x + pad, yy))
                    yy += val[0].get_linesize()
            y += h
        surf.set_clip(None)
        if self.max_scroll:
            track = pygame.Rect(P.right - int(16 * u), area.y, int(5 * u), area.h)
            draw_rect(surf, t["rule"], track, 3 * u)
            th = max(int(30 * u), area.h * area.h // content_h)
            ty = area.y + (area.h - th) * self.scroll // self.max_scroll
            draw_rect(surf, t["muted"], pygame.Rect(track.x, ty, track.w, th), 3 * u)

    def draw_error(self, surf):
        app, t, u = self.app, self.app.t, self.app.u
        P = self.page
        pad = int(44 * u)
        x, y, w = P.x + pad, P.y + int(32 * u), P.w - pad * 2
        hf, tf, f = app.font(20, bold=True), app.font(12.5), app.font(14)
        blit_text(surf, app.fonts, hf, self.error_title, t["error"], (x, y))
        y += hf.get_linesize() + int(4 * u)
        tip = ("위치를 누르면 편집기에서 그 줄이 열립니다. 고쳐서 저장하면 자동으로 다시 읽습니다." if self.dev
               else "스크립트를 고친 뒤 다시 실행해 주세요.")
        blit_text(surf, app.fonts, tf, tip, t["muted"], (x, y))
        y += tf.get_linesize() + int(14 * u)
        box_bottom = P.bottom - int(90 * u)
        box = pygame.Rect(x, y, w, box_bottom - y)
        pygame.draw.rect(surf, t["rule"], box, max(1, int(u)))
        surf.set_clip(box.inflate(-int(4 * u), -int(4 * u)))
        yy = y + int(12 * u)
        for loc, msg in self.errors:
            xx = x + int(14 * u)
            if loc:
                r = blit_text(surf, app.fonts, f, str(loc), t["error"], (xx, yy))
                pygame.draw.line(surf, t["error"], (r.left, r.bottom - 1), (r.right, r.bottom - 1), max(1, int(u)))
                if self.dev:
                    self.hit(r, lambda l=loc: self.open_source(l.file, l.line))
                xx = r.right + int(10 * u)
            lines = wrap(f, msg, box.right - int(14 * u) - xx)
            for line in lines:
                blit_text(surf, app.fonts, f, line, t["ink"], (xx, yy))
                yy += f.get_linesize()
            yy += int(6 * u)
        surf.set_clip(None)
        bx, by = x, P.bottom - int(66 * u)
        bf = app.font(14)
        btns = []
        if self.dev and any(l for l, _m in self.errors):
            btns.append(("편집기에서 열기 (F4)", self.open_in_editor))
        if self.dev:
            btns.append(("다시 읽기 (F5)", self.reload))
        if self.session and self.session.can_go_back():
            btns.append(("뒤로 가기", self.back))
        for text, fn in btns:
            bw = bf.size(text)[0] + int(28 * u)
            r = pygame.Rect(bx, by, bw, bf.get_linesize() + int(16 * u))
            self.button(surf, r, text, fn, bf)
            bx += bw + int(8 * u)

    def draw_status(self, surf, rect):
        app, t, u = self.app, self.app.t, self.app.u
        draw_rect(surf, t["status_bg"], rect)
        if self.dev and self.mode == "play" and self.session and self.session.page:
            page = self.session.page
            label = self.story.labels.get(page.label)
            passed = " → ".join(page.labels_passed) if len(page.labels_passed) > 1 else page.label
            text = f"단락: {passed}{f'  ({label.loc})' if label else ''}      F4 편집기 · F5 다시 읽기 · F6 이동 · F2 변수 · F7 검사"
        elif self.dev:
            text = f"개발 모드 · GameBook Studio {__version__} · 스크립트를 저장하면 자동으로 반영됩니다 · F1 가이드"
        else:
            text = "1~9 선택 · Backspace 뒤로 · Ctrl+S 저장 · Ctrl+O 불러오기 · F11 전체 화면"
        f = app.font(11.5)
        blit_text(surf, app.fonts, f, fit_text(f, text, rect.w - int(28 * u)), t["status_fg"],
                  (rect.x + int(14 * u), rect.centery), "midleft")

    def draw_vars(self, surf):
        app, t, u = self.app, self.app.t, self.app.u
        W, H = surf.get_size()
        hf, f = app.font(12, bold=True), app.font(13)
        s = self.session
        rows = [("h", "변수 (현재 페이지를 읽은 뒤)   F2 닫기")]
        if not s or not s.after:
            rows.append(("m", "게임이 시작되지 않았습니다."))
        else:
            for k, v in sorted(s.after.variables.items()):
                rows.append(("v", f"{k} = {v!r}"))
            if not s.after.variables:
                rows.append(("m", "(없음)"))
            rows.append(("h", "방문한 단락 (횟수)"))
            for k, v in s.after.visited.items():
                rows.append(("v", f"{k}  ×{v}"))
        content = sum((hf if k == "h" else f).get_linesize() + int(2 * u) + (int(8 * u) if k == "h" else 0)
                      for k, _ in rows) + int(24 * u)
        r = pygame.Rect(W - int(330 * u), int(12 * u), int(318 * u), min(content, H - int(52 * u)))
        draw_rect(surf, t["paper"], r, 8 * u)
        pygame.draw.rect(surf, t["border"], r, max(1, int(u)), border_radius=int(8 * u))
        x, y = r.x + int(14 * u), r.y + int(12 * u)
        surf.set_clip(r.inflate(-int(6 * u), -int(6 * u)))
        for kind, text in rows:
            ff = hf if kind == "h" else f
            if kind == "h" and y > r.y + int(20 * u):
                y += int(8 * u)
            blit_text(surf, app.fonts, ff, fit_text(ff, text, r.w - int(28 * u)),
                      t["muted"] if kind != "v" else t["ink"], (x, y))
            y += ff.get_linesize() + int(2 * u)
        surf.set_clip(None)

    # ================================================================ 입력
    def on_quit(self):
        self.app.running = False

    def on_wheel(self, dy, pos):
        if self.mode == "play":
            self.scroll = max(0, min(self.max_scroll, self.scroll - int(dy * 60 * self.app.u)))

    def on_key(self, e):
        k = e.key
        if mod_down(e):
            if k == pygame.K_s:
                return self.slot_dialog("save")
            if k == pygame.K_o:
                return self.slot_dialog("load")
            if k == pygame.K_n:
                return self.new_game()
            if k == pygame.K_t:
                self.app.theme_by_user = True
                self.app.theme_name = "night" if self.app.theme_name == "paper" else "paper"
                return
            if k in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                self.font_delta = min(25, self.font_delta + 1)
                return
            if k in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self.font_delta = max(-6, self.font_delta - 1)
                return
            if k == pygame.K_q:
                return self.on_quit()
            return
        if k == pygame.K_BACKSPACE:
            return self.back()
        if k == pygame.K_F11 or (k == pygame.K_RETURN and e.mod & pygame.KMOD_ALT):
            self.app.display.toggle_fullscreen()
            return
        if k == pygame.K_F1 and self.dev:
            if not open_guide():
                self.app.toast("문법 가이드 파일을 찾지 못했습니다")
            return
        if self.dev:
            if k == pygame.K_F5:
                return self.reload()
            if k == pygame.K_F6:
                return self.jump_dialog()
            if k == pygame.K_F2:
                self.show_vars = not self.show_vars
                return
            if k == pygame.K_F7:
                return self.lint_dialog()
            if k == pygame.K_F4:
                return self.open_in_editor()
        if pygame.K_1 <= k <= pygame.K_9 or pygame.K_KP1 <= k <= pygame.K_KP9:
            i = (k - pygame.K_1) if k <= pygame.K_9 else (k - pygame.K_KP1)
            if self.mode == "title":
                items = getattr(self, "title_items", [])
                if i < len(items):
                    items[i][1]()
            else:
                self.pick(i)
            return
        if k in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_KP_ENTER) and self.mode == "play" and self.session:
            p = self.session.page
            if not p.is_ending and not p.dead_end and len(p.choices) == 1 and p.choices[0].enabled:
                self.pick(0)
            return
        step = int(60 * self.app.u)
        if k == pygame.K_DOWN:
            self.scroll = min(self.max_scroll, self.scroll + step)
        elif k == pygame.K_UP:
            self.scroll = max(0, self.scroll - step)
        elif k == pygame.K_PAGEDOWN:
            self.scroll = min(self.max_scroll, self.scroll + self.text_area.h - step)
        elif k == pygame.K_PAGEUP:
            self.scroll = max(0, self.scroll - self.text_area.h + step)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="게임북 플레이어")
    ap.add_argument("project", help="프로젝트 폴더")
    ap.add_argument("--dev", action="store_true", help="개발 모드 (자동 다시 읽기, 개발용 키)")
    ap.add_argument("--start", default=None, help="이 단락부터 시작 (개발용)")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.project):
        raise SystemExit(f"프로젝트 폴더가 없습니다: {args.project}")
    project = Project(args.project)
    size = tuple(int(x) for x in (project.config.get("window") or [1024, 760])[:2])
    app = App(project.title, size, min_size=(480, 400))
    player = Player(app, project, dev=args.dev, start_at=args.start)
    app.run(player)


if __name__ == "__main__":
    main()
