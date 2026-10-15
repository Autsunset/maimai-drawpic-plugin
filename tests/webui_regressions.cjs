// Run with: node --test tests/webui_regressions.cjs
// Dependency-free controller tests. Browser QA separately checks native inert,
// focus, layout, and actual DOM form semantics; this fixture models only seams.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = path.join(__dirname, '../src/maimai_drawpic/interfaces/webui/src');
const read = name => fs.readFileSync(path.join(source, name), 'utf8');
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
const event = { preventDefault() {} };
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function node(values = {}) {
  return { value: '', textContent: '', innerHTML: '', checked: false,
    disabled: false, isConnected: true, inert: false, hidden: false,
    scrollTop: 0, clientHeight: 100, scrollHeight: 500, children: [],
    attrs: {}, listeners: {}, dataset: {},
    setAttribute(k, v) { this.attrs[k] = v; },
    removeAttribute(k) { delete this.attrs[k]; },
    addEventListener(k, fn) { this.listeners[k] = fn; },
    querySelectorAll() { return []; },
    classList: { toggle() {} }, focus() {}, ...values };
}
function harness(file, extra = {}) {
  const nodes = new Map();
  const get = selector => {
    if (!nodes.has(selector)) nodes.set(selector, node());
    return nodes.get(selector);
  };
  const errors = [], calls = [], actions = [], timers = new Map();
  let timerId = 0;
  const U = { state: { view: file, dirty: false, busy: 0, modalVersion: 0 },
    views: {}, $: get, e: String, icon: () => '', bindSubmit() {}, bindDirty() {},
    toast() {}, savedNotice() {}, error: e => errors.push(e),
    call(kind, name, args) {
      const d = deferred(); calls.push({ kind, name, args, ...d }); return d.promise;
    },
    buttonAction(button, operation) {
      button.disabled = true;
      const p = operation().catch(e => errors.push(e)).finally(() => {
        if (button.isConnected) button.disabled = false;
      });
      actions.push(p); return p;
    }, ...extra };
  const document = { hidden: false, querySelectorAll: () => [], createElement: () => node() };
  const context = vm.createContext({ window: { DrawpicUI: U }, document,
    structuredClone, URL, Blob, Uint8Array, atob, Date,
    setTimeout: (fn, delay) => { const id = ++timerId; timers.set(id, { fn, delay }); return id; },
    clearTimeout: id => timers.delete(id) });
  const run = name => vm.runInContext(read(name + '.js'), context, { filename: name + '.js' });
  run(file);
  return { U, nodes, get, calls, errors, actions, timers, context, document, run,
    tick: async delay => {
      const entry = [...timers].find(([, t]) => t.delay === delay);
      assert.ok(entry, `expected ${delay}ms timer`);
      timers.delete(entry[0]); entry[1].fn(); await flush();
    } };
}
const result = (lines, cursor = 'cursor', unchanged = false) => ({ lines, cursor, unchanged });
async function logs() {
  const h = harness('logs');
  h.get('#log-auto').checked = false;
  const opening = h.U.views.logs();
  h.calls[0].resolve(result(['initial'])); await opening;
  return h;
}
test('logs: a slow INFO query drains only the latest ERROR filter with auto refresh off', async () => {
  const h = await logs();
  h.get('#log-level').value = 'INFO'; h.get('#log-level').onchange();
  h.get('#log-level').value = 'WARNING'; h.get('#log-level').onchange();
  h.get('#log-level').value = 'ERROR'; h.get('#log-level').onchange();
  assert.equal(h.calls.length, 2);
  h.calls[1].resolve(result(['[INFO] stale'], 'old')); await flush();
  assert.equal(h.get('#log-output').textContent, 'initial');
  assert.equal(h.calls.length, 3);
  assert.equal(h.calls[2].args.level, 'ERROR');
  assert.equal(h.calls[2].args.cursor, '');
  h.calls[2].resolve(result(['[ERROR] latest'], 'new')); await flush();
  assert.equal(h.get('#log-output').textContent, '[ERROR] latest');
  assert.match(h.get('#log-status').textContent, /已更新/);
});
test('logs: task input invalidates an old response immediately, before debounce fires', async () => {
  const h = await logs();
  h.get('#log-level').value = 'INFO'; h.get('#log-level').onchange();
  h.get('#log-task').value = 'latest'; h.get('#log-task').oninput();
  h.calls[1].resolve(result(['stale'])); await flush();
  assert.equal(h.get('#log-output').textContent, 'initial');
  await h.tick(300);
  assert.equal(h.calls[2].args.task_id, 'latest');
  h.calls[2].resolve(result(['new task'])); await flush();
  assert.equal(h.get('#log-output').textContent, 'new task');
});
test('logs: task debounce during a slow request queues the latest task', async () => {
  const h = await logs();
  h.get('#log-filter').onsubmit(event);
  h.get('#log-task').value = 'demo00000003'; h.get('#log-task').oninput();
  await h.tick(300);
  h.calls[1].resolve(result(['stale'])); await flush();
  assert.equal(h.calls[2].args.task_id, 'demo00000003');
  h.calls[2].resolve(result(['latest task'])); await flush();
  assert.equal(h.get('#log-output').textContent, 'latest task');
});
test('logs: old errors do not suppress queued filters; current errors allow retry', async () => {
  const h = await logs();
  h.get('#log-filter').onsubmit(event);
  h.get('#log-level').value = 'ERROR'; h.get('#log-level').onchange();
  h.calls[1].reject(Error('old error')); await flush();
  assert.equal(h.calls.length, 3); assert.equal(h.errors.length, 0);
  h.calls[2].reject(Error('current error')); await flush();
  assert.match(h.get('#log-status').textContent, /查询失败/);
  h.get('#log-filter').onsubmit(event);
  h.calls[3].resolve(result(['retried'])); await flush();
  assert.equal(h.get('#log-output').textContent, 'retried');
});
test('logs: navigation and a newer render invalidate old responses', async () => {
  const h = await logs();
  h.get('#log-filter').onsubmit(event);
  const newer = h.U.views.logs();
  h.calls[1].resolve(result(['old render'])); await flush();
  assert.equal(h.get('#log-output').textContent, 'initial');
  h.calls[2].resolve(result(['new render'])); await newer;
  h.get('#log-filter').onsubmit(event); h.U.state.view = 'tasks';
  h.calls[3].resolve(result(['wrong page'])); await flush();
  assert.equal(h.get('#log-output').textContent, 'new render');
});
test('logs: unchanged refresh preserves text and scrolled-up position', async () => {
  const h = await logs();
  h.get('#log-auto').checked = true;
  h.get('#log-output').scrollTop = 15;
  await h.tick(5000);
  assert.equal(h.calls[1].args.cursor, 'cursor');
  h.calls[1].resolve(result([], 'cursor', true)); await flush();
  assert.equal(h.get('#log-output').textContent, 'initial');
  assert.equal(h.get('#log-output').scrollTop, 15);
});
async function platform() {
  let h, renders = 0, closes = 0, boot = 0, form;
  const record = { id: 'one', kind: 'openai', name: 'one', config: { enabled: true } };
  h = harness('platforms', {
    forms: { html: () => '', bind: () => () => ({ enabled: true }) },
    modal() { h.U.state.modalVersion++; form = node(); h.nodes.set('#provider-form', form); return node(); },
    closeModal() { closes++; form.isConnected = false; h.U.state.modalVersion++; },
    bootstrap: async () => { boot++; }, render: async () => { renders++; },
  });
  h.U.state.data = { revision: 9, catalog: [{ kind: 'openai', name: 'OpenAI', defaults: {} }],
    providers: [record], schema: { sections: { openai: { fields: {} } } } };
  const card = node({ dataset: { provider: 'one' } });
  h.document.querySelectorAll = () => [card];
  await h.U.views.platforms();
  await h.get('[data-edit]').onclick();
  return { ...h, form, stats: () => ({ renders, closes, boot }) };
}
test('platform: save freezes all fields and rejects repeated submissions', async () => {
  const h = await platform();
  h.get('#provider-name').value = 'submitted'; h.U.state.dirty = true;
  h.form.onsubmit(event); h.form.onsubmit(event);
  assert.equal(h.form.inert, true); assert.equal(h.form.attrs['aria-busy'], 'true');
  assert.equal(h.calls.length, 1); assert.equal(h.calls[0].args.revision, 9);
  assert.equal(JSON.parse(h.calls[0].args.provider_json).name, 'submitted');
  h.calls[0].resolve({}); await flush();
  assert.equal(h.U.state.dirty, false); assert.equal(h.stats().closes, 1);
  assert.equal(h.stats().renders, 1);
});
test('platform: failed saves retain the draft and unfreeze the form', async () => {
  const h = await platform();
  h.get('#provider-name').value = 'keep draft'; h.U.state.dirty = true;
  h.form.onsubmit(event); h.calls[0].reject(Error('conflict')); await flush();
  assert.equal(h.form.inert, false); assert.equal(h.form.attrs['aria-busy'], undefined);
  assert.equal(h.get('#provider-name').value, 'keep draft');
  assert.equal(h.U.state.dirty, true); assert.equal(h.stats().closes, 0);
  assert.equal(h.get('[type=submit]').disabled, false);
});
test('platform: an old save cannot close a replacement editor or clear its draft', async () => {
  const h = await platform();
  h.form.onsubmit(event);
  h.U.state.modalVersion++; h.U.state.dirty = true;
  h.calls[0].resolve({}); await flush();
  assert.equal(h.U.state.dirty, true); assert.equal(h.stats().closes, 0);
  assert.equal(h.stats().renders, 0); assert.equal(h.stats().boot, 1);
});
test('platform: detached forms cannot clear dirty state even with the same version', async () => {
  const h = await platform(); h.form.onsubmit(event);
  h.form.isConnected = false; h.U.state.dirty = true;
  h.calls[0].resolve({}); await flush();
  assert.equal(h.U.state.dirty, true); assert.equal(h.stats().closes, 0);
});
test('platform: durable-save warnings survive refresh errors without another save', async () => {
  const h = await platform();
  const notices = [];
  h.U.bootstrap = async () => { throw Error('read unavailable'); };
  h.U.savedNotice = (...args) => notices.push(args);
  h.U.state.dirty = true; h.form.onsubmit(event);
  const response = { saved: true, recovery_pending: true, warning: 'Saved; recovery pending' };
  h.calls[0].resolve(response); await flush();
  assert.equal(h.calls.length, 1); assert.equal(h.errors.length, 0);
  assert.equal(h.U.state.dirty, false); assert.equal(h.stats().closes, 1);
  assert.equal(h.stats().renders, 0); assert.equal(notices[0][0], response);
  assert.match(notices[0][2].message, /read unavailable/);
});
test('platform: delete warnings and read failures report a committed removal', async () => {
  const h = await platform(), notices = [];
  h.U.bootstrap = async () => { throw Error('read failed after removal'); };
  h.U.savedNotice = (...args) => notices.push(args);
  h.get('[data-delete]').onclick({ currentTarget: h.get('[data-delete]') });
  const response = { saved: true, runtime_refresh_pending: true, warning: 'pending' };
  h.calls[0].resolve(response); await flush();
  assert.equal(h.calls[0].name, 'provider_delete');
  assert.equal(h.errors.length, 0); assert.equal(notices[0][0], response);
  assert.equal(notices[0][1], '平台已移除'); assert.equal(h.stats().renders, 0);
});
test('platform: a completed deletion cannot rerender a newer settings draft', async () => {
  const h = await platform();
  h.get('[data-delete]').onclick({ currentTarget: h.get('[data-delete]') });
  h.U.state.view = 'settings'; h.U.state.dirty = true;
  h.calls[0].resolve({ saved: true }); await flush();
  assert.equal(h.stats().renders, 0); assert.equal(h.U.state.dirty, true);
});
async function settings() {
  let h;
  const tabs = ['general', 'style'].map(section => node({ dataset: { section } }));
  h = harness('settings', {
    forms: { html: () => '', bind: (panel, fields, values) => {
      panel.values = structuredClone(values); return () => structuredClone(panel.values);
    } },
    bootstrap: async () => {}, render: async () => {},
    submitForm: form => form.onsubmit(event),
  });
  h.U.state.data = { revision: 7,
    schema: { sections: { general: { fields: {} }, style: { fields: {} } } },
    settings: { general: { timeout: 150 }, style: { presets: [] } },
    defaults: { general: { timeout: 150 }, style: { presets: [] } } };
  const form = h.get('#settings-form');
  form.querySelector = () => null;
  form.append = panel => form.children.push(panel);
  h.U.$ = (selector, root) => selector.startsWith('#settings-panel-')
    ? form.children.find(p => '#' + p.id === selector) : h.get(selector);
  h.document.querySelectorAll = selector => selector === '[data-section]' ? tabs : [];
  // Controllers capture U.$ when loaded, so reload after installing the scoped seam.
  h.run('settings');
  await h.U.views.settings();
  return { ...h, form, tabs };
}
test('settings: both category drafts survive switching and submit in one snapshot', async () => {
  const h = await settings();
  h.form.children[0].values.timeout = 231;
  h.form.children[1].values.presets.push({ name: 'draft', positive_prompt_template: '{prompt}' });
  h.U.state.dirty = true;
  h.tabs[1].onclick(); h.tabs[0].onclick();
  assert.equal(h.form.children[0].values.timeout, 231);
  h.form.onsubmit(event); h.form.onsubmit(event);
  assert.equal(h.calls.length, 1); assert.equal(h.form.inert, true);
  const submitted = JSON.parse(h.calls[0].args.config_json);
  assert.equal(submitted.general.timeout, 231);
  assert.equal(submitted.style.presets[0].name, 'draft');
  h.calls[0].resolve({ saved: true }); await flush();
  assert.equal(h.U.state.dirty, false);
});
test('settings: failed saves retain both category drafts and allow editing', async () => {
  const h = await settings();
  h.form.children[0].values.timeout = 245;
  h.form.children[1].values.presets.push({ name: 'keep' }); h.U.state.dirty = true;
  h.form.onsubmit(event); h.calls[0].reject(Error('revision conflict')); await flush();
  assert.equal(h.form.children[0].values.timeout, 245);
  assert.equal(h.form.children[1].values.presets[0].name, 'keep');
  assert.equal(h.U.state.dirty, true); assert.equal(h.form.inert, false);
  assert.equal(h.get('#reset-settings').disabled, false);
});
test('settings: saved-but-unreadable state warns and prevents resubmission until refresh', async () => {
  const h = await settings(), notices = [];
  h.U.bootstrap = async () => { throw Error('bootstrap failed'); };
  h.U.savedNotice = (...args) => notices.push(args);
  h.U.state.dirty = true; h.form.onsubmit(event);
  const response = { saved: true, runtime_refresh_pending: true, warning: 'Runtime refresh pending' };
  h.calls[0].resolve(response); await flush();
  assert.equal(h.U.state.dirty, false); assert.equal(h.form.inert, true);
  assert.equal(h.get('#save-settings').disabled, true);
  assert.equal(h.get('#reset-settings').disabled, true);
  h.form.onsubmit(event); assert.equal(h.calls.length, 1);
  assert.equal(h.errors.length, 0); assert.equal(notices[0][0], response);
  assert.match(notices[0][2].message, /bootstrap failed/);
});
test('settings: stale completion leaves newer dirty state alone', async () => {
  const h = await settings(); h.form.onsubmit(event);
  h.form.isConnected = false; h.U.state.dirty = true;
  h.calls[0].resolve({ saved: true }); await flush();
  assert.equal(h.U.state.dirty, true);
});
test('task details: close/navigation/newer request before the first response keep it stale', async () => {
  let modals = 0;
  const h = harness('tasks', { modal: () => { modals++; return node(); } });
  for (const invalidate of [() => h.U.state.modalVersion++, () => h.U.state.view = 'logs']) {
    h.U.state.view = 'tasks'; const opening = h.U.openTask('old');
    invalidate(); h.calls.at(-1).resolve({}); await opening;
  }
  h.U.state.view = 'tasks'; const first = h.U.openTask('first');
  const second = h.U.openTask('second');
  h.calls.at(-2).resolve({}); await first;
  h.U.state.modalVersion++; h.calls.at(-1).resolve({}); await second;
  assert.equal(modals, 0);
});
test('forms: scalar hints link to controls and nested arrays have legends with unique IDs', () => {
  const h = harness('forms'); h.U.state.data = { models: [] };
  const html = h.U.forms.html({
    timeout: { type: 'integer', default: 150, label: 'Timeout', hint: 'Seconds' },
    presets: { type: 'array', item_type: 'object', default: [], label: 'Presets', hint: 'Templates',
      item_fields: { positive_prompt_template: { type: 'string', default: '', label: 'Prompt', hint: '{prompt}' } } },
  }, { presets: [{ positive_prompt_template: 'one' }, { positive_prompt_template: 'two' }] });
  assert.match(html, /<input id="(field-\d+)" aria-describedby="\1-hint"/);
  assert.match(html, /<fieldset[^>]*aria-describedby="field-\d+-hint"><legend>Presets<\/legend>/);
  assert.equal((html.match(/<textarea id="(field-\d+)" aria-describedby="\1-hint"/g) || []).length, 2);
  const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]);
  assert.equal(ids.length, new Set(ids).size);
  for (const [, id] of html.matchAll(/(?:for|aria-describedby)="([^"]+)"/g)) assert.ok(ids.includes(id));
});
test('invalid default model: diagnostics remain linked to the configuration control', () => {
  const h = harness('forms');
  h.U.state.data = { models: [], default_model: '', default_model_error: 'Ambiguous model',
    settings: { general: { default_model: 'shared' } } };
  const html = h.U.forms.html({ default_model: { type: 'string', default: '', label: 'Default model' } },
    { default_model: 'shared' });
  assert.match(html, /<select id="(field-\d+)" aria-describedby="\1-hint"/);
  assert.match(html, /Ambiguous model/);
  assert.match(html, /请选择完整/);
  assert.match(read('studio.js'), /<option value="" selected>请选择平台实例 \/ 模型<\/option>/);
});
test('light theme small text and selected foreground meet 4.5:1; dark colors stay covered', () => {
  const css = read('style.css');
  const contrast = (a, b) => {
    const luminance = hex => {
      const c = hex.slice(1).match(/../g).map(x => parseInt(x, 16) / 255)
        .map(x => x <= .04045 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4);
      return c[0] * .2126 + c[1] * .7152 + c[2] * .0722;
    };
    const x = luminance(a), y = luminance(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05);
  };
  for (const block of [css.split('.dark')[0], css.split('.dark {')[1].split('}')[0]]) {
    const color = key => { let s = block.match(new RegExp(`--${key}: (#[a-f0-9]+);`))[1]; return s.length === 4 ? '#' + [...s.slice(1)].map(c => c+c).join('') : s; };
    for (const bg of ['surface', 'bg', 'soft']) assert.ok(contrast(color('muted'), color(bg)) >= 4.5);
    assert.ok(contrast(color('accent'), color('accent-soft')) >= 4.5);
  }
});
test('mode state, mobile save label and allowed animations stay explicit', () => {
  const studio = read('studio.js');
  assert.match(studio, /id="mode-draw" aria-pressed="\$\{mode === "draw"\}"/);
  assert.match(studio, /id="mode-edit" aria-pressed="\$\{mode === "edit_image"\}"/);
  assert.doesNotMatch(studio, /duration: 190|translateY\(-5px\)/);
  assert.match(read('index.html'), /class="save-label-short" aria-hidden="true">保存<\/span>/);
});
