const API_URL = '/api/reservas';

const monitoringBody = document.getElementById('monitoring-body');
const btnCheckAll = document.getElementById('btn-check-all');
const chips = document.querySelectorAll('.filter-chip');
const cards = document.querySelectorAll('.cards-area [data-filter]');

// Status que o comparador pode reclassificar (resolvido/realizado são manuais)
const COMPARABLE_STATUS = ['pending', 'high_priority', 'low_priority', 'confirmed'];

const ICON_WARNING = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/></svg>';
const ICON_CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m8 12.5 3 3 5-6"/></svg>';
const ICON_CHEVRON_DOWN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>';
const ICON_CHEVRON_UP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 15 6-6 6 6"/></svg>';

const STATUS_CONFIG = {
    high_priority: { label: 'Alterado — Alta prioridade', dot: 'red', badge: 'badge-red', icon: ICON_WARNING },
    low_priority: { label: 'Alterado — Baixa prioridade', dot: 'yellow', badge: 'badge-yellow', icon: ICON_WARNING },
    confirmed: { label: 'Sem alteração', dot: 'green', badge: 'badge-green', icon: ICON_CHECK },
    solved: { label: 'Resolvido', dot: 'blue', badge: 'badge-blue', icon: ICON_CHECK },
    completed: { label: 'Realizado', dot: 'gray', badge: 'badge-gray', icon: '' },
    pending: { label: 'Aguardando verificação', dot: 'gray', badge: 'badge-gray', icon: '' }
};

// Ordem de exibição na tabela
const STATUS_ORDER = ['high_priority', 'low_priority', 'pending', 'confirmed', 'solved', 'completed'];

const AIRLINES = { azul: 'Azul', latam: 'LATAM', gol: 'GOL' };
const TYPES = { domestic: 'Doméstico', international: 'Internacional' };

// Cidades dos aeroportos (o cadastro só guarda o código). Se faltar algum, a cidade simplesmente não aparece.
const AIRPORT_CITIES = {
    BSB: 'Brasília', CGH: 'São Paulo', GRU: 'São Paulo', VCP: 'Campinas', SDU: 'Rio de Janeiro', GIG: 'Rio de Janeiro',
    CNF: 'Belo Horizonte', PLU: 'Belo Horizonte', SSA: 'Salvador', REC: 'Recife', FOR: 'Fortaleza', POA: 'Porto Alegre',
    CWB: 'Curitiba', FLN: 'Florianópolis', NAT: 'Natal', MCZ: 'Maceió', AJU: 'Aracaju', JPA: 'João Pessoa',
    SLZ: 'São Luís', THE: 'Teresina', BEL: 'Belém', MAO: 'Manaus', GYN: 'Goiânia', CGB: 'Cuiabá',
    CGR: 'Campo Grande', VIX: 'Vitória', UDI: 'Uberlândia', IGU: 'Foz do Iguaçu', LDB: 'Londrina',
    MGF: 'Maringá', NVT: 'Navegantes', JOI: 'Joinville', IOS: 'Ilhéus', BPS: 'Porto Seguro', IPN: 'Ipatinga',
    MOC: 'Montes Claros', JDO: 'Juazeiro do Norte', SJP: 'São José do Rio Preto', RAO: 'Ribeirão Preto',
    JFK: 'Nova York', EWR: 'Nova York', MIA: 'Miami', MCO: 'Orlando', LIS: 'Lisboa', OPO: 'Porto', MAD: 'Madri',
    EZE: 'Buenos Aires', SCL: 'Santiago', MVD: 'Montevidéu', CDG: 'Paris', FCO: 'Roma', LHR: 'Londres'
};

let reserves = [];
let activeFilter = null;
const expanded = new Set(); // ids das reservas com o detalhe aberto


/* ---------- Utilidades ---------- */

