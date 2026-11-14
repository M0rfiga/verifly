(() => {
    const form = document.getElementById('login-form');
    const button = form.querySelector('.btn-submit');
    const label = button.querySelector('[data-submit-label]');
    const feedback = document.getElementById('login-feedback');
    const password = document.getElementById('senha');
    const toggle = document.querySelector('.btn-toggle-eye');
    toggle.addEventListener('click', () => {
        const visible = password.type === 'password';
        password.type = visible ? 'text' : 'password';
        toggle.setAttribute('aria-pressed', String(visible));
        toggle.setAttribute('aria-label', visible ? 'Ocultar senha' : 'Mostrar senha');
    });
    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (!form.reportValidity() || button.disabled) return;
        button.disabled = true;
        label.textContent = 'ENTRANDO...';
        feedback.hidden = true;
        try {
            const response = await fetch(form.action, { method: 'POST', body: new FormData(form) });
            const body = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(body.erro || 'Não foi possível entrar. Tente novamente.');
            window.location.replace(body.redirect);
        } catch (error) {
            feedback.textContent = error.message;
            feedback.hidden = false;
            password.value = '';
            password.focus();
            if (window.turnstile) window.turnstile.reset();
        } finally {
            button.disabled = false;
            label.textContent = 'ENTRAR';
        }
    });
})();
