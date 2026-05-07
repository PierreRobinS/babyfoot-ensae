from sqlalchemy import inspect, text

from config import Config
from extensions import db
from models import SiteSetting, User
from services import parse_names_from_email


USER_COLUMNS = {
    "last_login_at": "DATETIME",
    "last_activity": "DATETIME",
    "is_admin": "BOOLEAN NOT NULL DEFAULT 0",
    "is_banned": "BOOLEAN NOT NULL DEFAULT 0",
    "ban_reason": "VARCHAR(255)",
    "banned_until": "DATETIME",
    "badge": "VARCHAR(80)",
}

DUAL_RATING_COLUMNS = {
    "hidden_rating_1v1": f"FLOAT NOT NULL DEFAULT {Config.GLICKO_DEFAULT_RATING}",
    "hidden_rd_1v1": f"FLOAT NOT NULL DEFAULT {Config.GLICKO_DEFAULT_RD}",
    "hidden_volatility_1v1": f"FLOAT NOT NULL DEFAULT {Config.GLICKO_DEFAULT_VOLATILITY}",
    "hidden_rating_2v2": f"FLOAT NOT NULL DEFAULT {Config.GLICKO_DEFAULT_RATING}",
    "hidden_rd_2v2": f"FLOAT NOT NULL DEFAULT {Config.GLICKO_DEFAULT_RD}",
    "hidden_volatility_2v2": f"FLOAT NOT NULL DEFAULT {Config.GLICKO_DEFAULT_VOLATILITY}",
    "visible_rating_1v1": f"FLOAT NOT NULL DEFAULT {Config.GLICKO_DEFAULT_RATING}",
    "visible_rd_1v1": f"FLOAT NOT NULL DEFAULT {Config.GLICKO_DEFAULT_RD}",
    "visible_volatility_1v1": f"FLOAT NOT NULL DEFAULT {Config.VISIBLE_GLICKO_DEFAULT_VOLATILITY}",
    "visible_rating_2v2": f"FLOAT NOT NULL DEFAULT {Config.GLICKO_DEFAULT_RATING}",
    "visible_rd_2v2": f"FLOAT NOT NULL DEFAULT {Config.GLICKO_DEFAULT_RD}",
    "visible_volatility_2v2": f"FLOAT NOT NULL DEFAULT {Config.VISIBLE_GLICKO_DEFAULT_VOLATILITY}",
}

MATCH_COLUMNS = {
    "live_score_a": "INTEGER NOT NULL DEFAULT 0",
    "live_score_b": "INTEGER NOT NULL DEFAULT 0",
    "proposal_round": "INTEGER NOT NULL DEFAULT 0",
    "stop_requested_by_id": "INTEGER",
}

NUMERIC_DEFAULT_FIXES = {
    "match": {
        "live_score_a": 0,
        "live_score_b": 0,
        "proposal_round": 0,
    },
    "ban_pair": {
        "count": 0,
    },
}


def migrate_light_schema():
    inspector = inspect(db.engine)
    if "user" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("user")}
    added_user_columns = set()
    with db.engine.begin() as connection:
        for name, ddl in {**USER_COLUMNS, **DUAL_RATING_COLUMNS}.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE user ADD COLUMN {name} {ddl}"))
                added_user_columns.add(name)
    existing = existing | added_user_columns
    _backfill_dual_rating_columns(existing, added_user_columns)
    if "match" in inspector.get_table_names():
        existing = {column["name"] for column in inspector.get_columns("match")}
        with db.engine.begin() as connection:
            for name, ddl in MATCH_COLUMNS.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE match ADD COLUMN {name} {ddl}"))

    table_names = set(inspector.get_table_names())
    with db.engine.begin() as connection:
        for table_name, columns in NUMERIC_DEFAULT_FIXES.items():
            if table_name not in table_names:
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, default_value in columns.items():
                if column_name in existing:
                    connection.execute(
                        text(
                            f"UPDATE {table_name} "
                            f"SET {column_name} = :default_value "
                            f"WHERE {column_name} IS NULL"
                        ),
                        {"default_value": default_value},
                    )


