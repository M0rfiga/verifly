const historyList = document.getElementById('history-list');
const feedback = document.getElementById('history-feedback');
const searchInput = document.getElementById('history-search');
const fromInput = document.getElementById('history-from');
const toInput = document.getElementById('history-to');
const expanded = new Set();
const timelines = new Map();
let reserves = [];
let selectedDays = null;
let loaded = false;

const STATUS = {
    pending: ['Aguardando verificação', 'neutral'], confirmed: ['Sem alteração', 'success'],
    high_priority: ['Alterado — Alta prioridade', 'error'], low_priority: ['Alterado — Baixa prioridade', 'warning'],
    solved: ['Resolvido', 'success'], completed: ['Realizado', 'completed']
};
const EVENT_NAMES = {
    created: 'Reserva cadastrada', updated: 'Cadastro atualizado', check_requested: 'Verificação solicitada',
    checked: 'Verificação concluída', check_failed: 'Falha na verificação', status_changed: 'Status atualizado'
};
const AIRLINES = { azul: 'Azul', gol: 'GOL', latam: 'LATAM' };

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
}

function plain(value) {
    return String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}

function timestamp(value) {
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : 0;
}

function formatTimestamp(value) {
    return timestamp(value) ? new Date(value).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : 'Data não registrada';
}

function formatFlight(value) {
    if (!value) return 'Não informado';
    const [day, hour] = String(value).split('T');
    return day.split('-').reverse().join('/') + (hour ? ` · ${hour.slice(0, 5)}` : '');
}

function lastMovement(reserve) {
    if (reserve.historyLastAt) return reserve.historyLastAt;
    return [reserve.createdAt, reserve.lastCheck, reserve.statusUpdatedAt]
        .filter(Boolean).sort((a, b) => timestamp(b) - timestamp(a))[0];
}

function statusTag(status) {
    const [label, color] = STATUS[status] || STATUS.pending;
    return `<span class="tag tag-${color}">${label}</span>`;
}

function dateRange() {
    let start = fromInput.value ? timestamp(`${fromInput.value}T00:00:00`) : 0;
    const end = toInput.value ? timestamp(`${toInput.value}T23:59:59.999`) : Infinity;
    if (selectedDays) {
        const day = new Date();
        day.setHours(0, 0, 0, 0);
        day.setDate(day.getDate() - selectedDays + 1);
        start = day.getTime();
    }
    return { start, end };
}

function visibleReserves() {
    const query = plain(searchInput.value.trim());
    const { start, end } = dateRange();
    return reserves.filter(reserve => {
        const text = plain(`${reserve.name} ${reserve.codeReserve} ${reserve.id} ${reserve.folder || ''}`);
        const at = timestamp(lastMovement(reserve));
        return text.includes(query) && at >= start && at <= end;
    }).sort((a, b) => timestamp(lastMovement(b)) - timestamp(lastMovement(a)) || String(a.id).localeCompare(String(b.id)));
}

function resultFor(snapshot, segment, index) {
    const results = snapshot?.segmentResults || [];
    return results.find(result => segment.order != null && result.order === segment.order) || results[index];
}

