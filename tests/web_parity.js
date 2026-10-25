// 비교 테스트용: 웹 플레이어 엔진(web_player/src/core)으로 이야기를 탐색해 페이지들을 JSON 으로 출력
// 입력(stdin): {"files":[{"path","text"}], "start":"start", "depth":10, "limit":300}
const path = require('path');
const core = path.join(__dirname, '..', 'web_player', 'src', 'core');
const { parseFiles } = require(path.join(core, 'script'));
const { Engine, Session } = require(path.join(core, 'runtime'));
const { lint } = require(path.join(core, 'lint'));

let input = '';
process.stdin.on('data', (d) => { input += d; });
process.stdin.on('end', () => {
  const req = JSON.parse(input);
  const story = parseFiles(req.files);
  const report = lint(story, { start: req.start || 'start' });
  const out = { errors: story.errors.map((e) => [e.loc.line, e.message]),
    issues: report.issues.map((i) => [i.level, i.loc ? i.loc.line : 0, i.message]), pages: {} };
  if (!story.errors.length) {
    const engine = new Engine(story, req.start || 'start');
    const queue = [[]];
    while (queue.length && Object.keys(out.pages).length < (req.limit || 300)) {
      const p = queue.shift();
      const s = new Session(engine);
      s.start(1);
      for (const i of p) s.choose(i);
      const pg = s.page;
      out.pages[p.join(',')] = { label: pg.label, image: pg.image, paragraphs: pg.paragraphs,
        choices: pg.choices.map((c) => [c.text, c.enabled]), ending: pg.ending, deadEnd: pg.deadEnd,
        vars: s.after.variables };
      if (p.length < (req.depth || 10)) pg.choices.forEach((c, i) => { if (c.enabled) queue.push([...p, i]); });
    }
  }
  process.stdout.write(JSON.stringify(out));
});
