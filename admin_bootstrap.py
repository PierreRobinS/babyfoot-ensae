from sqlalchemy import inspect, text

from config import Config
from extensions import db
from models import SiteSetting, User
from services import parse_names_from_email


USER_COLUMNS = {
    "last_login_at": "DATETIME",
    "is_admin": "BOOLEAN NOT NULL DEFAULT 0",
    "is_banned": "BOOLEAN NOT NULL DEFAULT 0",
    "ban_reason": "VARCHAR(255)",
    "banned_until": "DATETIME",
    "badge": "VARCHAR(80)",
}


def migrate_light_schema():
    inspector = inspect(db.engine)
    if "user" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("user")}
    with db.engine.begin() as connection:
        for name, ddl in USER_COLUMNS.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE user ADD COLUMN {name} {ddl}"))


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
