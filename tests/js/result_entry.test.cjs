const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../../app/static/js/result-entry.js'), 'utf8');

function setup(value = '', saved = false, acknowledged = false, lower = '40', upper = '400') {
  const element = props => ({ ...props, handlers: {}, addEventListener(name, handler) {
    this.handlers[name] = handler;
  }, fire(name) { this.handlers[name]?.(); } });
  const input = element({ value, type: 'number', dataset: { lowerCritical: lower, upperCritical: upper } });
  const ack = { checked: acknowledged, disabled: false, required: false };
  const notice = { hidden: true, querySelector: () => ack };
  const reason = { value: '', required: false };
  const container = { hidden: true };
  const toggle = saved ? element({ checked: false, dataset: { review: 'false' } }) : null;
  const fields = { disabled: saved, querySelectorAll: () => [input], querySelector(selector) {
    return { '[data-numeric-result]': input, '[data-critical-notice]': notice,
      '[data-reason-container] input': saved ? reason : null,
      '[data-reason-container]': saved ? container : null }[selector];
  } };
  const card = { querySelector: selector => selector === 'fieldset' ? fields : toggle };
  vm.runInNewContext(script, { document: { querySelectorAll: () => [card], querySelector: () => null } });
  return { input, ack, notice, toggle, reason, container, fields };
}

test('critical boundaries show acknowledgement only when applicable', () => {
  const state = setup();
  assert.equal(state.notice.hidden, true);
  for (const [value, critical] of [['95', false], ['40', true], ['40.000001', false],
    ['400', true], ['399.999999', false], ['', false], ['invalid', false]]) {
    state.input.value = value;
    state.input.fire('input');
    assert.equal(state.notice.hidden, !critical, value);
    assert.equal(state.ack.required, critical, value);
    assert.equal(state.ack.disabled, !critical, value);
  }
  assert.equal(setup('400', false, false, '', '').notice.hidden, true);
  assert.equal(setup('0', false, false, '0', '').notice.hidden, false);
});

test('changing a critical result clears prior acknowledgement', () => {
  const state = setup('400', true, true);
  assert.equal(state.ack.checked, true);
  state.toggle.checked = true;
  state.toggle.fire('change');
  state.input.value = '450';
  state.input.fire('input');
  assert.equal(state.notice.hidden, false);
  assert.equal(state.ack.checked, false);
  assert.equal(state.reason.required, true);
  state.toggle.checked = false;
  state.toggle.fire('change');
  assert.equal(state.input.value, '400');
  assert.equal(state.fields.disabled, true);
  assert.equal(state.ack.checked, true);
  assert.equal(state.reason.required, false);
  assert.equal(state.container.hidden, true);
});

function setupSave(fetchResponse) {
  const input = { value: '95' };
  const button = { disabled: false, textContent: 'บันทึกผลตรวจ' };
  const form = {
    action: 'http://localhost/worklist/orders/1',
    checkValidity: () => true,
    setAttribute() {}, removeAttribute() {}, querySelector: () => button,
    addEventListener(name, handler) { this.submit = handler; },
  };
  const dialog = { open: false, showModal() { this.open = true; } };
  const message = { textContent: '' };
  const loading = { visible: false, setAttribute() {}, classList: {
    add() { loading.visible = true; }, remove() { loading.visible = false; },
  } };
  const navigation = [];
  const requests = [];
  vm.runInNewContext(script, {
    document: { querySelectorAll: () => [], querySelector: selector => ({
      '[data-async-result-entry]': form, '#result-entry-error': dialog,
      '#result-entry-error-message': message, '#interaction-loading': loading,
    })[selector] },
    FormData: class { constructor(source) { assert.equal(source, form); this.value = input.value; } },
    fetch: async (url, options) => {
      requests.push({ url, options });
      return fetchResponse();
    },
    window: { location: { assign: url => navigation.push(url) } },
  });
  return { input, button, dialog, message, loading, navigation, requests,
    submit: () => form.submit({ preventDefault() {}, submitter: button }) };
}

test('unreceived specimens show a Thai popup and preserve entered results for correction', async () => {
  const state = setupSave(async () => ({ ok: false, status: 422,
    json: async () => ({ detail: 'results may only be entered for received specimens' }) }));
  await state.submit();
  assert.equal(state.dialog.open, true);
  assert.match(state.message.textContent, /ยังไม่ได้รับเข้าแล็บ/);
  assert.equal(state.input.value, '95');
  assert.deepEqual(state.navigation, []);
  assert.equal(state.button.disabled, false);
  assert.equal(state.button.textContent, 'บันทึกผลตรวจ');
  assert.equal(state.loading.visible, false);
  assert.equal(state.requests[0].options.body.value, '95');
  assert.equal(state.requests[0].options.headers['X-Result-Entry'], 'true');
});

test('successful asynchronous save returns to the result queue', async () => {
  const redirect = '/worklist?queue=results&success=results-saved';
  const state = setupSave(async () => ({ ok: true, status: 200,
    json: async () => ({ redirect_url: redirect }) }));
  await state.submit();
  assert.deepEqual(state.navigation, [redirect]);
  assert.equal(state.dialog.open, false);
});

test('network failures and non-JSON server errors retain the form and allow retry', async () => {
  for (const response of [
    async () => { throw new Error('network failed'); },
    async () => ({ ok: false, status: 500, json: async () => { throw new Error('HTML'); } }),
    async () => ({ ok: false, status: 422, json: async () => ({ detail: 'unknown error' }) }),
  ]) {
    const state = setupSave(response);
    await state.submit();
    assert.equal(state.dialog.open, true);
    assert.match(state.message.textContent, /ไม่สามารถ/);
    assert.equal(state.input.value, '95');
    assert.equal(state.button.disabled, false);
    assert.equal(state.loading.visible, false);
    assert.deepEqual(state.navigation, []);
  }
});

test('expired sessions show a popup instead of discarding entered values', async () => {
  const state = setupSave(async () => ({ redirected: true, status: 200 }));
  await state.submit();
  assert.match(state.message.textContent, /เข้าสู่ระบบอีกครั้ง/);
  assert.equal(state.input.value, '95');
  assert.deepEqual(state.navigation, []);
});

test('repeated submit cannot create overlapping save requests', async () => {
  let finish;
  const state = setupSave(() => new Promise(resolve => { finish = resolve; }));
  const first = state.submit();
  await state.submit();
  assert.equal(state.requests.length, 1);
  assert.equal(state.button.disabled, true);
  finish({ ok: false, status: 422, json: async () => ({ detail: 'a modification reason is required' }) });
  await first;
  assert.match(state.message.textContent, /เหตุผลการแก้ไข/);
  assert.equal(state.button.disabled, false);
});
