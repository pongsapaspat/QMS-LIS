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
  vm.runInNewContext(script, { document: { querySelectorAll: () => [card] } });
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
