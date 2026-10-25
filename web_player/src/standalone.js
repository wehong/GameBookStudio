// 내보낸 HTML 파일 안에서 실행되는 게임 (스크립트와 그림이 파일 안에 들어 있음)
'use strict';

const { Game } = require('./player/game');

const DATA = window.GB_DATA;
const KEY = 'gamebook:' + (DATA.config.title || 'untitled') + ':';

function store() {
  try { return window.localStorage; } catch { return null; }
}

const host = {
  dev: false,
  async load() {
    return { config: DATA.config, configError: null, scripts: DATA.scripts, images: Object.keys(DATA.images) };
  },
  imageUrl: (rel) => DATA.images[rel.replace(/\\/g, '/')] || null,
  async listSaves() {
    const out = {};
    const s = store();
    if (!s) return out;
    for (let slot = 1; slot <= 10; slot++) {
      try {
        const d = JSON.parse(s.getItem(KEY + slot));
        if (d) out[slot] = { time: d.time, label: d.label, excerpt: d.excerpt };
      } catch { /* 비어 있음 */ }
    }
    return out;
  },
  async readSave(slot) { return JSON.parse(store().getItem(KEY + slot)); },
  async writeSave(slot, data) {
    const s = store();
    if (!s) throw new Error('이 브라우저에서는 저장할 수 없습니다.');
    s.setItem(KEY + slot, JSON.stringify(data));
  },
  setTitle: (t) => { document.title = t; },
};

const game = new Game(document.getElementById('app'), host);
game.load(true);
