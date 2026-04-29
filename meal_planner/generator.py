import logging
import random
from datetime import datetime, timedelta

import anthropic

from .config import ANTHROPIC_API_KEY, ET
from .models import load_history, load_plan, parse_ai_json, rebuild_all_ingredients, save_history, save_plan

log = logging.getLogger("meal-planner")

CUISINE_THEMES = [
    "Mediterranean (Greek, Italian, Spanish, Turkish influences)",
    "Mexican and Tex-Mex",
    "East Asian (Chinese, Japanese, or Korean)",
    "Southeast Asian (Thai or Vietnamese)",
    "Indian subcontinent (curries, tandoori, dal, etc.)",
    "American comfort and BBQ (Southern, smokehouse, diner classics)",
    "Middle Eastern (Lebanese, Persian, or Israeli)",
    "French bistro and Provençal",
    "Latin American (Peruvian, Argentine, or Brazilian)",
    "Japanese izakaya and street food",
    "Korean BBQ and banchan-style sides",
    "Italian trattoria",
]

GENERATION_PROMPT = """Generate exactly 3 dinners for the week. These are the only 3 nights cooking will happen — make every one worth it.

**This week's cuisine theme: {cuisine_theme}**
Use this as inspiration, not a straitjacket. 1-2 meals should draw from this style; the third can diverge if there's a more compelling option. No need to force every dish into the theme.

**Meal Structure:**
- Each dinner = 1 protein + 2 sides
- Sides must be light accompaniments — roasted or sautéed vegetables, a simple salad, a grain. Not full sub-dishes like saag paneer, dal, or curry — those are mains, not sides.
- Mix of effort: at least 1 quick meal (under 30 minutes active cooking) and 1 more involved meal worth the effort
- Each recipe serves 2, but the cook is often eating solo — planned leftovers are intentional and welcome. If a meal batch-cooks well, say so explicitly in the description.

**Dislikes (never include):**
- Arugula, tuna salad, pickled anything, raw/uncooked onions, feta cheese
- Bone-in chicken — always use boneless thighs or breasts

**Flavor bar — the most important constraint:**
- Every dish must be interesting enough to order at a restaurant. If it wouldn't appear on a menu, it's not good enough.
- No bland proteins — everything must be marinated, spiced, glazed, or sauced
- Sides must be aggressively seasoned — roast, char, glaze, or finish with something bold. No plain steamed anything.
- Consider an overnight marinade for every protein. If you skip it, the dish must not need it.

**Grocery Strategy:**
- Choose the best dishes regardless of ingredient overlap — don't compromise flavor for the sake of reuse
- For salads, use salad kits instead of plain lettuce

**Do not repeat any of these recently served meals:**
{recent_meals}

For snacks, provide 6 ideas with enough variety to cover the week — mix of packaged snacks (e.g. chips, crackers, bars, jerky) and fresh options. Never suggest hummus.

Also produce a comprehensive grocery list covering every ingredient from every meal. Sum quantities intelligently and write items as you'd see them on a shopping list. Exclude true pantry staples (salt, pepper, cooking oil) unless a specific type or quantity matters. Categorise correctly: Produce = fresh veg and fruit only; Meat & Seafood = all proteins; Dairy & Eggs; Pantry & Dry Goods = spices, grains, sauces, condiments; Canned & Jarred; Bread & Bakery; Frozen; Other = genuine misfits only.

For each meal, also write a clear step-by-step recipe. Steps should be concise — one or two sentences each. Assume a competent home cook.

Return ONLY a JSON object with no markdown formatting:
{
  "week_of": "WEEK_OF_DATE",
  "meals": [
    {
      "name": "Dish Name",
      "description": "One sentence. Note if batch cooking or if marinating overnight.",
      "time": "X minutes active cooking",
      "ingredients": ["ingredient x qty", "ingredient x qty"],
      "recipe": {
        "prep_time": "X minutes",
        "cook_time": "X minutes",
        "steps": ["Step 1...", "Step 2..."],
        "tip": "One optional tip — omit the key entirely if there is nothing worth adding."
      }
    }
  ],
  "snacks": ["snack idea 1", "snack idea 2", "snack idea 3", "snack idea 4", "snack idea 5", "snack idea 6"],
  "grocery_list": {
    "Produce": ["item — qty"],
    "Meat & Seafood": ["item — qty"],
    "Dairy & Eggs": ["item — qty"],
    "Pantry & Dry Goods": ["item — qty"],
    "Canned & Jarred": ["item — qty"],
    "Bread & Bakery": ["item — qty"],
    "Frozen": ["item — qty"],
    "Other": ["item — qty"]
  }
}

Include exactly 3 meals. No day assignments. Each meal must have ingredients with quantities for 2 servings."""

