import uuid
from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from werkzeug.utils import secure_filename

from config import Config
from extensions import db
from models import AdminLog, BanPair, Dispute, Match, MatchParticipant, SiteSetting, Tournament, User, utcnow
from security import admin_required, log_admin_action
from seed import seed_demo_data
from services import complete_match, match_group_key, parse_score
from routes.profiles import _is_image_upload
from admin_bootstrap import apply_runtime_settings


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def setting_value(key, default=""):
    setting = SiteSetting.query.filter_by(key=key).first()
    return setting.value if setting else default


def set_setting(key, value):
    setting = SiteSetting.query.filter_by(key=key).first()
    if not setting:
        setting = SiteSetting(key=key)
        db.session.add(setting)
    setting.value = value
    setting.updated_at = utcnow()


def admin_tabs():
    return [
        ("Dashboard", "admin.dashboard"),
        ("Joueurs", "admin.users"),
        ("Matchs", "admin.matches"),
        ("Litiges", "admin.disputes"),
        ("Classements", "admin.rankings"),
        ("Tournois", "admin.tournaments"),
        ("Logs", "admin.logs"),
        ("Paramètres", "admin.settings"),
    ]


@admin_bp.context_processor
def inject_admin_tabs():
    return {"admin_tabs": admin_tabs()}


def _match_bucket(status):
    if status in {"pending_invitation", "pending_validation", "active"}:
        return "pending"
    return status


def _recalculate_mode(mode):
    completed = (
        Match.query.filter_by(mode=mode, status="completed")
        .order_by(Match.completed_at.asc(), Match.id.asc())
        .all()
    )
    for user in User.query.all():
        if mode == "1v1":
            user.rating_1v1 = Config.GLICKO_DEFAULT_RATING
            user.rd_1v1 = Config.GLICKO_DEFAULT_RD
            user.volatility_1v1 = Config.GLICKO_DEFAULT_VOLATILITY
            user.matches_1v1 = user.wins_1v1 = user.losses_1v1 = 0
        else:
            user.rating_2v2 = Config.GLICKO_DEFAULT_RATING
            user.rd_2v2 = Config.GLICKO_DEFAULT_RD
            user.volatility_2v2 = Config.GLICKO_DEFAULT_VOLATILITY
            user.matches_2v2 = user.wins_2v2 = user.losses_2v2 = 0
    db.session.flush()
    for match in completed:
        complete_match(match)


def _delete_match(match):
    MatchParticipant.query.filter_by(match_id=match.id).delete()
    db.session.delete(match)


@admin_bp.route("")
@login_required
@admin_required
def dashboard():
    now = utcnow()
    week_ago = now - timedelta(days=7)
    today_start = datetime(now.year, now.month, now.day)
    users = User.query.all()
    matches = Match.query.all()
    disputes_open = Match.query.filter(Match.status == "disputed").count()

    matches_by_day = []
    signups_by_day = []
    for offset in range(6, -1, -1):
        day = today_start - timedelta(days=offset)
        next_day = day + timedelta(days=1)
        matches_by_day.append(
            {
                "label": day.strftime("%d/%m"),
                "count": Match.query.filter(Match.created_at >= day, Match.created_at < next_day).count(),
            }
        )
        signups_by_day.append(
            {
                "label": day.strftime("%d/%m"),
                "count": User.query.filter(User.created_at >= day, User.created_at < next_day).count(),
            }
        )

    top_progress = (
        db.session.query(User, func.sum(MatchParticipant.elo_after - MatchParticipant.elo_before).label("delta"))
        .join(MatchParticipant, MatchParticipant.user_id == User.id)
        .join(Match, Match.id == MatchParticipant.match_id)
        .filter(Match.completed_at >= week_ago, MatchParticipant.elo_after.isnot(None))
        .group_by(User.id)
        .order_by(func.sum(MatchParticipant.elo_after - MatchParticipant.elo_before).desc())
        .limit(5)
        .all()
    )

    stats = {
        "players": len(users),
        "active_7d": User.query.filter(User.last_login_at >= week_ago).count(),
        "matches_today": Match.query.filter(Match.created_at >= today_start).count(),
        "matches_total": len(matches),
        "cancelled": Match.query.filter_by(status="cancelled").count(),
        "disputes_open": disputes_open,
        "active_bans": User.query.filter(User.is_banned.is_(True)).count() + BanPair.query.filter(BanPair.banned_until > now).count(),
    }

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        matches_by_day=matches_by_day,
        signups_by_day=signups_by_day,
        top_progress=top_progress,
        top_1v1=User.query.order_by(User.rating_1v1.desc()).limit(5).all(),
        top_2v2=User.query.order_by(User.rating_2v2.desc()).limit(5).all(),
    )


