"""Fila compartilhada: o painel solicita e o worker local executa as buscas."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from .comparator import COLLECTION, COMPARABLE_STATUS, STATUS_PENDING
from .firebase_db import db
from .reservation_history import append_event

JOBS_COLLECTION = "verificacoes"
LEASE_SECONDS = 300
PUBLIC_FIELDS = ("state", "requestedAt", "startedAt", "finishedAt", "error")


def now():
    return datetime.now(timezone.utc)


def public_job(job):
    return {key: job.get(key) for key in PUBLIC_FIELDS}


def attach_jobs(reserves):
    if not reserves:
        return reserves
    refs = [db.collection(JOBS_COLLECTION).document(reserve["id"]) for reserve in reserves]
    jobs = {snap.id: public_job(snap.to_dict()) for snap in db.get_all(refs) if snap.exists}
    for reserve in reserves:
        reserve["verification"] = jobs.get(reserve["id"])
    return reserves


def request_check(reserve_id):
    reserve_ref = db.collection(COLLECTION).document(reserve_id)
    job_ref = db.collection(JOBS_COLLECTION).document(reserve_id)

    @firestore.transactional
    def enqueue(transaction):
        snapshot = reserve_ref.get(transaction=transaction)
        job_snapshot = job_ref.get(transaction=transaction)
        if not snapshot.exists:
            raise LookupError(reserve_id)
        reserve = snapshot.to_dict()
        reserve["id"] = reserve_id
        job = job_snapshot.to_dict() or {}
        if reserve.get("status", STATUS_PENDING) in COMPARABLE_STATUS:
            # Um documento por reserva evita buscas duplicadas por cliques repetidos.
            if job.get("state") not in ("queued", "running"):
                job = {"state": "queued", "requestedAt": now().isoformat(), "error": None}
                transaction.set(job_ref, job)
                append_event(db, transaction, reserve_ref, "check_requested", reserve, reserve)
        reserve["verification"] = public_job(job) if job else None
        return reserve

    return enqueue(db.transaction())


def claim_next():
    jobs = db.collection(JOBS_COLLECTION)
    # Filtros simples dispensam a criação de índices compostos no Firestore.
    for state in ("queued", "running"):
        query = jobs.where(filter=FieldFilter("state", "==", state))
        for snapshot in query.stream():
            candidate = snapshot.to_dict()
            if state == "running" and candidate.get("leaseUntil", now()) > now():
                continue
            claim = _claim(snapshot.reference)
            if claim:
                return claim
    return None


def _claim(job_ref):
    @firestore.transactional
    def claim(transaction):
        snapshot = job_ref.get(transaction=transaction)
        job = snapshot.to_dict() or {}
        current_time = now()
        if job.get("state") != "queued" and not (
            job.get("state") == "running" and job.get("leaseUntil", current_time) <= current_time
        ):
            return None
        token = uuid4().hex
        transaction.update(job_ref, {
            "state": "running", "token": token,
            "startedAt": current_time.isoformat(), "finishedAt": None,
            "leaseUntil": current_time + timedelta(seconds=LEASE_SECONDS), "error": None,
        })
        return job_ref.id, token

    return claim(db.transaction())


def renew_lease(reserve_id, token):
    job_ref = db.collection(JOBS_COLLECTION).document(reserve_id)

    @firestore.transactional
    def renew(transaction):
        job = job_ref.get(transaction=transaction).to_dict() or {}
        if job.get("token") != token or job.get("state") != "running":
            return False
        transaction.update(job_ref, {"leaseUntil": now() + timedelta(seconds=LEASE_SECONDS)})
        return True

    return renew(db.transaction())


def finish_check(reserve_id, token, searched_reserve, update, error=None):
    """Publica apenas o resultado do worker atual e preserva edições manuais."""
    job_ref = db.collection(JOBS_COLLECTION).document(reserve_id)
    reserve_ref = db.collection(COLLECTION).document(reserve_id)

    @firestore.transactional
    def finish(transaction):
        job = job_ref.get(transaction=transaction).to_dict() or {}
        snapshot = reserve_ref.get(transaction=transaction)
        if job.get("token") != token or job.get("state") != "running":
            return False
        reserve = snapshot.to_dict() or {}
        state = "failed" if error or (update or {}).get("lastCheckError") else "done"
        message = error or (update or {}).get("lastCheckError")
        if not snapshot.exists or reserve.get("status", STATUS_PENDING) not in COMPARABLE_STATUS:
            state, message = "skipped", None
        elif searched_reserve is not None and reserve.get("stretches") != searched_reserve.get("stretches"):
            # O cadastro mudou enquanto a companhia era consultada: buscar novamente.
            transaction.update(job_ref, {"state": "queued", "error": None, "token": None})
            return False
        elif update:
            before = dict(reserve)
            reserve.update(update)
            transaction.update(reserve_ref, update)
            append_event(db, transaction, reserve_ref, "check_failed" if state == "failed" else "checked", before, reserve)
        transaction.update(job_ref, {
            "state": state, "error": message, "finishedAt": now().isoformat(),
            "leaseUntil": now(), "token": None,
        })
        return True

    return finish(db.transaction())
