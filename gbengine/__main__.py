"""명령줄 진입점.

    python -m gbengine                     런처 열기
    python -m gbengine edit <프로젝트>          설정한 편집기(VS Code 등)로 스크립트 열기
    python -m gbengine run <프로젝트> [--dev] [--start 단락]
    python -m gbengine guide                     문법 가이드 HTML 만들기 (docs/script_guide.html)
    python -m gbengine lint <프로젝트>
    python -m gbengine build <프로젝트>
    python -m gbengine html <프로젝트> [-o 파일]     HTML 파일 하나로 내보내기
    python -m gbengine new <폴더이름> [제목]
"""

import argparse
import os
import sys


def _tool_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:  # Windows 콘솔에서 한글이 깨지지 않도록
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="gbengine", description="GameBook Studio")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="게임 실행")
    r.add_argument("project")
    r.add_argument("--dev", action="store_true")
    r.add_argument("--start", default=None, help="이 단락부터 시작 (개발용)")
    ed = sub.add_parser("edit", help="편집기로 스크립트 열기")
    ed.add_argument("project")
    sub.add_parser("guide", help="문법 가이드 HTML 만들기")
    li = sub.add_parser("lint", help="스크립트 검사")
    li.add_argument("project")
    h = sub.add_parser("html", help="HTML 파일 하나로 내보내기 (브라우저로 플레이)")
    h.add_argument("project")
    h.add_argument("-o", "--output", default=None)
    b = sub.add_parser("build", help="배포용 zip 만들기")
    b.add_argument("project")
    n = sub.add_parser("new", help="새 프로젝트 (projects 폴더에)")
    n.add_argument("folder")
    n.add_argument("title", nargs="?", default="")
    args = ap.parse_args(argv)
    if args.cmd in (None, "run"):
        from .deps import require_pygame
        require_pygame()

    if args.cmd is None:
        from .gui.launcher import main as launcher_main
        launcher_main()
    elif args.cmd == "run":
        from .gui.player import main as player_main
        player_main([args.project] + (["--dev"] if args.dev else []) +
                    (["--start", args.start] if args.start else []))
    elif args.cmd == "edit":
        from .editors import open_in_editor
        from .project import Project
        project = Project(args.project)
        files = sorted(f for f in os.listdir(project.script_dir) if f.endswith(".gb")) \
            if os.path.isdir(project.script_dir) else []
        main_file = next((f for f in ("script.gb", "main.gb") if f in files), files[0] if files else None)
        if not main_file:
            sys.exit("스크립트 파일(.gb)이 없습니다: " + project.script_dir)
        print(open_in_editor(os.path.join(project.script_dir, main_file), 1, project.path))
    elif args.cmd == "guide":
        from .markdown_lite import to_html
        src = os.path.join(_tool_dir(), "docs", "script_guide.md")
        out = os.path.join(_tool_dir(), "docs", "script_guide.html")
        with open(src, encoding="utf-8") as f:
            html = to_html(f.read(), "게임북 스크립트 가이드")
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        print(out)
    elif args.cmd == "lint":
        from .lint import lint_project
        from .project import Project
        report = lint_project(Project(args.project))
        for issue in report.issues:
            print(issue)
        print(report.summary())
        sys.exit(1 if report.errors else 0)
    elif args.cmd == "html":
        from .html_export import check_before_export, export_html
        from .project import Project
        project = Project(args.project)
        n_err, summary = check_before_export(project)
        print(summary)
        out = export_html(project, args.output)
        print(out)
        sys.exit(1 if n_err else 0)
    elif args.cmd == "build":
        from .project import Project, build_distribution
        out = build_distribution(Project(args.project), os.path.dirname(os.path.abspath(__file__)),
                                 os.path.join(_tool_dir(), "dist"))
        print(out)
    elif args.cmd == "new":
        from .project import create_project
        p = create_project(os.path.join(_tool_dir(), "projects"), args.folder, args.title)
        print(p.path)


if __name__ == "__main__":
    main()
