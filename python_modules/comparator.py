"""
MÓDULO COMPARADOR DE VOOS

Fluxo (para uma reserva):
  1. Busca a reserva no Firestore e guarda a URL em uma variável (get_reserve_url)
  2. Passa a URL para o buscador real da companhia (flight_search.search_flight)
  3. Compara data e horário de embarque do retorno da companhia com o que está salvo
  4. Classifica e grava o status no próprio documento da reserva

A classificação usa SÓ o embarque. A chegada também é comparada, mas apenas
para exibir no detalhe da reserva (não muda a prioridade).
"""

import re
import unicodedata
from datetime import date, datetime

from .firebase_db import db
from google.cloud import firestore
from .reservation_history import append_event


COLLECTION = "reservas"

HIGH_PRIORITY_DAYS = 60  # <= 60 dias para o embarque = alta prioridade

# Status possíveis de uma reserva (campo "status" no Firestore)
STATUS_PENDING = "pending"            # cadastrada, ainda não verificada
STATUS_HIGH = "high_priority"         # alterada e embarque em até 60 dias
STATUS_LOW = "low_priority"           # alterada e embarque em mais de 60 dias
STATUS_CONFIRMED = "confirmed"        # sem alteração
STATUS_SOLVED = "solved"              # manual (botão RESOLVIDO)
STATUS_COMPLETED = "completed"        # manual (botão REALIZADO)

# O comparador só mexe nesses. "solved" e "completed" são definidos pela equipe
# e não podem ser sobrescritos por uma nova verificação.
COMPARABLE_STATUS = (STATUS_PENDING, STATUS_HIGH, STATUS_LOW, STATUS_CONFIRMED)


# ---------------------------------------------------------------------------
# Conversão de datas
# ---------------------------------------------------------------------------

def parse_saved_datetime(value):
    """Formato salvo pelo formulário: '2026-10-07T13:30' (ou só '2026-10-07').
    Devolve (date, 'HH:MM') ou (date, None) se não houver horário."""

    if not value:
        return None, None

    day_text, _, hour_text = value.partition("T")

    try:
        day = datetime.strptime(day_text, "%Y-%m-%d").date()
    except ValueError:
        return None, None

    return day, (hour_text[:5] or None)


MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12
}


def _plain(text):
    """minúsculas e sem acentos ('Fevereiro' -> 'fevereiro')."""
    normalized = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def parse_company_datetime(date_text, hour_text):
    """Lê data e hora como o buscador devolve.

    Aceita, na data: '23/05/2027', '23/05/27', '2027-05-23', '23/05' (sem ano),
    '23 de maio de 2027', '23 mai 2027', 'qui, 23 mai'.
    Aceita, na hora: '12:55', '6:10', '12h55'.

    Procura cada um pelo padrão, então funciona mesmo se data e hora vierem
    trocadas (o buscador da Azul troca os dois no 'destiny').

    Devolve ((ano|None, mes, dia) | None, 'HH:MM' | None).
    O ano pode vir None; resolve_day() descobre o ano depois."""

    joined = _plain(f"{date_text or ''} {hour_text or ''}")

    hour = None
    hour_match = re.search(r"(\d{1,2})\s*[:h]\s*(\d{2})", joined)
    if hour_match:
        hour = f"{int(hour_match.group(1)):02d}:{hour_match.group(2)}"

    date_info = None

    iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", joined)
    numeric = re.search(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?", joined)
    textual = re.search(r"(\d{1,2})\s*(?:de\s+)?([a-z]{3,9})\.?(?:\s*(?:de\s+)?(\d{4}))?", joined)

    if iso:
        date_info = (int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))

    elif numeric:
        year = int(numeric.group(3)) if numeric.group(3) else None
        if year is not None and year < 100:
            year += 2000
        date_info = (year, int(numeric.group(2)), int(numeric.group(1)))

    elif textual and textual.group(2)[:3] in MONTHS:
        year = int(textual.group(3)) if textual.group(3) else None
        date_info = (year, MONTHS[textual.group(2)[:3]], int(textual.group(1)))

    return date_info, hour


def resolve_day(date_info, reference):
    """Transforma (ano|None, mes, dia) em date.
    Sem ano, escolhe o ano que deixa a data mais perto da data de referência
    (a data cadastrada na reserva)."""

    if date_info is None:
        return None

    year, month, day = date_info

    years = [year] if year else [reference.year + delta for delta in (-1, 0, 1)] if reference else [date.today().year]

    candidates = []
    for candidate_year in years:
        try:
            candidates.append(date(candidate_year, month, day))
        except ValueError:
            continue

    if not candidates:
        return None

    if reference and not year:
        return min(candidates, key=lambda d: abs((d - reference).days))

    return candidates[0]


