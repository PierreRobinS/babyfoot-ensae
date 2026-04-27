from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func

from extensions import db
from models import SiteSetting, User, utcnow
from security import (
    admin_login_blocked,
    clear_admin_login_failures,
    log_admin_action,
    register_admin_login_failure,
)
from services import parse_names_from_email, valid_ensae_email


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pseudo = request.form.get("pseudo", "").strip()
        password = request.form.get("password", "")
        registrations = SiteSetting.query.filter_by(key="registrations_enabled").first()

        if registrations and registrations.value == "false":
            flash("Les inscriptions sont temporairement désactivées.", "error")
        elif not valid_ensae_email(email):
            flash("Adresse ENSAE obligatoire.", "error")
        elif len(pseudo) < 3 or len(pseudo) > 40:
            flash("Pseudo entre 3 et 40 caractères.", "error")
        elif len(password) < 8:
            flash("Mot de passe de 8 caractères minimum.", "error")
        elif User.query.filter_by(email=email).first():
            flash("Cette adresse existe déjà.", "error")
        elif User.query.filter(func.lower(User.pseudo) == pseudo.lower()).first():
            flash("Ce pseudo est déjà pris.", "error")
        else:
            first_name, last_name = parse_names_from_email(email)
            user = User(email=email, pseudo=pseudo, first_name=first_name, last_name=last_name)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Bienvenue sur le classement babyfoot ENSAE.", "success")
            return redirect(url_for("main.home"))

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.is_admin and admin_login_blocked(email):
            flash("Trop de tentatives admin. Réessayez dans quelques minutes.", "error")
        elif not user or not user.check_password(password):
            if user and user.is_admin:
                register_admin_login_failure(email)
            flash("Identifiants incorrects.", "error")
        elif user.is_banned and (not user.banned_until or user.banned_until > utcnow()):
            flash(user.ban_reason or "Compte banni.", "error")
        else:
            user.last_login_at = utcnow()
            if user.is_admin:
                clear_admin_login_failures(email)
                log_admin_action("admin_login", "user", user.id, "Connexion admin")
            login_user(user, remember=True)
            db.session.commit()
            flash("Connexion réussie.", "success")
            if user.is_admin:
                return redirect(url_for("admin.dashboard"))
            return redirect(url_for("main.home"))

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Session terminée.", "success")
    return redirect(url_for("auth.login"))
