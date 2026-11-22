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

  const form = document.querySelector('[data-async-result-entry]');
  const dialog = document.querySelector('#result-entry-error');
  const message = document.querySelector('#result-entry-error-message');
  if (!form || !dialog || !message) return;
  const loading = document.querySelector('#interaction-loading');
  const genericError = 'ไม่สามารถบันทึกผลตรวจได้ กรุณาลองอีกครั้ง หากยังพบปัญหาให้ติดต่อผู้ดูแลระบบ';
  const errors = {
    'results may only be entered for received specimens': 'ยังบันทึกผลตรวจไม่ได้ เนื่องจากสิ่งส่งตรวจบางรายการยังไม่ได้รับเข้าแล็บ หรือถูก Reject แล้ว กรุณาตรวจสอบสถานะสิ่งส่งตรวจก่อนบันทึกผล',
    'concurrent result update conflict': 'มีผู้แก้ไขผลตรวจนี้แล้ว กรุณาตรวจสอบข้อมูลล่าสุดก่อนบันทึกอีกครั้ง',
    'a modification reason is required': 'กรุณาระบุเหตุผลการแก้ไขผลตรวจ',
    'critical value acknowledgement is required before completion': 'กรุณาตรวจทานและทำเครื่องหมายรับทราบค่าวิกฤตก่อนบันทึกผล',
    'cancelled orders cannot accept results': 'Order นี้ถูกยกเลิกแล้ว จึงไม่สามารถบันทึกผลตรวจได้',
    'released results cannot be edited; use an amendment workflow': 'ผลตรวจนี้เผยแพร่แล้ว กรุณาใช้ขั้นตอนขอแก้ไขผล',
    'สิ่งส่งตรวจถูก Reject หรือเปลี่ยนสถานะแล้ว กรุณาโหลดใหม่': 'สิ่งส่งตรวจถูก Reject หรือเปลี่ยนสถานะแล้ว กรุณาตรวจสอบสถานะล่าสุดก่อนบันทึกผล',
  };
  let submitting = false;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (submitting || !form.checkValidity()) return;
    const payload = new FormData(form);
    const button = event.submitter || form.querySelector('button[type="submit"]');
    const label = button?.textContent;
    submitting = true;
    form.setAttribute('aria-busy', 'true');
    if (button) { button.disabled = true; button.textContent = 'กำลังบันทึก…'; }
    loading?.classList.add('is-visible');
    loading?.setAttribute('aria-hidden', 'false');
    let errorMessage = '';
    try {
      const response = await fetch(form.action, {
        method: 'POST', body: payload, credentials: 'same-origin',
        headers: { 'X-Result-Entry': 'true', 'Accept': 'application/json' },
      });
      if (response.redirected || response.status === 401) {
        errorMessage = 'เซสชันอาจหมดอายุ กรุณาเข้าสู่ระบบอีกครั้งก่อนบันทึกผล';
      } else {
        const data = await response.json().catch(() => null);
        if (response.ok && data?.redirect_url === '/worklist?queue=results&success=results-saved') {
          window.location.assign(data.redirect_url);
          return;
        }
        errorMessage = errors[data?.detail] || genericError;
      }
    } catch {
      errorMessage = 'ไม่สามารถยืนยันการบันทึกได้ กรุณาตรวจสอบการเชื่อมต่อและสถานะรายการก่อนบันทึกซ้ำ';
    } finally {
      submitting = false;
      form.removeAttribute('aria-busy');
      if (button) { button.disabled = false; button.textContent = label; }
      loading?.classList.remove('is-visible');
      loading?.setAttribute('aria-hidden', 'true');
    }
    message.textContent = errorMessage;
    if (!dialog.open) dialog.showModal();
  });
})();