def to_iso(day, hour):
    return day.isoformat() + (f"T{hour}" if hour else "")


def clean_airport(text):
    match = re.search(r"\b[A-Z]{3}\b", (text or "").upper())
    return match.group(0) if match else (text or "").strip().upper()


# ---------------------------------------------------------------------------
# Passo 1: URL da reserva
# ---------------------------------------------------------------------------

def get_reserve_url(stretches):
    """Primeira URL preenchida entre os trechos (uma reserva = um link)."""
    return next((s.get("urlReserve") for s in stretches if s.get("urlReserve")), None)


# ---------------------------------------------------------------------------
# Passo 3: comparação
# ---------------------------------------------------------------------------

def extract_company_legs(company_data):
    """Transforma o retorno do buscador em uma lista de voos (ida e volta)."""

    legs = []

    for key in ("outbound_flight_infos", "return_flight_infos"):
        info = (company_data or {}).get(key)

        if not info:
            continue

        origin = info.get("origin") or {}
        destiny = info.get("destiny") or {}

        departure_info, departure_hour = parse_company_datetime(origin.get("date"), origin.get("hour"))

        if departure_info is None:  # busca falhou (o buscador devolve None em tudo)
            continue

        arrival_info, arrival_hour = parse_company_datetime(destiny.get("date"), destiny.get("hour"))

        legs.append({
            "origin": clean_airport(origin.get("airport")),
            "destination": clean_airport(destiny.get("airport")),
            "departureInfo": departure_info,
            "departureHour": departure_hour,
            "arrivalInfo": arrival_info,
            "arrivalHour": arrival_hour
        })

    return legs


def match_legs(segments, legs):
    """Liga cada trecho cadastrado a um voo da companhia (cada voo é usado uma vez).
    Ordem de tentativa: origem + destino iguais -> só a origem igual ->
    mesma posição (só quando há o mesmo número de trechos e de voos)."""

    matched = [None] * len(segments)
    used = set()

    def attach(index, leg_index):
        matched[index] = legs[leg_index]
        used.add(leg_index)

    for i, segment in enumerate(segments):
        for j, leg in enumerate(legs):
            if j not in used and leg["origin"] == segment.get("origin") and leg["destination"] == segment.get("destination"):
                attach(i, j)
                break

    for i, segment in enumerate(segments):
        if matched[i] is not None:
            continue
        for j, leg in enumerate(legs):
            if j not in used and leg["origin"] == segment.get("origin"):
                attach(i, j)
                break

    if len(legs) == len(segments):
        for i in range(len(segments)):
            if matched[i] is None and i not in used:
                attach(i, i)

    return matched


def compare_segment(segment, leg):
    """Compara data e horário de embarque (e, só para exibição, a chegada) de UM trecho."""

    saved_day, saved_hour = parse_saved_datetime(segment.get("departureOriginal"))
    saved_arrival_day, saved_arrival_hour = parse_saved_datetime(segment.get("arrivalOriginal"))

    result = {
        "order": segment.get("order"),
        "origin": segment.get("origin"),
        "destination": segment.get("destination"),
        "savedDeparture": segment.get("departureOriginal"),
        "newDeparture": None,
        "changedFields": [],
        "savedArrival": segment.get("arrivalOriginal"),
        "newArrival": None,
        "arrivalChanged": None,   # None = não deu para conferir
        "status": "not_found"     # not_found | same | changed
    }

    if leg is None or saved_day is None:
        return result

    new_day = resolve_day(leg["departureInfo"], saved_day)

    if new_day is None:
        return result

    if saved_day != new_day:
        result["changedFields"].append("date")

    # Se o cadastro não tem horário, só a data é comparada
    if saved_hour and leg["departureHour"] and saved_hour != leg["departureHour"]:
        result["changedFields"].append("hour")

    result["newDeparture"] = to_iso(new_day, leg["departureHour"])
    result["status"] = "changed" if result["changedFields"] else "same"

    # Chegada: só informativa
    new_arrival_day = resolve_day(leg["arrivalInfo"], saved_arrival_day or saved_day)

    if new_arrival_day and saved_arrival_day:
        hour_differs = bool(saved_arrival_hour and leg["arrivalHour"] and saved_arrival_hour != leg["arrivalHour"])

        result["newArrival"] = to_iso(new_arrival_day, leg["arrivalHour"])
        result["arrivalChanged"] = (new_arrival_day != saved_arrival_day) or hour_differs

    return result


# ---------------------------------------------------------------------------
# Regras de negócio: classificação
# ---------------------------------------------------------------------------