function escapeHtml(text) {
    return String(text ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// '2026-10-07T13:30' -> Date (horário local)
function parseLocal(value) {
    if (!value) return null;

    const [day, hour] = value.split('T');
    const [year, month, dayOfMonth] = day.split('-').map(Number);
    const [hh, mm] = (hour || '00:00').split(':').map(Number);

    return new Date(year, month - 1, dayOfMonth, hh, mm);
}

// '2026-10-07T13:30' -> '07/10/2026 · 13:30'
function formatDateTime(value) {
    if (!value) return '-';

    const [day, hour] = value.split('T');
    const [year, month, dayOfMonth] = day.split('-');

    return `${dayOfMonth}/${month}/${year}` + (hour ? ` · ${hour.slice(0, 5)}` : '');
}

// Dias entre hoje e a data (negativo = já passou)
function daysUntil(value) {
    const target = parseLocal(value);
    if (!target) return null;

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    target.setHours(0, 0, 0, 0);

    return Math.round((target - today) / 86400000);
}

function daysLabel(days) {
    if (days === null) return '';
    if (days < 0) return '(voo passado)';
    if (days === 0) return '(hoje)';
    if (days === 1) return '(1 dia)';
    return `(${days} dias)`;
}

// Diferença entre o horário original e o novo: '+55min', '-1d', '+2h 5min'
function formatDelta(savedIso, newIso) {
    if (!savedIso || !newIso) return '';

    // Sem horário nos dois lados: compara só as datas
    const bothHaveHour = savedIso.includes('T') && newIso.includes('T');
    const from = parseLocal(bothHaveHour ? savedIso : savedIso.split('T')[0]);
    const to = parseLocal(bothHaveHour ? newIso : newIso.split('T')[0]);

    const minutes = Math.round((to - from) / 60000);
    if (minutes === 0) return '';

    const sign = minutes > 0 ? '+' : '-';
    const abs = Math.abs(minutes);

    if (abs < 120) return `${sign}${abs}min`;

    const days = Math.floor(abs / 1440);
    const hours = Math.floor((abs % 1440) / 60);
    const mins = abs % 60;

    return sign + [days && `${days}d`, hours && `${hours}h`, mins && `${mins}min`].filter(Boolean).join(' ');
}

function replaceReserve(updated) {
    const index = reserves.findIndex(reserve => reserve.id === updated.id);

    if (index >= 0) {
        reserves[index] = updated;
    } else {
        reserves.push(updated);
    }
}

function findResult(reserve, stretch, index) {
    const results = reserve.segmentResults || [];
    return results.find(result => result.order === stretch.order) || results[index];
}


/* ---------- Textos de status (linha da tabela) ---------- */

// 'Novo horário 14:25 (+55min)' ou 'Novo embarque 06/10/2026 · 13:30 (-1d)'
function changeSummary(reserve) {
    const changed = (reserve.segmentResults || []).find(result => result.status === 'changed');
    if (!changed) return '';

    const delta = formatDelta(changed.savedDeparture, changed.newDeparture);
    const suffix = delta ? ` (${delta})` : '';

    if (changed.changedFields.includes('date')) {
        return `Novo embarque ${formatDateTime(changed.newDeparture)}${suffix}`;
    }

    return `Novo horário ${changed.newDeparture.split('T')[1]}${suffix}`;
}


/* ---------- Detalhe da reserva (botão "Ver detalhes") ---------- */

function departureStatus(result) {
    if (!result) return '<span class="text-muted">Aguardando verificação</span>';
    if (result.status === 'not_found') return '<span class="text-error">Não conferido</span>';
    if (result.status === 'same') return '<span class="text-ok">Sem alterações</span>';

    const delta = formatDelta(result.savedDeparture, result.newDeparture);
    return `<span class="text-error">Novo horário: ${formatDateTime(result.newDeparture)}${delta ? ` (${delta})` : ''}</span>`;
}

function arrivalStatus(result, stretch) {
    if (!result) return '<span class="text-muted">Aguardando verificação</span>';
    if (result.arrivalChanged === null || result.arrivalChanged === undefined) return '<span class="text-muted">Não conferido</span>';
    if (!result.arrivalChanged) return '<span class="text-ok">Sem alterações</span>';

    const delta = formatDelta(stretch.arrivalOriginal, result.newArrival);
    return `<span class="text-error">Novo horário: ${formatDateTime(result.newArrival)}${delta ? ` (${delta})` : ''}</span>`;
}

function buildFlightCard(reserve, stretch, index) {
    const result = findResult(reserve, stretch, index);

    const originCity = AIRPORT_CITIES[stretch.origin];
    const destinationCity = AIRPORT_CITIES[stretch.destination];
    const cities = originCity && destinationCity
        ? `<span>${escapeHtml(originCity)} → ${escapeHtml(destinationCity)}</span>`
        : '';

    return `
        <div class="flight-card">
            <div class="flight-route"><strong>${escapeHtml(stretch.origin)} → ${escapeHtml(stretch.destination)}</strong>${cities}</div>
            <div class="flight-type">${escapeHtml(TYPES[stretch.type] || '')}</div>
            <div class="flight-line">Partida original: ${formatDateTime(stretch.departureOriginal)} ${departureStatus(result)}</div>
            <div class="flight-line">Chegada original: ${formatDateTime(stretch.arrivalOriginal)} ${arrivalStatus(result, stretch)}</div>
        </div>`;
}

function buildDetailsRow(reserve) {
    const stretches = reserve.stretches || [];
    const first = stretches[0] || {};

    const meta = [
        `PNR: ${escapeHtml(reserve.codeReserve)}`,
        escapeHtml(AIRLINES[first.company] || first.company || ''),
        reserve.telefone ? `Contato: ${escapeHtml(reserve.telefone)}` : '',
        reserve.folder ? `Pasta: ${escapeHtml(reserve.folder)}` : ''
    ].filter(Boolean).join(' · ');

    return `
        <tr class="details-row">
            <td colspan="7" class="details-cell">
                <div class="details-box">
                    <div class="details-name">${escapeHtml(reserve.name)}</div>
                    <div class="details-meta">${meta}</div>
                    <div class="details-flights">
                        ${stretches.map((stretch, index) => buildFlightCard(reserve, stretch, index)).join('')}
                    </div>
                </div>
            </td>
        </tr>`;
}


/* ---------- Renderização ---------- */

function renderCounters() {
    document.querySelectorAll('[data-count]').forEach(counter => {
        const status = counter.dataset.count;
        counter.textContent = reserves.filter(reserve => reserve.status === status).length;
    });
}

function buildRow(reserve) {
    const config = STATUS_CONFIG[reserve.status] || STATUS_CONFIG.pending;
    const stretches = reserve.stretches || [];
    const first = stretches[0] || {};
    const last = stretches[stretches.length - 1] || {};
    const id = escapeHtml(reserve.id);
    const isOpen = expanded.has(reserve.id);

    // Ida e volta (termina onde começou): mostra 'CNF ⇄ GRU'. Os demais: origem → destino final
    const isRoundTrip = stretches.length > 1 && last.destination === first.origin;
    const route = !stretches.length ? '-'
        : isRoundTrip ? `${first.origin} ⇄ ${first.destination}`
        : `${first.origin} → ${last.destination}`;
    const type = (stretches.some(stretch => stretch.type === 'international') ? TYPES.international : TYPES[first.type]) || '';
    const stretchesText = stretches.length > 1 ? (isRoundTrip ? 'ida e volta' : `${stretches.length} trechos`) : '';
    const routeSub = [type, stretchesText].filter(Boolean).join(' · ');

    // Resumo do que mudou (só para voos alterados ou já resolvidos)
    let detail = '';
    if (['high_priority', 'low_priority', 'solved'].includes(reserve.status)) {
        const summary = changeSummary(reserve);
        if (summary) detail = `<span class="change-detail">${escapeHtml(summary)}</span>`;
    }

    if (reserve.lastCheckError) {
        detail += `<span class="change-detail error">Falha na verificação: ${escapeHtml(reserve.lastCheckError)}</span>`;
    }

    const verification = reserve.verification;
    if (verification?.state === 'queued') {
        detail += '<span class="change-detail">Na fila — aguardando o verificador local</span>';
    } else if (verification?.state === 'running') {
        detail += '<span class="change-detail">Verificação em andamento</span>';
    } else if (verification?.state === 'failed' && verification.error && !reserve.lastCheckError) {
        detail += `<span class="change-detail error">Falha na verificação: ${escapeHtml(verification.error)}</span>`;
    }

    const canSolve = ['high_priority', 'low_priority'].includes(reserve.status);
    const canComplete = reserve.status !== 'completed';

    const buttons = [
        `<button type="button" class="btn-details" data-toggle="${id}">${isOpen ? ICON_CHEVRON_UP + ' Recolher' : ICON_CHEVRON_DOWN + ' Ver detalhes'}</button>`,
        reserve.telefone ? `<button type="button" class="btn-phone" data-phone="${escapeHtml(reserve.telefone)}" title="Copiar telefone">${escapeHtml(reserve.telefone)}</button>` : '',
        canSolve ? `<button type="button" class="btn-solved" data-action="solved" data-id="${id}">RESOLVIDO</button>` : '',
        canComplete ? `<button type="button" class="btn-completed" data-action="completed" data-id="${id}">REALIZADO</button>` : ''
    ].join('');

    const days = daysLabel(daysUntil(first.departureOriginal));

    const row = `
        <tr class="reserve-row">
            <td class="dot"><span class="status-dot ${config.dot}"></span></td>
            <td>
                <span class="client-name">${escapeHtml(reserve.name)}</span>
                <span class="client-pnr">PNR: ${escapeHtml(reserve.codeReserve)}</span>
            </td>
            <td>${escapeHtml(AIRLINES[first.company] || first.company || '-')}</td>
            <td>
                <span class="cell-main">${escapeHtml(route)}</span>
                <span class="cell-sub">${escapeHtml(routeSub)}</span>
            </td>
            <td>
                <span class="nowrap">${formatDateTime(first.departureOriginal)}</span>
                <span class="cell-sub">${days}</span>
            </td>
            <td>
                <span class="badge ${config.badge}">${config.icon}${config.label}</span>
                ${detail}
            </td>
            <td><div class="actions-cell">${buttons}</div></td>
        </tr>`;

    return row + (isOpen ? buildDetailsRow(reserve) : '');
}

function renderTable() {
    const query = (document.querySelector('[data-menu-search]')?.value || '')
        .normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
    const visible = reserves
        .filter(reserve => !activeFilter || reserve.status === activeFilter)
        .filter(reserve => `${reserve.name || ''} ${reserve.codeReserve || ''} ${reserve.id} ${reserve.folder || ''}`
            .normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().includes(query))
        .sort((a, b) => {
            const byStatus = STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status);
            if (byStatus !== 0) return byStatus;

            const dateA = (a.stretches?.[0]?.departureOriginal) || '';
            const dateB = (b.stretches?.[0]?.departureOriginal) || '';
            return dateA.localeCompare(dateB);
        });

    if (!visible.length) {
        monitoringBody.innerHTML = '<tr><td colspan="7" class="empty-row">Nenhuma reserva nesta lista.</td></tr>';
        return;
    }

    monitoringBody.innerHTML = visible.map(buildRow).join('');
}

function render() {
    renderCounters();
    renderTable();

    cards.forEach(card => {
        card.querySelector('.card').classList.toggle('card-active', card.dataset.filter === activeFilter);
    });

    chips.forEach(chip => {
        chip.classList.toggle('active', (chip.dataset.chip || null) === activeFilter);
    });
}

function setFilter(filter) {
    activeFilter = filter;
    render();
}


/* ---------- Carregar reservas ---------- */

async function loadReserves(silent = false) {
    try {
        const response = await window.Verifly.fetch(API_URL);

        if (!response.ok) {
            throw new Error('Erro ao buscar as reservas (status ' + response.status + ')');
        }

        reserves = await response.json();
        render();

    } catch (error) {
        console.error(error);
        if (!silent) {
            monitoringBody.innerHTML = '<tr><td colspan="7" class="empty-row">Não foi possível carregar as reservas.</td></tr>';
        }
    }
}


/* ---------- Filtros (cards e chips) ---------- */

cards.forEach(card => {
    card.addEventListener('click', (event) => {
        event.preventDefault();

        const filter = card.dataset.filter;
        setFilter(activeFilter === filter ? null : filter);
    });
});

chips.forEach(chip => {
    chip.addEventListener('click', () => setFilter(chip.dataset.chip || null));
});


/* ---------- Ações dentro da tabela ---------- */

async function copyPhone(button) {
    const phone = button.dataset.phone;
    const original = button.textContent;

    try {
        await navigator.clipboard.writeText(phone);
        button.textContent = 'Copiado!';
        setTimeout(() => { button.textContent = original; }, 1500);
    } catch (error) {
        window.prompt('Copie o telefone:', phone); // se o navegador bloquear a área de transferência
    }
}

async function changeStatus(button) {
    const message = button.dataset.action === 'solved'
        ? 'Marcar este voo como RESOLVIDO?'
        : 'Marcar este voo como REALIZADO?';

    if (!confirm(message)) return;

    button.disabled = true;

    try {
        const response = await window.Verifly.fetch(`${API_URL}/${encodeURIComponent(button.dataset.id)}/status`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: button.dataset.action })
        });

        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            throw new Error(body.erro || 'Erro ao atualizar o status (status ' + response.status + ')');
        }

        replaceReserve(await response.json());
        render(); // contadores e listas são recalculados

    } catch (error) {
        console.error(error);
        alert(error.message);
        button.disabled = false;
    }
}

