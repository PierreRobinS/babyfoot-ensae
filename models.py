from datetime import datetime

from flask import url_for
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from extensions import db


def utcnow():
    return datetime.utcnow()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    pseudo = db.Column(db.String(40), unique=True, nullable=False, index=True)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    profile_image = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)
    last_activity = db.Column(db.DateTime, nullable=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_banned = db.Column(db.Boolean, default=False, nullable=False)
    ban_reason = db.Column(db.String(255), nullable=True)
    banned_until = db.Column(db.DateTime, nullable=True)
    badge = db.Column(db.String(80), nullable=True)

    rating_1v1 = db.Column(db.Float, default=Config.GLICKO_DEFAULT_RATING, nullable=False)
    rd_1v1 = db.Column(db.Float, default=Config.GLICKO_DEFAULT_RD, nullable=False)
    volatility_1v1 = db.Column(
        db.Float, default=Config.GLICKO_DEFAULT_VOLATILITY, nullable=False
    )
    rating_2v2 = db.Column(db.Float, default=Config.GLICKO_DEFAULT_RATING, nullable=False)
    rd_2v2 = db.Column(db.Float, default=Config.GLICKO_DEFAULT_RD, nullable=False)
    volatility_2v2 = db.Column(
        db.Float, default=Config.GLICKO_DEFAULT_VOLATILITY, nullable=False
    )

    matches_1v1 = db.Column(db.Integer, default=0, nullable=False)
    wins_1v1 = db.Column(db.Integer, default=0, nullable=False)
    losses_1v1 = db.Column(db.Integer, default=0, nullable=False)
    matches_2v2 = db.Column(db.Integer, default=0, nullable=False)
    wins_2v2 = db.Column(db.Integer, default=0, nullable=False)
    losses_2v2 = db.Column(db.Integer, default=0, nullable=False)

    hosted_matches = db.relationship("Match", back_populates="host", foreign_keys="Match.host_id")
    participations = db.relationship(
        "MatchParticipant", back_populates="user", cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def avatar_url(self):
        if self.profile_image:
            return url_for("static", filename=f"uploads/{self.profile_image}")
        return url_for("static", filename="img/default-avatar.svg")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip().title()

    def rating_state(self, mode):
        if mode == "1v1":
            return self.rating_1v1, self.rd_1v1, self.volatility_1v1
        return self.rating_2v2, self.rd_2v2, self.volatility_2v2

    def winrate(self, mode):
        matches = self.matches_1v1 if mode == "1v1" else self.matches_2v2
        wins = self.wins_1v1 if mode == "1v1" else self.wins_2v2
        if matches == 0:
            return 0
        return round(100 * wins / matches)

    def active_ban_label(self):
        if not self.is_banned:
            return None
        if self.banned_until and self.banned_until > utcnow():
            return f"Banni jusqu'au {self.banned_until.strftime('%d/%m %H:%M')}"
        if self.banned_until:
            return None
        return "Banni définitivement"


class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mode = db.Column(db.String(8), nullable=False, index=True)
    status = db.Column(db.String(32), default="pending_invitation", nullable=False, index=True)
    host_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    score_a = db.Column(db.Integer, nullable=True)
    score_b = db.Column(db.Integer, nullable=True)
    proposal_round = db.Column(db.Integer, default=0, nullable=False)
    proposed_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    cancelled_reason = db.Column(db.String(255), nullable=True)
    public_note = db.Column(db.String(255), nullable=True)
    refused_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    non_response_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    host = db.relationship("User", back_populates="hosted_matches", foreign_keys=[host_id])
    proposed_by = db.relationship("User", foreign_keys=[proposed_by_id])
    refused_by = db.relationship("User", foreign_keys=[refused_by_id])
    non_response_user = db.relationship("User", foreign_keys=[non_response_user_id])
    participants = db.relationship(
        "MatchParticipant",
        back_populates="match",
        cascade="all, delete-orphan",
        order_by="MatchParticipant.id",
    )

    def participant_for(self, user_id):
        return next((p for p in self.participants if p.user_id == user_id), None)

    def team(self, team_name):
        return [p for p in self.participants if p.team == team_name]

    def team_label(self, team_name):
        return " + ".join(p.user.pseudo for p in self.team(team_name))

    def accepted_invitations(self):
        return all(p.invitation_status == "accepted" for p in self.participants)

    def accepted_validations(self):
        return all(p.validation_status == "accepted" for p in self.participants)

    @property
    def winner_team(self):
        if self.score_a is None or self.score_b is None:
            return None
        return "A" if self.score_a > self.score_b else "B"


class MatchParticipant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey("match.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    team = db.Column(db.String(1), nullable=False)
    role = db.Column(db.String(24), nullable=False, default="player")
    invitation_status = db.Column(db.String(24), default="pending", nullable=False)
    validation_status = db.Column(db.String(24), default="pending", nullable=False)
    invited_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    responded_at = db.Column(db.DateTime, nullable=True)
    elo_before = db.Column(db.Float, nullable=True)
    elo_after = db.Column(db.Float, nullable=True)

    match = db.relationship("Match", back_populates="participants")
    user = db.relationship("User", back_populates="participations")

    __table_args__ = (db.UniqueConstraint("match_id", "user_id", name="uq_match_user"),)

    @property
    def elo_delta(self):
        if self.elo_before is None or self.elo_after is None:
            return None
        return self.elo_after - self.elo_before


class BanPair(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mode = db.Column(db.String(8), nullable=False)
    group_key = db.Column(db.String(255), nullable=False, index=True)
    count = db.Column(db.Integer, default=0, nullable=False)
    banned_until = db.Column(db.DateTime, nullable=True)
    last_match_id = db.Column(db.Integer, db.ForeignKey("match.id"), nullable=True)
    updated_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("mode", "group_key", name="uq_ban_group"),)

    def is_active(self, now=None):
        now = now or utcnow()
        return self.banned_until is not None and self.banned_until > now


class Dispute(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey("match.id"), nullable=False)
    mode = db.Column(db.String(8), nullable=False)
    group_key = db.Column(db.String(255), nullable=False)
    triggered_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    count_after = db.Column(db.Integer, nullable=False)
    banned_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    match = db.relationship("Match")
    triggered_by = db.relationship("User")


class AdminLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    action = db.Column(db.String(80), nullable=False, index=True)
    target_type = db.Column(db.String(60), nullable=True)
    target_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)

    admin = db.relationship("User")


class SiteSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class Tournament(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(40), default="draft", nullable=False)
    banner_message = db.Column(db.String(255), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    created_by = db.relationship("User")
