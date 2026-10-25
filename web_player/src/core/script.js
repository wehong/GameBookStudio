// 게임북 스크립트(.gb) 파서. 문법은 docs/script_guide.md 를 참고하세요.
'use strict';

const { Expr, ExprError, isIdentifier } = require('./expr');

const NAME_RE = /^[\p{L}\p{M}\p{N}_]+$/u;       // 단락 이름: 한글, 영문, 숫자, _
const SET_RE = /^([\p{L}\p{M}\p{N}_]+)\s*(\+=|-=|=)\s*(.+)$/u;

class Loc {
  constructor(file, line) { this.file = file; this.line = line; }
  toString() { return `${basename(this.file)}:${this.line}`; }
}

function basename(p) {
  const parts = String(p).split(/[\\/]/);
  return parts[parts.length - 1];
}

class Story {
  constructor() {
    this.labels = new Map();   // 이름 → {name, body, loc}
    this.defaults = [];        // {name, expr, loc}
    this.errors = [];          // {loc, message}
    this.files = [];
  }
}

function* walk(body) {
  for (const node of body) {
    yield node;
    if (node.type === 'if') {
      for (const [, sub] of node.branches) yield* walk(sub);
    } else if (node.type === 'choice') {
      yield* walk(node.body);
    }
  }
}

// ------------------------------------------------------------------ 줄 단위 전처리

function stripComment(s) {
  let quote = null;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (quote) {
      if (c === '\\') { i++; continue; }
      if (c === quote) quote = null;
    } else if (c === '"' || c === "'") {
      quote = c;
    } else if (c === '#') {
      return s.slice(0, i).trimEnd();
    }
  }
  return s.trimEnd();
}

function expandTabs(line) {
  if (!line.includes('\t')) return line;
  let out = '';
  for (const ch of line) {
    if (ch === '\t') out += ' '.repeat(4 - (out.length % 4));
    else out += ch;
  }
  return out;
}

function leading(line) {
  return line.length - line.replace(/^ +/, '').length;
}

function dedentBlock(lines) {
  while (lines.length && !lines[0].trim()) lines.shift();
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
  const ind = lines.filter((l) => l.trim()).map(leading);
  const cut = ind.length ? Math.min(...ind) : 0;
  return lines.map((l) => l.slice(cut).trimEnd()).join('\n');
}

function logicalLines(source, filename, errors) {
  const raw = source.replace(/\r\n?/g, '\n').split('\n').map(expandTabs);
  const out = [];
  let i = 0;
  while (i < raw.length) {
    const line = raw[i];
    const stripped = line.trim();
    const lineno = i + 1;
    const indent = leading(line);
    i++;
    if (!stripped || stripped.startsWith('#')) continue;
    if (stripped.startsWith('"""')) {
      const rest = stripped.slice(3);
      const k = rest.indexOf('"""');
      if (k >= 0) {
        const after = rest.slice(k + 3).trim();
        if (after && !after.startsWith('#')) {
          errors.push({ loc: new Loc(filename, lineno), message: '닫는 """ 뒤에 다른 내용이 있습니다.' });
        }
        out.push({ indent, text: '"""', lineno, block: rest.slice(0, k).trim() });
        continue;
      }
      const body = rest.trim() ? [rest] : [];
      let closed = false;
      while (i < raw.length) {
        const l2 = raw[i++];
        const q = l2.indexOf('"""');
        if (q >= 0) {
          const before = l2.slice(0, q);
          if (before.trim()) body.push(before);
          closed = true;
          break;
        }
        body.push(l2);
      }
      if (!closed) errors.push({ loc: new Loc(filename, lineno), message: '여러 줄 본문을 닫는 """ 가 없습니다.' });
      out.push({ indent, text: '"""', lineno, block: dedentBlock(body) });
      continue;
    }
    out.push({ indent, text: stripComment(stripped), lineno, block: null });
  }
  return out;
}

// ------------------------------------------------------------------ 문자열

