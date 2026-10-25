"""pygame 화면 기반 (Ren'Py 처럼 창 안을 모두 직접 그림).

- 한글 글꼴(나눔고딕·나눔명조)을 함께 넣어 두고 직접 그리므로 운영체제·글꼴 설정과 상관없이 똑같이 보입니다.
- 고해상도(Retina) 화면에서는 실제 화소 크기로 그려서 글자가 선명합니다.
- 모든 크기는 '배율 u' 를 곱해서 정합니다. 창을 키우면 글자·여백·그림이 함께 커집니다.

화면(Screen)은 매번 전체를 다시 그리는 단순한 방식입니다. 그리면서 누를 수 있는 영역을
self.hits 에 등록하고, 마우스 이벤트가 오면 그 목록에서 찾습니다.
"""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame  # noqa: E402

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONT_FILES = {
    ("sans", False): "NanumGothic-Regular.ttf",
    ("sans", True): "NanumGothic-Bold.ttf",
    ("serif", False): "NanumMyeongjo-Regular.ttf",
    ("serif", True): "NanumMyeongjo-Bold.ttf",
}

THEMES = {
    "paper": {
        "desk": (42, 36, 32), "page": (244, 236, 218), "ink": (47, 39, 33), "muted": (139, 123, 103),
        "accent": (142, 59, 40), "accent_ink": (255, 248, 238), "rule": (220, 205, 174),
        "choice": (235, 223, 198), "hover": (223, 204, 166), "locked": (179, 165, 142),
        "status_bg": (31, 26, 23), "status_fg": (168, 153, 138), "error": (163, 50, 31),
        "warning": (154, 106, 18), "info": (79, 109, 134), "paper": (251, 248, 241), "dim": (20, 16, 14, 140),
        "field": (255, 253, 248), "border": (214, 201, 174),
    },
    "night": {
        "desk": (15, 17, 20), "page": (27, 30, 35), "ink": (228, 223, 211), "muted": (138, 143, 152),
        "accent": (219, 163, 90), "accent_ink": (27, 30, 35), "rule": (45, 50, 57),
        "choice": (36, 41, 49), "hover": (47, 54, 64), "locked": (89, 96, 107),
        "status_bg": (11, 12, 14), "status_fg": (125, 130, 139), "error": (240, 122, 98),
        "warning": (227, 178, 82), "info": (143, 176, 207), "paper": (34, 38, 44), "dim": (0, 0, 0, 150),
        "field": (22, 25, 29), "border": (58, 64, 73),
    },
}

MOD_KEYS = (pygame.KMOD_CTRL | pygame.KMOD_META)


def mod_down(event) -> bool:
    return bool(getattr(event, "mod", 0) & MOD_KEYS)


# ====================================================================== 창

class Display:
    """창 하나. 고해상도 화면이면 실제 화소 크기의 그림판(surface)을 줍니다."""

    def __init__(self, title, size, min_size=(480, 360)):
        self.title = title
        self.fullscreen = False
        self.window = None
        self.renderer = None
        self.screen = None
        self.min_size = min_size
        try:
            from pygame._sdl2 import video
            self.video = video
            self.window = video.Window(title, size=size, resizable=True, allow_high_dpi=True)
            self.renderer = video.Renderer(self.window, accelerated=-1, vsync=False)
            try:
                self.window.minimum_size = min_size
            except Exception:
                pass
        except Exception:
            self.window = None
            self.screen = pygame.display.set_mode(size, pygame.RESIZABLE)
            pygame.display.set_caption(title)
        self.surface = None
        self.refresh_size()

    def refresh_size(self):
        if self.window is not None:
            pw, ph = self.renderer.get_viewport().size
            ww, wh = self.window.size
            if pw <= 0 or ph <= 0:
                pw, ph = ww, wh
            self.ratio = pw / max(1, ww)
            self.size = (pw, ph)
            self.point_size = (ww, wh)
            if self.surface is None or self.surface.get_size() != self.size:
                self.surface = pygame.Surface(self.size)
        else:
            self.screen = pygame.display.get_surface()
            self.ratio = 1.0
            self.size = self.screen.get_size()
            self.point_size = self.size
            self.surface = self.screen

    def present(self):
        if self.window is not None:
            tex = self.video.Texture.from_surface(self.renderer, self.surface)
            self.renderer.clear()
            tex.draw()
            self.renderer.present()
        else:
            pygame.display.flip()

    def to_pixels(self, pos):
        return (int(pos[0] * self.ratio), int(pos[1] * self.ratio))

    def to_points(self, rect):
        r = self.ratio
        return pygame.Rect(int(rect.x / r), int(rect.y / r), max(1, int(rect.w / r)), max(1, int(rect.h / r)))

    def set_title(self, title):
        self.title = title
        if self.window is not None:
            self.window.title = title
        else:
            pygame.display.set_caption(title)

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        if self.window is not None:
            if self.fullscreen:
                self.window.set_fullscreen(desktop=True)
            else:
                self.window.set_windowed()
        else:
            pygame.display.toggle_fullscreen()
        self.refresh_size()

    def resize(self, size):
        if self.window is not None:
            self.window.size = size
        else:
            pygame.display.set_mode(size, pygame.RESIZABLE)
        self.refresh_size()


