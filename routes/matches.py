from datetime import timedelta

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import Match, MatchParticipant, User, utcnow
from services import (
    active_ban,
    complete_match,
    expire_matches,
    has_open_match_between,
    invitation_timeout,
    max_score_proposals,
    parse_score,
    prediction_1v1,
    prediction_2v2,
    register_disagreement,
    score_label,
    setup_group_key,
)


matches_bp = Blueprint("matches", __name__, url_prefix="/matches")


def _payload():
    return request.get_json(silent=True) or request.form


def _reply(ok, message, status=200, redirect_to=None):
    if request.is_json:
        return jsonify({"ok": ok, "message": message, "redirect": redirect_to}), status
    flash(message, "success" if ok else "error")
    return redirect(redirect_to or url_for("main.home"))


def _participant_or_403(match):
    participant = match.participant_for(current_user.id)
    if not participant:
        abort(403)
    return participant


@matches_bp.route("/create_1v1", methods=["POST"])
@login_required
def create_1v1():
    data = _payload()
    try:
        opponent_id = int(data.get("opponent_id", 0))
    except ValueError:
        return _reply(False, "Adversaire invalide.", 400)

    opponent = db.session.get(User, opponent_id)
    if not opponent or opponent.id == current_user.id:
        return _reply(False, "Adversaire invalide.", 400)

    group_key = setup_group_key("1v1", [current_user.id], [opponent.id])
    ban = active_ban("1v1", group_key)
    if ban:
        return _reply(
            False,
            f"Défi bloqué jusqu'au {ban.banned_until.strftime('%d/%m %H:%M')}.",
            403,
        )

    if has_open_match_between([current_user.id, opponent.id]):
        return _reply(False, "Un match est déjà ouvert avec ce joueur.", 400)

    match = Match(
        mode="1v1",
        host_id=current_user.id,
        status="pending_invitation",
        expires_at=utcnow() + invitation_timeout("1v1"),
    )
    db.session.add(match)
    db.session.flush()
    db.session.add_all(
        [
            MatchParticipant(
                match_id=match.id,
                user_id=current_user.id,
                team="A",
                role="host",
                invitation_status="accepted",
                validation_status="pending",
                responded_at=utcnow(),
            ),
            MatchParticipant(
                match_id=match.id,
                user_id=opponent.id,
                team="B",
                role="opponent",
                invitation_status="pending",
                validation_status="pending",
            ),
        ]
    )
    db.session.commit()
    return _reply(True, "Défi envoyé.", redirect_to=url_for("main.home"))


@matches_bp.route("/create_2v2", methods=["POST"])
@login_required
def create_2v2():
    data = _payload()
    try:
        partner_id = int(data.get("partner_id", 0))
        opponent1_id = int(data.get("opponent1_id", 0))
        opponent2_id = int(data.get("opponent2_id", 0))
    except ValueError:
        return _reply(False, "Sélection invalide.", 400)

    users = [db.session.get(User, user_id) for user_id in (partner_id, opponent1_id, opponent2_id)]
    if any(user is None for user in users):
        return _reply(False, "Joueur introuvable.", 400)

    partner, opponent_1, opponent_2 = users
    ids = {current_user.id, partner.id, opponent_1.id, opponent_2.id}
    if len(ids) != 4:
        return _reply(False, "Un joueur apparaît plusieurs fois.", 400)

    group_key = setup_group_key(
        "2v2", [current_user.id, partner.id], [opponent_1.id, opponent_2.id]
    )
    ban = active_ban("2v2", group_key)
    if ban:
        return _reply(
            False,
            f"2v2 bloqué jusqu'au {ban.banned_until.strftime('%d/%m %H:%M')}.",
            403,
        )

    if has_open_match_between(list(ids)):
        return _reply(False, "Un match est déjà ouvert avec ce groupe.", 400)

    match = Match(
        mode="2v2",
        host_id=current_user.id,
        status="pending_invitation",
        expires_at=utcnow() + invitation_timeout("2v2"),
    )
    db.session.add(match)
    db.session.flush()
    db.session.add_all(
        [
            MatchParticipant(
                match_id=match.id,
                user_id=current_user.id,
                team="A",
                role="host",
                invitation_status="accepted",
                validation_status="pending",
                responded_at=utcnow(),
            ),
            MatchParticipant(match_id=match.id, user_id=partner.id, team="A", role="partner"),
            MatchParticipant(match_id=match.id, user_id=opponent_1.id, team="B", role="opponent"),
            MatchParticipant(match_id=match.id, user_id=opponent_2.id, team="B", role="opponent"),
        ]
    )
    db.session.commit()
    return _reply(True, "Invitation 2v2 envoyée.", redirect_to=url_for("main.home"))


