// 게임 화면. 앱 안(개발 모드)과 내보낸 HTML(단독 실행) 모두에서 쓰입니다.
// host 가 데이터 읽기·저장 방법을 제공합니다 (player-app.js / player-standalone.js).
'use strict';

const { parseFiles } = require('../core/script');
const { Engine, Session, RuntimeScriptError } = require('../core/runtime');
const { lint } = require('../core/lint');
const { el, modal, pickBox, toast, issuesList } = require('./ui');

const SLOTS = 10;

class Game {
  constructor(root, host) {
    this.root = root;
    this.host = host;
    this.dev = !!host.dev;
    this.mode = 'title';          // title | play | error
    this.session = null;
    this.engine = null;
    this.story = null;
    this.data = null;
    this.errors = [];
    this.fontSize = 15;
    this.theme = 'paper';
    this.imageVersion = 0;
    this.build();
    this.bindKeys();
    addEventListener('resize', () => this.rescale());
  }

  // ---------------------------------------------------------------- 화면 틀
  build() {
    this.root.innerHTML = '';
    this.page = el('article', { id: 'page' });
    this.desk = el('div', { id: 'desk' }, this.page);
    this.status = el('footer', { id: 'status' });
    this.root.append(this.desk, this.status);
  }

  rescale() {
    const [w0, h0] = (this.data && this.data.config.window) || [1024, 760];
    let k = Math.max(0.6, Math.min(3, Math.min(innerWidth / (w0 || 1024), innerHeight / (h0 || 760))));
    if (innerWidth < 700) k = Math.max(k, 0.85);   // 휴대폰처럼 좁은 화면에서도 읽을 수 있는 크기
    const s = document.documentElement.style;
    s.setProperty('--k', k.toFixed(3));
    s.setProperty('--fs', String(this.fontSize));
  }

  applyConfig() {
    const c = this.data.config;
    this.fontSize = Number(c.font_size) || 15;
    if (!this.themeSetByUser) this.theme = c.theme === 'night' ? 'night' : 'paper';
    document.body.classList.toggle('night', this.theme === 'night');
    const f = String(c.font || '');
    const fam = f === 'serif' || f === '명조' ? 'var(--serif)' : (f === 'sans' || f === '고딕' || f === '') ? 'var(--ui)'
      : `"${f.replace(/"/g, '')}", var(--serif)`;
    document.documentElement.style.setProperty('--body-font', fam);
    this.host.setTitle(c.title || '게임북');
    this.rescale();
  }

  // ---------------------------------------------------------------- 읽기
  async load(initial = false) {
    try {
      this.data = await this.host.load();
    } catch (e) {
      this.showError('프로젝트를 읽지 못했습니다', [{ loc: null, message: e.message }]);
      return;
    }
    this.imageVersion++;
    this.applyConfig();
    const story = parseFiles(this.data.scripts);
    this.story = story;
    let errors = [...story.errors];
    const start = this.data.config.start || 'start';
    if (!errors.length && !story.labels.has(start)) {
      errors = [{ loc: null, message: `시작 단락 '${start}' 이(가) 없습니다. (game.json 의 "start" 확인)` }];
    }
    if (this.data.configError) errors.unshift({ loc: null, message: this.data.configError });
    if (errors.length) {
      this.engine = null;
      this.showError('스크립트에 오류가 있습니다', errors);
      return;
    }
    this.engine = new Engine(story, start, !!this.data.config.show_locked_choices);
    if (this.session && (this.mode === 'play' || this.mode === 'error') && this.session.entry) {
      try {
        this.session.reload(this.engine);
        this.mode = 'play';
      } catch (e) {
        return this.runtimeError(e);
      }
    } else if (this.mode === 'error' || initial) {
      this.mode = 'title';
    }
    this.render();
    if (!initial) toast('스크립트를 다시 읽었습니다');
  }

  runtimeError(e) {
    if (e instanceof RuntimeScriptError) this.showError('실행 중 오류', [{ loc: e.loc, message: e.plain }]);
    else this.showError('실행 중 오류', [{ loc: null, message: String(e && e.message || e) }]);
  }

  // ---------------------------------------------------------------- 진행
  newGame() {
    if (!this.engine) return;
    this.session = new Session(this.engine);
    try { this.session.start(); this.mode = 'play'; } catch (e) { return this.runtimeError(e); }
    this.render();
  }

  startAt(label) {
    if (!this.engine) return;
    if (!this.story.labels.has(label)) { toast(`단락 '${label}' 이(가) 없습니다`); return; }
    this.session = new Session(this.engine);
    try { this.session.startAt(label); this.mode = 'play'; } catch (e) { return this.runtimeError(e); }
    this.render();
    toast(`'${label}' 단락부터 시작합니다`);
  }