# ====================================================================== 글꼴과 글

class Fonts:
    def __init__(self):
        self.cache = {}
        self.text_cache = {}
        self.custom = {}

    def path(self, kind, bold=False):
        if kind in ("sans", "serif"):
            return os.path.join(FONT_DIR, FONT_FILES[(kind, bold)])
        return kind if os.path.isfile(kind) else os.path.join(FONT_DIR, FONT_FILES[("serif", bold)])

    def get(self, kind, size, bold=False):
        size = max(6, int(round(size)))
        key = (kind, size, bold)
        f = self.cache.get(key)
        if f is None:
            try:
                f = pygame.font.Font(self.path(kind, bold), size)
            except (OSError, pygame.error):
                f = pygame.font.Font(self.path("sans", bold), size)
            self.cache[key] = f
        return f

    def render(self, font, text, color):
        key = (id(font), text, tuple(color))
        s = self.text_cache.get(key)
        if s is None:
            if len(self.text_cache) > 3000:
                self.text_cache.clear()
            s = font.render(text, True, color) if text else pygame.Surface((1, font.get_height()), pygame.SRCALPHA)
            self.text_cache[key] = s
        return s


def wrap(font, text, width):
    """글을 width 안에 들어가게 줄로 나눕니다. 띄어쓰기에서 끊고, 너무 긴 낱말은 글자 단위로 끊습니다."""
    lines = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        words = []
        cur = ""
        for ch in para:          # 공백을 앞 낱말에 붙여서 나눔
            cur += ch
            if ch == " ":
                words.append(cur)
                cur = ""
        if cur:
            words.append(cur)
        line = ""
        for w in words:
            if font.size(line + w.rstrip())[0] <= width:
                line += w
                continue
            if line.strip():
                lines.append(line.rstrip())
                line = ""
            while font.size(w.rstrip())[0] > width and len(w) > 1:
                cut = len(w)
                while cut > 1 and font.size(w[:cut])[0] > width:
                    cut -= 1
                lines.append(w[:cut])
                w = w[cut:]
            line = w
        lines.append(line.rstrip())
    return lines


# ====================================================================== 그리기 도우미

def draw_rect(surf, color, rect, radius=0):
    if len(color) == 4:
        layer = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(layer, color, layer.get_rect(), border_radius=int(radius))
        surf.blit(layer, rect.topleft)
    else:
        pygame.draw.rect(surf, color, rect, border_radius=int(radius))


def blit_text(surf, fonts, font, text, color, pos, anchor="topleft"):
    img = fonts.render(font, text, color)
    r = img.get_rect(**{anchor: pos})
    surf.blit(img, r)
    return r


def fit_text(font, text, width):
    """width 를 넘으면 … 으로 줄입니다."""
    if font.size(text)[0] <= width:
        return text
    while text and font.size(text + "…")[0] > width:
        text = text[:-1]
    return text + "…"


def load_image(path):
    try:
        img = pygame.image.load(path)
        return img.convert_alpha() if pygame.display.get_init() and pygame.display.get_surface() else img
    except (pygame.error, FileNotFoundError, OSError):
        return None


