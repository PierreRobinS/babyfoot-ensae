from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent


def _inside_onedrive(path):
    onedrive_paths = [os.getenv("OneDrive"), os.getenv("OneDriveConsumer"), os.getenv("OneDriveCommercial")]
    resolved = path.resolve()
    for item in onedrive_paths:
        if item:
            try:
                resolved.relative_to(Path(item).resolve())
                return True
            except ValueError:
                pass
    return "onedrive" in {part.lower() for part in resolved.parts}


def _default_data_dir():
    if os.getenv("DATA_DIR"):
        return Path(os.getenv("DATA_DIR"))
    local_app_data = os.getenv("LOCALAPPDATA")
    if os.name == "nt" and local_app_data and _inside_onedrive(BASE_DIR):
        return Path(local_app_data) / "BabyfootENSAE" / "data"
    return BASE_DIR / "data"


DATA_DIR = _default_data_dir()
DATABASE_PATH = DATA_DIR / "babyfoot.sqlite3"
DATABASE_URI = f"sqlite:///{DATABASE_PATH.as_posix()}"


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "local-babyfoot-ensae-change-me")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    DATA_DIR = DATA_DIR
    SQLALCHEMY_DATABASE_URI = DATABASE_URI
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path(os.getenv("UPLOAD_FOLDER", BASE_DIR / "static" / "uploads"))
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024

    # Glicko-2 constants. Ratings are stored on the classic 1500 scale in DB
    # and converted to the Glicko-2 internal scale only inside rating_system.py.
    GLICKO_DEFAULT_RATING = 1500.0
    GLICKO_DEFAULT_RD = 350.0
    GLICKO_DEFAULT_VOLATILITY = 0.06
    GLICKO_SCALE = 173.7178
    GLICKO_TAU = 0.5
    GLICKO_EPSILON = 0.000001

    # Hidden Skill Rating keeps the current conservative Glicko-2 behavior.
    HIDDEN_GLICKO_MIN_RD = 30.0
    HIDDEN_GLICKO_MAX_RD = 350.0

    # Visible Ladder Rating is intentionally livelier: wins matter more,
    # score gaps still count, and RD/volatility stay high enough to move.
    VISIBLE_GLICKO_DEFAULT_VOLATILITY = 0.075
    VISIBLE_GLICKO_TAU = 0.9
    VISIBLE_GLICKO_MIN_RD = 80.0
    VISIBLE_GLICKO_MAX_RD = 350.0

    INVITATION_TIMEOUT_1V1_SECONDS = 2 * 60
    INVITATION_TIMEOUT_2V2_SECONDS = 3 * 60

    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@ensae.fr")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "AdminPassword123!")
    ADMIN_PSEUDO = os.getenv("ADMIN_PSEUDO", "GodMode")

    REGISTRATIONS_ENABLED = True
    MAINTENANCE_ENABLED = False
    MAINTENANCE_MESSAGE = ""
    THEME_COLOR = "warm"
