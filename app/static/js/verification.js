(() => {
  document.addEventListener('submit', async event => {
    const form = event.target;
    if (!form.matches('form[data-inline-verification]')) return;
    event.preventDefault();
    const card = form.closest('[data-verification-card]');
    if (card.getAttribute('aria-busy') === 'true') return;
    const payload = new FormData(form);
    const buttons = [...card.querySelectorAll('button[type="submit"]')];
    const submitter = event.submitter;
    const label = submitter?.textContent;
    card.querySelector('[data-inline-message]')?.remove();
    card.setAttribute('aria-busy', 'true');
    buttons.forEach(button => { button.disabled = true; });
    if (submitter) submitter.textContent = 'กำลังบันทึก…';
    try {
      const response = await fetch(form.action, {
        method: 'POST', body: payload, credentials: 'same-origin',
        headers: { 'X-Verification-Inline': 'true', 'Accept': 'text/html' },
      });
      if (response.redirected) throw new Error('เซสชันอาจหมดอายุ กรุณาเปิดหน้าใหม่เพื่อตรวจสอบสถานะ');
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (!response.ok) {
        const errors = [...page.querySelectorAll('[data-verification-error]')];
        throw new Error(errors.map(error => error.textContent).join(' · ') || 'บันทึกไม่สำเร็จ กรุณาตรวจสอบสถานะก่อนลองอีกครั้ง');
      }
      const updated = page.getElementById(card.id);
      if (!updated) throw new Error('ไม่พบสถานะล่าสุด กรุณาเปิดหน้าใหม่เพื่อตรวจสอบผล');
      // Keep the space occupied by the forms so lower cards never jump upward.
      card.style.minHeight = `${card.getBoundingClientRect().height}px`;
      card.replaceChildren(...updated.childNodes);
      const progress = document.querySelector('[data-verification-progress]');
      const remaining = [...document.querySelectorAll('[data-result-status]')]
        .filter(status => status.textContent.trim() === 'COMPLETED').length;
      if (progress) progress.textContent = `รอ Verify ${remaining} รายการ`;
      const message = document.createElement('div');
      message.className = 'alert alert-success mx-3 mb-3';
      message.dataset.inlineMessage = '';
      message.setAttribute('role', 'status');
      message.textContent = 'บันทึกแล้ว · ' + card.querySelector('[data-result-status]').textContent;
      card.querySelector('.card-body').append(message);
      card.querySelector('[data-result-status]').focus({ preventScroll: true });
    } catch (error) {
      const message = document.createElement('div');
      message.className = 'alert alert-danger mx-3 mb-3';
      message.dataset.inlineMessage = '';
      message.setAttribute('role', 'alert');
      message.textContent = error.message || 'เชื่อมต่อไม่สำเร็จ กรุณาตรวจสอบสถานะก่อนลองอีกครั้ง';
      card.querySelector('.card-body').append(message);
    } finally {
      card.removeAttribute('aria-busy');
      buttons.forEach(button => { button.disabled = false; });
      if (submitter) submitter.textContent = label;
    }
  });
})();
