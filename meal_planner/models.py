import json
import re

from .config import MEAL_HISTORY_FILE, MEAL_PLAN_FILE, PLACEHOLDER

HISTORY_WEEKS_TO_KEEP = 4


def load_history() -> list:
    """Load meal history (list of recent weeks, oldest first)."""
    if MEAL_HISTORY_FILE.exists():
        with open(MEAL_HISTORY_FILE) as f:
            return json.load(f)
    return []


def save_history(week_of: str, meal_names: list[str], cuisine_theme: str = ""):
    """Append this week to history, keeping only the most recent HISTORY_WEEKS_TO_KEEP weeks."""
    history = load_history()
    history.append({"week_of": week_of, "meals": meal_names, "cuisine_theme": cuisine_theme})
    history = history[-HISTORY_WEEKS_TO_KEEP:]
    MEAL_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MEAL_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def load_plan():
    if MEAL_PLAN_FILE.exists():
        with open(MEAL_PLAN_FILE) as f:
            return json.load(f)
    return PLACEHOLDER


def save_plan(plan):
    MEAL_PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MEAL_PLAN_FILE, "w") as f:
        json.dump(plan, f, indent=2)


def _parse_ingredient(text):
    """Parse an ingredient string into (name, quantity, unit).

    Handles formats like:
      "lemon x 2"          -> ("lemon", 2.0, "")
      "chicken breast x 1.5 lbs" -> ("chicken breast", 1.5, "lbs")
      "garlic x 3 cloves"  -> ("garlic", 3.0, "cloves")
      "olive oil"           -> ("olive oil", None, "")
    """
    # Split on " x " or " × " (with surrounding spaces to avoid splitting
    # words like "extra" that contain the letter x)
    parts = re.split(r"\s+[x×]\s+", text, maxsplit=1)

    name = parts[0].strip()

    if len(parts) == 1:
        return name, None, ""

    qty_str = parts[1].strip()
    # Try to pull a leading number (int or float, including fractions like 1/2)
    m = re.match(r"(\d+(?:\.\d+)?(?:/\d+)?)", qty_str)
    if m:
        raw_num = m.group(1)
        if "/" in raw_num:
            num, denom = raw_num.split("/")
            qty = float(num) / float(denom)
        else:
            qty = float(raw_num)
        unit = qty_str[m.end():].strip()
        return name, qty, unit

    # No parseable number — treat the whole qty side as a unit-like label
    return name, None, qty_str


def rebuild_all_ingredients(meals):
    """Deduplicate and consolidate ingredients across all meals.

    Combines quantities for ingredients that share the same base name and unit.
    E.g. "lemon x 1" + "lemon x 2" becomes "lemon x 3".
    """
    # Key: (lowercase_name, lowercase_unit) -> [total_qty, display_name, unit]
    combined = {}
    # Preserve insertion order for stable output
    order = []

    for meal in meals:
        for ing in meal.get("ingredients", []):
            if " from " in ing.lower():
                continue
            name, qty, unit = _parse_ingredient(ing)
            key = (name.lower(), unit.lower())

            if key not in combined:
                combined[key] = [qty, name, unit]
                order.append(key)
            else:
                existing = combined[key]
                if existing[0] is not None and qty is not None:
                    existing[0] += qty
                # If either qty is None, keep what we have (can't sum unknowns)

    result = []
    for key in order:
        qty, name, unit = combined[key]
        if qty is not None:
            # Format as integer when possible (3.0 -> "3"), otherwise keep decimal
            qty_str = str(int(qty)) if qty == int(qty) else str(qty)
            if unit:
                result.append(f"{name} x {qty_str} {unit}")
            else:
                result.append(f"{name} x {qty_str}")
        else:
            if unit:
                result.append(f"{name} x {unit}")
            else:
                result.append(name)

    return result


def parse_ai_json(raw: str) -> dict:
    """Strip markdown fences from AI response and parse JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())
