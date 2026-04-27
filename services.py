import math
from datetime import timedelta

from flask import url_for
from sqlalchemy import and_, or_

from config import Config
from extensions import db
from models import BanPair, Dispute, Match, MatchParticipant, User, utcnow
from rating_system import (
    RatingState,
    predict_point_probability,
    predict_score_distribution,
    update_glicko_1v1,
    update_glicko_2v2,
)


OPEN_STATUSES = ("pending_invitation", "active", "pending_validation", "disputed")
PLAY_STATUSES = ("active", "pending_validation", "disputed")


def parse_names_from_email(email):
    local = email.split("@", 1)[0]
    parts = [part for part in local.replace("-", ".").replace("_", ".").split(".") if part]
    first_name = parts[0] if parts else "Joueur"
    last_name = parts[-1] if len(parts) > 1 else "ENSAE"
    return first_name.title(), last_name.title()


def valid_ensae_email(email):
    return email and email.lower().endswith("@ensae.fr")


def invitation_timeout(mode):
    seconds = (
        Config.INVITATION_TIMEOUT_1V1_SECONDS
        if mode == "1v1"
        else Config.INVITATION_TIMEOUT_2V2_SECONDS
    )
    return timedelta(seconds=seconds)


def max_score_proposals(mode):
    return 2 if mode == "1v1" else 3


def expire_matches():
    now = utcnow()
    expired = Match.query.filter(
        Match.status == "pending_invitation",
        Match.expires_at.isnot(None),
        Match.expires_at < now,
    ).all()

    if not expired:
        return

    for match in expired:
        pending = [p for p in match.participants if p.invitation_status == "pending"]
        if not pending:
            continue

        for participant in pending:
            participant.invitation_status = "expired"

        match.status = "cancelled"
        match.cancelled_reason = "Invitation expirée"
        match.non_response_user_id = pending[0].user_id
        names = ", ".join(p.user.pseudo for p in pending)
        if match.mode == "2v2":
            match.public_note = f"2v2 annulé: {names} n'a pas répondu."
        else:
            match.public_note = f"Défi 1v1 annulé: {names} n'a pas répondu."

    db.session.commit()


def team_key(user_ids):
    return "-".join(str(user_id) for user_id in sorted(user_ids))


def setup_group_key(mode, team_a_ids, team_b_ids):
    if mode == "1v1":
        return team_key([team_a_ids[0], team_b_ids[0]])
    teams = sorted([team_key(team_a_ids), team_key(team_b_ids)])
    return "__vs__".join(teams)


def match_group_key(match):
    team_a_ids = [p.user_id for p in match.team("A")]
    team_b_ids = [p.user_id for p in match.team("B")]
    return setup_group_key(match.mode, team_a_ids, team_b_ids)


def active_ban(mode, group_key):
    ban = BanPair.query.filter_by(mode=mode, group_key=group_key).first()
    if ban and ban.is_active():
        return ban
    return None


def register_disagreement(match, triggered_by):
    group_key = match_group_key(match)
    ban = BanPair.query.filter_by(mode=match.mode, group_key=group_key).first()
    if not ban:
        ban = BanPair(mode=match.mode, group_key=group_key)
        db.session.add(ban)

    ban.count += 1
    ban.last_match_id = match.id
    ban.updated_at = utcnow()

    banned_until = None
    if ban.count >= 2:
        hours_by_count = {2: 1, 3: 6, 4: 24, 5: 72}
        hours = hours_by_count.get(ban.count, 168)
        banned_until = utcnow() + timedelta(hours=hours)
        ban.banned_until = banned_until

    dispute = Dispute(
        match_id=match.id,
        mode=match.mode,
        group_key=group_key,
        triggered_by_id=triggered_by.id,
        count_after=ban.count,
        banned_until=banned_until,
    )
    db.session.add(dispute)

    if ban.count == 1:
        return "Premier joker utilisé: le prochain désaccord déclenchera un ban temporaire."
    until = banned_until.strftime("%d/%m %H:%M") if banned_until else ""
    return f"Désaccord enregistré: ban temporaire actif jusqu'au {until}."


def _rating_state(user, mode):
    rating, rd, volatility = user.rating_state(mode)
    return RatingState(rating=rating, rd=rd, volatility=volatility)


def _set_rating_state(user, mode, state):
    if mode == "1v1":
        user.rating_1v1 = state.rating
        user.rd_1v1 = state.rd
        user.volatility_1v1 = state.volatility
    else:
        user.rating_2v2 = state.rating
        user.rd_2v2 = state.rd
        user.volatility_2v2 = state.volatility


