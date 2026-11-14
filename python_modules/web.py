"""Aplicação Flask, autenticação das rotas e APIs do VeriFly."""

import os
import secrets
from pathlib import Path

from flask import Flask, g, render_template, request, jsonify, redirect, make_response, url_for

from .firebase_db import db
from .comparator import set_manual_status
from .verification_queue import attach_jobs, request_check
from .reservation_history import get_history, save_reserve
from .authentication import (
    SESSION_COOKIE, LOGIN_CSRF_COOKIE, SESSION_SECONDS, LoginThrottled,
    authenticate, create_session, load_session, revoke_session, valid_csrf, verify_turnstile,
)
from .menu_services import search_reserves, list_notifications, mark_notifications_read


PROJECT_ROOT = Path(__file__).resolve().parent.parent
app = Flask(
    __name__,
    template_folder=str(PROJECT_ROOT / "templates"),
    static_folder=str(PROJECT_ROOT / "static"),
    static_url_path="/static",
)
app.config.update(
    SESSION_COOKIE_SECURE=os.environ.get("VERIFLY_COOKIE_SECURE", "0") == "1",
    TURNSTILE_SITE_KEY=os.environ.get("TURNSTILE_SITE_KEY", ""),
    TURNSTILE_SECRET_KEY=os.environ.get("TURNSTILE_SECRET_KEY", ""),
    MAX_CONTENT_LENGTH=1024 * 1024,
)


def set_private_cookie(response, name, value, max_age):
    response.set_cookie(name, value, max_age=max_age, httponly=True, samesite="Lax",
                        secure=app.config["SESSION_COOKIE_SECURE"] or request.is_secure)


@app.before_request
def require_session():
    if request.endpoint in ("static", "login", "login_submit") or request.endpoint is None:
        return None
    g.auth = load_session(db, request.cookies.get(SESSION_COOKIE))
    if not g.auth:
        if request.path.startswith("/api/"):
            return jsonify({"erro": "Sua sessão expirou. Entre novamente."}), 401
        return redirect(url_for("login", next=request.path))
    if request.method not in ("GET", "HEAD", "OPTIONS") and not valid_csrf(
        g.auth["csrfToken"], request.headers.get("X-CSRF-Token")
    ):
        return jsonify({"erro": "Solicitação inválida. Atualize a página e tente novamente."}), 403


@app.after_request
def private_responses(response):
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


# ---------- Páginas ----------
# Usei os nomes com .html para os links do menu continuarem funcionando

@app.route("/")
@app.route("/login.html")
def login():
    if load_session(db, request.cookies.get(SESSION_COOKIE)):
        return redirect(url_for("dashboard"))
    csrf_token = secrets.token_urlsafe(32)
    response = make_response(render_template(
        "login.html", login_csrf=csrf_token, next_page=request.args.get("next", "/dashboard.html"),
        turnstile_site_key=app.config["TURNSTILE_SITE_KEY"] if app.config["TURNSTILE_SECRET_KEY"] else "",
    ))
    set_private_cookie(response, LOGIN_CSRF_COOKIE, csrf_token, 15 * 60)
    return response


@app.route("/api/auth/login", methods=["POST"])
def login_submit():
    data = request.get_json(silent=True) if request.is_json else request.form
    data = data or {}
    if not isinstance(data, dict) and not request.form:
        return jsonify({"erro": "Dados inválidos"}), 400
    if not valid_csrf(request.cookies.get(LOGIN_CSRF_COOKIE), data.get("csrf_token")):
        return jsonify({"erro": "Atualize a tela de login e tente novamente."}), 403
    email, password = data.get("email", ""), data.get("password", "")
    if not isinstance(email, str) or not isinstance(password, str) or not email.strip() or not password or len(email) > 254 or len(password) > 256:
        return jsonify({"erro": "Informe um e-mail e uma senha válidos."}), 400
    if app.config["TURNSTILE_SITE_KEY"] or app.config["TURNSTILE_SECRET_KEY"]:
        if not (app.config["TURNSTILE_SITE_KEY"] and app.config["TURNSTILE_SECRET_KEY"]):
            return jsonify({"erro": "A verificação de segurança precisa ser configurada pelo administrador."}), 503
        if not verify_turnstile(app.config["TURNSTILE_SECRET_KEY"], data.get("cf-turnstile-response"), request.remote_addr):
            return jsonify({"erro": "Conclua novamente a verificação de segurança."}), 400
    try:
        user = authenticate(db, email, password, request.remote_addr)
    except LoginThrottled as error:
        response = jsonify({"erro": "Muitas tentativas. Aguarde 15 minutos antes de tentar novamente."})
        response.headers["Retry-After"] = str(error.retry_after)
        return response, 429
    if user is None:
        return jsonify({"erro": "E-mail ou senha inválidos."}), 401
    revoke_session(db, request.cookies.get(SESSION_COOKIE))
    token = create_session(db, user)
    next_page = data.get("next", "/dashboard.html")
    if next_page not in ("/dashboard.html", "/history.html", "/new_reserve.html"):
        next_page = "/dashboard.html"
    response = jsonify({"redirect": next_page})
    set_private_cookie(response, SESSION_COOKIE, token, SESSION_SECONDS)
    response.delete_cookie(LOGIN_CSRF_COOKIE)
    return response


