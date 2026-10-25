"""화면(pygame) 기본 동작 시험. pygame-ce 가 없으면 건너뜀. 화면 없이(dummy) 그려 봅니다."""

import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import pygame  # noqa: F401
    HAVE_PYGAME = True
except ImportError:
    HAVE_PYGAME = False

SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "projects", "sample_lighthouse")


@unittest.skipUnless(HAVE_PYGAME, "pygame-ce 없음")
class GuiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.proj = os.path.join(self.tmp, "p")
        shutil.copytree(SAMPLE, self.proj, ignore=shutil.ignore_patterns("saves"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_player_flow(self):
        from gbengine.gui.base import App
        from gbengine.gui.player import Player
        from gbengine.project import Project
        app = App("t", (1024, 760))
        pl = Player(app, Project(self.proj), dev=True)
        app.screen = pl
        app.draw()
        self.assertEqual(pl.mode, "title")
        pl.new_game()
        app.draw()
        self.assertEqual(pl.mode, "play")
        self.assertTrue(any(True for _ in pl.hits))          # 선택지 버튼이 등록됨
        first = pl.session.page.label
        pl.pick(0)
        app.draw()
        self.assertNotEqual(pl.session.page.label, first)
        pl.back()
        self.assertEqual(pl.session.page.label, first)
        for size in ((560, 460), (1800, 1200)):               # 창 크기를 바꿔도 그려짐
            app.display.resize(size)
            app.draw()
        pl.slot_dialog("save")
        app.draw()
        app.modals[-1].close(3)
        self.assertEqual(pl.latest_slot(), 3)
        pl.show_vars = True
        pl.jump_dialog()
        app.draw()

    def test_player_shows_script_error(self):
        from gbengine.gui.base import App
        from gbengine.gui.player import Player
        from gbengine.project import Project
        with open(os.path.join(self.proj, "script", "main.gb"), "a", encoding="utf-8") as f:
            f.write("\nlabel 깨짐:\n    choice x ->\n")
        app = App("t", (1024, 760))
        pl = Player(app, Project(self.proj), dev=True)
        app.screen = pl
        app.draw()
        self.assertEqual(pl.mode, "error")
        self.assertTrue(pl.errors and pl.errors[0][0] is not None)

    def test_launcher_draws(self):
        from gbengine.gui import launcher as L
        from gbengine.gui.base import App
        old = L.PROJECTS_DIR
        L.PROJECTS_DIR = self.tmp
        try:
            app = App("t", L.BASE_SIZE)
            la = L.Launcher(app)
            app.screen = la
            app.draw()
            self.assertEqual(len(la.projects), 1)
            la.lint_dialog()
            la.new_project()
            app.draw()
        finally:
            L.PROJECTS_DIR = old

    def test_launcher_delete(self):
        from gbengine.gui import launcher as L
        from gbengine.gui.base import App
        old = L.PROJECTS_DIR
        L.PROJECTS_DIR = self.tmp
        try:
            shutil.copytree(self.proj, os.path.join(self.tmp, "q"))
            app = App("t", L.BASE_SIZE)
            la = L.Launcher(app)
            app.screen = la
            self.assertEqual(len(la.projects), 2)
            la.delete_dialog()
            app.draw()
            app.modals[-1].close(None)                       # 취소
            self.assertEqual(len(la.projects), 2)
            la.delete_dialog()
            app.modals[-1].close("del")
            app.modals.clear()
            self.assertEqual(len(la.projects), 1)
            self.assertFalse(os.path.exists(self.proj))
            self.assertIsNotNone(la.current)
            app.draw()
        finally:
            L.PROJECTS_DIR = old

    def test_wrap_korean(self):
        import pygame
        from gbengine.gui.base import Fonts, wrap
        pygame.font.init()
        f = Fonts().get("serif", 20)
        lines = wrap(f, "아주 긴 한국어 문장을 좁은 폭에 맞춰서 여러 줄로 나눕니다. " * 3, 200)
        self.assertGreater(len(lines), 3)
        self.assertTrue(all(f.size(line)[0] <= 200 for line in lines))


if __name__ == "__main__":
    unittest.main()