function flightDetails(after, before, checked) {
    return (after.stretches || []).map((segment, index) => {
        const result = checked ? resultFor(after, segment, index) : null;
        const previousSegment = (before?.stretches || []).find(item => segment.order != null && item.order === segment.order) || before?.stretches?.[index];
        const previousResult = checked && previousSegment ? resultFor(before, previousSegment, index) : null;
        const previousDeparture = previousResult?.newDeparture || previousSegment?.departureOriginal;
        const previousArrival = previousResult?.newArrival || previousSegment?.arrivalOriginal;
        const departure = result?.newDeparture || segment.departureOriginal;
        const arrival = result?.newArrival || segment.arrivalOriginal;
        const difference = (label, oldValue, newValue) => oldValue && newValue && oldValue !== newValue
            ? `<p class="flight-change">${label}: ${escapeHtml(formatFlight(oldValue))} → <strong>${escapeHtml(formatFlight(newValue))}</strong></p>` : '';
        return `<div class="flight">
            <strong>${escapeHtml(segment.origin)} → ${escapeHtml(segment.destination)}</strong>
            <p class="flight-type">${escapeHtml(AIRLINES[segment.company] || segment.company || '')} · ${segment.type === 'international' ? 'Internacional' : 'Doméstico'}</p>
            <p>Partida cadastrada: ${escapeHtml(formatFlight(segment.departureOriginal))}</p>
            <p>Chegada cadastrada: ${escapeHtml(formatFlight(segment.arrivalOriginal))}</p>
            ${previousSegment && (previousSegment.origin !== segment.origin || previousSegment.destination !== segment.destination) ? `<p class="flight-change">Rota anterior: ${escapeHtml(previousSegment.origin)} → ${escapeHtml(previousSegment.destination)}</p>` : ''}
            ${previousSegment && previousSegment.company !== segment.company ? `<p class="flight-change">Companhia anterior: ${escapeHtml(AIRLINES[previousSegment.company] || previousSegment.company)}</p>` : ''}
            ${result ? `<p class="${result.status === 'changed' ? 'text-error' : result.status === 'same' ? 'text-ok' : 'text-muted'}">${result.status === 'not_found' ? 'Trecho não conferido' : `Partida consultada: ${escapeHtml(formatFlight(result.newDeparture))}`}</p>
                ${result.newArrival ? `<p>Chegada consultada: ${escapeHtml(formatFlight(result.newArrival))}</p>` : ''}` : ''}
            ${difference('Mudança na partida', previousDeparture, departure)}
            ${difference('Mudança na chegada', previousArrival, arrival)}
        </div>`;
    }).join('');
}

function eventHtml(event) {
    const after = event.after || {};
    const before = event.before;
    const checked = event.type === 'checked';
    const statusChanged = before && before.status !== after.status;
    const changedFields = event.type === 'updated' ? ['name', 'codeReserve', 'folder', 'telefone'].filter(key => before?.[key] !== after[key]) : [];
    const labels = { name: 'Passageiro', codeReserve: 'Reserva', folder: 'Pasta', telefone: 'Contato' };
    return `<article class="verification">
        <div class="verification-top"><div><h3>${escapeHtml(EVENT_NAMES[event.type] || 'Atualização')}</h3><time>${escapeHtml(formatTimestamp(event.occurredAt))}</time></div>${statusTag(after.status)}</div>
        ${statusChanged ? `<p class="status-transition">${escapeHtml((STATUS[before.status] || STATUS.pending)[0])} → ${escapeHtml((STATUS[after.status] || STATUS.pending)[0])}</p>` : ''}
        ${event.type === 'check_requested' ? '<p>Solicitação enviada. Aguardando o verificador local.</p>' : ''}
        ${event.type === 'check_failed' ? `<p class="text-error">${escapeHtml(after.lastCheckError || 'Não foi possível consultar a companhia.')} O status da reserva foi mantido.</p>` : ''}
        ${changedFields.map(key => `<p>${labels[key]}: ${escapeHtml(before?.[key] || 'Não informado')} → ${escapeHtml(after[key] || 'Não informado')}</p>`).join('')}
        ${event.type === 'updated' && before?.stretches?.length !== after.stretches?.length ? `<p>Quantidade de trechos: ${before?.stretches?.length || 0} → ${after.stretches?.length || 0}</p>` : ''}
        ${['created', 'updated', 'checked'].includes(event.type) ? `<div class="flights-grid">${flightDetails(after, before, checked)}</div>` : ''}
    </article>`;
}