function readString(s, pos = 0) {
  const quote = s[pos];
  if (quote !== '"' && quote !== "'") throw new Error('따옴표로 시작하는 문자열이 필요합니다.');
  const esc = { n: '\n', t: '\t', '\\': '\\', '"': '"', "'": "'" };
  let buf = '';
  let i = pos + 1;
  while (i < s.length) {
    const c = s[i];
    if (c === '\\' && i + 1 < s.length) {
      buf += esc[s[i + 1]] !== undefined ? esc[s[i + 1]] : '\\' + s[i + 1];
      i += 2;
      continue;
    }
    if (c === quote) return [buf, i + 1];
    buf += c;
    i++;
  }
  throw new Error('문자열을 닫는 따옴표가 없습니다.');
}

function findArrow(s) {
  let quote = null;
  for (let i = 0; i < s.length - 1; i++) {
    const c = s[i];
    if (quote) {
      if (c === '\\') { i++; continue; }
      if (c === quote) quote = null;
    } else if (c === '"' || c === "'") {
      quote = c;
    } else if (s.startsWith('->', i)) {
      return i;
    }
  }
  return -1;
}

// ------------------------------------------------------------------ 파서

class Parser {
  constructor(filename, story) {
    this.filename = filename;
    this.story = story;
    this.lines = [];
    this.pos = 0;
  }
  error(line, msg) { this.story.errors.push({ loc: new Loc(this.filename, line.lineno), message: msg }); }
  loc(line) { return new Loc(this.filename, line.lineno); }
  expr(line, src) {
    try {
      return new Expr(src);
    } catch (e) {
      if (e instanceof ExprError) { this.error(line, e.message); return null; }
      throw e;
    }
  }

  parse(source) {
    this.lines = logicalLines(source, this.filename, this.story.errors);
    this.pos = 0;
    while (this.pos < this.lines.length) {
      const line = this.lines[this.pos++];
      if (line.indent !== 0) {
        this.error(line, '최상위 문장은 들여쓰지 않아야 합니다. (label 또는 default)');
        this.skipBlock(line.indent);
        continue;
      }
      const text = line.text;
      if (line.block === null && (text.startsWith('label ') || text.startsWith('label:'))) {
        this.parseLabel(line);
      } else if (line.block === null && text.startsWith('default ')) {
        this.parseDefault(line);
      } else {
        this.error(line, 'label 밖에는 label 과 default 만 쓸 수 있습니다.');
        this.skipBlock(0);
      }
    }
  }

  skipBlock(indent) {
    while (this.pos < this.lines.length && this.lines[this.pos].indent > indent) this.pos++;
  }

  parseDefault(line) {
    const m = SET_RE.exec(line.text.slice('default '.length).trim());
    if (!m || m[2] !== '=') {
      this.error(line, "default 는 'default 이름 = 값' 형태로 써야 합니다.");
      return;
    }
    if (!isIdentifier(m[1])) {
      this.error(line, `'${m[1]}'은(는) 변수 이름으로 쓸 수 없습니다.`);
      return;
    }
    const e = this.expr(line, m[3]);
    if (e) this.story.defaults.push({ name: m[1], expr: e, loc: this.loc(line) });
  }

  parseLabel(line) {
    let head = line.text.slice('label'.length).trim();
    if (!head.endsWith(':')) {
      this.error(line, 'label 줄은 콜론(:)으로 끝나야 합니다. 예) label 동굴:');
    }
    let name = head.replace(/:+$/, '').trim();
    if (!NAME_RE.test(name)) {
      this.error(line, `단락 이름 '${name}'이(가) 올바르지 않습니다. 한글, 영문, 숫자, _ 만 쓸 수 있습니다.`);
      name = null;
    }
    const body = this.parseBlock(line, 'label');
    if (!body.length) this.error(line, '단락에 내용이 없습니다. 아래 줄을 들여써서 내용을 적어 주세요.');
    if (name === null) return;
    if (this.story.labels.has(name)) {
      const prev = this.story.labels.get(name);
      this.error(line, `단락 '${name}'이(가) 이미 ${prev.loc}에 있습니다.`);
      return;
    }
    let n = 0;
    for (const node of walk(body)) {
      if (node.type === 'choice') node.uid = `${name}#${n++}`;
    }
    this.story.labels.set(name, { name, body, loc: this.loc(line) });
  }

