// 스크립트 검사기: 끊긴 링크, 도달할 수 없는 단락, 막다른 단락, 빠진 이미지, 의심스러운 변수.
'use strict';

const { walk } = require('./script');

const ERROR = '오류', WARNING = '경고', INFO = '참고';
const LEVEL_ORDER = { [ERROR]: 0, [WARNING]: 1, [INFO]: 2 };
const INTERP_RE = /(?<!\{)\{([\p{L}\p{M}\p{N}_]+)\}/gu;
const IMAGE_EXT = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg', '.avif'];

function exits(body) {
  for (const n of walk(body)) if (n.type === 'choice' || n.type === 'goto' || n.type === 'end') return true;
  return false;
}

function guaranteedExit(body) {
  for (const n of body) {
    if (n.type === 'goto' || n.type === 'end') return true;
    if (n.type === 'choice' && n.cond === null) return true;
    if (n.type === 'if' && n.branches[n.branches.length - 1][0] === null &&
        n.branches.every(([, sub]) => guaranteedExit(sub))) return true;
  }
  return false;
}

function* targets(body) {
  for (const n of walk(body)) if ((n.type === 'choice' || n.type === 'goto') && n.target) yield n;
}

function interpNames(text) {
  return [...text.matchAll(INTERP_RE)].map((m) => m[1]);
}

/**
 * story: parseFiles 결과
 * opts.start: 시작 단락, opts.images: images 폴더의 파일 목록(상대 경로, '/' 구분) 또는 null,
 * opts.titleImage: 타이틀 이미지
 */
function lint(story, opts = {}) {
  const start = opts.start || 'start';
  const issues = story.errors.map((e) => ({ level: ERROR, loc: e.loc, message: e.message }));
  const labels = story.labels;
  const add = (level, loc, message) => issues.push({ level, loc, message });

  if (labels.size && !labels.has(start)) {
    add(ERROR, null, `시작 단락 '${start}' 이(가) 없습니다. game.json 의 "start" 를 확인하거나 label ${start}: 을 만들어 주세요.`);
  }

  for (const label of labels.values()) {
    for (const n of targets(label.body)) {
      if (!labels.has(n.target)) {
        const kind = n.type === 'choice' ? '선택지' : 'goto';
        add(ERROR, n.loc, `${kind}가 가리키는 단락 '${n.target}' 이(가) 없습니다.`);
      } else if (n.target === label.name && n.type === 'goto') {
        add(ERROR, n.loc, `단락 '${label.name}' 이(가) 자기 자신으로 goto 합니다 (무한 반복).`);
      }
    }
    if (!exits(label.body)) {
      add(WARNING, label.loc, `단락 '${label.name}' 에 선택지·goto·end 가 없어 막다른 곳이 됩니다.`);
    } else if (!guaranteedExit(label.body)) {
      add(WARNING, label.loc, `단락 '${label.name}' 은(는) 조건에 따라 선택지가 하나도 없을 수 있습니다. ` +
        '조건 없는 선택지나 else 를 두는 것을 권장합니다.');
    }
  }

  let seen = null;
  if (labels.has(start)) {
    seen = new Set([start]);
    const stack = [start];
    while (stack.length) {
      for (const n of targets(labels.get(stack.pop()).body)) {
        if (labels.has(n.target) && !seen.has(n.target)) { seen.add(n.target); stack.push(n.target); }
      }
    }
    for (const [name, label] of labels) {
      if (!seen.has(name)) add(WARNING, label.loc, `단락 '${name}' 은(는) 시작 단락에서 갈 수 있는 길이 없습니다.`);
    }
  }

  const assigned = new Map(), used = new Map();
  const setDefault = (m, k, v) => { if (!m.has(k)) m.set(k, v); };
  for (const d of story.defaults) {
    setDefault(assigned, d.name, d.loc);
    for (const v of d.expr.names) setDefault(used, v, d.loc);
  }
  for (const label of labels.values()) {
    for (const n of walk(label.body)) {
      const exprs = [];
      if (n.type === 'set') {
        setDefault(assigned, n.name, n.loc);
        exprs.push(n.expr);
        if (n.op !== '=') setDefault(used, n.name, n.loc);
      } else if (n.type === 'if') {
        for (const [c] of n.branches) if (c) exprs.push(c);
      } else if (n.type === 'choice') {
        if (n.cond) exprs.push(n.cond);
        for (const v of interpNames(n.text)) setDefault(used, v, n.loc);
      } else if (n.type === 'text') {
        for (const v of interpNames(n.text)) setDefault(used, v, n.loc);
      }
      for (const e of exprs) {
        for (const v of e.names) setDefault(used, v, n.loc);
        for (const lab of e.labels) {
          if (!labels.has(lab)) add(ERROR, n.loc, `visited("${lab}") 의 단락 '${lab}' 이(가) 없습니다.`);
        }
      }
    }
  }
  for (const [v, loc] of used) {
    if (!assigned.has(v)) {
      add(WARNING, loc, `변수 '${v}' 에 값을 넣는 곳(default/set)이 없습니다. 오타가 아닌지 확인해 주세요. (값은 0 으로 취급)`);
    }
  }
  for (const [v, loc] of assigned) {
    if (!used.has(v)) add(INFO, loc, `변수 '${v}' 은(는) 값만 넣고 어디에서도 쓰지 않습니다.`);
  }

  if (opts.images) {
    const files = new Set(opts.images);
    const lower = new Map(opts.images.map((f) => [f.toLowerCase(), f]));
    const check = (rel, loc, what) => {
      const r = rel.replace(/\\/g, '/');
      if (!files.has(r)) {
        const other = lower.get(r.toLowerCase());
        if (other) {
          add(WARNING, loc, `${what} '${rel}' 의 대소문자가 실제 파일 '${other}' 과(와) 다릅니다. ` +
            'Windows 외의 운영체제에서는 열리지 않습니다.');
        } else {
          add(ERROR, loc, `${what} 파일 '${rel}' 이(가) images 폴더에 없습니다.`);
        }
        return;
      }
      const ext = r.slice(r.lastIndexOf('.')).toLowerCase();
      if (!IMAGE_EXT.includes(ext)) add(ERROR, loc, `'${rel}' 은(는) 지원하지 않는 이미지 형식입니다. (PNG, JPG, WebP 권장)`);
    };
    for (const label of labels.values()) {
      for (const n of walk(label.body)) if (n.type === 'image' && n.path) check(n.path, n.loc, '이미지');
    }
    if (opts.titleImage) check(opts.titleImage, null, '타이틀 이미지');
  }

  const stats = { labels: labels.size, choices: 0, endings: 0, chars: 0 };
  for (const label of labels.values()) {
    for (const n of walk(label.body)) {
      if (n.type === 'choice') stats.choices++;
      else if (n.type === 'end') stats.endings++;
      else if (n.type === 'text') stats.chars += [...n.text].length;
    }
  }

  issues.sort((a, b) => (LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level]) ||
    ((a.loc ? a.loc.file : '') < (b.loc ? b.loc.file : '') ? -1 : (a.loc ? a.loc.file : '') > (b.loc ? b.loc.file : '') ? 1 : 0) ||
    ((a.loc ? a.loc.line : 0) - (b.loc ? b.loc.line : 0)));

  const unreachable = new Set(seen ? [...labels.keys()].filter((n) => !seen.has(n)) : []);
  const endingLabels = new Set([...labels.values()]
    .filter((l) => [...walk(l.body)].some((n) => n.type === 'end')).map((l) => l.name));
  const errors = issues.filter((i) => i.level === ERROR);
  const warnings = issues.filter((i) => i.level === WARNING);
  const summary = `단락 ${stats.labels}개 · 선택지 ${stats.choices}개 · 엔딩 ${stats.endings}개 · ` +
    `본문 ${stats.chars.toLocaleString('ko-KR')}자 · 오류 ${errors.length}개 · 경고 ${warnings.length}개`;
  return { issues, errors, warnings, stats, summary, unreachable, endingLabels, story };
}

function issueText(i) {
  return `[${i.level}] ${i.loc ? i.loc + '  ' : ''}${i.message}`;
}

module.exports = { lint, issueText, ERROR, WARNING, INFO, IMAGE_EXT };
