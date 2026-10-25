# 웹 플레이어

**HTML 로 내보내기**에 들어가는 게임 화면입니다. 내보낸 HTML 파일 안에서 브라우저가 실행합니다.

- 쓰는 사람은 이 폴더가 필요 없습니다. 빌드된 결과(`gbengine/web/player.js`, `player.css`)가 이미 들어 있습니다.
- 스크립트 엔진(`src/core`)은 Python 엔진(`gbengine/script.py`, `expr.py`, `runtime.py`)과 같은 문법·동작을 JavaScript 로 옮긴 것입니다.
  문법을 바꿀 때는 양쪽을 함께 고치고 `python -m unittest discover tests` 의 비교 테스트로 확인하세요.

다시 빌드하려면 (Node.js 필요):

```
npm install
npm run build
```