function timelineHtml(reserve) {
    const timeline = timelines.get(reserve.id);
    if (!timeline || (timeline.loading && !timeline.events.length)) return '<p class="history-message">Carregando histórico...</p>';
    const events = timeline.events.map(eventHtml).join('');
    const empty = !events && !timeline.error ? '<p class="history-message">Não há eventos salvos para esta reserva. As próximas movimentações aparecerão aqui.</p>' : '';
    return `${events}${empty}
        ${timeline.error ? `<p class="text-error" role="alert">${escapeHtml(timeline.error)}</p><button class="filter" data-retry="${escapeHtml(reserve.id)}">Tentar novamente</button>` : ''}
        ${timeline.nextCursor ? `<button class="filter load-more" data-more="${escapeHtml(reserve.id)}" ${timeline.loading ? 'disabled' : ''}>${timeline.loading ? 'Carregando...' : 'Carregar eventos anteriores'}</button>` : ''}`;
}

function render() {
    const visible = visibleReserves();
    document.getElementById('count-checked').textContent = visible.filter(r => r.lastCheck && !r.lastCheckError).length;
    document.getElementById('count-errors').textContent = visible.filter(r => r.lastCheckError).length;
    document.getElementById('count-completed').textContent = visible.filter(r => r.status === 'completed').length;
    document.getElementById('count-active').textContent = visible.filter(r => ['queued', 'running'].includes(r.verification?.state)).length;
    const { start, end } = dateRange();
    document.getElementById('history-period').textContent = start > end ? 'Período inválido: confira as datas.'
        : selectedDays ? `Reservas movimentadas nos últimos ${selectedDays} dias`
        : fromInput.value || toInput.value ? `Última movimentação: ${fromInput.value ? formatFlight(fromInput.value) : 'início'} a ${toInput.value ? formatFlight(toInput.value) : 'hoje'}` : 'Todas as movimentações';
    const focused = document.activeElement;
    const focusedId = focused?.closest('[data-reserve]')?.dataset.reserve;
    const focusedAction = focused?.dataset.more != null ? 'more' : focused?.dataset.retry != null ? 'retry' : 'toggle';
    historyList.innerHTML = visible.map((reserve, index) => {
        const id = escapeHtml(reserve.id);
        const companies = [...new Set((reserve.stretches || []).map(s => AIRLINES[s.company] || s.company).filter(Boolean))].join(' / ');
        const open = expanded.has(reserve.id);
        const summary = reserve.verification?.state === 'queued' ? 'Na fila — aguardando o verificador local'
            : reserve.verification?.state === 'running' ? 'Verificação em andamento'
            : reserve.lastCheckError ? 'Falha na última verificação'
            : EVENT_NAMES[reserve.historyLastType] || 'Situação atual da reserva';
        return `<article class="booking" data-reserve="${id}">
            <button class="booking-row" data-toggle="${id}" aria-expanded="${open}" aria-controls="history-details-${index}">
                <span class="col-passenger"><span class="folder">${reserve.folder ? `PASTA ${escapeHtml(reserve.folder)}` : 'SEM PASTA'}</span><span class="passenger-info"><strong class="passenger-name">${escapeHtml(reserve.name)} · ${escapeHtml(reserve.codeReserve || reserve.id)}</strong><small class="passenger-summary">${escapeHtml(summary)}</small></span></span>
                <span>${escapeHtml(companies || 'Não informada')}</span><span>${statusTag(reserve.status)}</span><span class="date">${escapeHtml(formatTimestamp(lastMovement(reserve)))}</span>
            </button>
            <div id="history-details-${index}" class="details" ${open ? '' : 'hidden'}>${open ? timelineHtml(reserve) : ''}</div>
        </article>`;
    }).join('') || '<p class="history-message">Nenhuma reserva encontrada para os filtros selecionados.</p>';
    if (focusedId) {
        const row = Array.from(historyList.querySelectorAll('[data-reserve]')).find(node => node.dataset.reserve === focusedId);
        row?.querySelector(`[data-${focusedAction}]`)?.focus({ preventScroll: true });
    }
}