@admin_bp.route("/users")
@login_required
@admin_required
def users():
    q = request.args.get("q", "").strip()
    query = User.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(User.pseudo.ilike(like), User.email.ilike(like), User.first_name.ilike(like), User.last_name.ilike(like)))
    return render_template("admin/users.html", users=query.order_by(User.created_at.desc()).all(), q=q)


@admin_bp.route("/users/<int:user_id>/action", methods=["POST"])
@login_required
@admin_required
def user_action(user_id):
    user = User.query.get_or_404(user_id)
    action = request.form.get("action")

    if user.is_admin and user.id != current_user.id and action in {"delete", "ban_temp", "ban_perm"}:
        flash("Impossible de cibler un autre admin.", "error")
        return redirect(url_for("admin.users"))

    if action == "update":
        user.pseudo = request.form.get("pseudo", user.pseudo).strip() or user.pseudo
        user.rating_1v1 = float(request.form.get("rating_1v1", user.rating_1v1))
        user.rating_2v2 = float(request.form.get("rating_2v2", user.rating_2v2))
        log_admin_action("user_update", "user", user.id, f"Pseudo/Elo modifiés pour {user.email}")
    elif action == "reset_password":
        password = request.form.get("password", "").strip()
        if len(password) < 8:
            flash("Mot de passe de 8 caractères minimum.", "error")
            return redirect(url_for("admin.users"))
        user.set_password(password)
        log_admin_action("password_reset", "user", user.id, "Reset mot de passe")
    elif action == "reset_glicko":
        user.rd_1v1 = user.rd_2v2 = Config.GLICKO_DEFAULT_RD
        user.volatility_1v1 = user.volatility_2v2 = Config.GLICKO_DEFAULT_VOLATILITY
        log_admin_action("glicko_reset", "user", user.id, "RD/volatility reset")
    elif action == "upload_photo":
        photo = request.files.get("photo")
        if not photo or not photo.filename or not _is_image_upload(photo):
            flash("Image invalide.", "error")
            return redirect(url_for("admin.users"))
        extension = secure_filename(photo.filename).rsplit(".", 1)[-1].lower()
        filename = f"{uuid.uuid4().hex}.{extension}"
        Path(Config.UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)
        photo.save(Path(Config.UPLOAD_FOLDER) / filename)
        user.profile_image = filename
        log_admin_action("user_photo_upload", "user", user.id, filename)
    elif action == "ban_temp":
        hours = max(1, int(request.form.get("hours", 24)))
        user.is_banned = True
        user.banned_until = utcnow() + timedelta(hours=hours)
        user.ban_reason = request.form.get("reason") or "Ban temporaire admin"
        log_admin_action("user_ban_temp", "user", user.id, user.ban_reason)
    elif action == "ban_perm":
        user.is_banned = True
        user.banned_until = None
        user.ban_reason = request.form.get("reason") or "Ban définitif admin"
        log_admin_action("user_ban_perm", "user", user.id, user.ban_reason)
    elif action == "unban":
        user.is_banned = False
        user.banned_until = None
        user.ban_reason = None
        log_admin_action("user_unban", "user", user.id, "Déban")
    elif action == "badge":
        user.badge = request.form.get("badge") or "Champion"
        log_admin_action("badge_grant", "user", user.id, user.badge)
    elif action == "delete":
        if user.id == current_user.id:
            flash("Impossible de supprimer le compte admin courant.", "error")
            return redirect(url_for("admin.users"))
        for participant in MatchParticipant.query.filter_by(user_id=user.id).all():
            _delete_match(participant.match)
        log_admin_action("user_delete", "user", user.id, user.email)
        db.session.delete(user)
    elif action == "merge":
        target_id = int(request.form.get("target_id", 0))
        target = db.session.get(User, target_id)
        if not target or target.id == user.id:
            flash("Compte cible invalide.", "error")
            return redirect(url_for("admin.users"))
        for participant in MatchParticipant.query.filter_by(user_id=user.id).all():
            duplicate = MatchParticipant.query.filter_by(
                match_id=participant.match_id, user_id=target.id
            ).first()
            if duplicate:
                db.session.delete(participant)
            else:
                participant.user_id = target.id
        for match in Match.query.filter_by(host_id=user.id).all():
            match.host_id = target.id
        log_admin_action("user_merge", "user", user.id, f"Fusion vers {target.email}")
        db.session.delete(user)
    else:
        flash("Action inconnue.", "error")
        return redirect(url_for("admin.users"))

    db.session.commit()
    flash("Action joueur appliquée.", "success")
    return redirect(url_for("admin.users", q=request.args.get("q", "")))