  parseBlock(header, context) {
    if (this.pos >= this.lines.length || this.lines[this.pos].indent <= header.indent) return [];
    const indent = this.lines[this.pos].indent;
    const body = [];
    while (this.pos < this.lines.length) {
      const line = this.lines[this.pos];
      if (line.indent <= header.indent) break;
      if (line.indent !== indent) {
        this.error(line, '들여쓰기가 위 줄들과 맞지 않습니다.');
        this.pos++;
        this.skipBlock(line.indent);
        continue;
      }
      this.pos++;
      const node = this.parseStatement(line, body, context);
      if (node) body.push(node);
    }
    return body;
  }

  textOk(line, context) {
    if (context === 'choice') {
      this.error(line, '선택지 블록 안에는 본문을 쓸 수 없습니다. 선택 후 보여 줄 내용은 이동할 단락에 적어 주세요.');
      return false;
    }
    return true;
  }

  parseStatement(line, body, context) {
    const loc = this.loc(line);
    const text = line.text;

    if (line.block !== null) {
      return this.textOk(line, context) ? { type: 'text', text: line.block, loc } : null;
    }
    if (text[0] === '"' || text[0] === "'") {
      let value, end;
      try {
        [value, end] = readString(text);
      } catch (e) {
        this.error(line, e.message);
        return null;
      }
      if (text.slice(end).trim()) this.error(line, '본문 문자열 뒤에 다른 내용이 있습니다.');
      return this.textOk(line, context) ? { type: 'text', text: value, loc } : null;
    }

    const sp = text.indexOf(' ');
    let word = sp < 0 ? text : text.slice(0, sp);
    const rest = sp < 0 ? '' : text.slice(sp + 1).trim();
    if (word === 'else:') word = 'else';

    if (word === 'set') {
      const m = SET_RE.exec(rest);
      if (!m) {
        this.error(line, "set 은 'set 이름 = 값', 'set 이름 += 값', 'set 이름 -= 값' 형태로 씁니다.");
        return null;
      }
      if (!isIdentifier(m[1])) {
        this.error(line, `'${m[1]}'은(는) 변수 이름으로 쓸 수 없습니다.`);
        return null;
      }
      const e = this.expr(line, m[3]);
      return e ? { type: 'set', name: m[1], op: m[2], expr: e, loc } : null;
    }

    if (word === 'if') return this.parseIf(line, context);

    if (word === 'elif' || word === 'else') {
      const prev = body[body.length - 1];
      if (!prev || prev.type !== 'if' || prev.branches[prev.branches.length - 1][0] === null) {
        this.error(line, `${word} 앞에 짝이 되는 if 가 없습니다.`);
        this.parseBlock(line, context);
        return null;
      }
      if (word === 'else') {
        if (text.replace(/ /g, '') !== 'else:') this.error(line, "else 는 'else:' 로만 씁니다.");
        prev.branches.push([null, this.parseBlock(line, context)]);
      } else {
        const cond = this.condHeader(line, rest);
        prev.branches.push([cond || FALSE_EXPR, this.parseBlock(line, context)]);
      }
      return null;
    }

    const choiceOnly = '선택지 블록 안에서는 set 과 if 만 쓸 수 있습니다.';
    if (word === 'image') {
      if (context === 'choice') { this.error(line, choiceOnly); return null; }
      if (['none', 'None', '없음'].includes(rest)) return { type: 'image', path: null, loc };
      try {
        const [value] = readString(rest);
        return { type: 'image', path: value, loc };
      } catch (e) {
        this.error(line, '이미지는 image "파일이름.png" 형태로 씁니다.');
        return null;
      }
    }

    if (word === 'choice') {
      if (context === 'choice') { this.error(line, '선택지 블록 안에 다른 선택지를 둘 수 없습니다.'); return null; }
      return this.parseChoice(line, rest);
    }

    if (word === 'goto') {
      if (context === 'choice') {
        this.error(line, '선택지 블록 안에서는 set 과 if 만 쓸 수 있습니다. (이동할 곳은 -> 뒤에 씁니다)');
        return null;
      }
      if (!NAME_RE.test(rest)) { this.error(line, 'goto 뒤에는 단락 이름을 씁니다. 예) goto 동굴'); return null; }
      return { type: 'goto', target: rest, loc };
    }

    if (word === 'end') {
      if (context === 'choice') { this.error(line, choiceOnly); return null; }
      let title = '';
      if (rest) {
        try {
          [title] = readString(rest);
        } catch (e) {
          this.error(line, '엔딩 제목은 따옴표로 감싸 주세요. 예) end "행복한 결말"');
        }
      }
      return { type: 'end', title, loc };
    }

    if (word === 'label' || word === 'default') {
      this.error(line, `${word} 는 들여쓰지 않고 맨 앞에 써야 합니다.`);
      return null;
    }
    this.error(line, `알 수 없는 문장입니다: ${text}`);
    return null;
  }