  showTitle() { if (this.engine) { this.mode = 'title'; this.render(); } }

  endActions() {
    const acts = [['처음부터 다시 하기', () => this.newGame()], ['타이틀로 돌아가기', () => this.showTitle()]];
    if (this.session && this.session.canGoBack()) acts.unshift(['뒤로 가기', () => this.back()]);
    return acts;
  }

  pick(i) {
    if (this.mode !== 'play' || !this.session) return;
    const page = this.session.page;
    if (page.ending !== null || page.deadEnd) {
      const a = this.endActions()[i];
      if (a) a[1]();
      return;
    }
    const c = page.choices[i];
    if (!c || !c.enabled) return;
    try { this.session.choose(i); } catch (e) { return this.runtimeError(e); }
    this.render(true);
  }

  back() {
    if (this.mode === 'error' && this.session && this.session.canGoBack()) this.mode = 'play';
    if (this.mode !== 'play' || !this.session || !this.session.canGoBack()) return;
    try { this.session.back(); } catch (e) { return this.runtimeError(e); }
    this.render();
  }

  // ---------------------------------------------------------------- 그리기
  render(scrollTop = true) {
    this.page.className = this.mode;
    if (this.mode === 'title') this.renderTitle();
    else if (this.mode === 'error') this.renderError();
    else this.renderPlay(scrollTop);
    this.updateStatus();
    if (this.varsPanel) this.drawVars();
  }

  img(rel, cls) {
    if (!rel) return null;
    const url = this.host.imageUrl(rel, this.imageVersion);
    if (!url) return el('div', { class: 'imgmissing' }, `[이미지를 찾을 수 없음: ${rel}]`);
    const im = el('img', { class: cls, src: url, alt: '', draggable: 'false' });
    im.onerror = () => im.replaceWith(el('div', { class: 'imgmissing' }, `[이미지를 열 수 없음: ${rel}]`));
    // 창 크기 배율에 맞춰 그림도 커지도록 (원본 크기 × 배율, 단 칸을 넘지 않게)
    im.onload = () => { im.style.width = `min(100%, calc(${im.naturalWidth} * var(--u)))`; };
    return im;
  }

  async renderTitle() {
    const c = this.data.config;
    const latest = await this.latestSlot();
    const items = [['새로 시작하기', () => this.newGame()]];
    if (latest) items.push(['이어하기', () => this.loadSlot(latest)]);
    items.push(['불러오기', () => this.slotDialog('load')]);
    if (this.host.quit) items.push(['끝내기', () => this.host.quit()]);
    if (this.mode !== 'title') return;
    this.page.replaceChildren(el('div', { class: 'titlebox' },
      this.img(c.title_image, 'titleimg'),
      el('h1', {}, c.title || '게임북'),
      c.author ? el('div', { class: 'author' }, c.author) : null,
      el('hr'),
      el('div', { class: 'menu' }, items.map(([t, fn], i) => el('button', { class: 'choice center', onclick: fn,
        'data-key': i + 1 }, t)))));
  }

  renderPlay(scrollTop) {
    const page = this.session.page;
    const text = el('div', { class: 'text' });
    for (const para of page.paragraphs) {
      const p = el('p');
      para.split('\n').forEach((line, i) => { if (i) p.append(el('br')); p.append(line); });
      text.append(p);
    }
    if (page.ending !== null) text.append(el('p', { class: 'ending' }, page.ending ? `— ${page.ending} —` : '— 끝 —'));
    else if (page.deadEnd) {
      text.append(el('p', { class: 'note' }, this.dev
        ? '⚠ 막다른 단락입니다: 보여 줄 선택지가 없습니다. (개발 모드에서만 보이는 안내)'
        : '이야기가 여기서 멈췄습니다.'));
    }
    const entries = (page.ending !== null || page.deadEnd)
      ? this.endActions().map(([t]) => ({ text: t, enabled: true }))
      : page.choices;
    const choices = el('nav', { class: 'choices' }, entries.map((c, i) => el('button', {
      class: 'choice' + (c.enabled ? '' : ' locked'), disabled: !c.enabled, onclick: () => this.pick(i),
    }, i < 9 ? el('span', { class: 'num' }, `${i + 1}.`) : null, el('span', {}, c.text))));
    const scroll = el('div', { class: 'scroll' }, page.image ? el('figure', {}, this.img(page.image, 'pageimg')) : null, text);
    this.page.replaceChildren(scroll, choices);
    if (scrollTop) scroll.scrollTop = 0;
  }