@admin_bp.route("/matches")
@login_required
@admin_required
def matches():
    mode = request.args.get("mode", "")
    status = request.args.get("status", "")
    query = Match.query
    if mode in {"1v1", "2v2"}:
        query = query.filter_by(mode=mode)
    if status:
        if status == "pending":
            query = query.filter(Match.status.in_(["pending_invitation", "pending_validation", "active"]))
        else:
            query = query.filter_by(status=status)
    return render_template("admin/matches.html", matches=query.order_by(Match.created_at.desc()).all(), mode=mode, status=status)


@admin_bp.route("/matches/<int:match_id>/action", methods=["POST"])
@login_required
@admin_required
def match_action(match_id):
    match = Match.query.get_or_404(match_id)
    action = request.form.get("action")

    if action in {"score", "force_a", "force_b", "manual_validate"}:
        if action == "force_a":
            match.score_a, match.score_b = 10, 0
        elif action == "force_b":
            match.score_a, match.score_b = 0, 10
        elif action == "manual_validate" and (match.score_a is None or match.score_b is None):
            match.score_a, match.score_b = 10, 0
        elif action == "score":
            score_a, score_b, error = parse_score(request.form.get("score_a"), request.form.get("score_b"))
            if error:
                flash(error, "error")
                return redirect(url_for("admin.matches"))
            match.score_a, match.score_b = score_a, score_b
        match.status = "pending_validation"
        for participant in match.participants:
            participant.validation_status = "accepted"
        complete_match(match)
        log_admin_action("match_validate_manual", "match", match.id, f"{match.score_a}-{match.score_b}")
    elif action == "cancel":
        match.status = "cancelled"
        match.cancelled_reason = request.form.get("reason") or "Annulé par admin"
        match.public_note = match.cancelled_reason
        log_admin_action("match_cancel", "match", match.id, match.cancelled_reason)
    elif action == "unlock":
        match.status = "active"
        match.cancelled_reason = None
        match.public_note = "Match débloqué par admin."
        log_admin_action("match_unlock", "match", match.id, "Déblocage")
    elif action == "delete":
        log_admin_action("match_delete", "match", match.id, "Suppression")
        _delete_match(match)
    elif action == "recalculate":
        _recalculate_mode(match.mode)
        log_admin_action("match_recalculate", "match", match.id, f"Recalcul {match.mode}")
    else:
        flash("Action inconnue.", "error")
        return redirect(url_for("admin.matches"))

    db.session.commit()
    flash("Action match appliquée.", "success")
    return redirect(url_for("admin.matches"))


