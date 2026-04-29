import logging

from flask import Blueprint, jsonify, render_template, request

from .generator import generate_meal_plan, regenerate_meal
from .models import load_plan
from .scheduler import scheduler

log = logging.getLogger("meal-planner")

bp = Blueprint("main", __name__)


def _normalize_ingredients(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    return {"Other": raw or []}


@bp.route("/")
def index():
    data = load_plan()
    all_ingredients = _normalize_ingredients(data.get("all_ingredients"))
    return render_template(
        "index.html",
        week_of=data.get("week_of", "—"),
        cuisine_theme=data.get("cuisine_theme", ""),
        meals=data.get("meals", []),
        snacks=data.get("snacks", []),
        all_ingredients=all_ingredients,
        ingredient_count=sum(len(v) for v in all_ingredients.values()),
    )


@bp.route("/generate", methods=["POST"])
def generate():
    """Manually trigger a new meal plan generation."""
    try:
        plan = generate_meal_plan()
        return jsonify({"status": "ok", "week_of": plan.get("week_of")})
    except Exception as e:
        log.error(f"generate failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@bp.route("/regenerate", methods=["POST"])
def regenerate():
    body = request.get_json()
    meal_index = body.get("meal_index")
    disliked = body.get("disliked", "").strip()

    try:
        new_meal = regenerate_meal(meal_index, disliked)
        return jsonify(new_meal)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        log.error(f"regenerate failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@bp.route("/plan")
def get_plan():
    return jsonify(load_plan())


@bp.route("/health")
def health():
    return jsonify({"status": "ok", "jobs": [str(j) for j in scheduler.get_jobs()]})
