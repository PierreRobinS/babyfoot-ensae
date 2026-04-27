import math
from dataclasses import dataclass

from config import Config


@dataclass
class RatingState:
    rating: float
    rd: float
    volatility: float


def _to_mu(rating):
    return (rating - Config.GLICKO_DEFAULT_RATING) / Config.GLICKO_SCALE


def _to_phi(rd):
    return rd / Config.GLICKO_SCALE


def _from_mu(mu):
    return Config.GLICKO_DEFAULT_RATING + Config.GLICKO_SCALE * mu


def _from_phi(phi):
    return Config.GLICKO_SCALE * phi


def _g(phi):
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / (math.pi * math.pi))


def _expected_score(mu, opponent_mu, opponent_phi):
    return 1.0 / (1.0 + math.exp(-_g(opponent_phi) * (mu - opponent_mu)))


def predict_point_probability(player_rating, opponent_rating, opponent_rd):
    """Return the Glicko-2 expected probability of scoring the next point.

    The app interprets the Glicko-2 expected score as a per-point probability,
    not as a binary match win probability. The opponent RD is included through
    the usual Glicko-2 g(phi) term: uncertain opponents pull predictions toward
    50%, which is desirable for early-season local rankings.
    """
    mu = _to_mu(player_rating)
    opponent_mu = _to_mu(opponent_rating)
    opponent_phi = _to_phi(opponent_rd)
    return _expected_score(mu, opponent_mu, opponent_phi)


def predict_score_distribution(point_probability, target_score=10):
    """Approximate a babyfoot score line as a race to 10.

    The displayed prediction must look like an actual submitted match score:
    either 10-k or k-10. We estimate the losing side's points by scaling the
    favorite's expected race-to-target score from the per-point probability.
    """
    p = max(0.01, min(0.99, point_probability))
    if p >= 0.5:
        a_points = target_score
        b_points = round(target_score * (1.0 - p) / p)
        favorite = "A"
    else:
        a_points = round(target_score * p / (1.0 - p))
        b_points = target_score
        favorite = "B"

    a_points = max(0, min(target_score, a_points))
    b_points = max(0, min(target_score, b_points))
    if a_points == b_points:
        if favorite == "A":
            b_points = target_score - 1
        else:
            a_points = target_score - 1

    return {
        "favorite": favorite,
        "point_probability": p,
        "score_a": a_points,
        "score_b": b_points,
    }


def _volatility_update(phi, sigma, delta, v):
    tau = Config.GLICKO_TAU
    epsilon = Config.GLICKO_EPSILON
    a = math.log(sigma * sigma)

    def f(x):
        ex = math.exp(x)
        numerator = ex * (delta * delta - phi * phi - v - ex)
        denominator = 2.0 * (phi * phi + v + ex) ** 2
        return numerator / denominator - (x - a) / (tau * tau)

    if delta * delta > phi * phi + v:
        b = math.log(delta * delta - phi * phi - v)
    else:
        k = 1
        b = a - k * tau
        while f(b) < 0:
            k += 1
            b = a - k * tau

    fa = f(a)
    fb = f(b)
    while abs(b - a) > epsilon:
        c = a + (a - b) * fa / (fb - fa)
        fc = f(c)
        if fc * fb < 0:
            a = b
            fa = fb
        else:
            fa /= 2.0
        b = c
        fb = fc

    return math.exp(a / 2.0)


def _update_single_game(player, opponent, observed_score):
    mu = _to_mu(player.rating)
    phi = _to_phi(player.rd)
    sigma = player.volatility

    opponent_mu = _to_mu(opponent.rating)
    opponent_phi = _to_phi(opponent.rd)
    g_phi = _g(opponent_phi)
    expected = _expected_score(mu, opponent_mu, opponent_phi)

    # Glicko-2 usually receives a binary s in {0, 1}. Here s is continuous:
    # points_scored / total_points. The same likelihood gradient works and
    # gives a smooth update for close or lopsided score lines.
    s = max(0.0, min(1.0, observed_score))
    v = 1.0 / (g_phi * g_phi * expected * (1.0 - expected))
    delta = v * g_phi * (s - expected)

    new_sigma = _volatility_update(phi, sigma, delta, v)
    phi_star = math.sqrt(phi * phi + new_sigma * new_sigma)
    new_phi = 1.0 / math.sqrt((1.0 / (phi_star * phi_star)) + (1.0 / v))
    new_mu = mu + new_phi * new_phi * g_phi * (s - expected)

    return RatingState(
        rating=_from_mu(new_mu),
        rd=max(30.0, min(350.0, _from_phi(new_phi))),
        volatility=new_sigma,
    )


def update_glicko_1v1(player_a, player_b, score_a, score_b):
    total = score_a + score_b
    observed_a = score_a / total
    observed_b = score_b / total
    probability_a = predict_point_probability(
        player_a.rating, player_b.rating, player_b.rd
    )

    return {
        "player_a": _update_single_game(player_a, player_b, observed_a),
        "player_b": _update_single_game(player_b, player_a, observed_b),
        "probability_a": probability_a,
    }


def _team_rating(players):
    rating = sum(player.rating for player in players) / len(players)
    # The team is treated as an average of two independent players. Variances
    # add, then the average divides by team size.
    rd = math.sqrt(sum(player.rd * player.rd for player in players)) / len(players)
    volatility = sum(player.volatility for player in players) / len(players)
    return RatingState(rating=rating, rd=rd, volatility=volatility)


def update_glicko_2v2(team_a, team_b, score_a, score_b):
    total = score_a + score_b
    observed_a = score_a / total
    observed_b = score_b / total

    temp_a = _team_rating(team_a)
    temp_b = _team_rating(team_b)
    probability_a = predict_point_probability(temp_a.rating, temp_b.rating, temp_b.rd)

    return {
        "team_a": [_update_single_game(player, temp_b, observed_a) for player in team_a],
        "team_b": [_update_single_game(player, temp_a, observed_b) for player in team_b],
        "probability_a": probability_a,
    }
