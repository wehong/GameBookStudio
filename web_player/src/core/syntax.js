// 구문 강조용 토크나이저 (에디터와 가이드가 함께 사용).
// tokenizeLine(line, inBlock) → { spans: [[시작, 끝, 종류]], inBlock }
// 종류: keyword, labeldef, target, variable, string, interp, comment, number, const, func, arrow
'use strict';

const STATEMENT_KEYWORDS = new Set(['label', 'default', 'set', 'if', 'elif', 'else', 'choice', 'goto', 'end', 'image']);
const INLINE_KEYWORDS = new Set(['if', 'and', 'or', 'not']);
const CONSTS = new Set(['true', 'false', 'True', 'False', 'none', 'None', '참', '거짓', '없음']);
const FUNCS = new Set(['visited', 'random']);
const WORD_RE = /[\p{L}\p{M}\p{N}_]+/uy;
const INTERP_RE = /\{\{|\}\}|\{[\p{L}\p{M}\p{N}_]+\}/gu;

function stringSpans(line, s, e, out) {
  out.push([s, e, 'string']);
  INTERP_RE.lastIndex = s;
  let m;
  while ((m = INTERP_RE.exec(line)) && m.index < e) {
    if (m[0].length > 2 && m.index + m[0].length <= e) out.push([m.index, m.index + m[0].length, 'interp']);
  }
}

function quoteEnd(line, i, q) {
  while (i < line.length) {
    const c = line[i];
    if (c === '\\') { i += 2; continue; }
    if (c === q) return i + 1;
    i++;
  }
  return line.length;
}

function tokenizeLine(line, inBlock) {
  const spans = [];
  let i = 0;
  const n = line.length;
  if (inBlock) {
    const k = line.indexOf('"""');
    if (k < 0) { stringSpans(line, 0, n, spans); return { spans, inBlock: true }; }
    stringSpans(line, 0, k + 3, spans);
    i = k + 3;
    inBlock = false;
  }
  let first = null;
  let expect = null;
  while (i < n) {
    const c = line[i];
    if (c === ' ' || c === '\t') { i++; continue; }
    if (c === '#') { spans.push([i, n, 'comment']); break; }
    if (line.startsWith('"""', i)) {
      const k = line.indexOf('"""', i + 3);
      if (k < 0) { stringSpans(line, i, n, spans); return { spans, inBlock: true }; }
      stringSpans(line, i, k + 3, spans);
      i = k + 3;
      first = first || '"';
      continue;
    }
    if (c === '"' || c === "'") {
      const e = quoteEnd(line, i + 1, c);
      stringSpans(line, i, e, spans);
      i = e;
      first = first || '"';
      continue;
    }
    if (line.startsWith('->', i)) { spans.push([i, i + 2, 'arrow']); i += 2; expect = 'target'; continue; }
    WORD_RE.lastIndex = i;
    const m = WORD_RE.exec(line);
    if (m) {
      const w = m[0], s = i, e = i + w.length;
      if (expect) { spans.push([s, e, expect]); expect = null; }
      else if (first === null && STATEMENT_KEYWORDS.has(w)) {
        spans.push([s, e, 'keyword']);
        expect = { label: 'labeldef', goto: 'target', set: 'variable', default: 'variable' }[w] || null;
      } else if (INLINE_KEYWORDS.has(w)) spans.push([s, e, 'keyword']);
      else if (CONSTS.has(w)) spans.push([s, e, 'const']);
      else if (FUNCS.has(w) && line[e] === '(') spans.push([s, e, 'func']);
      else if (/^\d+(\.\d+)?$/.test(w)) spans.push([s, e, 'number']);
      if (first === null) first = w;
      i = e;
      continue;
    }
    i++;
  }
  return { spans, inBlock };
}

function tokenize(source) {
  let inBlock = false;
  return source.split('\n').map((line) => {
    const r = tokenizeLine(line, inBlock);
    inBlock = r.inBlock;
    return r.spans;
  });
}

const LABEL_LINE_RE = /^label\s+([\p{L}\p{M}\p{N}_]+)\s*:/u;

/** 1부터 센 줄 번호 lineno 가 속한 단락 이름 */
function labelAtLine(lines, lineno) {
  for (let i = Math.min(lineno, lines.length) - 1; i >= 0; i--) {
    const m = LABEL_LINE_RE.exec(lines[i]);
    if (m) return m[1];
  }
  return null;
}

function highlightHTML(code) {
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const lines = code.split('\n');
  const toks = tokenize(code);
  return lines.map((line, li) => {
    const spans = toks[li];
    const bounds = new Set([0, line.length]);
    for (const [s, e] of spans) { bounds.add(s); bounds.add(e); }
    const b = [...bounds].sort((x, y) => x - y);
    let out = '';
    for (let k = 0; k < b.length - 1; k++) {
      const a = b[k], z = b[k + 1];
      let kind = null;
      for (const [s, e, t] of spans) if (s <= a && z <= e) kind = (kind === null || t === 'interp') ? t : kind;
      const piece = esc(line.slice(a, z));
      out += kind ? `<span class="t-${kind}">${piece}</span>` : piece;
    }
    return out;
  }).join('\n');
}

module.exports = { tokenize, tokenizeLine, labelAtLine, highlightHTML, LABEL_LINE_RE, STATEMENT_KEYWORDS };
