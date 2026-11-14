"""Pesquisa global e notificações com leitura persistida por usuário."""

import unicodedata
import hashlib

from google.cloud import firestore


def plain(value):
    text = unicodedata.normalize("NFD", str(value or ""))
    return "".join(char for char in text if not unicodedata.combining(char)).casefold()


def search_reserves(db, query):
    query = plain(query.strip())
    if not query:
        return []
    results = []
    for snapshot in db.collection("reservas").stream():
        reserve = snapshot.to_dict()
        text = " ".join(str(reserve.get(field) or "") for field in ("name", "codeReserve", "folder"))
        if query not in plain(f"{snapshot.id} {text}"):
            continue
        results.append({
            "id": snapshot.id, "name": reserve.get("name"), "codeReserve": reserve.get("codeReserve") or snapshot.id,
            "folder": reserve.get("folder"), "status": reserve.get("status", "pending"),
        })
    results.sort(key=lambda item: (plain(item["codeReserve"]) != query, plain(item["name"])))
    return results[:8]


def notification_state_ref(db, user_id):
    return db.collection("usuarios").document(user_id).collection("estado").document("notificacoes")


def list_notifications(db, user_id):
    state = notification_state_ref(db, user_id).get().to_dict() or {}
    read_ids = set(state.get("readIds", []))
    snapshots = db.collection("notificacoes").order_by("occurredAt", direction=firestore.Query.DESCENDING).limit(50).stream()
    notifications = [{**snapshot.to_dict(), "id": snapshot.id, "read": snapshot.id in read_ids} for snapshot in snapshots]
    # Reservas anteriores à central de notificações também exibem seus alertas atuais.
    represented = {(item["reserveId"], item["type"]) for item in notifications}
    for snapshot in db.collection("reservas").stream():
        reserve = snapshot.to_dict()
        if reserve.get("status") not in ("pending", "confirmed", "high_priority", "low_priority"):
            continue
        kind = "check_failed" if reserve.get("lastCheckError") else "checked" if reserve.get("status") in ("high_priority", "low_priority") else None
        if not kind or (snapshot.id, kind) in represented:
            continue
        occurred_at = reserve.get("lastCheck") or reserve.get("historyLastAt") or reserve.get("createdAt") or ""
        fingerprint = f"{snapshot.id}|{kind}|{occurred_at}|{reserve.get('lastCheckError', '')}"
        notification_id = "legacy-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:32]
        notifications.append({
            "id": notification_id, "reserveId": snapshot.id, "type": kind,
            "title": "Falha na verificação" if kind == "check_failed" else "Alteração de voo identificada",
            "occurredAt": occurred_at, "name": reserve.get("name"), "codeReserve": reserve.get("codeReserve") or snapshot.id,
            "status": reserve.get("status"), "message": reserve.get("lastCheckError"), "read": notification_id in read_ids,
        })
    notifications.sort(key=lambda item: item.get("occurredAt") or "", reverse=True)
    notifications = notifications[:50]
    return {"notifications": notifications, "unreadCount": sum(not item["read"] for item in notifications)}


def mark_notifications_read(db, user_id, ids):
    if not isinstance(ids, list) or len(ids) > 50 or any(not isinstance(item, str) or not item or len(item) > 128 or "/" in item for item in ids):
        raise ValueError("Notificações inválidas")
    ref = notification_state_ref(db, user_id)

    @firestore.transactional
    def mark(transaction):
        state = ref.get(transaction=transaction).to_dict() or {}
        read_ids = list(dict.fromkeys(state.get("readIds", []) + ids))[-200:]
        transaction.set(ref, {"readIds": read_ids})

    mark(db.transaction())