def classify(segment_results, today=None):
    changed = [r for r in segment_results if r["status"] == "changed"]

    if not changed:
        return STATUS_CONFIRMED

    today = today or date.today()

    # Embarque mais próximo entre os trechos alterados (data ORIGINAL cadastrada)
    nearest = min(parse_saved_datetime(r["savedDeparture"])[0] for r in changed)

    if (nearest - today).days <= HIGH_PRIORITY_DAYS:
        return STATUS_HIGH

    return STATUS_LOW


# ---------------------------------------------------------------------------
# Funções chamadas pelo app.py
# ---------------------------------------------------------------------------

def compare_reserve(reserve_id):
    """Executa o fluxo completo para uma reserva e devolve a reserva atualizada."""

    doc_ref = db.collection(COLLECTION).document(reserve_id)
    snapshot = doc_ref.get()

    if not snapshot.exists:
        raise LookupError(reserve_id)

    reserve = snapshot.to_dict()

    # Resolvido/Realizado são manuais: não são reclassificados
    if reserve.get("status", STATUS_PENDING) not in COMPARABLE_STATUS:
        return _with_id(reserve, reserve_id)

    update = build_comparison_update(reserve)

    @firestore.transactional
    def publish(transaction):
        current_snapshot = doc_ref.get(transaction=transaction)
        if not current_snapshot.exists:
            raise LookupError(reserve_id)
        current = current_snapshot.to_dict()
        if current.get("status", STATUS_PENDING) not in COMPARABLE_STATUS:
            return _with_id(current, reserve_id)
        if current.get("stretches") != reserve.get("stretches"):
            raise ValueError("A reserva foi editada durante a busca; verifique novamente")
        updated = {**current, **update}
        transaction.update(doc_ref, update)
        append_event(db, transaction, doc_ref, "check_failed" if update.get("lastCheckError") else "checked", current, updated)
        return _with_id(updated, reserve_id)

    return publish(db.transaction())


def build_comparison_update(reserve):
    """Busca e compara localmente, sem gravar resultados no banco."""
    from .flight_search import search_flight

    stretches = reserve.get("stretches") or []
    reserve_url = get_reserve_url(stretches)                         # 1. URL em uma variável
    company = stretches[0].get("company") if stretches else None

    update = {"lastCheck": _now()}

    try:
        if not reserve_url:
            raise ValueError("Reserva sem URL cadastrada")

        company_data = search_flight(reserve_url, company, reserve)  # 2. URL vai para o buscador
        legs = extract_company_legs(company_data)

        if not legs:
            raise ValueError("A busca não retornou dados de voo")

        matched = match_legs(stretches, legs)
        results = [compare_segment(s, leg) for s, leg in zip(stretches, matched)]  # 3. comparação

        has_changes = any(r["status"] == "changed" for r in results)
        has_missing = any(r["status"] == "not_found" for r in results)

        if has_missing and not has_changes:
            raise ValueError("Não foi possível localizar todos os trechos na companhia")

        update["status"] = classify(results)                         # 4. classificação
        update["segmentResults"] = results
        update["lastCheckError"] = None

    except Exception as error:
        # Falha na busca: mantém o status atual e registra o motivo
        update["lastCheckError"] = str(error)

    return update


def set_manual_status(reserve_id, new_status):
    """Botões RESOLVIDO e REALIZADO. Devolve a reserva atualizada."""

    if new_status not in (STATUS_SOLVED, STATUS_COMPLETED):
        raise ValueError("Status inválido")

    doc_ref = db.collection(COLLECTION).document(reserve_id)

    @firestore.transactional
    def change(transaction):
        snapshot = doc_ref.get(transaction=transaction)
        if not snapshot.exists:
            raise LookupError(reserve_id)
        reserve = snapshot.to_dict()
        current = reserve.get("status", STATUS_PENDING)
        if new_status == STATUS_SOLVED and current not in (STATUS_HIGH, STATUS_LOW):
            raise ValueError("Só é possível resolver voos que sofreram alteração")
        if new_status == STATUS_COMPLETED and current == STATUS_COMPLETED:
            raise ValueError("O voo já está como realizado")
        update = {"status": new_status, "previousStatus": current, "statusUpdatedAt": _now()}
        updated = {**reserve, **update}
        transaction.update(doc_ref, update)
        append_event(db, transaction, doc_ref, "status_changed", reserve, updated)
        return _with_id(updated, reserve_id)

    return change(db.transaction())


def _with_id(reserve, reserve_id):
    reserve["id"] = reserve_id
    return reserve


def _now():
    return datetime.now().isoformat(timespec="seconds")
