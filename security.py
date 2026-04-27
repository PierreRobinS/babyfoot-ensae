import secrets
from datetime import timedelta
from functools import wraps

from flask import flash, redirect, request, session, url_for
from flask_login import current_user

from extensions import db
from models import AdminLog, utcnow


ADMIN_LOGIN_ATTEMPTS = {}
CSRF_EXEMPT_ENDPOINTS = set()


def csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def validate_csrf():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return True
    if request.endpoint in CSRF_EXEMPT_ENDPOINTS:
        return True
    expected = session.get("_csrf_token")
    provided = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
    return bool(expected and provided and secrets.compare_digest(expected, provided))


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Accès refusé: zone admin réservée.", "error")
            return redirect(url_for("main.home"))
        return view(*args, **kwargs)

    return wrapped


def log_admin_action(action, target_type=None, target_id=None, details=None):
    admin_id = current_user.id if current_user.is_authenticated else None
    log = AdminLog(
        admin_id=admin_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
        ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
    )
    db.session.add(log)


def admin_login_blocked(email):
    key = email.lower()
    item = ADMIN_LOGIN_ATTEMPTS.get(key)
    return bool(item and item["locked_until"] > utcnow())


def register_admin_login_failure(email):
    key = email.lower()
    item = ADMIN_LOGIN_ATTEMPTS.setdefault(key, {"count": 0, "locked_until": utcnow()})
    item["count"] += 1
    if item["count"] >= 5:
        item["locked_until"] = utcnow() + timedelta(minutes=15)


def clear_admin_login_failures(email):
    ADMIN_LOGIN_ATTEMPTS.pop(email.lower(), None)
