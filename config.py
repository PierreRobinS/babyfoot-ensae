from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


class Config:
    SECRET_KEY = "local-babyfoot-ensae-change-me"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    DATA_DIR = DATA_DIR
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATA_DIR / 'babyfoot.sqlite3'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024

    # Glicko-2 constants. Ratings are stored on the classic 1500 scale in DB
    # and converted to the Glicko-2 internal scale only inside rating_system.py.
    GLICKO_DEFAULT_RATING = 1500.0
    GLICKO_DEFAULT_RD = 350.0
    GLICKO_DEFAULT_VOLATILITY = 0.06
    GLICKO_SCALE = 173.7178
    GLICKO_TAU = 0.5
    GLICKO_EPSILON = 0.000001

    INVITATION_TIMEOUT_1V1_SECONDS = 2 * 60
    INVITATION_TIMEOUT_2V2_SECONDS = 3 * 60

    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@ensae.fr")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "AdminPassword123!")
    ADMIN_PSEUDO = os.getenv("ADMIN_PSEUDO", "GodMode")

    REGISTRATIONS_ENABLED = True
    MAINTENANCE_ENABLED = False
    MAINTENANCE_MESSAGE = ""
    THEME_COLOR = "warm"