  condHeader(line, rest) {
    if (!rest.endsWith(':')) this.error(line, '조건 줄은 콜론(:)으로 끝나야 합니다.');
    else rest = rest.slice(0, -1);
    return this.expr(line, rest);
  }

  parseIf(line, context) {
    const cond = this.condHeader(line, line.text.slice(2).trim());
    const body = this.parseBlock(line, context);
    if (!body.length) this.error(line, 'if 아래에 들여쓴 내용이 없습니다.');
    return { type: 'if', branches: [[cond || FALSE_EXPR, body]], loc: this.loc(line) };
  }

  parseChoice(line, rest) {
    const loc = this.loc(line);
    if (rest[0] !== '"' && rest[0] !== "'") {
      this.error(line, '선택지는 choice "보여 줄 글" -> 단락이름 형태로 씁니다.');
      return null;
    }
    let text, end;
    try {
      [text, end] = readString(rest);
    } catch (e) {
      this.error(line, e.message);
      return null;
    }
    let tail = rest.slice(end).trim();
    const hasBlock = tail.endsWith(':');
    if (hasBlock) tail = tail.slice(0, -1).trimEnd();
    const arrow = findArrow(tail);
    if (arrow < 0) {
      this.error(line, '선택지에 이동할 단락이 없습니다. 예) choice "문을 연다" -> 방안');
      if (hasBlock) this.parseBlock(line, 'choice');
      return null;
    }
    const before = tail.slice(0, arrow).trim();
    let target = tail.slice(arrow + 2).trim();
    let cond = null;
    if (before) {
      if (!before.startsWith('if ')) {
        this.error(line, '선택지 조건은 if 로 시작해야 합니다. 예) choice "..." if 횃불 -> 동굴');
      } else {
        cond = this.expr(line, before.slice(3)) || FALSE_EXPR;
      }
    }
    if (!NAME_RE.test(target)) {
      this.error(line, `이동할 단락 이름 '${target}'이(가) 올바르지 않습니다.`);
      target = '';
    }
    const body = hasBlock ? this.parseBlock(line, 'choice') : [];
    if (hasBlock && !body.length) this.error(line, '선택지 줄이 콜론(:)으로 끝났지만 아래에 들여쓴 내용이 없습니다.');
    return { type: 'choice', text, cond, target, body, loc, uid: '' };
  }
}

// 식에 오류가 있을 때 대신 쓰는 '거짓' (오류는 이미 보고됨)
const FALSE_EXPR = new Expr('false');

function parseSource(source, filename = '<script>', story = null) {
  story = story || new Story();
  new Parser(filename, story).parse(source);
  return story;
}

/** files: [{path, text}] 를 하나의 이야기로 합칩니다. (파일 이름 순서) */
function parseFiles(files) {
  const story = new Story();
  const sorted = [...files].sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
  if (!sorted.length) {
    story.errors.push({ loc: new Loc('script', 0), message: '스크립트(.gb) 파일이 하나도 없습니다.' });
  }
  for (const f of sorted) {
    story.files.push(f.path);
    if (f.error) {
      story.errors.push({ loc: new Loc(f.path, 0), message: f.error });
      continue;
    }
    parseSource(f.text, f.path, story);
  }
  return story;
}

module.exports = {
  Story, Loc, walk, parseSource, parseFiles, stripComment, readString, NAME_RE, basename,
};
