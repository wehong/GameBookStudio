// 게임 진행 로직 (화면과 분리).
// 한 "페이지"는 단락 하나를 실행한 결과(이미지, 본문, 선택지)입니다.
// 저장과 '뒤로 가기'는 페이지에 들어서기 직전의 상태(스냅샷)를 기록하고,
// 필요할 때 그 단락을 다시 실행해 같은 페이지를 만들어 냅니다.
'use strict';

const { ExprError, Rng } = require('./expr');

const MAX_GOTO_CHAIN = 200;
const MAX_HISTORY = 200;

class RuntimeScriptError extends Error {
  constructor(message, loc = null) {
    super(loc ? `${loc}  ${message}` : message);
    this.loc = loc;
    this.plain = message;
  }
}

class Stop {}

function clone(v) { return JSON.parse(JSON.stringify(v)); }

function display(value) {
  if (value === true) return '참';
  if (value === false) return '거짓';
  if (value === null || value === undefined) return '';
  return String(value);
}

function interpolate(text, variables) {
  return text.replace(/\{\{|\}\}|\{([\p{L}\p{M}\p{N}_]+)\}/gu, (tok, name) => {
    if (tok === '{{') return '{';
    if (tok === '}}') return '}';
    return display(Object.prototype.hasOwnProperty.call(variables, name) ? variables[name] : 0);
  });
}

class Engine {
  constructor(story, start = 'start', showLocked = false) {
    this.story = story;
    this.start = start;
    this.showLocked = showLocked;
  }

  ctx(variables, visited, rng) {
    return { variables, visited, rng };
  }

  eval(expr, ctx, loc) {
    try {
      return expr.eval(ctx);
    } catch (e) {
      if (e instanceof ExprError) throw new RuntimeScriptError(e.message, loc);
      throw e;
    }
  }

  newGame(seed) {
    if (seed === undefined || seed === null) seed = Math.floor(Math.random() * 2147483647);
    const variables = {};
    const rng = new Rng(seed);
    const ctx = this.ctx(variables, {}, rng);
    for (const d of this.story.defaults) variables[d.name] = this.eval(d.expr, ctx, d.loc);
    return { label: this.start, variables, visited: {}, seed: rng.seed31() };
  }

  /** 스냅샷에서 시작해 페이지를 만듭니다. → { page, after } */
  runPage(entry) {
    const variables = clone(entry.variables);
    const visited = { ...entry.visited };
    const rng = new Rng(entry.seed);
    const ctx = this.ctx(variables, visited, rng);
    let labelName = entry.label;
    const passed = [];
    let page;
    let n = 0;
    for (;;) {
      if (++n > MAX_GOTO_CHAIN) {
        throw new RuntimeScriptError(
          `goto 가 ${MAX_GOTO_CHAIN}번 넘게 이어졌습니다. 단락끼리 서로 goto 하는 무한 반복인지 확인해 주세요.`);
      }
      const label = this.story.labels.get(labelName);
      if (!label) throw new RuntimeScriptError(`단락 '${labelName}'을(를) 찾을 수 없습니다.`);
      passed.push(labelName);
      visited[labelName] = (visited[labelName] || 0) + 1;
      page = { label: labelName, image: null, paragraphs: [], choices: [], ending: null, deadEnd: false };
      ctx.page = page;
      ctx.goto = null;
      try {
        this.exec(label.body, ctx);
      } catch (e) {
        if (!(e instanceof Stop)) throw e;
      }
      if (ctx.goto !== null) {
        if (page.paragraphs.length || page.image) {
          page.choices = [{ text: '계속', target: ctx.goto, enabled: true, node: null }];
          break;
        }
        labelName = ctx.goto;     // 보여 줄 내용이 없으면 바로 넘어감
        continue;
      }
      break;
    }
    page.labelsPassed = passed;
    const isEnding = page.ending !== null;
    if (!isEnding && !page.choices.some((c) => c.enabled)) page.deadEnd = true;
    const after = { label: page.label, variables, visited, seed: rng.seed31() };
    return { page, after };
  }

