// 화면 공통 도우미: 대화 상자, 알림, 목록 고르기, 문제 목록
'use strict';

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}

/** 대화 상자. buttons: [{label, value, primary}] → 누른 버튼의 value (Esc: null) */
function modal({ title, body, buttons = [{ label: '확인', value: true, primary: true }], onOpen, className = '' }) {
  return new Promise((resolve) => {
    const back = el('div', { class: 'modal-back' });
    const box = el('div', { class: 'modal ' + className, role: 'dialog' });
    if (title) box.append(el('h2', {}, title));
    const content = el('div', { class: 'body' });
    if (typeof body === 'string') content.append(...body.split('\n\n').map((p) => el('p', {}, p)));
    else if (body) content.append(body);
    box.append(content);
    const row = el('div', { class: 'row' });
    const close = (v) => {
      document.removeEventListener('keydown', onKey, true);
      back.remove();
      resolve(v);
    };
    for (const b of buttons) {
      row.append(el('button', { class: 'btn' + (b.primary ? ' primary' : ''), onclick: () => close(b.value) }, b.label));
    }
    if (buttons.length) box.append(row);
    back.append(box);
    back.addEventListener('mousedown', (e) => { if (e.target === back) close(null); });
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(null); }
    };
    document.addEventListener('keydown', onKey, true);
    document.body.append(back);
    const api = { close, box, content };
    if (onOpen) onOpen(api);
    else {
      const p = row.querySelector('.primary');
      if (p) p.focus();
    }
  });
}

function alertBox(message, title = '') {
  return modal({ title, body: message });
}

function confirmBox(message, { title = '', ok = '확인', cancel = '취소', danger = false } = {}) {
  return modal({ title, body: message, buttons: [{ label: cancel, value: false }, { label: ok, value: true, primary: !danger }] })
    .then((v) => v === true);
}

/** 한 줄 입력. fields: [{name, label, hint, value}] → {name: 값} 또는 null */
function promptBox(title, fields, okLabel = '확인') {
  const form = el('div');
  const inputs = {};
  for (const f of fields) {
    form.append(el('label', {}, f.label));
    const input = el('input', { type: 'text', value: f.value || '', spellcheck: 'false' });
    inputs[f.name] = input;
    form.append(input);
    if (f.hint) form.append(el('div', { class: 'hint' }, f.hint));
  }
  return modal({
    title, body: form,
    buttons: [{ label: '취소', value: null }, { label: okLabel, value: 'ok', primary: true }],
    onOpen: (api) => {
      const first = Object.values(inputs)[0];
      first.focus();
      first.select();
      for (const input of Object.values(inputs)) {
        input.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); api.close('ok'); }
        });
      }
    },
  }).then((v) => {
    if (v !== 'ok') return null;
    const out = {};
    for (const [k, i] of Object.entries(inputs)) out[k] = i.value;
    return out;
  });
}

/** 걸러 가며 고르는 목록. items: [{label, sub, value}] → value 또는 null */
function pickBox(title, items, placeholder = '거르기') {
  const input = el('input', { type: 'text', placeholder, spellcheck: 'false' });
  const ul = el('ul', { class: 'list-pick' });
  const wrap = el('div', {}, input, ul);
  let shown = [];
  let sel = 0;
  return modal({
    title, body: wrap, buttons: [{ label: '닫기', value: null }],
    onOpen: (api) => {
      const draw = () => {
        const q = input.value.trim().toLowerCase();
        shown = items.filter((it) => !q || it.label.toLowerCase().includes(q));
        sel = Math.min(sel, Math.max(0, shown.length - 1));
        ul.replaceChildren(...shown.map((it, i) => el('li', {
          class: i === sel ? 'sel' : '', onclick: () => api.close(it.value),
          onmousemove: () => { if (sel !== i) { sel = i; draw(); } },
        }, el('span', {}, it.label), it.sub ? el('span', { class: 'sub' }, it.sub) : null)));
        const cur = ul.children[sel];
        if (cur) cur.scrollIntoView({ block: 'nearest' });
      };
      input.addEventListener('input', () => { sel = 0; draw(); });
      input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') { sel = Math.min(shown.length - 1, sel + 1); draw(); e.preventDefault(); }
        if (e.key === 'ArrowUp') { sel = Math.max(0, sel - 1); draw(); e.preventDefault(); }
        if (e.key === 'Enter' && !e.isComposing && shown[sel]) { e.preventDefault(); api.close(shown[sel].value); }
      });
      draw();
      input.focus();
    },
  });
}

let toastTimer = null;
function toast(message, ms = 1800) {
  let t = document.querySelector('.toast');
  if (!t) { t = el('div', { class: 'toast' }); document.body.append(t); }
  t.textContent = message;
  t.style.opacity = '1';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.style.opacity = '0'; }, ms);
}

function issuesList(issues, onPick) {
  if (!issues.length) return el('p', {}, '문제가 발견되지 않았습니다.');
  return el('ul', { class: 'issues' }, issues.map((i) => el('li', {
    style: { cursor: onPick && i.loc ? 'pointer' : 'default' },
    onclick: () => onPick && i.loc && onPick(i),
  }, el('span', { class: 'lv-' + i.level }, i.level), el('span', { class: 'where' }, i.loc ? String(i.loc) : ''),
  el('span', {}, i.message))));
}

function contextMenu(x, y, items) {
  document.querySelectorAll('.ctxmenu').forEach((m) => m.remove());
  const m = el('div', { class: 'ctxmenu', style: { left: x + 'px', top: y + 'px' } },
    items.map(([label, fn]) => el('div', { onclick: () => { m.remove(); fn(); } }, label)));
  document.body.append(m);
  const off = (e) => { if (!m.contains(e.target)) { m.remove(); document.removeEventListener('mousedown', off, true); } };
  setTimeout(() => document.addEventListener('mousedown', off, true));
}

module.exports = { esc, el, modal, alertBox, confirmBox, promptBox, pickBox, toast, issuesList, contextMenu };