def _backfill_dual_rating_columns(existing_columns, added_columns):
    # Existing deployments used rating_*/rd_*/volatility_* as the only rating.
    # On the first dual-rating boot, copy those values into hidden and visible
    # so history is preserved while future updates split the two systems.
    legacy_map = {
        "hidden_rating_1v1": ("rating_1v1", Config.GLICKO_DEFAULT_RATING),
        "hidden_rd_1v1": ("rd_1v1", Config.GLICKO_DEFAULT_RD),
        "hidden_volatility_1v1": ("volatility_1v1", Config.GLICKO_DEFAULT_VOLATILITY),
        "hidden_rating_2v2": ("rating_2v2", Config.GLICKO_DEFAULT_RATING),
        "hidden_rd_2v2": ("rd_2v2", Config.GLICKO_DEFAULT_RD),
        "hidden_volatility_2v2": ("volatility_2v2", Config.GLICKO_DEFAULT_VOLATILITY),
        "visible_rating_1v1": ("rating_1v1", Config.GLICKO_DEFAULT_RATING),
        "visible_rating_2v2": ("rating_2v2", Config.GLICKO_DEFAULT_RATING),
    }
    visible_rd_map = {
        "visible_rd_1v1": "rd_1v1",
        "visible_rd_2v2": "rd_2v2",
    }
    visible_volatility = {
        "visible_volatility_1v1": Config.VISIBLE_GLICKO_DEFAULT_VOLATILITY,
        "visible_volatility_2v2": Config.VISIBLE_GLICKO_DEFAULT_VOLATILITY,
    }

    with db.engine.begin() as connection:
        for column, (legacy, default) in legacy_map.items():
            if column not in existing_columns:
                continue
            source = legacy if legacy in existing_columns else f"{default}"
            condition = "1 = 1" if column in added_columns else f"{column} IS NULL"
            connection.execute(text(f"UPDATE user SET {column} = COALESCE({source}, :default) WHERE {condition}"), {"default": default})

        for column, legacy in visible_rd_map.items():
            if column not in existing_columns:
                continue
            source = legacy if legacy in existing_columns else None
            condition = "1 = 1" if column in added_columns else f"{column} IS NULL"
            if source:
                connection.execute(
                    text(
                        f"UPDATE user SET {column} = "
                        f"CASE WHEN COALESCE({source}, :default_rd) < :min_rd THEN :min_rd "
                        f"ELSE COALESCE({source}, :default_rd) END "
                        f"WHERE {condition}"
                    ),
                    {"default_rd": Config.GLICKO_DEFAULT_RD, "min_rd": Config.VISIBLE_GLICKO_MIN_RD},
                )
            else:
                connection.execute(text(f"UPDATE user SET {column} = :default_rd WHERE {condition}"), {"default_rd": Config.GLICKO_DEFAULT_RD})

        for column, default in visible_volatility.items():
            if column in existing_columns:
                condition = "1 = 1" if column in added_columns else f"{column} IS NULL"
                connection.execute(text(f"UPDATE user SET {column} = :default WHERE {condition}"), {"default": default})


def ensure_default_settings():
    defaults = {
        "registrations_enabled": str(Config.REGISTRATIONS_ENABLED).lower(),
        "maintenance_enabled": str(Config.MAINTENANCE_ENABLED).lower(),
        "maintenance_message": Config.MAINTENANCE_MESSAGE,
        "theme_color": Config.THEME_COLOR,
        "glicko_tau": str(Config.GLICKO_TAU),
        "glicko_default_rd": str(Config.GLICKO_DEFAULT_RD),
        "glicko_default_volatility": str(Config.GLICKO_DEFAULT_VOLATILITY),
        "invitation_timeout_1v1": str(Config.INVITATION_TIMEOUT_1V1_SECONDS),
        "invitation_timeout_2v2": str(Config.INVITATION_TIMEOUT_2V2_SECONDS),
        "auto_ban_hours": "1,6,24,72,168",
        "global_banner": "",
        "rankings_frozen": "false",
    }
    for key, value in defaults.items():
        if not SiteSetting.query.filter_by(key=key).first():
            db.session.add(SiteSetting(key=key, value=value))


def apply_runtime_settings():
    mapping = {item.key: item.value for item in SiteSetting.query.all()}
    try:
        Config.GLICKO_TAU = float(mapping.get("glicko_tau", Config.GLICKO_TAU))
        Config.GLICKO_DEFAULT_RD = float(mapping.get("glicko_default_rd", Config.GLICKO_DEFAULT_RD))
        Config.GLICKO_DEFAULT_VOLATILITY = float(
            mapping.get("glicko_default_volatility", Config.GLICKO_DEFAULT_VOLATILITY)
        )
        Config.INVITATION_TIMEOUT_1V1_SECONDS = int(
            mapping.get("invitation_timeout_1v1", Config.INVITATION_TIMEOUT_1V1_SECONDS)
        )
        Config.INVITATION_TIMEOUT_2V2_SECONDS = int(
            mapping.get("invitation_timeout_2v2", Config.INVITATION_TIMEOUT_2V2_SECONDS)
        )
        Config.REGISTRATIONS_ENABLED = mapping.get("registrations_enabled", "true") == "true"
        Config.MAINTENANCE_ENABLED = mapping.get("maintenance_enabled", "false") == "true"
        Config.MAINTENANCE_MESSAGE = mapping.get("maintenance_message", "")
        Config.THEME_COLOR = mapping.get("theme_color", "warm")
    except (TypeError, ValueError):
        pass


def ensure_admin_account():
    if not Config.ADMIN_EMAIL or not Config.ADMIN_PASSWORD or not Config.ADMIN_PSEUDO:
        return

    existing_admin = User.query.filter_by(is_admin=True).first()
    if existing_admin:
        for extra in User.query.filter(User.is_admin.is_(True), User.id != existing_admin.id).all():
            extra.is_admin = False
        return

    email = Config.ADMIN_EMAIL.strip().lower()
    user = User.query.filter_by(email=email).first()
    if not user:
        first_name, last_name = parse_names_from_email(email)
        user = User(
            email=email,
            pseudo=Config.ADMIN_PSEUDO,
            first_name=first_name,
            last_name=last_name,
            is_admin=True,
        )
        user.set_password(Config.ADMIN_PASSWORD)
        db.session.add(user)
    else:
        user.is_admin = True
        if not user.password_hash:
            user.set_password(Config.ADMIN_PASSWORD)


def bootstrap_admin_system():
    migrate_light_schema()
    db.create_all()
    ensure_default_settings()
    apply_runtime_settings()
    ensure_admin_account()
    db.session.commit()
