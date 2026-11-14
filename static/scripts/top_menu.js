(() => {
    const nativeFetch = window.fetch.bind(window);
    const search = document.querySelector('[data-menu-search]');
    if (!document.getElementById('top-menu')) return;
    const results = document.getElementById('menu-search-results');
    const bell = document.getElementById('menu-notifications');
    const panel = document.getElementById('menu-notification-panel');
    const list = document.getElementById('notification-list');
    const feedback = document.getElementById('menu-feedback');
    const notificationFeedback = document.getElementById('notification-feedback');
    const readAll = document.getElementById('notifications-read-all');
    let csrfToken;
    let notifications = [];
    let searchTimer;
    let searchVersion = 0;
    let selected = -1;
    let notificationVersion = 0;

    function showError(message) {
        feedback.textContent = message;
        feedback.hidden = false;
    }

    const ready = nativeFetch('/api/auth/me', { cache: 'no-store' }).then(async response => {
        if (response.status === 401) {
            window.location.replace('/');
            throw new Error('Entre novamente para continuar.');
        }
        if (!response.ok) throw new Error('Não foi possível verificar sua sessão. Atualize a página.');
        const body = await response.json();
        csrfToken = body.csrfToken;
        document.getElementById('menu-user').textContent = `Usuário: ${body.user.name}`;
        document.getElementById('menu-user').title = body.user.email;
        return body.user;
    });

    async function apiFetch(url, options = {}) {
        await ready;
        const headers = new Headers(options.headers || {});
        if (!['GET', 'HEAD', 'OPTIONS'].includes((options.method || 'GET').toUpperCase())) {
            headers.set('X-CSRF-Token', csrfToken);
        }
        const response = await nativeFetch(url, { ...options, headers, cache: 'no-store' });
        if (response.status === 401) {
            window.location.replace('/');
            throw new Error('Sua sessão expirou. Entre novamente.');
        }
        return response;
    }

    window.Verifly = { fetch: apiFetch, ready };

    function closeSearch() {
        if (!search || !results) return;
        results.hidden = true;
        search.setAttribute('aria-expanded', 'false');
        search.removeAttribute('aria-activedescendant');
        selected = -1;
    }

    function messageIn(container, text) {
        container.replaceChildren();
        const paragraph = document.createElement('p');
        paragraph.className = 'menu-empty';
        paragraph.textContent = text;
        container.appendChild(paragraph);
    }

    async function searchReserves() {
        const query = search.value.trim();
        const version = ++searchVersion;
        if (!query) return closeSearch();
        results.hidden = false;
        search.setAttribute('aria-expanded', 'true');
        messageIn(results, 'Buscando reservas...');
        try {
            const response = await apiFetch(`/api/pesquisa?q=${encodeURIComponent(query)}`);
            if (!response.ok) throw new Error('Não foi possível pesquisar. Tente novamente.');
            const body = await response.json();
            if (version !== searchVersion || query !== search.value.trim()) return;
            results.replaceChildren();
            selected = -1;
            if (!body.results.length) return messageIn(results, 'Nenhuma reserva encontrada.');
            body.results.forEach((reserve, index) => {
                const link = document.createElement('a');
                link.id = `menu-result-${index}`;
                link.href = `/history.html?reserve=${encodeURIComponent(reserve.id)}`;
                link.setAttribute('role', 'option');
                link.setAttribute('aria-selected', 'false');
                const name = document.createElement('strong');
                name.textContent = reserve.name || 'Reserva sem nome';
                const details = document.createElement('small');
                details.textContent = `PNR: ${reserve.codeReserve}${reserve.folder ? ` · Pasta ${reserve.folder}` : ''}`;
                link.append(name, details);
                results.appendChild(link);
            });
        } catch (error) {
            if (version === searchVersion) messageIn(results, error.message);
        }
    }

    search?.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchVersion++;
        if (!search.value.trim()) closeSearch();
        else searchTimer = setTimeout(searchReserves, 250);
    });
    search?.addEventListener('focus', () => { if (search.value.trim()) searchReserves(); });
    search?.addEventListener('keydown', event => {
        const links = Array.from(results.querySelectorAll('a'));
        if (event.key === 'Escape') {
            searchVersion++;
            clearTimeout(searchTimer);
            closeSearch();
        } else if (['ArrowDown', 'ArrowUp'].includes(event.key) && links.length && !results.hidden) {
            event.preventDefault();
            selected = selected === -1 ? (event.key === 'ArrowDown' ? 0 : links.length - 1)
                : (selected + (event.key === 'ArrowDown' ? 1 : -1) + links.length) % links.length;
            links.forEach((link, index) => link.setAttribute('aria-selected', String(index === selected)));
            search.setAttribute('aria-activedescendant', links[selected].id);
            links[selected].scrollIntoView({ block: 'nearest' });
        } else if (event.key === 'Enter') {
            event.preventDefault();
            if (!results.hidden && links.length) links[Math.max(0, selected)].click();
            else searchReserves();
        }
    });

    function renderNotifications() {
        const unread = notifications.filter(item => !item.read).length;
        const badge = document.getElementById('notification-count');
        badge.textContent = unread > 9 ? '9+' : String(unread);
        badge.hidden = unread === 0;
        bell.setAttribute('aria-label', unread ? `Notificações: ${unread} não lidas` : 'Notificações');
        readAll.disabled = unread === 0;
        list.replaceChildren();
        if (!notifications.length) return messageIn(list, 'Você não tem notificações.');
        notifications.forEach(item => {
            const link = document.createElement('a');
            link.href = `/history.html?reserve=${encodeURIComponent(item.reserveId)}`;
            link.dataset.notification = item.id;
            link.className = item.read ? 'notification-item' : 'notification-item notification-unread';
            const title = document.createElement('strong');
            title.textContent = item.title;
            const details = document.createElement('span');
            details.textContent = `${item.name || 'Reserva'} · ${item.codeReserve}`;
            const message = document.createElement('small');
            message.textContent = item.message || '';
            const time = document.createElement('time');
            const date = new Date(item.occurredAt);
            time.textContent = Number.isNaN(date.getTime()) ? 'Data não registrada' : date.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
            link.append(title, details, message, time);
            list.appendChild(link);
        });
    }

    async function loadNotifications() {
        const version = ++notificationVersion;
        try {
            const response = await apiFetch('/api/notificacoes');
            if (!response.ok) throw new Error('Não foi possível atualizar as notificações.');
            const body = await response.json();
            if (version !== notificationVersion) return;
            notifications = body.notifications;
            notificationFeedback.textContent = '';
            renderNotifications();
        } catch (error) {
            if (version === notificationVersion) notificationFeedback.textContent = error.message;
        }
    }

    async function markRead(ids) {
        const response = await apiFetch('/api/notificacoes/lidas', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids })
        });
        if (!response.ok) throw new Error('Não foi possível marcar as notificações como lidas.');
        notificationVersion++;
        notifications.forEach(item => { if (ids.includes(item.id)) item.read = true; });
        renderNotifications();
    }

    bell.addEventListener('click', () => {
        panel.hidden = !panel.hidden;
        bell.setAttribute('aria-expanded', String(!panel.hidden));
        closeSearch();
        if (!panel.hidden) loadNotifications();
    });
    readAll.addEventListener('click', async () => {
        readAll.disabled = true;
        try { await markRead(notifications.filter(item => !item.read).map(item => item.id)); }
        catch (error) { notificationFeedback.textContent = error.message; readAll.disabled = false; }
    });
    list.addEventListener('click', async event => {
        const link = event.target.closest('[data-notification]');
        if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        try { await markRead([link.dataset.notification]); window.location.assign(link.href); }
        catch (error) { notificationFeedback.textContent = error.message; }
    });
    document.addEventListener('click', event => {
        if (!event.target.closest('.navbar-search')) {
            searchVersion++;
            clearTimeout(searchTimer);
            closeSearch();
        }
        if (!panel.contains(event.target) && !bell.contains(event.target)) {
            panel.hidden = true;
            bell.setAttribute('aria-expanded', 'false');
        }
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && !panel.hidden) {
            panel.hidden = true;
            bell.setAttribute('aria-expanded', 'false');
            bell.focus();
        }
    });
    document.getElementById('menu-logout').addEventListener('click', async event => {
        const button = event.currentTarget;
        button.disabled = true;
        try {
            const response = await apiFetch('/api/auth/logout', { method: 'POST' });
            if (!response.ok) throw new Error('Não foi possível sair. Tente novamente.');
            window.location.replace('/');
        } catch (error) {
            showError(error.message);
            button.disabled = false;
        }
    });

    async function refresh() {
        if (!document.hidden) await loadNotifications();
        setTimeout(refresh, 15000);
    }
    ready.then(refresh).catch(error => showError(error.message));
    window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
})();