  renderError() {
    const tip = this.host.openSource
      ? '위치를 누르면 에디터에서 그 줄이 열립니다. 고쳐서 저장하면 자동으로 다시 읽습니다.'
      : this.dev ? '스크립트를 고쳐서 저장하면 자동으로 다시 읽습니다.' : '';
    const list = el('div', { class: 'errlist' }, this.errors.map((e) => el('div', { class: 'err' },
      e.loc ? el('a', { class: 'loc', onclick: () => this.host.openSource && this.host.openSource(e.loc.file, e.loc.line) },
        String(e.loc)) : null, ' ', e.message)));
    const btns = el('div', { class: 'row' });
    if (this.host.openSource && this.errors.some((e) => e.loc)) {
      btns.append(el('button', { class: 'choice inline', onclick: () => this.openInEditor() }, '에디터에서 열기 (F4)'));
    }
    if (this.dev) btns.append(el('button', { class: 'choice inline', onclick: () => this.load() }, '다시 읽기 (F5)'));
    if (this.session && this.session.canGoBack()) btns.append(el('button', { class: 'choice inline', onclick: () => this.back() }, '뒤로 가기'));
    this.page.replaceChildren(el('div', { class: 'errorbox' }, el('h2', {}, this.errorTitle), tip ? el('div', { class: 'tip' }, tip) : null, list, btns));
  }

  showError(title, errors) {
    this.mode = 'error';
    this.errorTitle = title;
    this.errors = errors;
    this.render();
  }

  updateStatus() {
    let text;
    if (this.dev && this.mode === 'play' && this.session && this.session.page) {
      const page = this.session.page;
      const label = this.story.labels.get(page.label);
      const passed = page.labelsPassed.length > 1 ? page.labelsPassed.join(' → ') : page.label;
      text = `단락: ${passed}${label ? `  (${label.loc})` : ''}      ${this.host.openSource ? 'F4 에디터 · ' : ''}F5 다시 읽기 · F6 이동 · F2 변수 · F7 검사`;
    } else if (this.dev) {
      text = '개발 모드 · 스크립트를 저장하면 자동으로 반영됩니다';
    } else {
      text = '1~9 선택 · Backspace 뒤로 · Ctrl+S 저장 · Ctrl+O 불러오기';
    }
    this.status.textContent = text;
  }

  // ---------------------------------------------------------------- 저장
  async latestSlot() {
    const list = await this.host.listSaves().catch(() => ({}));
    let best = null, bestTime = '';
    for (const [slot, meta] of Object.entries(list)) if (meta && meta.time > bestTime) { best = Number(slot); bestTime = meta.time; }
    return best;
  }

  async loadSlot(slot) {
    let data;
    try { data = await this.host.readSave(slot); } catch { return; }
    const s = new Session(this.engine);
    try {
      s.load(data.session);
    } catch (e) {
      modal({ title: '불러오기 실패', body: `저장 파일을 불러올 수 없습니다. 스크립트가 바뀌어 단락이 없어졌을 수 있습니다.\n\n${e.message}` });
      return;
    }
    this.session = s;
    this.mode = 'play';
    this.render();
    toast(`슬롯 ${slot}에서 불러왔습니다`);
  }

  async slotDialog(kind) {
    if (!this.engine) return;
    if (kind === 'save' && (this.mode !== 'play' || !this.session)) { toast('게임 중에만 저장할 수 있습니다'); return; }
    const list = await this.host.listSaves().catch(() => ({}));
    const ul = el('ul', { class: 'list-pick slots' });
    const slot = await modal({
      title: kind === 'save' ? '저장할 칸을 고르세요' : '불러올 칸을 고르세요', body: ul,
      buttons: [{ label: '닫기', value: null }],
      onOpen: (api) => {
        for (let n = 1; n <= SLOTS; n++) {
          const m = list[n];
          const enabled = !!m || kind === 'save';
          ul.append(el('li', { class: enabled ? '' : 'disabled', onclick: () => enabled && api.close(n) },
            el('span', {}, `${n}.  ` + (m ? `[${m.label}] ${m.excerpt || ''}` : '— 비어 있음 —')),
            m ? el('span', { class: 'sub' }, m.time) : null));
        }
      },
    });
    if (!slot) return;
    if (kind === 'save') {
      if (list[slot] && !(await modal({ body: `슬롯 ${slot}에 덮어쓸까요?`,
        buttons: [{ label: '취소', value: false }, { label: '덮어쓰기', value: true, primary: true }] }))) return;
      const page = this.session.page;
      await this.host.writeSave(slot, {
        format: 1, time: new Date().toLocaleString('sv-SE').slice(0, 16), label: this.session.entry.label,
        excerpt: (page.paragraphs[0] || '').replace(/\n/g, ' ').slice(0, 60), session: this.session.toJSON(),
      });
      toast(`슬롯 ${slot}에 저장했습니다`);
    } else {
      this.loadSlot(slot);
    }
  }

