// 조건식과 값 계산.
// 스크립트의 `if 금화 >= 3`, `set 체력 -= 2` 같은 식을 안전하게 계산합니다.
// Python 문법의 일부(비교, and/or/not, 사칙연산, visited(), random())만 지원하며,
// 지원하지 않는 구문은 스크립트를 읽는 시점에 오류로 알려 줍니다.
'use strict';

const CONSTANTS = {
  true: true, false: false, none: null,
  True: true, False: false, None: null,
  '참': true, '거짓': false,
};
const FUNCTIONS = new Set(['visited', 'random']);
const RESERVED = new Set(['and', 'or', 'not', 'if', 'elif', 'else', 'in', 'is']);

const IDENT_START = /[\p{L}_]/u;
const IDENT_PART = /[\p{L}\p{M}\p{N}_]/u;

class ExprError extends Error {}

// ------------------------------------------------------------------ 값 도우미

function pyRepr(v) {
  if (v === true) return 'True';
  if (v === false) return 'False';
  if (v === null || v === undefined) return 'None';
  if (typeof v === 'string') return "'" + v.replace(/\\/g, '\\\\').replace(/'/g, "\\'") + "'";
  return formatNumber(v);
}

function formatNumber(n) {
  if (Number.isInteger(n)) return String(n);
  return String(n);
}

function truthy(v) {
  return !(v === false || v === null || v === undefined || v === 0 || v === '' || Number.isNaN(v));
}

function isNum(v) {
  return typeof v === 'number' || typeof v === 'boolean';
}

function num(v) {
  return typeof v === 'boolean' ? (v ? 1 : 0) : v;
}

function pyEq(a, b) {
  if (isNum(a) && isNum(b)) return num(a) === num(b);
  return a === b;
}

function pyCompare(op, a, b) {
  if (op === '==') return pyEq(a, b);
  if (op === '!=') return !pyEq(a, b);
  let x, y;
  if (isNum(a) && isNum(b)) {
    x = num(a); y = num(b);
  } else if (typeof a === 'string' && typeof b === 'string') {
    x = a; y = b;
  } else {
    throw new ExprError(`서로 비교할 수 없는 값입니다: ${pyRepr(a)}, ${pyRepr(b)}`);
  }
  switch (op) {
    case '<': return x < y;
    case '<=': return x <= y;
    case '>': return x > y;
    case '>=': return x >= y;
  }
  throw new ExprError('지원하지 않는 비교입니다.');
}

function binop(op, a, b) {
  const bad = () => new ExprError(`서로 계산할 수 없는 값입니다: ${pyRepr(a)}, ${pyRepr(b)}`);
  if (op === '+') {
    if (isNum(a) && isNum(b)) return num(a) + num(b);
    if (typeof a === 'string' && typeof b === 'string') return a + b;
    throw bad();
  }
  if (op === '*') {
    if (isNum(a) && isNum(b)) return num(a) * num(b);
    if (typeof a === 'string' && isNum(b) && Number.isInteger(num(b))) return a.repeat(Math.max(0, num(b)));
    if (isNum(a) && typeof b === 'string' && Number.isInteger(num(a))) return b.repeat(Math.max(0, num(a)));
    throw bad();
  }
  if (!(isNum(a) && isNum(b))) throw bad();
  const x = num(a), y = num(b);
  switch (op) {
    case '-': return x - y;
    case '/':
      if (y === 0) throw new ExprError('0으로 나눌 수 없습니다.');
      return x / y;
    case '//':
      if (y === 0) throw new ExprError('0으로 나눌 수 없습니다.');
      return Math.floor(x / y);
    case '%':
      if (y === 0) throw new ExprError('0으로 나눌 수 없습니다.');
      return x - y * Math.floor(x / y);
  }
  throw bad();
}

// ------------------------------------------------------------------ 토큰

function tokenize(src) {
  const toks = [];
  let i = 0;
  const fail = () => { throw new ExprError(`식을 이해할 수 없습니다: ${src.trim()}`); };
  while (i < src.length) {
    const c = src[i];
    if (/\s/.test(c)) { i++; continue; }
    if (/[0-9]/.test(c) || (c === '.' && /[0-9]/.test(src[i + 1] || ''))) {
      const m = /^(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?/.exec(src.slice(i));
      toks.push({ t: 'num', v: Number(m[0]) });
      i += m[0].length;
      if (i < src.length && IDENT_PART.test(src[i])) fail();
      continue;
    }
    if (c === '"' || c === "'") {
      let j = i + 1, buf = '';
      const esc = { n: '\n', t: '\t', '\\': '\\', '"': '"', "'": "'" };
      while (j < src.length && src[j] !== c) {
        if (src[j] === '\\' && j + 1 < src.length) {
          buf += esc[src[j + 1]] !== undefined ? esc[src[j + 1]] : '\\' + src[j + 1];
          j += 2;
          continue;
        }
        buf += src[j++];
      }
      if (j >= src.length) fail();
      toks.push({ t: 'str', v: buf });
      i = j + 1;
      continue;
    }
    if (IDENT_START.test(c)) {
      let j = i + 1;
      while (j < src.length && IDENT_PART.test(src[j])) j++;
      toks.push({ t: 'name', v: src.slice(i, j) });
      i = j;
      continue;
    }
    const two = src.slice(i, i + 2);
    if (['//', '==', '!=', '<=', '>=', '**'].includes(two)) {
      toks.push({ t: 'op', v: two });
      i += 2;
      continue;
    }
    if ('+-*/%<>(),'.includes(c)) {
      toks.push({ t: 'op', v: c });
      i++;
      continue;
    }
    fail();
  }
  toks.push({ t: 'end' });
  return toks;
}

// ------------------------------------------------------------------ 구문 분석 (Python 우선순위)

class Parser {
  constructor(src) {
    this.src = src.trim();
    this.toks = tokenize(src);
    this.i = 0;
    this.names = new Set();
    this.labels = new Set();
  }
  fail() { throw new ExprError(`식을 이해할 수 없습니다: ${this.src}`); }
  peek() { return this.toks[this.i]; }
  isOp(v) { const t = this.peek(); return t.t === 'op' && t.v === v; }
  isName(v) { const t = this.peek(); return t.t === 'name' && t.v === v; }
  next() { return this.toks[this.i++]; }

  parse() {
    const e = this.orExpr();
    if (this.peek().t !== 'end') {
      const t = this.peek();
      if (t.t === 'op' && t.v === '**') throw new ExprError(`지원하지 않는 연산입니다: ${this.src}`);
      this.fail();
    }
    return e;
  }
  orExpr() {
    let e = this.andExpr();
    while (this.isName('or')) { this.next(); e = { k: 'or', a: e, b: this.andExpr() }; }
    return e;
  }
  andExpr() {
    let e = this.notExpr();
    while (this.isName('and')) { this.next(); e = { k: 'and', a: e, b: this.notExpr() }; }
    return e;
  }
  notExpr() {
    if (this.isName('not')) { this.next(); return { k: 'not', a: this.notExpr() }; }
    return this.compare();
  }
  compare() {
    const first = this.arith();
    const ops = [], rest = [];
    while (['==', '!=', '<', '<=', '>', '>='].some((o) => this.isOp(o))) {
      ops.push(this.next().v);
      rest.push(this.arith());
    }
    return ops.length ? { k: 'cmp', first, ops, rest } : first;
  }
  arith() {
    let e = this.term();
    while (this.isOp('+') || this.isOp('-')) { const op = this.next().v; e = { k: 'bin', op, a: e, b: this.term() }; }
    return e;
  }
  term() {
    let e = this.unary();
    while (this.isOp('*') || this.isOp('/') || this.isOp('//') || this.isOp('%')) {
      const op = this.next().v;
      e = { k: 'bin', op, a: e, b: this.unary() };
    }
    return e;
  }
  unary() {
    if (this.isOp('-') || this.isOp('+')) { const op = this.next().v; return { k: 'neg', op, a: this.unary() }; }
    return this.atom();
  }
  atom() {
    const t = this.next();
    if (t.t === 'num') return { k: 'const', v: t.v };
    if (t.t === 'str') return { k: 'const', v: t.v };
    if (t.t === 'op' && t.v === '(') {
      const e = this.orExpr();
      if (!this.isOp(')')) this.fail();
      this.next();
      return e;
    }
    if (t.t === 'name') {
      if (this.isOp('(')) return this.call(t.v);
      if (Object.prototype.hasOwnProperty.call(CONSTANTS, t.v)) return { k: 'const', v: CONSTANTS[t.v] };
      if (RESERVED.has(t.v)) this.fail();
      this.names.add(t.v);
      return { k: 'name', v: t.v };
    }
    this.fail();
  }
  call(fname) {
    this.next(); // (
    const args = [];
    if (!this.isOp(')')) {
      args.push(this.orExpr());
      while (this.isOp(',')) { this.next(); args.push(this.orExpr()); }
    }
    if (!this.isOp(')')) this.fail();
    this.next();
    if (!FUNCTIONS.has(fname)) {
      throw new ExprError(`사용할 수 있는 함수는 visited("단락"), random(최소, 최대) 뿐입니다: ${this.src}`);
    }
    if (fname === 'visited') {
      if (args.length !== 1 || args[0].k !== 'const' ||
          !(typeof args[0].v === 'string' || (typeof args[0].v === 'number' && Number.isInteger(args[0].v)))) {
        throw new ExprError(`visited는 visited("단락이름") 형태로 써야 합니다: ${this.src}`);
      }
      this.labels.add(String(args[0].v));
      return { k: 'visited', label: String(args[0].v) };
    }
    if (args.length !== 2) throw new ExprError(`random은 random(최소, 최대) 형태로 써야 합니다: ${this.src}`);
    return { k: 'random', a: args[0], b: args[1] };
  }
}

function evalNode(n, ctx) {
  switch (n.k) {
    case 'const': return n.v;
    case 'name': return Object.prototype.hasOwnProperty.call(ctx.variables, n.v) ? ctx.variables[n.v] : 0;
    case 'or': { const a = evalNode(n.a, ctx); return truthy(a) ? a : evalNode(n.b, ctx); }
    case 'and': { const a = evalNode(n.a, ctx); return truthy(a) ? evalNode(n.b, ctx) : a; }
    case 'not': return !truthy(evalNode(n.a, ctx));
    case 'neg': {
      const v = evalNode(n.a, ctx);
      if (!isNum(v)) throw new ExprError(`서로 계산할 수 없는 값입니다: ${pyRepr(v)}, ${pyRepr(0)}`);
      return n.op === '-' ? -num(v) : num(v);
    }
    case 'bin': return binop(n.op, evalNode(n.a, ctx), evalNode(n.b, ctx));
    case 'cmp': {
      let left = evalNode(n.first, ctx);
      for (let i = 0; i < n.ops.length; i++) {
        const right = evalNode(n.rest[i], ctx);
        if (!pyCompare(n.ops[i], left, right)) return false;
        left = right;
      }
      return true;
    }
    case 'visited': return ctx.visited[n.label] || 0;
    case 'random': {
      let lo = Math.trunc(num(evalNode(n.a, ctx)));
      let hi = Math.trunc(num(evalNode(n.b, ctx)));
      if (lo > hi) [lo, hi] = [hi, lo];
      return ctx.rng.randint(lo, hi);
    }
  }
  throw new ExprError('계산할 수 없는 식입니다.');
}

class Expr {
  constructor(source) {
    this.source = String(source).trim();
    if (!this.source) throw new ExprError('식이 비어 있습니다.');
    const p = new Parser(this.source);
    this.tree = p.parse();
    this.names = p.names;
    this.labels = p.labels;
  }
  eval(ctx) { return evalNode(this.tree, ctx); }
}

// 재현 가능한 난수 (저장/뒤로 가기 후에도 같은 결과)
class Rng {
  constructor(seed) { this.s = (seed >>> 0) || 0x9e3779b9; }
  next() {
    let t = (this.s = (this.s + 0x6d2b79f5) >>> 0);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  randint(lo, hi) { return lo + Math.floor(this.next() * (hi - lo + 1)); }
  seed31() { return Math.floor(this.next() * 2147483648); }
}

function isIdentifier(name) {
  if (!name || !IDENT_START.test(name[0])) return false;
  for (const ch of name.slice(1)) if (!IDENT_PART.test(ch)) return false;
  return !RESERVED.has(name) && !Object.prototype.hasOwnProperty.call(CONSTANTS, name);
}

module.exports = { Expr, ExprError, Rng, truthy, pyRepr, isIdentifier, CONSTANTS };