async function loadTimeline(id, more = false) {
    const previous = timelines.get(id) || { events: [], nextCursor: null };
    if (previous.loading) return;
    const cursor = more ? previous.nextCursor : null;
    timelines.set(id, { ...previous, loading: true, error: null });
    render();
    try {
        const response = await window.Verifly.fetch(`/api/reservas/${encodeURIComponent(id)}/historico${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`, { cache: 'no-store' });
        if (!response.ok) throw new Error('Não foi possível carregar o histórico desta reserva.');
        const body = await response.json();
        const events = new Map((previous.events || []).map(event => [event.id, event]));
        body.events.forEach(event => events.set(event.id, event));
        // Ao atualizar, preserva as páginas antigas já carregadas.
        timelines.set(id, {
            events: Array.from(events.values()).sort((a, b) => timestamp(b.occurredAt) - timestamp(a.occurredAt)),
            nextCursor: more || !previous.events.length ? body.nextCursor : previous.nextCursor,
            version: body.reserve.historyLastAt, loading: false, error: null
        });
    } catch (error) {
        timelines.set(id, { ...previous, loading: false, error: error.message });
    }
    render();
}

async function loadReserves() {
    try {
        const response = await window.Verifly.fetch('/api/reservas', { cache: 'no-store' });
        if (!response.ok) throw new Error('Não foi possível atualizar as reservas. Tentaremos novamente automaticamente.');
        const next = await response.json();
        const changed = JSON.stringify(next) !== JSON.stringify(reserves);
        reserves = next;
        feedback.textContent = '';
        if (changed || !loaded) render();
        loaded = true;
        await Promise.all(Array.from(expanded).filter(id => {
            const reserve = reserves.find(item => item.id === id);
            const timeline = timelines.get(id);
            return reserve && !timeline?.loading && (!timeline || timeline.error || reserve.historyLastAt !== timeline.version);
        }).map(id => loadTimeline(id)));
    } catch (error) {
        feedback.textContent = error.message;
        if (!loaded) historyList.innerHTML = '<p class="history-message">Não foi possível carregar as reservas.</p>';
    } finally {
        historyList.setAttribute('aria-busy', 'false');
    }
}

historyList.addEventListener('click', event => {
    const toggle = event.target.closest('[data-toggle]');
    if (toggle) {
        const id = toggle.dataset.toggle;
        if (expanded.has(id)) expanded.delete(id);
        else { expanded.add(id); loadTimeline(id); }
        render();
    }
    const more = event.target.closest('[data-more]');
    if (more) loadTimeline(more.dataset.more, true);
    const retry = event.target.closest('[data-retry]');
    if (retry) loadTimeline(retry.dataset.retry);
});

function updateFilters() {
    document.querySelectorAll('[data-days]').forEach(button => {
        const active = (Number(button.dataset.days) || null) === selectedDays;
        button.classList.toggle('filter-active', active);
        button.setAttribute('aria-pressed', String(active));
    });
    render();
}

document.querySelectorAll('[data-days]').forEach(button => button.addEventListener('click', () => {
    selectedDays = Number(button.dataset.days) || null;
    fromInput.value = toInput.value = '';
    updateFilters();
}));
[fromInput, toInput].forEach(input => input.addEventListener('change', () => { selectedDays = null; updateFilters(); }));
document.getElementById('history-clear').addEventListener('click', () => {
    selectedDays = null;
    fromInput.value = toInput.value = '';
    updateFilters();
});
searchInput.addEventListener('input', render);

async function refresh() {
    if (!document.hidden) await loadReserves();
    setTimeout(refresh, 5000);
}
const requestedReserve = new URLSearchParams(window.location.search).get('reserve');
if (requestedReserve) {
    searchInput.value = requestedReserve;
    expanded.add(requestedReserve);
}
refresh();
