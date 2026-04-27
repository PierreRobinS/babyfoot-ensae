import sys
from pathlib import Path

from flask import Flask, request
from flask_login import current_user

from config import Config
from extensions import db, login_manager
from models import SiteSetting, User
from routes import admin_bp, auth_bp, main_bp, matches_bp, profiles_bp, rankings_bp
from security import csrf_token, validate_csrf


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    Path(Config.DATA_DIR).mkdir(parents=True, exist_ok=True)
    Path(Config.UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Connectez-vous pour continuer."
    login_manager.login_message_category = "error"

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.context_processor
    def inject_security_helpers():
        settings = {item.key: item.value for item in SiteSetting.query.all()}
        return {"csrf_token": csrf_token, "site_settings": settings}

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(matches_bp)
    app.register_blueprint(rankings_bp)
    app.register_blueprint(profiles_bp)
    app.register_blueprint(admin_bp)

    @app.before_request
    def keep_match_state_fresh():
        if request.endpoint and request.endpoint.startswith("static"):
            return
        if not validate_csrf():
            from flask import abort

            abort(400, "CSRF token invalide.")
        if current_user.is_authenticated and current_user.is_banned:
            from flask import flash, redirect, url_for

            if not current_user.is_admin:
                flash(current_user.ban_reason or "Compte banni.", "error")
                return redirect(url_for("auth.logout"))
        if request.endpoint not in {"auth.login", "auth.logout", "static"}:
            maintenance = SiteSetting.query.filter_by(key="maintenance_enabled").first()
            if maintenance and maintenance.value == "true":
                if not current_user.is_authenticated or not current_user.is_admin:
                    from flask import flash, redirect, url_for

                    message = SiteSetting.query.filter_by(key="maintenance_message").first()
                    flash((message.value if message else None) or "Maintenance en cours.", "error")
                    return redirect(url_for("auth.login"))
        from services import expire_matches

        expire_matches()

    with app.app_context():
        from admin_bootstrap import bootstrap_admin_system

        bootstrap_admin_system()

    return app


app = create_app()


if __name__ == "__main__":
    if "--seed" in sys.argv:
        from seed import seed_demo_data

        with app.app_context():
            seed_demo_data()
        print("Demo users ready. Password for all demo accounts: password123")
        sys.exit(0)

    app.run(debug=True, host="127.0.0.1", port=5000)
