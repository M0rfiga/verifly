"""Contas administrativas e sessões revogáveis armazenadas no Firestore."""

import hashlib
import re
import secrets
import time
from datetime import datetime, timezone

import httpx
from google.cloud import firestore
from werkzeug.security import check_password_hash, generate_password_hash

SESSION_COOKIE = "verifly_session"
LOGIN_CSRF_COOKIE = "verifly_login_csrf"
SESSION_SECONDS = 8 * 60 * 60
ATTEMPT_WINDOW = 15 * 60
MAX_ATTEMPTS = 5
DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(32))


class LoginThrottled(Exception):
    def __init__(self, retry_after):
        self.retry_after = retry_after


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_email(value):
    return str(value or "").strip().casefold()


def public_user(user):
    return {"id": user["id"], "email": user["email"], "name": user.get("name") or user["email"]}


def create_user(db, email, name, password, reset=False):
    email = normalize_email(email)
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Informe um e-mail válido")
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("A senha deve ter entre 12 e 256 caracteres")
    if not str(name or "").strip():
        raise ValueError("Informe o nome do usuário")
    ref = db.collection("usuarios").document(digest(email))
    password_hash = generate_password_hash(password)

    @firestore.transactional
    def save(transaction):
        previous = ref.get(transaction=transaction)
        if previous.exists and not reset:
            raise ValueError("Usuário já existe. Use --reset-password para redefinir a senha")
        if reset and not previous.exists:
            raise ValueError("Usuário não encontrado para redefinição")
        now = datetime.now(timezone.utc).isoformat()
        user = {
            "email": email, "name": str(name).strip()[:100], "passwordHash": password_hash,
            "enabled": True, "passwordVersion": secrets.token_hex(16),
            "createdAt": (previous.to_dict() or {}).get("createdAt") or now, "updatedAt": now,
        }
        transaction.set(ref, user)
        return {**public_user({**user, "id": ref.id})}

    return save(db.transaction())


def consume_login_attempt(db, email, remote_ip):
    ref = db.collection("tentativas_login").document(digest(f"{email}|{remote_ip}"))

    @firestore.transactional
    def consume(transaction):
        record = ref.get(transaction=transaction).to_dict() or {}
        now = time.time()
        start = record.get("windowStart", now)
        count = record.get("count", 0) if now - start < ATTEMPT_WINDOW else 0
        if count >= MAX_ATTEMPTS:
            raise LoginThrottled(max(1, int(start + ATTEMPT_WINDOW - now)))
        transaction.set(ref, {"count": count + 1, "windowStart": start if count else now})

    consume(db.transaction())
    return ref


def authenticate(db, email, password, remote_ip):
    email = normalize_email(email)
    attempt_ref = consume_login_attempt(db, email, remote_ip)
    snapshot = db.collection("usuarios").document(digest(email)).get()
    user = snapshot.to_dict() or {}
    valid = check_password_hash(user.get("passwordHash") or DUMMY_HASH, password)
    if not valid or not snapshot.exists or not user.get("enabled", False):
        return None
    attempt_ref.delete()
    return {**user, "id": snapshot.id}


def create_session(db, user):
    token = secrets.token_urlsafe(48)
    session = {
        "userId": user["id"], "csrfToken": secrets.token_urlsafe(32),
        "passwordVersion": user["passwordVersion"],
        "expiresAt": time.time() + SESSION_SECONDS,
    }
    db.collection("sessoes").document(digest(token)).set(session)
    return token


def load_session(db, token):
    if not token or len(token) > 256:
        return None
    snapshot = db.collection("sessoes").document(digest(token)).get()
    session = snapshot.to_dict() or {}
    if not snapshot.exists or session.get("expiresAt", 0) <= time.time():
        return None
    user_snapshot = db.collection("usuarios").document(session["userId"]).get()
    user = user_snapshot.to_dict() or {}
    if not user.get("enabled") or user.get("passwordVersion") != session.get("passwordVersion"):
        return None
    return {**session, "user": public_user({**user, "id": user_snapshot.id})}


def revoke_session(db, token):
    if token and len(token) <= 256:
        db.collection("sessoes").document(digest(token)).delete()


def valid_csrf(expected, supplied):
    return bool(expected and supplied and secrets.compare_digest(str(expected), str(supplied)))


def verify_turnstile(secret, token, remote_ip):
    if not isinstance(token, str) or not token or len(token) > 2048:
        return False
    try:
        response = httpx.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": secret, "response": token, "remoteip": remote_ip}, timeout=10,
        )
        response.raise_for_status()
        return response.json().get("success") is True
    except (httpx.HTTPError, ValueError):
        return False
