# GameBook Studio

텍스트 스크립트로 **분기형 게임북**을 만들고 PC에서 플레이하는 도구입니다.
Ren'Py처럼 *스크립트 + 엔진 + 런처*로 이루어져 있고, 각 단락은 **이미지 한 장 + 본문 + 선택지**로 보여집니다.

- 화면은 Ren'Py와 같은 방식으로 **pygame(SDL2)이 창 안을 직접 그립니다.**
  운영체제의 GUI 툴킷(Tk 등)을 쓰지 않으므로 Windows · macOS · Linux에서 똑같이 보입니다.
- 한글 글꼴(**나눔고딕·나눔명조**, SIL OFL)이 들어 있어서 시스템 글꼴 설정과 상관없이 한글이 깨지지 않습니다.
- Retina 같은 고해상도 화면에서는 실제 화소로 그려서 선명하고, 창 크기를 바꾸면 글자·버튼·그림이 함께 커집니다.
- 스크립트는 Ren'Py처럼 **외부 편집기(VS Code 추천)**로 씁니다. 저장하면 게임 창에 바로 반영됩니다.

## 설치

Python 3.9 이상과 [pygame-ce](https://pypi.org/project/pygame-ce/)가 필요합니다.

```
python -m pip install pygame-ce
```

(macOS · Linux에서는 `python` 대신 `python3`. pygame-ce가 없으면 처음 실행할 때 설치할지 물어봅니다.
Linux의 시스템 Python에서 pip가 막혀 있으면 `python3 -m pip install --user pygame-ce` 또는 가상 환경을 쓰세요.)

## 시작하기

```
python launcher.py
```

1. 런처에서 프로젝트를 고르거나 **＋ 새 프로젝트**로 만듭니다.
2. 처음 한 번 **VS Code 확장 설치**를 누릅니다 → `.gb` 파일 구문 강조, 4칸 들여쓰기, 문장 틀(조각).
3. **스크립트 편집하기**로 편집기에서 스크립트를 열고, **▶ 실행하기**로 게임 창(개발 모드)을 띄웁니다.
4. 편집기에서 저장할 때마다 게임 창이 다시 읽어서 보고 있던 단락에 바로 반영합니다.
   오류가 나면 게임 창에 위치가 나오고, 그 위치를 누르거나 `F4`를 누르면 편집기의 그 줄이 열립니다.

다른 편집기를 쓰려면 런처의 **편집기 고르기**에서 고릅니다
(VS Code · VSCodium · Cursor · Sublime Text · Notepad++ · Kate · gedit 등 자동으로 찾음, 또는 명령 직접 지정).
설정은 사용자 폴더의 `.gamebook_studio.json`에 저장됩니다.

## 문서

- **[스크립트 가이드](docs/script_guide.md)** — 모든 문법, 예제, 자주 쓰는 패턴, 오류 해결, 편집기·단축키
  - 런처의 **문법 가이드** 또는 게임 창(개발 모드)의 `F1`로 브라우저에서 열립니다.
  - 브라우저용: `docs/script_guide.html` (`python -m gbengine guide`로 다시 만들 수 있음)

## 명령줄

| 명령 | 하는 일 |
|---|---|
| `python -m gbengine` | 런처 열기 |
| `python -m gbengine run <프로젝트> [--dev] [--start 단락]` | 게임 실행 (`--dev`: 개발 모드) |
| `python -m gbengine edit <프로젝트>` | 설정한 편집기로 스크립트 열기 |
| `python -m gbengine lint <프로젝트>` | 스크립트 검사 |
| `python -m gbengine html <프로젝트> [-o 파일]` | HTML 파일 하나로 내보내기 (기본: 프로젝트의 `dist/`) |
| `python -m gbengine build <프로젝트>` | 배포용 zip 만들기 (`dist/`) |
| `python -m gbengine new <폴더> [제목]` | 새 프로젝트 만들기 (`projects/`) |
| `python -m gbengine guide` | 가이드 HTML 다시 만들기 |

## 게임 창 조작

| 키 | 동작 |
|---|---|
| `1`~`9`, 마우스 | 선택지 고르기 |
| `Backspace` | 뒤로 가기 |
| `Ctrl+S` / `Ctrl+O` | 저장 / 불러오기 (10칸) |
| `Ctrl+N` | 처음부터 |
| `Ctrl+=` / `Ctrl+-` | 글자 크기 |
| `Ctrl+T` | 종이/밤 테마 |
| `F11`, `Alt+Enter` | 전체 화면 |

개발 모드: `F4` 편집기에서 열기 · `F5` 다시 읽기 · `F6` 단락으로 이동 · `F2` 변수 보기 · `F7` 검사 · `F1` 가이드.
macOS에서는 `Ctrl` 대신 `Cmd`도 됩니다.

## 폴더 구조

```
gamebook/
├─ launcher.py              런처 실행 파일
├─ docs/                    스크립트 가이드 (md, html)
├─ editor_support/
│   └─ vscode-gamebook/     VS Code 확장 (구문 강조, 들여쓰기, 문장 틀)
├─ gbengine/
│   ├─ script.py            스크립트 파서
│   ├─ expr.py              조건식 계산 (안전한 부분 문법)
│   ├─ runtime.py           진행 로직, 저장/불러오기 (화면과 분리)
│   ├─ lint.py              스크립트 검사기
│   ├─ project.py           프로젝트 설정, 새 프로젝트, 배포
│   ├─ editors.py           외부 편집기 찾기·열기, VS Code 확장 설치
│   ├─ deps.py              pygame-ce 확인
│   ├─ html_export.py       HTML 파일 하나로 내보내기
│   ├─ syntax.py            구문 토크나이저 (가이드의 코드 색칠)
│   ├─ markdown_lite.py     가이드 마크다운 → HTML
│   ├─ gui/
│   │   ├─ base.py          pygame 화면 기반: 창(고해상도), 글꼴, 배율, 대화 상자, 한글 입력
│   │   ├─ player.py        게임 창
│   │   ├─ launcher.py      런처
│   │   └─ fonts/           나눔고딕·나눔명조 (SIL OFL)
│   └─ web/                 내보낸 HTML 에 들어가는 웹 플레이어 (빌드 결과)
├─ projects/
│   └─ sample_lighthouse/   예제 「잊혀진 등대」
│       ├─ game.json        설정
│       ├─ script/*.gb      스크립트 (여러 파일로 나눠도 하나로 합쳐짐)
│       ├─ images/          이미지 (PNG, JPG, GIF, WebP, BMP)
│       └─ saves/           저장 파일 (자동 생성)
├─ web_player/              웹 플레이어 소스 (JavaScript, 고칠 때만 Node.js 필요)
└─ tests/                   테스트 (python -m unittest discover tests)
```

## 배포

### HTML 파일 하나로 (추천)

런처의 **HTML 로 내보내기**(또는 `html` 명령)는 스크립트, 설정, 그림을 모두 담은 HTML 파일 하나를 만듭니다.
받은 사람은 아무것도 설치하지 않고 브라우저로 열기만 하면 되고, 휴대폰에서도 플레이할 수 있습니다.
저장은 그 브라우저에 됩니다.

### Python 실행 파일로

런처의 **배포 파일 만들기**(또는 `build` 명령)는 `dist/`에 zip을 만듭니다 (엔진·글꼴·게임 포함, 저장 파일 제외).
받은 사람은 Python과 pygame-ce를 설치한 뒤 압축을 풀고 `python play.py`로 실행합니다.

## 글꼴 라이선스

`gbengine/gui/fonts/`의 나눔고딕·나눔명조는 NAVER가 SIL Open Font License 1.1로 배포한 글꼴입니다 (`OFL-Nanum.txt`).