def _rating_value(user, mode):
    return user.rating_1v1 if mode == "1v1" else user.rating_2v2


def complete_match(match):
    if match.score_a is None or match.score_b is None:
        raise ValueError("Score manquant")

    team_a = match.team("A")
    team_b = match.team("B")
    for participant in match.participants:
        participant.elo_before = _rating_value(participant.user, match.mode)

    if match.mode == "1v1":
        player_a = team_a[0].user
        player_b = team_b[0].user
        result = update_glicko_1v1(
            _rating_state(player_a, "1v1"),
            _rating_state(player_b, "1v1"),
            match.score_a,
            match.score_b,
        )
        _set_rating_state(player_a, "1v1", result["player_a"])
        _set_rating_state(player_b, "1v1", result["player_b"])
        _apply_stats(player_a, "1v1", match.score_a > match.score_b)
        _apply_stats(player_b, "1v1", match.score_b > match.score_a)
    else:
        result = update_glicko_2v2(
            [_rating_state(p.user, "2v2") for p in team_a],
            [_rating_state(p.user, "2v2") for p in team_b],
            match.score_a,
            match.score_b,
        )
        for participant, state in zip(team_a, result["team_a"]):
            _set_rating_state(participant.user, "2v2", state)
            _apply_stats(participant.user, "2v2", match.score_a > match.score_b)
        for participant, state in zip(team_b, result["team_b"]):
            _set_rating_state(participant.user, "2v2", state)
            _apply_stats(participant.user, "2v2", match.score_b > match.score_a)

    now = utcnow()
    for participant in match.participants:
        participant.elo_after = _rating_value(participant.user, match.mode)
        participant.user.last_activity = now
        participant.validation_status = "accepted"

    match.status = "completed"
    match.completed_at = now
    match.public_note = (
        f"{match.mode} validé: {match.team_label('A')} "
        f"{match.score_a}-{match.score_b} {match.team_label('B')}."
    )


def _apply_stats(user, mode, won):
    if mode == "1v1":
        user.matches_1v1 += 1
        user.wins_1v1 += int(won)
        user.losses_1v1 += int(not won)
    else:
        user.matches_2v2 += 1
        user.wins_2v2 += int(won)
        user.losses_2v2 += int(not won)


def parse_score(score_a, score_b):
    try:
        a = int(score_a)
        b = int(score_b)
    except (TypeError, ValueError):
        return None, None, "Scores invalides."

    if a < 0 or b < 0:
        return None, None, "Les scores doivent être positifs."
    if not ((a == 10 and 0 <= b < 10) or (b == 10 and 0 <= a < 10)):
        return None, None, "Score babyfoot obligatoire: 10-k ou k-10."
    return a, b, None


def _team_prediction_values(users):
    rating = sum(user.rating_2v2 for user in users) / len(users)
    rd = math.sqrt(sum(user.rd_2v2 * user.rd_2v2 for user in users)) / len(users)
    return rating, rd


def prediction_1v1(player_a, player_b):
    probability = predict_point_probability(player_a.rating_1v1, player_b.rating_1v1, player_b.rd_1v1)
    distribution = predict_score_distribution(probability)
    favorite = player_a if probability >= 0.5 else player_b
    favorite_probability = probability if probability >= 0.5 else 1.0 - probability
    return {
        "probability": probability,
        "favorite": favorite.pseudo,
        "text": f"{favorite.pseudo} est favori à {round(favorite_probability * 100)} % par point.",
        "score": f"{distribution['score_a']}-{distribution['score_b']}",
    }


def prediction_2v2(team_a_users, team_b_users):
    rating_a, rd_a = _team_prediction_values(team_a_users)
    rating_b, rd_b = _team_prediction_values(team_b_users)
    probability = predict_point_probability(rating_a, rating_b, rd_b)
    distribution = predict_score_distribution(probability)
    label_a = " + ".join(user.pseudo for user in team_a_users)
    label_b = " + ".join(user.pseudo for user in team_b_users)
    favorite = label_a if probability >= 0.5 else label_b
    favorite_probability = probability if probability >= 0.5 else 1.0 - probability
    return {
        "probability": probability,
        "favorite": favorite,
        "text": f"{favorite} est favori à {round(favorite_probability * 100)} % par point.",
        "score": f"{distribution['score_a']}-{distribution['score_b']}",
        "team_a_probability": probability,
        "team_a_rd": rd_a,
    }


