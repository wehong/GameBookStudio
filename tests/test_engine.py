"""엔진 테스트: python -m unittest discover tests"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gbengine.lint import ERROR, WARNING, lint  # noqa: E402
from gbengine.runtime import Engine, Session, read_save, write_save  # noqa: E402
from gbengine.script import parse_source  # noqa: E402

STORY = '''
# 테스트용 이야기
default 금화 = 3
default 횃불 = false

label start:
    image "forest.png"
    "숲 입구다. 금화는 {금화}개."
    choice "오두막으로" -> 오두막
    choice "동굴로" if 횃불 -> 동굴
    choice "상인에게 ({금화}개 있음)" if 금화 >= 5 -> 상인

label 오두막:
    """
    낡은 오두막.
    구석에 횃불이 있다.
    """
    set 횃불 = true
    set 금화 += 2   # 금화 줍기
    choice "숲으로 돌아간다" -> start:
        set 용기 = 1

label 동굴:
    if visited("동굴") > 1:
        "다시 왔다."
    else:
        "처음 와 본 동굴이다."
    goto 갈림길

label 갈림길:
    goto 147

label 147:
    "깊은 곳에 도착했다."
    end "동굴의 끝"

label 상인:
    "상인이 웃는다."
    end
'''


class ParserTests(unittest.TestCase):
    def test_parse_ok(self):
        story = parse_source(STORY, "t.gb")
        self.assertEqual(story.errors, [])
        self.assertEqual(set(story.labels), {"start", "오두막", "동굴", "갈림길", "147", "상인"})
        self.assertEqual(len(story.defaults), 2)

    def test_errors_have_lines(self):
        src = 'label a:\n    "글"\n    choice "x" -> \n    bogus line\n    set 1x = 3\nlabel a:\n    end\n'
        story = parse_source(src, "e.gb")
        lines = sorted(e.loc.line for e in story.errors)
        self.assertEqual(lines, [3, 4, 5, 6])

    def test_choice_block_rules(self):
        src = 'label a:\n    choice "x" -> b:\n        "본문은 안 됨"\n        set y = 1\nlabel b:\n    end\n'
        story = parse_source(src, "c.gb")
        self.assertEqual(len(story.errors), 1)
        self.assertEqual(story.errors[0].loc.line, 3)

    def test_bad_expression(self):
        story = parse_source('label a:\n    if __import__("os"):\n        end\n    end\n', "x.gb")
        self.assertEqual(len(story.errors), 1)

    def test_comment_inside_string(self):
        story = parse_source('label a:\n    "#1 번 방"  # 주석\n    end\n', "x.gb")
        self.assertEqual(story.errors, [])
        self.assertEqual(story.labels["a"].body[0].text, "#1 번 방")


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(parse_source(STORY, "t.gb"))
        self.s = Session(self.engine)
        self.s.start(seed=1)

    def texts(self):
        return [c.text for c in self.s.page.choices]

    def test_flow(self):
        p = self.s.page
        self.assertEqual(p.image, "forest.png")
        self.assertEqual(p.paragraphs, ["숲 입구다. 금화는 3개."])
        self.assertEqual(self.texts(), ["오두막으로"])
        self.s.choose(0)
        self.assertEqual(self.s.page.paragraphs, ["낡은 오두막.\n구석에 횃불이 있다."])
        self.s.choose(0)
        self.assertEqual(self.s.after.variables["용기"], 1)
        self.assertEqual(self.texts(), ["오두막으로", "동굴로", "상인에게 (5개 있음)"])
        self.s.choose(1)  # 동굴: 본문 + goto -> '계속'
        self.assertEqual(self.s.page.paragraphs, ["처음 와 본 동굴이다."])
        self.assertEqual(self.texts(), ["계속"])
        self.s.choose(0)  # 갈림길은 내용 없이 바로 147 로
        self.assertEqual(self.s.page.label, "147")
        self.assertEqual(self.s.page.labels_passed, ["갈림길", "147"])
        self.assertEqual(self.s.page.ending, "동굴의 끝")

    def test_back_and_save(self):
        self.s.choose(0)
        self.s.choose(0)
        self.assertEqual(self.s.page.label, "start")
        self.s.back()
        self.assertEqual(self.s.page.label, "오두막")
        self.assertEqual(self.s.after.variables["금화"], 5)
        with tempfile.TemporaryDirectory() as d:
            write_save(d, 1, self.s)
            data = read_save(d, 1)
            s2 = Session(self.engine)
            s2.load_json(data["session"])
            self.assertEqual(s2.page.label, "오두막")
            self.assertEqual(s2.after.variables, self.s.after.variables)
            s2.back()
            self.assertEqual(s2.page.label, "start")

    def test_locked_choices_shown(self):
        engine = Engine(parse_source(STORY, "t.gb"), show_locked_choices=True)
        s = Session(engine)
        s.start(seed=1)
        self.assertEqual([c.enabled for c in s.page.choices], [True, False, False])

    def test_random_is_replayable(self):
        src = 'label start:\n    set d = random(1, 1000)\n    "{d}"\n    choice "다시" -> start\n'
        s = Session(Engine(parse_source(src, "r.gb")))
        s.start(seed=42)
        first = s.page.paragraphs[0]
        s.choose(0)
        s.back()
        self.assertEqual(s.page.paragraphs[0], first)

    def test_dead_end(self):
        s = Session(Engine(parse_source('label start:\n    "끝?"\n', "d.gb")))
        s.start()
        self.assertTrue(s.page.dead_end)


class LintTests(unittest.TestCase):
    def test_clean_story(self):
        report = lint(parse_source(STORY, "t.gb"))
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])
        self.assertEqual(report.stats["endings"], 2)

    def test_problems_found(self):
        src = '''
label start:
    "{이름}"
    choice "a" -> 없음
    choice "b" if 열쇠 -> 고립
label 고립:
    "막힘"
label 외딴곳:
    end
'''
        report = lint(parse_source(src, "p.gb"))
        msgs = [str(i) for i in report.issues]
        self.assertTrue(any("'없음'" in m and ERROR in m for m in msgs))
        self.assertTrue(any("막다른" in m for m in msgs))
        self.assertTrue(any("외딴곳" in m and "갈 수 있는 길" in m for m in msgs))
        self.assertTrue(any("'이름'" in m for m in msgs))
        self.assertTrue(any("'열쇠'" in m and WARNING in m for m in msgs))


if __name__ == "__main__":
    unittest.main()


class EditorSupportTests(unittest.TestCase):
    def test_tokenize(self):
        from gbengine.syntax import tokenize
        lines = tokenize('label 동굴:\n    choice "금화 {금화}개" if 횃불 -> 숲  # 메모\n    """\n    여러 줄 # 아님\n    """')
        kinds = lambda i: [k for _s, _e, k in lines[i]]  # noqa: E731
        self.assertEqual(kinds(0), ["keyword", "labeldef"])
        self.assertEqual(kinds(1), ["keyword", "string", "interp", "keyword", "arrow", "target", "comment"])
        self.assertEqual(kinds(3), ["string"])     # 세 따옴표 안의 # 은 주석이 아님
        self.assertEqual(kinds(4), ["string"])

    def test_overrides_and_start_at(self):
        from gbengine.script import load_story
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.gb")
            with open(path, "w", encoding="utf-8") as f:
                f.write('label start:\n    "디스크"\n    end\n')
            story = load_story(d, {path: 'label start:\n    "편집 중"\n    goto 둘\nlabel 둘:\n    end "끝"\n'})
            self.assertEqual(set(story.labels), {"start", "둘"})
            s = Session(Engine(story))
            s.start_at("둘")
            self.assertEqual(s.page.ending, "끝")

    def test_guide_examples_parse(self):
        from gbengine import markdown_lite as md
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "docs", "script_guide.md"), encoding="utf-8") as f:
            blocks = md.parse(f.read())
        anchors = {b.anchor for b in blocks if b.kind == "heading"}
        bad = []
        for b in blocks:
            if b.kind == "code" and "(내용)" not in b.text and "(조건이" not in b.text:
                st = parse_source(b.text, "g")
                if st.errors:
                    wrapped = "label _t:\n" + "\n".join("    " + l for l in b.text.split("\n"))
                    if parse_source(wrapped, "g").errors:
                        bad.append(b.text[:40])
            for _t, _s, link in [x for x in md.inline(b.text)] if b.kind == "para" else []:
                if link and link.startswith("#"):
                    self.assertIn(link[1:], anchors)
        self.assertEqual(bad, [])
