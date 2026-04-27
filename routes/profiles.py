import uuid
from pathlib import Path

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from config import Config
from extensions import db
from models import User
from services import match_history_for


profiles_bp = Blueprint("profiles", __name__)

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}


def _is_image_upload(file_storage):
    filename = file_storage.filename or ""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        return False

    head = file_storage.stream.read(16)
    file_storage.stream.seek(0)
    signatures = (
        head.startswith(b"\xff\xd8\xff"),
        head.startswith(b"\x89PNG\r\n\x1a\n"),
        head.startswith(b"GIF87a"),
        head.startswith(b"GIF89a"),
        head.startswith(b"RIFF") and b"WEBP" in head,
    )
    return any(signatures)


@profiles_bp.route("/profile")
@login_required
def my_profile():
    return redirect(url_for("profiles.profile", user_id=current_user.id))


@profiles_bp.route("/profile/<int:user_id>", methods=["GET", "POST"])
@login_required
def profile(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == "POST":
        if user.id != current_user.id:
            flash("Profil non modifiable.", "error")
            return redirect(url_for("profiles.profile", user_id=user.id))

        photo = request.files.get("photo")
        if not photo or not photo.filename:
            flash("Image manquante.", "error")
        elif not _is_image_upload(photo):
            flash("Format image invalide.", "error")
        else:
            extension = secure_filename(photo.filename).rsplit(".", 1)[-1].lower()
            filename = f"{uuid.uuid4().hex}.{extension}"
            Path(Config.UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)
            photo.save(Path(Config.UPLOAD_FOLDER) / filename)
            user.profile_image = filename
            db.session.commit()
            flash("Photo mise à jour.", "success")
            return redirect(url_for("profiles.profile", user_id=user.id))

    history_1v1 = match_history_for(user, "1v1")
    history_2v2 = match_history_for(user, "2v2")
    return render_template(
        "profile.html",
        user=user,
        history_1v1=history_1v1,
        history_2v2=history_2v2,
    )


@profiles_bp.route("/profile/<int:user_id>/history")
@login_required
def match_history(user_id):
    user = User.query.get_or_404(user_id)
    return render_template(
        "match_history.html",
        user=user,
        history_1v1=match_history_for(user, "1v1"),
        history_2v2=match_history_for(user, "2v2"),
    )
