from flask import Blueprint, render_template
from flask_login import login_required

from models import User


rankings_bp = Blueprint("rankings", __name__)


@rankings_bp.route("/rankings")
@login_required
def rankings():
    ranking_1v1 = User.query.order_by(User.rating_1v1.desc(), User.matches_1v1.desc()).all()
    ranking_2v2 = User.query.order_by(User.rating_2v2.desc(), User.matches_2v2.desc()).all()
    return render_template("rankings.html", ranking_1v1=ranking_1v1, ranking_2v2=ranking_2v2)