REGENERATE_PROMPT = """Generate a replacement dinner to swap out: {old_name}.

Rules:
- Serves 2 people — scale all ingredient quantities for 2 servings
- Must be interesting enough to order at a restaurant — bold, well-seasoned, not bland
- All ingredients must be available at a standard Market Basket supermarket
- NEVER include: arugula, tuna salad, pickled anything, raw/uncooked onions, feta cheese, or bone-in chicken
- Vegetable sides must be aggressively seasoned — roast, char, glaze, no plain steamed anything
- For proteins, prefer overnight marinades where it makes sense — note this in the description
- When possible, reuse ingredients already in this week's meal plan to minimize waste
- For salads, use salad kits instead of plain lettuce
{disliked_note}
{other_note}

Also write a clear step-by-step recipe. Steps should be concise — one or two sentences each.

Return ONLY a JSON object with no markdown formatting:
{{
  "name": "Dish Name",
  "description": "One sentence describing the dish. Note if marinating overnight.",
  "time": "X minutes active cooking",
  "ingredients": ["ingredient x qty", "ingredient x qty"],
  "recipe": {{
    "prep_time": "X minutes",
    "cook_time": "X minutes",
    "steps": ["Step 1...", "Step 2..."],
    "tip": "One optional tip — omit the key entirely if there is nothing worth adding."
  }}
}}"""


def _pick_cuisine_theme(history: list) -> str:
    recent_themes = [w.get("cuisine_theme") for w in history[-2:] if w.get("cuisine_theme")]
    available = [t for t in CUISINE_THEMES if t not in recent_themes]
    if not available:
        available = CUISINE_THEMES
    return random.choice(available)


_PROTEIN_KEYWORDS = {
    "chicken", "beef", "pork", "lamb", "turkey", "salmon", "shrimp",
    "tuna", "fish", "steak", "sausage", "bacon", "ground", "tilapia",
    "cod", "halibut", "scallop", "crab", "lobster", "duck", "venison",
}

def _fix_grocery_categories(grocery_list: dict) -> dict:
    """Move obviously mislabeled proteins out of Produce into Meat & Seafood."""
    produce = grocery_list.get("Produce", [])
    meat = grocery_list.get("Meat & Seafood", [])
    still_produce = []

    for item in produce:
        if any(kw in item.lower() for kw in _PROTEIN_KEYWORDS):
            log.warning(f"Moving mislabeled protein out of Produce: {item}")
            meat.append(item)
        else:
            still_produce.append(item)

    if still_produce:
        grocery_list["Produce"] = still_produce
    elif "Produce" in grocery_list:
        del grocery_list["Produce"]

    if meat:
        grocery_list["Meat & Seafood"] = meat

    return {k: v for k, v in grocery_list.items() if v}


def _format_recent_meals(history: list) -> str:
    if not history:
        return "None — this is the first week, so feel free to start anywhere."
    lines = []
    for week in history:
        lines.append(f"  Week of {week['week_of']}: {', '.join(week['meals'])}")
    return "\n".join(lines)


def generate_meal_plan():
    """Call Claude to generate a weekly meal plan."""
    now = datetime.now(ET)
    days_until_monday = (7 - now.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 1
    next_monday = now.date() + timedelta(days=days_until_monday)
    week_of = next_monday.strftime("%B %-d, %Y")

    history = load_history()
    cuisine_theme = _pick_cuisine_theme(history)
    recent_meals = _format_recent_meals(history)

    prompt = (
        GENERATION_PROMPT
        .replace("WEEK_OF_DATE", week_of)
        .replace("{cuisine_theme}", cuisine_theme)
        .replace("{recent_meals}", recent_meals)
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    plan = parse_ai_json(message.content[0].text)
    grocery_list = plan.get("grocery_list")
    if not isinstance(grocery_list, dict) or not grocery_list:
        grocery_list = {"Other": rebuild_all_ingredients(plan.get("meals", []))}
    plan["all_ingredients"] = _fix_grocery_categories(grocery_list)
    plan["cuisine_theme"] = cuisine_theme
    save_plan(plan)

    meal_names = [m["name"] for m in plan.get("meals", []) if m["name"] != "—"]
    save_history(week_of, meal_names, cuisine_theme)

    log.info(f"Generated meal plan for week of {week_of} (theme: {cuisine_theme})")
    return plan


def regenerate_meal(meal_index: int, disliked: str):
    """Regenerate a single meal in the current plan."""
    plan = load_plan()
    meals = plan.get("meals", [])

    if meal_index is None or meal_index >= len(meals):
        raise ValueError("Invalid meal index")

    meal = meals[meal_index]
    other_meals = [m["name"] for i, m in enumerate(meals) if i != meal_index and m["name"] != "—"]

    disliked_note = f"The user dislikes: {disliked}. Avoid these entirely." if disliked else ""
    other_note = f"Already on the plan this week (don't repeat): {', '.join(other_meals)}." if other_meals else ""

    prompt = REGENERATE_PROMPT.format(
        old_name=meal["name"],
        disliked_note=disliked_note,
        other_note=other_note,
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    new_meal = parse_ai_json(message.content[0].text)

    meals[meal_index] = new_meal
    plan["meals"] = meals
    grocery_list = plan.get("all_ingredients")
    if not isinstance(grocery_list, dict) or not grocery_list:
        grocery_list = {"Other": rebuild_all_ingredients(meals)}
    plan["all_ingredients"] = _fix_grocery_categories(grocery_list)
    save_plan(plan)

    return new_meal
