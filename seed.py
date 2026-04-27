from datetime import timedelta

from extensions import db
from models import Match, MatchParticipant, User, utcnow
from services import complete_match, parse_names_from_email


DEMO_USERS = [
    ("alice.martin@ensae.fr", "AliceM"),
    ("bastien.durand@ensae.fr", "Bastou"),
    ("chloe.bernard@ensae.fr", "ChloeB"),
    ("mehdi.moreau@ensae.fr", "MehdiM"),
    ("ines.leroy@ensae.fr", "InesL"),
    ("paul.robert@ensae.fr", "PaulR"),
]


def seed_demo_data():
    users = {}
    for email, pseudo in DEMO_USERS:
        user = User.query.filter_by(email=email).first()
        if not user:
            first_name, last_name = parse_names_from_email(email)
            user = User(email=email, pseudo=pseudo, first_name=first_name, last_name=last_name)
            user.set_password("password123")
            db.session.add(user)
        users[pseudo] = user

    db.session.flush()

    if Match.query.count() == 0:
        _completed_1v1(users["AliceM"], users["Bastou"], 10, 7)
        _completed_1v1(users["ChloeB"], users["MehdiM"], 6, 10)
        _completed_2v2(
            [users["AliceM"], users["InesL"]],
            [users["ChloeB"], users["PaulR"]],
            10,
            8,
        )

    db.session.commit()


def _completed_1v1(player_a, player_b, score_a, score_b):
    match = Match(
        mode="1v1",
        host_id=player_a.id,
        status="pending_validation",
        started_at=utcnow() - timedelta(minutes=20),
        score_a=score_a,
        score_b=score_b,
        proposal_round=1,
        proposed_by_id=player_a.id,
    )
    db.session.add(match)
    db.session.flush()
    db.session.add_all(
        [
            MatchParticipant(
                match_id=match.id,
                user_id=player_a.id,
                team="A",
                role="host",
                invitation_status="accepted",
                validation_status="accepted",
            ),
            MatchParticipant(
                match_id=match.id,
                user_id=player_b.id,
                team="B",
                role="opponent",
                invitation_status="accepted",
                validation_status="accepted",
            ),
        ]
    )
    db.session.flush()
    complete_match(match)


def _completed_2v2(team_a, team_b, score_a, score_b):
    match = Match(
        mode="2v2",
        host_id=team_a[0].id,
        status="pending_validation",
        started_at=utcnow() - timedelta(minutes=40),
        score_a=score_a,
        score_b=score_b,
        proposal_round=1,
        proposed_by_id=team_a[0].id,
    )
    db.session.add(match)
    db.session.flush()
    participants = [
        MatchParticipant(
            match_id=match.id,
            user_id=team_a[0].id,
            team="A",
            role="host",
            invitation_status="accepted",
            validation_status="accepted",
        ),
        MatchParticipant(
            match_id=match.id,
            user_id=team_a[1].id,
            team="A",
            role="partner",
            invitation_status="accepted",
            validation_status="accepted",
        ),
        MatchParticipant(
            match_id=match.id,
            user_id=team_b[0].id,
            team="B",
            role="opponent",
            invitation_status="accepted",
            validation_status="accepted",
        ),
        MatchParticipant(
            match_id=match.id,
            user_id=team_b[1].id,
            team="B",
            role="opponent",
            invitation_status="accepted",
            validation_status="accepted",
        ),
    ]
    db.session.add_all(participants)
    db.session.flush()
    complete_match(match)