  // ---------------------------------------------------------------- 개발 도구
  openInEditor() {
    if (!this.host.openSource) return;
    if (this.mode === 'error') {
      const e = this.errors.find((x) => x.loc);
      if (e) this.host.openSource(e.loc.file, e.loc.line);
    } else if (this.mode === 'play' && this.session) {
      const label = this.story.labels.get(this.session.page.label);
      if (label) this.host.openSource(label.loc.file, label.loc.line);
    }
  }

  async jumpDialog() {
    if (!this.engine) return;
    const items = [...this.story.labels.values()].map((l) => ({ label: l.name, sub: String(l.loc), value: l.name }));
    const name = await pickBox('단락으로 이동 (변수는 유지됩니다)', items, '단락 이름');
    if (!name) return;
    if (!this.session) this.session = new Session(this.engine);
    try { this.session.jump(name); this.mode = 'play'; } catch (e) { return this.runtimeError(e); }
    this.render();
  }

  toggleVars() {
    if (this.varsPanel) { this.varsPanel.remove(); this.varsPanel = null; return; }
    this.varsPanel = el('aside', { id: 'vars' });
    document.body.append(this.varsPanel);
    this.drawVars();
  }

  drawVars() {
    const s = this.session;
    const rows = [el('h3', {}, '변수 (현재 페이지를 읽은 뒤)', el('button', { class: 'x', onclick: () => this.toggleVars() }, '✕'))];
    if (!s || !s.after) rows.push(el('div', { class: 'muted' }, '게임이 시작되지 않았습니다.'));
    else {
      const vars = Object.entries(s.after.variables).sort(([a], [b]) => (a < b ? -1 : 1));
      rows.push(el('table', {}, vars.map(([k, v]) => el('tr', {}, el('td', {}, k), el('td', {}, JSON.stringify(v))))));
      if (!vars.length) rows.push(el('div', { class: 'muted' }, '(없음)'));
      rows.push(el('h3', {}, '방문한 단락'));
      rows.push(el('table', {}, Object.entries(s.after.visited).map(([k, v]) => el('tr', {}, el('td', {}, k), el('td', {}, `×${v}`)))));
    }
    this.varsPanel.replaceChildren(...rows);
  }

  showLint() {
    if (!this.data) return;
    const report = lint(parseFiles(this.data.scripts), { start: this.data.config.start || 'start', images: this.data.images,
      titleImage: this.data.config.title_image || '' });
    modal({ title: '검사 결과', body: el('div', {}, el('p', {}, report.summary),
      issuesList(report.issues, (i) => this.host.openSource && this.host.openSource(i.loc.file, i.loc.line))) });
  }

  // ---------------------------------------------------------------- 키
  command(cmd) {
    switch (cmd) {
      case 'newGame': return this.newGame();
      case 'saveGame': return this.slotDialog('save');
      case 'loadGame': return this.slotDialog('load');
      case 'back': return this.back();
      case 'title': return this.showTitle();
      case 'fontUp': this.fontSize = Math.min(40, this.fontSize + 1); return this.rescale();
      case 'fontDown': this.fontSize = Math.max(9, this.fontSize - 1); return this.rescale();
      case 'theme':
        this.themeSetByUser = true;
        this.theme = this.theme === 'night' ? 'paper' : 'night';
        document.body.classList.toggle('night', this.theme === 'night');
        return;
      case 'fullscreen':
        if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen();
        return;
      case 'reload': return this.dev && this.load();
      case 'jump': return this.dev && this.jumpDialog();
      case 'vars': return this.dev && this.toggleVars();
      case 'check': return this.dev && this.showLint();
      case 'openEditor': return this.openInEditor();
    }
  }

  bindKeys() {
    addEventListener('keydown', (e) => {
      if (document.querySelector('.modal-back')) return;
      if (e.target instanceof HTMLInputElement) return;
      const mod = e.ctrlKey || e.metaKey;
      const key = e.key;
      const map = mod ? { s: 'saveGame', o: 'loadGame', n: 'newGame', t: 'theme', '=': 'fontUp', '+': 'fontUp', '-': 'fontDown' }
        : { Backspace: 'back', F11: 'fullscreen', F5: 'reload', F6: 'jump', F2: 'vars', F7: 'check', F4: 'openEditor' };
      if (map[key]) { e.preventDefault(); this.command(map[key]); return; }
      if (!mod && /^[1-9]$/.test(key)) {
        e.preventDefault();
        if (this.mode === 'title') { const b = this.page.querySelectorAll('.menu .choice')[Number(key) - 1]; if (b) b.click(); }
        else this.pick(Number(key) - 1);
      }
      if (!mod && (key === ' ' || key === 'Enter') && this.mode === 'play' && this.session) {
        const p = this.session.page;
        if (p.ending === null && !p.deadEnd && p.choices.length === 1 && p.choices[0].enabled) { e.preventDefault(); this.pick(0); }
      }
    });
  }
}

module.exports = { Game };
