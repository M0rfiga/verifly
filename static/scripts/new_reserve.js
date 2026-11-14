const form = document.getElementById('new-reserve-form');
const segmentsList = document.getElementById('segments-list');
const btnAddSegment = document.getElementById('btn-add-segment');
const btnRegister = form.querySelector('.btn-register');

const API_URL = '/api/reservas';


/* ---------- Trechos (adicionar / remover) ---------- */

function updateSegments() {
    const segments = segmentsList.querySelectorAll('.segment');

    segments.forEach((segment, index) => {
        segment.querySelector('.segment-tag').textContent = 'TRECHO ' + (index + 1);

        const btnRemove = segment.querySelector('.btn-remove-segment');

        // O primeiro trecho nunca pode ser removido
        if (index === 0 && btnRemove) {
            btnRemove.remove();
        }
    });
}

function createRemoveButton() {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-remove-segment';
    btn.setAttribute('aria-label', 'Remover trecho');
    btn.innerHTML = '&times;';
    return btn;
}

function addSegment() {
    const clone = segmentsList.querySelector('.segment').cloneNode(true);

    clone.querySelectorAll('input').forEach(input => {
        input.value = '';
        input.setCustomValidity('');
    });
    clone.querySelectorAll('select').forEach(select => select.selectedIndex = 0);

    clone.querySelector('.segment-top').appendChild(createRemoveButton());

    segmentsList.appendChild(clone);
    updateSegments();
}

function resetSegments() {
    const segments = segmentsList.querySelectorAll('.segment');
    segments.forEach((segment, index) => {
        if (index > 0) segment.remove();
    });
    updateSegments();
}

btnAddSegment.addEventListener('click', addSegment);

segmentsList.addEventListener('click', (event) => {
    const btnRemove = event.target.closest('.btn-remove-segment');
    if (!btnRemove) return;

    btnRemove.closest('.segment').remove();
    updateSegments();
});


/* ---------- Validação: chegada não pode ser antes da partida ---------- */

function validateDates(segment) {
    const departure = segment.querySelector('[name="departure_date"]');
    const arrival = segment.querySelector('[name="arrival_date"]');

    // datetime-local ('2026-10-07T13:30') pode ser comparado como texto
    if (departure.value && arrival.value && arrival.value < departure.value) {
        arrival.setCustomValidity('A chegada não pode ser antes da partida.');
    } else {
        arrival.setCustomValidity('');
    }
}

// Funciona também nos trechos adicionados depois (delegação de eventos)
segmentsList.addEventListener('input', (event) => {
    if (event.target.matches('[name="departure_date"], [name="arrival_date"]')) {
        validateDates(event.target.closest('.segment'));
    }
});


/* ---------- Coleta dos dados do formulário ---------- */

function getSegmentsData() {
    return Array.from(segmentsList.querySelectorAll('.segment')).map((segment, index) => ({
        order: index + 1,
        origin: segment.querySelector('[name="origin"]').value.trim().toUpperCase(),
        destination: segment.querySelector('[name="destination"]').value.trim().toUpperCase(),
        type: segment.querySelector('[name="type"]').value,
        departureOriginal: segment.querySelector('[name="departure_date"]').value, // '2026-10-07T13:30'
        arrivalOriginal: segment.querySelector('[name="arrival_date"]').value,     // '2026-10-07T16:50'
        company: segment.querySelector('[name="airline"]').value,
        urlReserve: segment.querySelector('[name="reserve_url"]').value.trim()
    }));
}

function getReserveData() {
    return {
        name: form.elements['client_name'].value.trim(),
        codeReserve: form.elements['reserve_pnr'].value.trim().toUpperCase(),
        telefone: form.elements['client_phone'].value.trim(),
        folder: form.elements['folder'].value.trim(),
        stretches: getSegmentsData()
    };
}


/* ---------- Envio para o backend (que grava no Firestore) ---------- */

form.addEventListener('submit', async (event) => {
    event.preventDefault();

    const reserveData = getReserveData();

    btnRegister.disabled = true;
    btnRegister.textContent = 'Cadastrando...';

    try {
        const response = await window.Verifly.fetch(API_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(reserveData)
        });

        if (!response.ok) {
            throw new Error('Erro ao salvar a reserva (status ' + response.status + ')');
        }

        alert('Reserva cadastrada com sucesso!');
        form.reset();
        resetSegments();

    } catch (error) {
        console.error(error);
        alert('Não foi possível cadastrar a reserva. Tente novamente.');

    } finally {
        btnRegister.disabled = false;
        btnRegister.textContent = 'Cadastrar e Monitorar';
    }
});