  exec(body, ctx) {
    for (const node of body) {
      switch (node.type) {
        case 'text':
          ctx.page.paragraphs.push(interpolate(node.text, ctx.variables));
          break;
        case 'image':
          ctx.page.image = node.path;
          break;
        case 'set':
          this.set(node, ctx);
          break;
        case 'if':
          for (const [cond, sub] of node.branches) {
            if (cond === null || this.truthy(this.eval(cond, ctx, node.loc))) {
              this.exec(sub, ctx);
              break;
            }
          }
          break;
        case 'choice': {
          const ok = node.cond === null || this.truthy(this.eval(node.cond, ctx, node.loc));
          if (ok || this.showLocked) {
            ctx.page.choices.push({ text: interpolate(node.text, ctx.variables), target: node.target,
              enabled: ok, node });
          }
          break;
        }
        case 'goto':
          ctx.goto = node.target;
          throw new Stop();
        case 'end':
          ctx.page.ending = node.title;
          ctx.page.choices = [];
          throw new Stop();
      }
    }
  }

  truthy(v) {
    return !(v === false || v === null || v === undefined || v === 0 || v === '');
  }

  set(node, ctx) {
    const value = this.eval(node.expr, ctx, node.loc);
    if (node.op === '=') { ctx.variables[node.name] = value; return; }
    const old = Object.prototype.hasOwnProperty.call(ctx.variables, node.name) ? ctx.variables[node.name] : 0;
    const numeric = (v) => typeof v === 'number' || typeof v === 'boolean';
    if (numeric(old) && numeric(value)) {
      ctx.variables[node.name] = node.op === '+=' ? Number(old) + Number(value) : Number(old) - Number(value);
    } else if (node.op === '+=' && typeof old === 'string' && typeof value === 'string') {
      ctx.variables[node.name] = old + value;
    } else {
      throw new RuntimeScriptError(
        `'${node.name}'(${JSON.stringify(old)})에 ${JSON.stringify(value)}을(를) 더하거나 뺄 수 없습니다.`, node.loc);
    }
  }

  /** 선택지를 고른 뒤 다음 페이지의 시작 상태 */
  choose(after, choice) {
    if (!choice.enabled) throw new RuntimeScriptError('선택할 수 없는 선택지입니다.');
    const variables = clone(after.variables);
    const visited = { ...after.visited };
    const rng = new Rng(after.seed);
    if (choice.node && choice.node.body.length) {
      const ctx = this.ctx(variables, visited, rng);
      ctx.page = { paragraphs: [], choices: [] };
      this.exec(choice.node.body, ctx);
    }
    return { label: choice.target, variables, visited, seed: rng.seed31() };
  }
}

/** 현재 페이지와 지나온 기록 (뒤로 가기, 저장) */
class Session {
  constructor(engine) {
    this.engine = engine;
    this.history = [];
    this.entry = null;
    this.page = null;
    this.after = null;
  }
  start(seed) { this.history = []; this.enter(this.engine.newGame(seed)); }
  startAt(label, seed) {
    this.history = [];
    const entry = this.engine.newGame(seed);
    entry.label = label;
    this.enter(entry);
  }
  enter(entry) {
    const { page, after } = this.engine.runPage(entry);
    this.entry = entry; this.page = page; this.after = after;
  }
  choose(index) {
    const choice = this.page.choices[index];
    const next = this.engine.choose(this.after, choice);
    const prev = this.entry;
    this.enter(next);
    this.history.push(prev);
    if (this.history.length > MAX_HISTORY) this.history.splice(0, this.history.length - MAX_HISTORY);
  }
  jump(label) {
    const base = this.after || this.engine.newGame();
    const next = { label, variables: clone(base.variables), visited: { ...base.visited }, seed: base.seed };
    const prev = this.entry;
    this.enter(next);
    if (prev) this.history.push(prev);
  }
  canGoBack() { return this.history.length > 0; }
  back() { if (this.history.length) this.enter(this.history.pop()); }
  reload(engine) { this.engine = engine; if (this.entry) this.enter(this.entry); }
  toJSON() { return { entry: this.entry, history: this.history.slice(-50) }; }
  load(data) {
    this.history = (data.history || []).map(clone);
    this.enter(clone(data.entry));
  }
}

module.exports = { Engine, Session, RuntimeScriptError, interpolate, display };
