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
    """Deduplicate ingredients across all meals.

    Groups by ingredient name. Sums quantities that share the same unit.
    When an ingredient appears with multiple different units, shows each
    unit's total as an array. E.g.:
      "olive oil x 2 tbsp" + "olive oil x 1 tbsp" -> "olive oil — 3 tbsp"
      "garlic x 3 cloves" + "garlic x 1 head"     -> "garlic — 3 cloves, 1 head"
    """
    # name_key -> [display_name, {unit_key -> [total_qty, display_unit]}]
    combined = {}
    order = []

    for meal in meals:
        for ing in meal.get("ingredients", []):
            if " from " in ing.lower():
                continue
            name, qty, unit = _parse_ingredient(ing)
            name_key = name.lower()
            unit_key = unit.lower()

            if name_key not in combined:
                combined[name_key] = [name, {}]
                order.append(name_key)

            by_unit = combined[name_key][1]
            if unit_key not in by_unit:
                by_unit[unit_key] = [qty, unit]
            else:
                existing_qty = by_unit[unit_key][0]
                if existing_qty is not None and qty is not None:
                    by_unit[unit_key][0] = existing_qty + qty

    def _fmt_qty(qty, unit):
        if qty is None:
            # Multi-word units with no number are notes ("already have", "to taste") — skip
            return unit if unit and " " not in unit.strip() else ""
        qty_str = str(int(qty)) if qty == int(qty) else str(qty)
        return f"{qty_str} {unit}".strip() if unit else qty_str

    result = []
    for name_key in order:
        display_name, by_unit = combined[name_key]
        parts = [_fmt_qty(qty, unit) for qty, unit in by_unit.values() if _fmt_qty(qty, unit)]
        if parts:
            result.append(f"{display_name} — {', '.join(parts)}")
        else:
            result.append(display_name)

    return result


def parse_ai_json(raw: str) -> dict:
    """Strip markdown fences from AI response and parse JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())
