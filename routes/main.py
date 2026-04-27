from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from models import User
from services import (
    active_ban,
    dashboard_payload,
    expire_matches,
    prediction_1v1,
    prediction_2v2,
    setup_group_key,
    user_search,
)


main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def home():
    expire_matches()
    payload = dashboard_payload(current_user)
    return render_template("home.html", dashboard=payload)


@main_bp.route("/api/users/search")
@login_required
def api_user_search():
    return jsonify(user_search(request.args.get("q", ""), current_user.id))


@main_bp.route("/api/home-state")
@login_required
def api_home_state():
    expire_matches()
    return jsonify(dashboard_payload(current_user))


@main_bp.route("/api/predict")
@login_required
def api_predict():
    mode = request.args.get("mode")
    try:
        if mode == "1v1":
            opponent = User.query.get_or_404(int(request.args.get("opponent_id", 0)))
            prediction = prediction_1v1(current_user, opponent)
            group_key = setup_group_key("1v1", [current_user.id], [opponent.id])
        elif mode == "2v2":
            partner = User.query.get_or_404(int(request.args.get("partner_id", 0)))
            opponent_1 = User.query.get_or_404(int(request.args.get("opponent1_id", 0)))
            opponent_2 = User.query.get_or_404(int(request.args.get("opponent2_id", 0)))
            ids = {current_user.id, partner.id, opponent_1.id, opponent_2.id}
            if len(ids) != 4:
                return jsonify({"ok": False, "message": "Joueurs en double."}), 400
            prediction = prediction_2v2([current_user, partner], [opponent_1, opponent_2])
            group_key = setup_group_key(
                "2v2", [current_user.id, partner.id], [opponent_1.id, opponent_2.id]
            )
        else:
            return jsonify({"ok": False, "message": "Mode inconnu."}), 400
    except ValueError:
        return jsonify({"ok": False, "message": "Sélection invalide."}), 400

    ban = active_ban(mode, group_key)
    return jsonify(
        {
            "ok": True,
            "prediction": prediction,
            "ban": bool(ban),
            "ban_until": ban.banned_until.strftime("%d/%m %H:%M") if ban else None,
        }
    )
