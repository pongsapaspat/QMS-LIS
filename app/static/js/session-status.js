(() => {
  let ended = false;
  async function check() {
    if (ended) return;
    try {
      const response = await fetch('/session-status', {cache: 'no-store'});
      if (!response.ok) return;
      const state = await response.json();
      if (state.active) return;
      ended = true;
      const dialog = document.createElement('dialog');
      const message = document.createElement('p');
      message.textContent = state.reason === 'replaced'
        ? 'Session ถูกยกเลิก เนื่องจากบัญชีนี้เข้าสู่ระบบจากอุปกรณ์อื่น กรุณาเข้าสู่ระบบใหม่'
        : 'Session หมดอายุแล้ว กรุณาเข้าสู่ระบบใหม่';
      const button = document.createElement('button');
      button.textContent = 'เข้าสู่ระบบใหม่';
      button.className = 'btn btn-primary';
      button.onclick = () => window.location.assign('/login');
      dialog.append(message, button);
      dialog.addEventListener('cancel', event => event.preventDefault());
      document.body.append(dialog);
      dialog.showModal();
    } catch (_) { /* Retry after temporary network failures. */ }
  }
  setInterval(check, 15000);
  window.addEventListener('focus', check);
  check();
})();
