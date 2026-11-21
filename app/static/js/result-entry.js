(() => {
  document.querySelectorAll('.result-entry-card').forEach(card => {
    const fields = card.querySelector('fieldset');
    const toggle = card.querySelector('[data-edit-result]');
    const values = [...fields.querySelectorAll('[name^="value_"], [name^="parameter_"]')];
    const originals = values.map(value => value.value);
    const reason = fields.querySelector('[data-reason-container] input');
    const reasonContainer = fields.querySelector('[data-reason-container]');
    const numeric = fields.querySelector('[data-numeric-result]');
    const notice = fields.querySelector('[data-critical-notice]');
    const ack = notice?.querySelector('input');
    const originalAck = ack?.checked || false;
    const isCritical = () => {
      if (!numeric || !numeric.value.trim()) return false;
      const value = Number(numeric.value);
      if (!Number.isFinite(value)) return false;
      const lower = numeric.dataset.lowerCritical;
      const upper = numeric.dataset.upperCritical;
      return (lower !== '' && value <= Number(lower)) || (upper !== '' && value >= Number(upper));
    };
    function updateCritical(clearAcknowledgement = false) {
      if (!notice) return;
      const critical = isCritical();
      notice.hidden = !critical;
      ack.disabled = !critical;
      ack.required = critical;
      if (!critical || clearAcknowledgement) ack.checked = false;
    }
    function updateReason() {
      if (!reason || !toggle) return;
      const changed = values.some((value, index) => value.type === 'number'
        ? Number(value.value) !== Number(originals[index]) || value.value === ''
        : value.value.trim().replace(/\s+/g, ' ') !== originals[index].trim().replace(/\s+/g, ' '));
      reasonContainer.hidden = !toggle.checked;
      reason.required = toggle.checked && (changed || toggle.dataset.review === 'true');
    }
    toggle?.addEventListener('change', () => {
      fields.disabled = !toggle.checked;
      if (!toggle.checked) {
        values.forEach((value, index) => { value.value = originals[index]; });
        reason.value = '';
        if (ack) ack.checked = originalAck;
      }
      updateReason();
      updateCritical();
    });
    values.forEach(value => value.addEventListener('input', () => {
      updateReason();
      updateCritical(true);
    }));
    updateCritical();
  });
})();