@app.route("/api/auth/me")
def current_user():
    return jsonify({"user": g.auth["user"], "csrfToken": g.auth["csrfToken"]})


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    revoke_session(db, request.cookies.get(SESSION_COOKIE))
    response = jsonify({"redirect": "/"})
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.route("/api/pesquisa")
def search_route():
    return jsonify({"results": search_reserves(db, request.args.get("q", "")[:120])})


@app.route("/api/notificacoes")
def notifications_route():
    return jsonify(list_notifications(db, g.auth["user"]["id"]))


@app.route("/api/notificacoes/lidas", methods=["POST"])
def read_notifications_route():
    data = request.get_json(silent=True)
    try:
        mark_notifications_read(db, g.auth["user"]["id"], data.get("ids") if isinstance(data, dict) else None)
    except ValueError as error:
        return jsonify({"erro": str(error)}), 400
    return jsonify({"status": "ok"})


@app.route("/dashboard.html")
def dashboard():
    return render_template("dashboard.html")

@app.route("/history.html")
def history():
    return render_template("history.html")

@app.route("/new_reserve.html")
def new_reserve():
    return render_template("new_reserve.html")


# ---------- API: reservas no Firestore ----------

@app.route("/api/reservas", methods=["POST"])
def create_reserve():
    data = request.get_json()

    # Chaves iguais às enviadas pelo new_reserve.js
    if not data or not data.get("name") or not data.get("codeReserve"):
        return jsonify({"erro": "Dados incompletos"}), 400

    if not data.get("stretches"):
        return jsonify({"erro": "Informe ao menos um trecho"}), 400

    save_reserve(db, data)
    return jsonify({"status": "ok", "id": data["codeReserve"]}), 201


@app.route("/api/reservas", methods=["GET"])
def list_reserves():
    reserves = []

    for doc in db.collection("reservas").stream():
        reserve = doc.to_dict()
        reserve["id"] = doc.id
        reserves.append(reserve)

    return jsonify(attach_jobs(reserves))


@app.route("/api/reservas/<reserve_id>/historico", methods=["GET"])
def reserve_history(reserve_id):
    try:
        limit = int(request.args.get("limit", 25))
        if not 1 <= limit <= 100:
            raise ValueError("O limite deve estar entre 1 e 100")
        result = get_history(db, reserve_id, limit, request.args.get("cursor"))
    except LookupError:
        return jsonify({"erro": "Reserva não encontrada"}), 404
    except ValueError as error:
        return jsonify({"erro": str(error)}), 400
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


# ---------- API: comparador e ações manuais ----------

@app.route("/api/reservas/<reserve_id>/comparar", methods=["POST"])
def compare_reserve_route(reserve_id):
    try:
        reserve = request_check(reserve_id)
    except LookupError:
        return jsonify({"erro": "Reserva não encontrada"}), 404

    return jsonify(reserve), 202


@app.route("/api/reservas/<reserve_id>/status", methods=["PATCH"])
def update_reserve_status(reserve_id):
    data = request.get_json() or {}

    try:
        reserve = set_manual_status(reserve_id, data.get("status"))
    except LookupError:
        return jsonify({"erro": "Reserva não encontrada"}), 404
    except ValueError as error:
        return jsonify({"erro": str(error)}), 400

    return jsonify(reserve)