monitoringBody.addEventListener('click', (event) => {
    const toggle = event.target.closest('[data-toggle]');
    if (toggle) {
        const id = toggle.dataset.toggle;
        expanded.has(id) ? expanded.delete(id) : expanded.add(id);
        render();
        return;
    }

    const phone = event.target.closest('[data-phone]');
    if (phone) {
        copyPhone(phone);
        return;
    }

    const action = event.target.closest('[data-action]');
    if (action) {
        changeStatus(action);
    }
});


/* ---------- Solicitar verificações para o worker local ---------- */

btnCheckAll.addEventListener('click', async () => {
    const targets = reserves.filter(reserve => COMPARABLE_STATUS.includes(reserve.status));

    if (!targets.length) {
        alert('Não há reservas para verificar.');
        return;
    }

    btnCheckAll.disabled = true;
    let failures = 0;

    try {
        for (let index = 0; index < targets.length; index++) {
            btnCheckAll.textContent = `Solicitando ${index + 1}/${targets.length}...`;

            try {
                const response = await window.Verifly.fetch(`${API_URL}/${encodeURIComponent(targets[index].id)}/comparar`, { method: 'POST' });

                if (!response.ok) {
                    const body = await response.json().catch(() => ({}));
                    throw new Error(body.erro || `Falha ao solicitar verificação (${response.status})`);
                }

                replaceReserve(await response.json());
                render();
            } catch (error) {
                failures++;
                console.error(error);
            }
        }
    } finally {
        btnCheckAll.disabled = false;
        btnCheckAll.textContent = 'Verificar voos agora';
    }
    if (failures) {
        alert(`Não foi possível solicitar a verificação de ${failures} reserva(s). Tente novamente.`);
    }
});


document.querySelector('[data-menu-search]')?.addEventListener('input', renderTable);
loadReserves();

// Atualiza os resultados que o worker publica, inclusive após recarregar o painel.
async function refreshMonitoring() {
    if (!document.hidden && !btnCheckAll.disabled) {
        await loadReserves(true);
    }
    setTimeout(refreshMonitoring, 5000);
}
setTimeout(refreshMonitoring, 5000);