class ImageCache:
    def __init__(self):
        self.src = {}
        self.scaled = {}

    def clear(self):
        self.src.clear()
        self.scaled.clear()

    def get(self, path, max_w, max_h, max_scale=1.0):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        s = self.src.get(path)
        if s is None or s[0] != mtime:
            img = load_image(path)
            if img is None:
                return None
            s = (mtime, img)
            self.src[path] = s
            self.scaled = {k: v for k, v in self.scaled.items() if k[0] != path}
        key = (path, int(max_w), int(max_h), round(max_scale, 3))
        out = self.scaled.get(key)
        if out is None:
            img = s[1]
            w, h = img.get_size()
            k = min(max_w / w, max_h / h, max_scale)
            size = (max(1, int(w * k)), max(1, int(h * k)))
            out = pygame.transform.smoothscale(img, size) if size != (w, h) else img
            self.scaled[key] = out
        return out


# ====================================================================== 글 입력 (한글 조합 포함)

class TextInput:
    def __init__(self, value="", placeholder=""):
        self.value = value
        self.cursor = len(value)
        self.composing = ""        # 한글 조합 중인 글자
        self.placeholder = placeholder
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.changed = False

    def handle(self, e) -> bool:
        """처리했으면 True."""
        if e.type == pygame.TEXTEDITING:
            self.composing = e.text
            return True
        if e.type == pygame.TEXTINPUT:
            self.composing = ""
            self.value = self.value[:self.cursor] + e.text + self.value[self.cursor:]
            self.cursor += len(e.text)
            self.changed = True
            return True
        if e.type == pygame.KEYDOWN:
            if self.composing:          # 조합 중에는 입력기가 키를 처리
                return e.key not in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE, pygame.K_TAB)
            k = e.key
            if k == pygame.K_BACKSPACE and self.cursor > 0:
                self.value = self.value[:self.cursor - 1] + self.value[self.cursor:]
                self.cursor -= 1
                self.changed = True
            elif k == pygame.K_DELETE and self.cursor < len(self.value):
                self.value = self.value[:self.cursor] + self.value[self.cursor + 1:]
                self.changed = True
            elif k == pygame.K_LEFT:
                self.cursor = max(0, self.cursor - 1)
            elif k == pygame.K_RIGHT:
                self.cursor = min(len(self.value), self.cursor + 1)
            elif k == pygame.K_HOME:
                self.cursor = 0
            elif k == pygame.K_END:
                self.cursor = len(self.value)
            elif mod_down(e) and k == pygame.K_v:
                try:
                    text = pygame.scrap.get_text() if hasattr(pygame.scrap, "get_text") else ""
                except Exception:
                    text = ""
                text = (text or "").replace("\r", "").split("\n")[0]
                self.value = self.value[:self.cursor] + text + self.value[self.cursor:]
                self.cursor += len(text)
                self.changed = True
            elif mod_down(e) and k == pygame.K_a:
                self.cursor = len(self.value)
            else:
                return k in (pygame.K_BACKSPACE, pygame.K_DELETE)
            return True
        return False

    def draw(self, surf, fonts, font, rect, theme, focused=True):
        self.rect = rect
        draw_rect(surf, theme["field"], rect, 4)
        pygame.draw.rect(surf, theme["accent"] if focused else theme["border"], rect,
                         max(1, rect.h // 18), border_radius=4)
        pad = rect.h // 4
        x, y = rect.x + pad, rect.centery
        before = self.value[:self.cursor]
        after = self.value[self.cursor:]
        if not self.value and not self.composing:
            blit_text(surf, fonts, font, self.placeholder, theme["muted"], (x, y), "midleft")
        surf.set_clip(rect.inflate(-pad, -2))
        r = blit_text(surf, fonts, font, before, theme["ink"], (x, y), "midleft")
        cx = r.right if before else x
        if self.composing:
            cr = blit_text(surf, fonts, font, self.composing, theme["accent"], (cx, y), "midleft")
            pygame.draw.line(surf, theme["accent"], (cr.left, cr.bottom), (cr.right, cr.bottom), max(1, rect.h // 20))
            cx2 = cr.right
        else:
            cx2 = cx
        blit_text(surf, fonts, font, after, theme["ink"], (cx2, y), "midleft")
        if focused and (int(time.time() * 2) % 2 == 0 or self.composing):
            h = font.get_height()
            pygame.draw.line(surf, theme["ink"], (cx2, y - h // 2), (cx2, y + h // 2), max(1, rect.h // 20))
        surf.set_clip(None)
        return pygame.Rect(cx, rect.y, 2, rect.h)


# ====================================================================== 앱과 화면

class Screen:
    """화면 하나. draw() 에서 self.hit(rect, fn) 으로 누를 곳을 등록합니다."""

    def __init__(self, app):
        self.app = app
        self.hits = []

    # 앱이 부름
    def draw(self, surf):
        pass

    def on_key(self, e):
        pass

    def on_text(self, e):
        pass

    def on_wheel(self, dy, pos):
        pass

    def on_resize(self):
        pass

    def tick(self):
        """1초에 몇 번씩 불림 (파일 변경 확인 등)."""

    # 도우미
    def hit(self, rect, fn, hover=True, data=None):
        self.hits.append((pygame.Rect(rect), fn, hover, data))


class App:
    def __init__(self, title, base_size, min_size=(560, 420)):
        pygame.display.init()
        pygame.font.init()
        try:
            pygame.scrap.init()
        except Exception:
            pass
        self.base_size = base_size
        self.display = Display(title, base_size, min_size)
        self.fonts = Fonts()
        self.theme_name = "paper"
        self.screen = None
        self.modals = []
        self.mouse = (-1, -1)
        self.dirty = True
        self.running = True
        self.timers = []
        self.toast_text = None
        self.toast_until = 0
        self.zoom = 1.0
        self.text_input_on = False
        pygame.key.set_repeat(400, 35)

    @property
    def t(self):
        return THEMES[self.theme_name]

    @property
    def u(self):
        """기준 크기 대비 배율 (화소 단위). 모든 크기에 곱해서 씀."""
        pw, ph = self.display.point_size
        bw, bh = self.base_size
        k = max(0.6, min(3.0, min(pw / bw, ph / bh)))
        return k * self.display.ratio * self.zoom

    UI_FONT = 1.15     # 화면 요소(메뉴·상자·상태 줄) 글자 배율

    def font(self, size, kind="sans", bold=False):
        return self.fonts.get(kind, size * self.UI_FONT * self.u, bold)

    def after(self, ms, fn):
        self.timers.append((time.time() + ms / 1000, fn))

    def background(self, fn, done):
        """fn 을 따로 실행하고(화면이 멈추지 않게) 끝나면 done(결과 또는 예외) 을 부릅니다."""
        import threading
        box = {}

        def work():
            try:
                box["r"] = fn()
            except Exception as e:  # noqa: BLE001
                box["r"] = e
        th = threading.Thread(target=work, daemon=True)
        th.start()

        def poll():
            if th.is_alive():
                self.after(150, poll)
            else:
                done(box.get("r"))
                self.invalidate()
        self.after(150, poll)

    def toast(self, text, ms=1800):
        self.toast_text = text
        self.toast_until = time.time() + ms / 1000
        self.after(ms + 30, self.invalidate)
        self.invalidate()

    def invalidate(self):
        self.dirty = True

    def push(self, modal):
        self.modals.append(modal)
        self.invalidate()

    def pop(self, modal=None):
        if modal is None and self.modals:
            self.modals.pop()
        elif modal in self.modals:
            self.modals.remove(modal)
        self.invalidate()

    def top(self):
        return self.modals[-1] if self.modals else self.screen

    def set_text_input(self, rect_px):
        """한글 입력기를 켜고 후보 창 위치를 알려 줌 (rect 는 화소 좌표)."""
        if not self.text_input_on:
            pygame.key.start_text_input()
            self.text_input_on = True
        try:
            pygame.key.set_text_input_rect(self.display.to_points(rect_px))
        except Exception:
            pass

    def stop_text_input(self):
        if self.text_input_on:
            pygame.key.stop_text_input()
            self.text_input_on = False

    # ------------------------------------------------------------ 그리기
    def draw(self):
        surf = self.display.surface
        for layer in [self.screen] + self.modals:
            layer.hits = []
        self.screen.draw(surf)
        wants_text = False
        for m in self.modals:
            draw_rect(surf, self.t["dim"], surf.get_rect())
            m.draw(surf)
            wants_text = wants_text or getattr(m, "wants_text", False)
        wants_text = wants_text or getattr(self.screen, "wants_text", False)
        if not wants_text:
            self.stop_text_input()
        if self.toast_text and time.time() < self.toast_until:
            f = self.font(13)
            img = self.fonts.render(f, self.toast_text, self.t["accent_ink"])
            pad = 8 * self.u
            r = img.get_rect(midtop=(surf.get_width() // 2, int(14 * self.u)))
            box = r.inflate(pad * 3, pad * 1.4)
            draw_rect(surf, self.t["accent"], box, 5 * self.u)
            surf.blit(img, r)
        self.display.present()
        self.dirty = False

    def hover_target(self):
        layer = self.top()
        for rect, fn, hover, data in reversed(layer.hits):
            if rect.collidepoint(self.mouse):
                return rect, fn, hover, data
        return None

    # ------------------------------------------------------------ 이벤트
    def handle(self, e):
        if e.type == pygame.QUIT:
            if hasattr(self.screen, "on_quit"):
                self.screen.on_quit()
            else:
                self.running = False
            return
        if e.type in (pygame.WINDOWRESIZED, pygame.WINDOWSIZECHANGED, pygame.VIDEORESIZE):
            self.display.refresh_size()
            self.screen.on_resize()
            self.invalidate()
            return
        if e.type in (pygame.WINDOWEXPOSED, pygame.WINDOWSHOWN, pygame.WINDOWFOCUSGAINED, pygame.WINDOWRESTORED):
            self.display.refresh_size()
            self.invalidate()
            if e.type == pygame.WINDOWFOCUSGAINED and hasattr(self.screen, "on_focus"):
                self.screen.on_focus()
            return
        layer = self.top()
        if e.type == pygame.MOUSEMOTION:
            pos = self.display.to_pixels(e.pos)
            before = self.hover_target()
            self.mouse = pos
            after = self.hover_target()
            if (before and before[0]) != (after and after[0]):
                self.invalidate()
            return
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            self.mouse = self.display.to_pixels(e.pos)
            target = self.hover_target()
            if target:
                target[1]()
            elif self.modals and hasattr(layer, "on_outside"):
                layer.on_outside()
            self.invalidate()
            return
        if e.type == pygame.MOUSEWHEEL:
            layer.on_wheel(e.precise_y if hasattr(e, "precise_y") else e.y, self.mouse)
            self.invalidate()
            return
        if e.type in (pygame.TEXTINPUT, pygame.TEXTEDITING):
            layer.on_text(e)
            self.invalidate()
            return
        if e.type == pygame.KEYDOWN:
            layer.on_key(e)
            self.invalidate()

    def run(self, screen):
        self.screen = screen
        last_tick = 0
        while self.running:
            now = time.time()
            due = [t for t in self.timers if t[0] <= now]
            if due:
                self.timers = [t for t in self.timers if t[0] > now]
                for _, fn in due:
                    fn()
            if now - last_tick > 0.5:
                last_tick = now
                self.screen.tick()
            if self.dirty or self.text_input_on:
                self.draw()
            timeout = 500 if not self.text_input_on else 250
            if self.timers:
                timeout = max(10, min(timeout, int((min(t[0] for t in self.timers) - time.time()) * 1000)))
            e = pygame.event.wait(timeout)
            if e.type != pygame.NOEVENT:
                self.handle(e)
                for e in pygame.event.get():
                    self.handle(e)
        pygame.quit()


# ====================================================================== 대화 상자

class Dialog(Screen):
    """가운데에 뜨는 상자. buttons: [(글, 값, 강조?)], on_done(값)."""

    width = 520

    def __init__(self, app, title, body="", buttons=(("확인", True, True),), on_done=None):
        super().__init__(app)
        self.title = title
        self.body = body
        self.buttons = list(buttons)
        self.on_done = on_done
        self.box = pygame.Rect(0, 0, 0, 0)

    def close(self, value):
        self.app.pop(self)
        if self.on_done:
            self.on_done(value)

    def on_outside(self):
        pass

    def on_key(self, e):
        if e.key == pygame.K_ESCAPE:
            self.close(None)
        elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            primary = [b for b in self.buttons if len(b) > 2 and b[2]]
            if primary:
                self.close(primary[0][1])

    def content_height(self, width):
        f = self.app.font(14)
        return len(wrap(f, self.body, width)) * f.get_linesize() if self.body else 0

    def draw_content(self, surf, rect):
        f = self.app.font(14)
        y = rect.y
        for line in wrap(f, self.body, rect.w):
            blit_text(surf, self.app.fonts, f, line, self.app.t["ink"], (rect.x, y))
            y += f.get_linesize()

    def draw(self, surf):
        app, t, u = self.app, self.app.t, self.app.u
        W, H = surf.get_size()
        w = min(int(self.width * u), W - int(40 * u))
        pad = int(22 * u)
        inner_w = w - pad * 2
        title_f = app.font(17, bold=True)
        ch = self.content_height(inner_w)
        bh = int(36 * u)
        h = pad + title_f.get_linesize() + int(10 * u) + ch + int(18 * u) + bh + pad
        h = min(h, H - int(30 * u))
        box = pygame.Rect(0, 0, w, h)
        box.center = (W // 2, H // 2)
        self.box = box
        draw_rect(surf, t["paper"], box, 8 * u)
        self.hit(box, lambda: None, hover=False)
        blit_text(surf, app.fonts, title_f, self.title, t["ink"], (box.x + pad, box.y + pad))
        content = pygame.Rect(box.x + pad, box.y + pad + title_f.get_linesize() + int(10 * u), inner_w,
                              box.bottom - pad - bh - int(18 * u) - (box.y + pad + title_f.get_linesize() + int(10 * u)))
        surf.set_clip(content.inflate(int(4 * u), int(4 * u)))
        self.draw_content(surf, content)
        surf.set_clip(None)
        x = box.right - pad
        bf = app.font(14, bold=True)
        for b in reversed(self.buttons):
            label, value = b[0], b[1]
            primary = len(b) > 2 and b[2]
            tw = bf.size(label)[0] + int(28 * u)
            r = pygame.Rect(x - tw, box.bottom - pad - bh, tw, bh)
            hov = r.collidepoint(app.mouse)
            draw_rect(surf, t["accent"] if primary else (t["hover"] if hov else t["choice"]), r, 5 * u)
            blit_text(surf, app.fonts, bf, label, t["accent_ink"] if primary else t["ink"], r.center, "center")
            self.hit(r, lambda v=value: self.close(v))
            x -= tw + int(8 * u)


class InputDialog(Dialog):
    """입력 칸이 있는 상자. fields: [(이름, 제목, 힌트, 처음 값)] → on_done({이름: 값} 또는 None)"""

    wants_text = True

    def __init__(self, app, title, fields, ok="확인", on_done=None, body=""):
        super().__init__(app, title, body, [("취소", None), (ok, "ok", True)], None)
        self.fields = fields
        self.inputs = [TextInput(v or "") for _n, _l, _h, v in fields]
        self.focus = 0
        self.result_cb = on_done

    def close(self, value):
        self.app.pop(self)
        if self.result_cb:
            self.result_cb({f[0]: i.value for f, i in zip(self.fields, self.inputs)} if value == "ok" else None)

    def on_text(self, e):
        self.inputs[self.focus].handle(e)

    def on_key(self, e):
        if self.inputs[self.focus].composing and e.key not in (pygame.K_ESCAPE,):
            self.inputs[self.focus].handle(e)
            return
        if e.key == pygame.K_TAB:
            self.focus = (self.focus + 1) % len(self.inputs)
            return
        if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE):
            return super().on_key(e)
        self.inputs[self.focus].handle(e)

    def content_height(self, width):
        u = self.app.u
        base = super().content_height(width)
        return base + len(self.fields) * int(78 * u)

    def draw_content(self, surf, rect):
        app, t, u = self.app, self.app.t, self.app.u
        super().draw_content(surf, rect)
        y = rect.y + super().content_height(rect.w)
        lf, inf, hf = app.font(13, bold=True), app.font(15), app.font(11.5)
        for i, (name, label, hint, _v) in enumerate(self.fields):
            blit_text(surf, app.fonts, lf, label, t["ink"], (rect.x, y))
            y += lf.get_linesize() + int(4 * u)
            r = pygame.Rect(rect.x, y, rect.w, int(34 * u))
            caret = self.inputs[i].draw(surf, app.fonts, inf, r, t, focused=(i == self.focus))
            self.hit(r, lambda i=i: setattr(self, "focus", i))
            if i == self.focus:
                app.set_text_input(caret)
            y += r.h + int(3 * u)
            if hint:
                blit_text(surf, app.fonts, hf, hint, t["muted"], (rect.x, y))
            y += hf.get_linesize() + int(8 * u)


class ListDialog(Dialog):
    """고를 수 있는 목록. items: [(글, 보조 글, 값, 색 또는 None)] → on_done(값 또는 None)
    filter=True 면 위에 거르기 입력 칸."""

    width = 640

    def __init__(self, app, title, items, on_done=None, filter=False, body="", placeholder="거르기", rows=12):
        super().__init__(app, title, body, [("닫기", None)], on_done)
        self.items = items
        self.filter = TextInput(placeholder=placeholder) if filter else None
        self.wants_text = filter
        self.sel = 0
        self.scroll = 0
        self.rows = rows

    def shown(self):
        if not self.filter or not self.filter.value.strip():
            return self.items
        q = self.filter.value.strip().lower()
        return [it for it in self.items if q in it[0].lower()]

    def on_text(self, e):
        if self.filter:
            self.filter.handle(e)
            self.sel = 0
            self.scroll = 0

    def on_key(self, e):
        items = self.shown()
        if self.filter and self.filter.composing:
            self.filter.handle(e)
            return
        if e.key == pygame.K_DOWN:
            self.sel = min(len(items) - 1, self.sel + 1)
        elif e.key == pygame.K_UP:
            self.sel = max(0, self.sel - 1)
        elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if items and items[self.sel][2] is not None:
                self.close(items[self.sel][2])
        elif e.key == pygame.K_ESCAPE:
            self.close(None)
        elif self.filter:
            self.filter.handle(e)
            self.sel = 0
            self.scroll = 0
        self.keep_visible()

    def keep_visible(self):
        if self.sel < self.scroll:
            self.scroll = self.sel
        elif self.sel >= self.scroll + self.rows:
            self.scroll = self.sel - self.rows + 1

    def on_wheel(self, dy, pos):
        n = len(self.shown())
        step = int(round(dy * 3)) or (1 if dy > 0 else -1)
        self.scroll = max(0, min(max(0, n - self.rows), self.scroll - step))

    def content_height(self, width):
        u = self.app.u
        h = super().content_height(width) + self.rows * int(34 * u)
        if self.filter:
            h += int(44 * u)
        return h

    def draw_content(self, surf, rect):
        app, t, u = self.app, self.app.t, self.app.u
        super().draw_content(surf, rect)
        y = rect.y + super().content_height(rect.w)
        if self.filter:
            r = pygame.Rect(rect.x, y, rect.w, int(34 * u))
            caret = self.filter.draw(surf, app.fonts, app.font(15), r, t, True)
            app.set_text_input(caret)
            y += int(44 * u)
        items = self.shown()
        rh = int(34 * u)
        f, sf = app.font(14), app.font(12)
        area = pygame.Rect(rect.x, y, rect.w, self.rows * rh)
        draw_rect(surf, t["field"], area, 4 * u)
        for i in range(self.scroll, min(len(items), self.scroll + self.rows)):
            text, sub, value, color = items[i]
            r = pygame.Rect(rect.x, y + (i - self.scroll) * rh, rect.w, rh)
            sel = i == self.sel and value is not None
            if sel:
                draw_rect(surf, t["accent"], r, 4 * u)
            elif r.collidepoint(app.mouse) and value is not None:
                draw_rect(surf, t["choice"], r, 4 * u)
            ink = t["accent_ink"] if sel else (color or t["ink"])
            subw = sf.size(sub)[0] if sub else 0
            blit_text(surf, app.fonts, f, fit_text(f, text, rect.w - subw - int(30 * u)), ink, (r.x + int(10 * u), r.centery), "midleft")
            if sub:
                blit_text(surf, app.fonts, sf, sub, t["accent_ink"] if sel else t["muted"],
                          (r.right - int(10 * u), r.centery), "midright")
            if value is not None:
                self.hit(r, lambda v=value: self.close(v))
        if not items:
            blit_text(surf, app.fonts, f, "항목이 없습니다.", t["muted"], (rect.x + int(10 * u), y + int(8 * u)))
