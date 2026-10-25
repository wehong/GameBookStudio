"""HTML 내보내기와 웹 플레이어 엔진 테스트.

- 내보낸 파일 안에 스크립트·그림·플레이어가 제대로 들어가는지
- 웹 플레이어(JavaScript) 엔진이 Python 엔진과 같은 화면을 만드는지 (node 가 있을 때만)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gbengine.html_export import collect, export_html  # noqa: E402
from gbengine.lint import lint  # noqa: E402
from gbengine.project import Project  # noqa: E402
from gbengine.runtime import Engine, Session  # noqa: E402
from gbengine.script import parse_source  # noqa: E402

SAMPLE = os.path.join(ROOT, "projects", "sample_lighthouse")
NODE = shutil.which("node")


def python_pages(files, start="start", depth=10, limit=300):
    story = None
    for f in files:
        story = parse_source(f["text"], f["path"], story)
    out = {"errors": [[e.loc.line, e.message] for e in story.errors],
           "issues": [[i.level, i.loc.line if i.loc else 0, i.message] for i in lint(story, start).issues],
           "pages": {}}
    if story.errors:
        return out
    engine = Engine(story, start)
    queue = [[]]
    while queue and len(out["pages"]) < limit:
        p = queue.pop(0)
        s = Session(engine)
        s.start(seed=1)
        for i in p:
            s.choose(i)
        pg = s.page
        out["pages"][",".join(map(str, p))] = {
            "label": pg.label, "image": pg.image, "paragraphs": pg.paragraphs,
            "choices": [[c.text, c.enabled] for c in pg.choices], "ending": pg.ending,
            "deadEnd": pg.dead_end, "vars": s.after.variables}
        if len(p) < depth:
            queue += [p + [i] for i, c in enumerate(pg.choices) if c.enabled]
    return out


def web_pages(files, start="start"):
    r = subprocess.run([NODE, os.path.join(ROOT, "tests", "web_parity.js")],
                       input=json.dumps({"files": files, "start": start}), capture_output=True,
                       text=True, encoding="utf-8", timeout=60)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


def normalize(v):
    """3.0 과 3 처럼 표기만 다른 숫자를 같게."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, dict):
        return {k: normalize(x) for k, x in v.items()}
    if isinstance(v, list):
        return [normalize(x) for x in v]
    return v


def sample_files():
    d = os.path.join(SAMPLE, "script")
    out = []
    for f in sorted(os.listdir(d)):
        with open(os.path.join(d, f), encoding="utf-8") as fp:
            out.append({"path": f, "text": fp.read()})
    return out


EXTRA = '''
default 금화 = 3
default 체력 = 10
default 이름 = "카이"
label start:
    "금화 {금화}, {이름}님."
    set 칭호 = 이름 + " 경"
    set 나눔 = 7 // 2
    set 나머지 = -7 % 3
    if 1 <= 금화 <= 5 and not visited("상점"):
        "조건 연쇄 통과 {칭호} {나눔} {나머지}"
    choice "상점 ({금화})" if 금화 >= 2 -> 상점:
        set 금화 -= 2
    choice "함정" -> 함정
    choice "잠김" if 금화 > 100 -> 상점
label 상점:
    if visited("상점") == 1:
        "처음 온 상점"
    else:
        "다시 온 상점"
    choice "돌아가기" -> start
label 함정:
    set 체력 -= 11
    if 체력 <= 0:
        goto 죽음
    "살았다"
    choice "계속" -> start
label 죽음:
    """
    눈앞이 캄캄해진다.

    끝.
    """
    end "죽음"
'''

BROKEN = 'label start:\n    chioce "x" -> a\n    choice "y" -> 없음\n    if 금화 => 3:\n        end\n    end\nlabel 고립:\n    "막힘"\n'


class ExportTests(unittest.TestCase):
    def test_export_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = export_html(Project(SAMPLE), os.path.join(d, "game.html"))
            with open(out, encoding="utf-8") as f:
                page = f.read()
        self.assertIn("<title>잊혀진 등대</title>", page)
        m = re.search(r"window\.GB_DATA = (.*?);</script>", page, re.S)
        data = json.loads(m.group(1).replace("<\\/", "</"))
        self.assertEqual([s["path"] for s in data["scripts"]], ["main.gb"])
        self.assertIn("title.png", data["images"])
        self.assertTrue(data["images"]["shore.png"].startswith("data:image/png;base64,"))
        self.assertEqual(page.count("</script>"), 2)   # 데이터·플레이어 안에 닫는 태그가 없어야 함

    def test_script_close_tag_is_escaped(self):
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(SAMPLE, os.path.join(d, "p"))
            with open(os.path.join(d, "p", "script", "main.gb"), "a", encoding="utf-8") as f:
                f.write('\nlabel 위험:\n    "</script><script>alert(1)</script>"\n    end\n')
            with open(export_html(Project(os.path.join(d, "p"))), encoding="utf-8") as f:
                page = f.read()
        # 본문의 </script> 가 그대로 들어가면 페이지가 깨지므로 이스케이프되어야 함
        self.assertEqual(page.count("</script>"), 2)

    def test_collect_subfolders(self):
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(SAMPLE, os.path.join(d, "p"))
            os.makedirs(os.path.join(d, "p", "images", "items"))
            shutil.copy(os.path.join(SAMPLE, "images", "map.png"), os.path.join(d, "p", "images", "items", "m.png"))
            data = collect(Project(os.path.join(d, "p")))
        self.assertIn("items/m.png", data["images"])


@unittest.skipUnless(NODE, "node 가 없어서 웹 엔진 비교를 건너뜁니다")
class ParityTests(unittest.TestCase):
    def compare(self, files):
        py, web = normalize(python_pages(files)), normalize(web_pages(files))
        self.assertEqual(py["errors"], web["errors"])
        self.assertEqual(sorted(map(tuple, py["issues"])), sorted(map(tuple, web["issues"])))
        self.assertEqual(set(py["pages"]), set(web["pages"]))
        for k in py["pages"]:
            self.assertEqual(py["pages"][k], web["pages"][k], f"경로 {k!r}")
        return py

    def test_sample_same_pages(self):
        py = self.compare(sample_files())
        self.assertGreater(len(py["pages"]), 50)

    def test_features_same_pages(self):
        py = self.compare([{"path": "x.gb", "text": EXTRA}])
        self.assertIn("조건 연쇄 통과 카이 경 3 2", py["pages"][""]["paragraphs"][1])

    def test_errors_same(self):
        self.compare([{"path": "b.gb", "text": BROKEN}])


if __name__ == "__main__":
    unittest.main()