def user_search(query, current_user_id, limit=8):
    q = (query or "").strip().lower()
    if len(q) < 1:
        return []

    like = f"%{q}%"
    users = (
        User.query.filter(User.id != current_user_id)
        .filter(
            or_(
                User.pseudo.ilike(like),
                User.email.ilike(like),
                User.first_name.ilike(like),
                User.last_name.ilike(like),
            )
        )
        .order_by(User.pseudo.asc())
        .limit(limit)
        .all()
    )
    return [serialize_user(user) for user in users]


def serialize_user(user):
    return {
        "id": user.id,
        "pseudo": user.pseudo,
        "email": user.email,
        "name": user.full_name,
        "avatar": user.avatar_url,
        "rating_1v1": round(user.rating_1v1),
        "rating_2v2": round(user.rating_2v2),
    }


def pending_invitations_for(user):
    return (
        Match.query.join(MatchParticipant)
        .filter(
            Match.status == "pending_invitation",
            MatchParticipant.user_id == user.id,
            MatchParticipant.invitation_status == "pending",
        )
        .order_by(Match.created_at.desc())
        .all()
    )


def active_matches_for(user):
    return (
        Match.query.join(MatchParticipant)
        .filter(
            Match.status.in_(PLAY_STATUSES),
            MatchParticipant.user_id == user.id,
        )
        .order_by(Match.started_at.desc().nullslast(), Match.created_at.desc())
        .all()
    )


def public_events(limit=8):
    return (
        Match.query.filter(Match.public_note.isnot(None))
        .order_by(Match.created_at.desc())
        .limit(limit)
        .all()
    )


def dashboard_payload(user):
    return {
        "pending_invitations": [serialize_invitation(match, user) for match in pending_invitations_for(user)],
        "active_matches": [serialize_match_card(match, user) for match in active_matches_for(user)],
        "events": [serialize_event(match) for match in public_events()],
    }


def serialize_invitation(match, user):
    remaining = 0
    if match.expires_at:
        remaining = max(0, int((match.expires_at - utcnow()).total_seconds()))

    if match.mode == "1v1":
        title = f"{match.host.pseudo} vous défie en 1v1"
        subtitle = f"{match.team_label('A')} contre {match.team_label('B')}"
    else:
        title = f"{match.host.pseudo} propose un 2v2"
        subtitle = f"{match.team_label('A')} contre {match.team_label('B')}"

    return {
        "id": match.id,
        "mode": match.mode,
        "title": title,
        "subtitle": subtitle,
        "remaining": remaining,
        "href": url_for("matches.match_detail", match_id=match.id),
    }


def serialize_match_card(match, user):
    status_labels = {
        "active": "En cours",
        "pending_validation": "Validation",
        "disputed": "Correction",
    }
    return {
        "id": match.id,
        "mode": match.mode,
        "status": match.status,
        "status_label": status_labels.get(match.status, match.status),
        "title": f"{match.mode} · {match.team_label('A')} vs {match.team_label('B')}",
        "subtitle": score_label(match),
        "href": url_for("matches.match_detail", match_id=match.id),
    }


def serialize_event(match):
    return {
        "id": match.id,
        "tone": "success" if match.status == "completed" else "warning",
        "text": match.public_note,
        "date": match.created_at.strftime("%d/%m %H:%M"),
    }


def score_label(match):
    if match.score_a is None or match.score_b is None:
        return "Score à venir"
    return f"{match.team_label('A')} {match.score_a}-{match.score_b} {match.team_label('B')}"


def match_history_for(user, mode=None):
    query = (
        Match.query.join(MatchParticipant)
        .filter(MatchParticipant.user_id == user.id, Match.status == "completed")
        .order_by(Match.completed_at.desc())
    )
    if mode:
        query = query.filter(Match.mode == mode)

    return [history_item(match, user) for match in query.all()]


def history_item(match, user):
    participant = match.participant_for(user.id)
    user_team = participant.team
    opponent_team = "B" if user_team == "A" else "A"
    won = match.winner_team == user_team
    delta = participant.elo_delta
    return {
        "match": match,
        "mode": match.mode,
        "date": (match.completed_at or match.created_at).strftime("%d/%m/%Y"),
        "opponents": match.team_label(opponent_team),
        "allies": match.team_label(user_team),
        "score": f"{match.score_a}-{match.score_b}",
        "result": "Victoire" if won else "Défaite",
        "won": won,
        "delta": round(delta) if delta is not None else 0,
    }


def has_open_match_between(user_ids):
    ids = set(user_ids)
    matches = (
        Match.query.join(MatchParticipant)
        .filter(Match.status.in_(OPEN_STATUSES), MatchParticipant.user_id.in_(ids))
        .all()
    )
    for match in matches:
        participant_ids = {p.user_id for p in match.participants}
        if ids.issubset(participant_ids):
            return True
    return False