@matches_bp.route("/<int:match_id>")
@login_required
def match_detail(match_id):
    expire_matches()
    match = Match.query.get_or_404(match_id)
    participant = _participant_or_403(match)
    prediction = None
    if match.mode == "1v1":
        prediction = prediction_1v1(match.team("A")[0].user, match.team("B")[0].user)
    elif len(match.team("A")) == 2 and len(match.team("B")) == 2:
        prediction = prediction_2v2(
            [p.user for p in match.team("A")],
            [p.user for p in match.team("B")],
        )

    return render_template(
        "match.html",
        match=match,
        participant=participant,
        prediction=prediction,
        score_label=score_label(match),
        max_proposals=max_score_proposals(match.mode),
    )


@matches_bp.route("/<int:match_id>/invitation", methods=["POST"])
@login_required
def answer_invitation(match_id):
    expire_matches()
    match = Match.query.get_or_404(match_id)
    participant = _participant_or_403(match)
    data = _payload()
    action = data.get("action")

    if match.status != "pending_invitation" or participant.invitation_status != "pending":
        return _reply(False, "Invitation inactive.", 400, url_for("main.home"))

    participant.responded_at = utcnow()
    if action == "refuse":
        participant.invitation_status = "refused"
        match.status = "cancelled"
        match.refused_by_id = current_user.id
        match.cancelled_reason = "Invitation refusée"
        match.public_note = f"{match.mode} annulé: {current_user.pseudo} a refusé."
        db.session.commit()
        return _reply(True, "Invitation refusée.", redirect_to=url_for("main.home"))

    if action != "accept":
        return _reply(False, "Action invalide.", 400)

    participant.invitation_status = "accepted"
    if match.accepted_invitations():
        match.status = "active"
        match.started_at = utcnow()
        for item in match.participants:
            item.validation_status = "pending"
        db.session.commit()
        return _reply(
            True,
            "Match lancé.",
            redirect_to=url_for("matches.match_detail", match_id=match.id),
        )

    db.session.commit()
    return _reply(True, "Invitation acceptée.", redirect_to=url_for("main.home"))


@matches_bp.route("/<int:match_id>/score", methods=["POST"])
@login_required
def submit_score(match_id):
    match = Match.query.get_or_404(match_id)
    _participant_or_403(match)

    if match.status not in ("active", "disputed"):
        return _reply(False, "Score non modifiable pour ce match.", 400, url_for("matches.match_detail", match_id=match.id))

    if match.mode == "2v2" and match.host_id != current_user.id:
        return _reply(False, "Seul le host renseigne le score en 2v2.", 403, url_for("matches.match_detail", match_id=match.id))

    if match.status == "disputed" and match.proposal_round >= max_score_proposals(match.mode):
        return _reply(False, "Limite de corrections atteinte.", 400, url_for("matches.match_detail", match_id=match.id))

    data = _payload()
    score_a, score_b, error = parse_score(data.get("score_a"), data.get("score_b"))
    if error:
        return _reply(False, error, 400, url_for("matches.match_detail", match_id=match.id))

    match.score_a = score_a
    match.score_b = score_b
    match.proposal_round += 1
    match.proposed_by_id = current_user.id
    match.status = "pending_validation"
    match.public_note = None
    for participant in match.participants:
        participant.validation_status = (
            "accepted" if participant.user_id == current_user.id else "pending"
        )

    db.session.commit()
    return _reply(True, "Score proposé.", redirect_to=url_for("matches.match_detail", match_id=match.id))


@matches_bp.route("/<int:match_id>/validate", methods=["POST"])
@login_required
def validate_score(match_id):
    match = Match.query.get_or_404(match_id)
    participant = _participant_or_403(match)
    data = _payload()
    action = data.get("action")

    if match.status != "pending_validation":
        return _reply(False, "Aucun score en attente.", 400, url_for("matches.match_detail", match_id=match.id))

    if participant.validation_status != "pending":
        return _reply(False, "Validation déjà enregistrée.", 400, url_for("matches.match_detail", match_id=match.id))

    if action == "accept":
        participant.validation_status = "accepted"
        if match.accepted_validations():
            complete_match(match)
            db.session.commit()
            return _reply(True, "Match validé, Elo mis à jour.", redirect_to=url_for("matches.match_detail", match_id=match.id))
        db.session.commit()
        return _reply(True, "Score confirmé.", redirect_to=url_for("matches.match_detail", match_id=match.id))

    if action != "refuse":
        return _reply(False, "Action invalide.", 400)

    participant.validation_status = "refused"
    warning = register_disagreement(match, current_user)
    if match.proposal_round >= max_score_proposals(match.mode):
        match.status = "cancelled"
        match.cancelled_reason = "Désaccord sur le score"
        match.public_note = f"{match.mode} annulé après désaccord sur le score."
    else:
        match.status = "disputed"
        match.public_note = f"Correction demandée par {current_user.pseudo} sur un {match.mode}."

    db.session.commit()
    return _reply(True, warning, redirect_to=url_for("matches.match_detail", match_id=match.id))