@admin_bp.route("/disputes")
@login_required
@admin_required
def disputes():
    disputed_matches = Match.query.filter(Match.status.in_(["disputed", "pending_validation"])).order_by(Match.created_at.desc()).all()
    disputes_log = Dispute.query.order_by(Dispute.created_at.desc()).limit(80).all()
    return render_template("admin/disputes.html", matches=disputed_matches, disputes=disputes_log)


@admin_bp.route("/disputes/<int:match_id>/action", methods=["POST"])
@login_required
@admin_required
def dispute_action(match_id):
    match = Match.query.get_or_404(match_id)
    action = request.form.get("action")
    if action == "decide":
        score_a, score_b, error = parse_score(request.form.get("score_a"), request.form.get("score_b"))
        if error:
            flash(error, "error")
            return redirect(url_for("admin.disputes"))
        match.score_a, match.score_b = score_a, score_b
        for participant in match.participants:
            participant.validation_status = "accepted"
        complete_match(match)
        log_admin_action("dispute_decide", "match", match.id, f"{score_a}-{score_b}")
    elif action == "cancel":
        match.status = "cancelled"
        match.cancelled_reason = "Litige annulé par admin"
        match.public_note = match.cancelled_reason
        log_admin_action("dispute_cancel", "match", match.id, "Annulation litige")
    elif action == "warn":
        match.public_note = request.form.get("message") or "Avertissement admin envoyé aux joueurs."
        log_admin_action("dispute_warn", "match", match.id, match.public_note)
    elif action == "blacklist":
        hours = max(1, int(request.form.get("hours", 24)))
        key = match_group_key(match)
        ban = BanPair.query.filter_by(mode=match.mode, group_key=key).first()
        if not ban:
            ban = BanPair(mode=match.mode, group_key=key, count=0)
            db.session.add(ban)
        ban.count += 1
        ban.banned_until = utcnow() + timedelta(hours=hours)
        log_admin_action("pair_blacklist", "match", match.id, f"{key} {hours}h")
    else:
        flash("Action inconnue.", "error")
        return redirect(url_for("admin.disputes"))
    db.session.commit()
    flash("Litige traité.", "success")
    return redirect(url_for("admin.disputes"))


@admin_bp.route("/rankings", methods=["GET", "POST"])
@login_required
@admin_required
def rankings():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "recalc_1v1":
            _recalculate_mode("1v1")
        elif action == "recalc_2v2":
            _recalculate_mode("2v2")
        elif action == "reset_season":
            for user in User.query.all():
                user.rating_1v1 = user.rating_2v2 = Config.GLICKO_DEFAULT_RATING
                user.rd_1v1 = user.rd_2v2 = Config.GLICKO_DEFAULT_RD
                user.volatility_1v1 = user.volatility_2v2 = Config.GLICKO_DEFAULT_VOLATILITY
                user.matches_1v1 = user.matches_2v2 = 0
                user.wins_1v1 = user.wins_2v2 = user.losses_1v1 = user.losses_2v2 = 0
        elif action == "archive_season":
            log_admin_action("season_archive", "ranking", None, "Saison archivée")
        elif action == "new_season":
            set_setting("season_started_at", utcnow().isoformat())
        elif action == "freeze":
            set_setting("rankings_frozen", "true")
        elif action == "unfreeze":
            set_setting("rankings_frozen", "false")
        else:
            flash("Action inconnue.", "error")
            return redirect(url_for("admin.rankings"))
        log_admin_action("ranking_action", "ranking", None, action)
        db.session.commit()
        flash("Action classement appliquée.", "success")
        return redirect(url_for("admin.rankings"))

    return render_template(
        "admin/rankings.html",
        frozen=setting_value("rankings_frozen", "false") == "true",
        ranking_1v1=User.query.order_by(User.rating_1v1.desc()).limit(20).all(),
        ranking_2v2=User.query.order_by(User.rating_2v2.desc()).limit(20).all(),
    )


@admin_bp.route("/tournaments", methods=["GET", "POST"])
@login_required
@admin_required
def tournaments():
    if request.method == "POST":
        tournament = Tournament(
            name=request.form.get("name", "").strip() or "Event babyfoot",
            kind=request.form.get("kind", "tournoi_1v1"),
            status="published" if request.form.get("publish") else "draft",
            banner_message=request.form.get("banner_message"),
            created_by_id=current_user.id,
        )
        db.session.add(tournament)
        if tournament.banner_message:
            set_setting("global_banner", tournament.banner_message)
        log_admin_action("tournament_create", "tournament", None, tournament.name)
        db.session.commit()
        flash("Event créé.", "success")
        return redirect(url_for("admin.tournaments"))
    return render_template("admin/tournaments.html", tournaments=Tournament.query.order_by(Tournament.created_at.desc()).all())


@admin_bp.route("/logs")
@login_required
@admin_required
def logs():
    action = request.args.get("action", "")
    query = AdminLog.query
    if action:
        query = query.filter(AdminLog.action.ilike(f"%{action}%"))
    return render_template("admin/logs.html", logs=query.order_by(AdminLog.created_at.desc()).limit(250).all(), action=action)


@admin_bp.route("/settings", methods=["GET", "POST"])
@login_required
@admin_required
def settings():
    if request.method == "POST":
        for key in [
            "glicko_tau",
            "glicko_default_rd",
            "glicko_default_volatility",
            "invitation_timeout_1v1",
            "invitation_timeout_2v2",
            "auto_ban_hours",
            "registrations_enabled",
            "maintenance_enabled",
            "maintenance_message",
            "theme_color",
            "global_banner",
        ]:
            set_setting(key, request.form.get(key, ""))
        log_admin_action("settings_update", "settings", None, "Paramètres globaux")
        db.session.commit()
        apply_runtime_settings()
        flash("Paramètres enregistrés.", "success")
        return redirect(url_for("admin.settings"))
    settings_map = {item.key: item.value for item in SiteSetting.query.order_by(SiteSetting.key.asc()).all()}
    return render_template("admin/settings.html", settings=settings_map)


@admin_bp.route("/god", methods=["GET", "POST"])
@login_required
@admin_required
def god():
    if request.method == "POST":
        if request.form.get("confirm") != "GODMODE":
            flash("Double confirmation requise: tape GODMODE.", "error")
            return redirect(url_for("admin.god"))
        action = request.form.get("action")
        if action == "reset_all_elo":
            for user in User.query.all():
                user.rating_1v1 = user.rating_2v2 = Config.GLICKO_DEFAULT_RATING
                user.rd_1v1 = user.rd_2v2 = Config.GLICKO_DEFAULT_RD
                user.volatility_1v1 = user.volatility_2v2 = Config.GLICKO_DEFAULT_VOLATILITY
        elif action == "champion_badge":
            user = db.session.get(User, int(request.form.get("user_id", 0)))
            if user:
                user.badge = "Champion"
        elif action == "global_notif":
            set_setting("global_banner", request.form.get("message") or "Annonce admin")
        elif action == "ban_inactive":
            cutoff = utcnow() - timedelta(days=180)
            User.query.filter(User.is_admin.is_(False), or_(User.last_login_at.is_(None), User.last_login_at < cutoff)).update({"is_banned": True, "ban_reason": "Compte inactif"})
        elif action == "inject_demo":
            seed_demo_data()
        elif action == "delete_test_matches":
            for match in Match.query.filter(Match.public_note.ilike("%demo%")).all():
                _delete_match(match)
        elif action == "maintenance_on":
            set_setting("maintenance_enabled", "true")
        elif action == "maintenance_off":
            set_setting("maintenance_enabled", "false")
        else:
            flash("Action inconnue.", "error")
            return redirect(url_for("admin.god"))
        log_admin_action("god_power", "system", None, action)
        db.session.commit()
        flash("God power exécuté.", "success")
        return redirect(url_for("admin.god"))
    return render_template("admin/god.html", users=User.query.order_by(User.pseudo.asc()).all())
