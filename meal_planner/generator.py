import logging
import random
from datetime import datetime, timedelta

import anthropic

from .config import ANTHROPIC_API_KEY, ET
from .models import load_history, load_plan, parse_ai_json, rebuild_all_ingredients, save_history, save_plan

RECIPE_PROMPT = """Write a clear, practical recipe for "{name}" for 2 people.

Ingredients already decided:
{ingredients}

Return ONLY a JSON object with no markdown formatting:
{{
  "prep_time": "X minutes",
  "cook_time": "X minutes",
  "steps": [
    "Step text...",
    "Step text..."
  ],
  "tip": "One optional tip (marinating timing, make-ahead note, etc.). Omit the key if there is no useful tip."
}}

Steps should be clear and numbered in sequence. Each step is one sentence or two at most. Assume a competent home cook."""

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

GENERATION_PROMPT = """Generate a weekly meal plan (Monday–Sunday dinners) for 2 people.

**This week's cuisine theme: {cuisine_theme}**
Lean into this style for most meals — mix of proteins and preparations within the theme. A couple of meals can diverge if they fit naturally, but the week should feel cohesive and intentional around this theme.

**Meal Structure:**
- Each dinner = 1 protein + 2 vegetable sides

**Dislikes (never include):**
- Arugula, Tuna salad, Pickled anything, Raw/uncooked onions, Feta cheese
- Bone-in chicken — always use boneless (thighs or breasts)

**Grocery Strategy:**
- Minimize total groceries for this week — reuse ingredients across meals within the week
- Use full pack sizes (e.g. if chicken thighs come in a 6-pack, plan 2-3 chicken meals to use them all)
- For salads, use salad kits instead of plain lettuce

**Recipe Style:**
- Flavorful and satisfying but not technically complicated
- Vary spice profiles so reused ingredients feel like different meals
- Emphasize bold, well-seasoned flavors
- Vegetable sides must be flavorful — roast, char, glaze, or season them well (no plain steamed veggies)
- Examples of good sides: garlic-parmesan roasted broccoli, honey-glazed carrots, charred lemon asparagus, cajun corn, sesame green beans
- For proteins, prefer overnight marinades where it makes sense (e.g. chicken thighs, skirt steak, pork) — note this in the description so the cook knows to prep the night before

**Do not repeat any of these recently served meals:**
{recent_meals}

Return ONLY a JSON object with no markdown formatting:
{
  "week_of": "WEEK_OF_DATE",
  "meals": [
    {
      "day": "Monday",
      "name": "Dish Name",
      "description": "One sentence describing the dish. Serves 2.",
      "ingredients": ["ingredient x qty", "ingredient x qty"]
    }
  ],
  "snacks": ["snack idea 1", "snack idea 2", "snack idea 3"]
}

Include all 7 days (Monday–Sunday). Each meal must have ingredients with quantities for 2 servings."""

REGENERATE_PROMPT = """Generate a replacement dinner for {day} to swap out: {old_name}.

Rules:
- Serves 2 people — scale all ingredient quantities for 2 servings
- Flavorful and satisfying but not technically complicated
- All ingredients must be available at a standard Market Basket supermarket
- NEVER include: arugula, tuna salad, pickled anything, raw/uncooked onions, feta cheese, or bone-in chicken
- Vegetable sides must be flavorful — roast, char, glaze, or season them (no plain steamed veggies)
- For proteins, prefer overnight marinades where it makes sense (e.g. chicken thighs, skirt steak, pork) — note this in the description so the cook knows to prep the night before
- When possible, reuse ingredients already in this week's meal plan to minimize waste within the week
- Use full grocery store pack sizes across the week (e.g. if chicken thighs come 6 per pack, plan to use all 6 across meals)
- For salads, use salad kits instead of plain lettuce
{disliked_note}
{other_note}

Return ONLY a JSON object with no markdown formatting:
{{
  "day": "{day}",
  "name": "Dish Name",
  "description": "One sentence describing the dish and how it's cooked. Serves 2.",
  "ingredients": ["ingredient x qty", "ingredient x qty"]
}}"""


def _pick_cuisine_theme(history: list) -> str:
    """Pick a cuisine theme, avoiding the last 2 weeks' themes if stored."""
    recent_themes = [w.get("cuisine_theme") for w in history[-2:] if w.get("cuisine_theme")]
    available = [t for t in CUISINE_THEMES if t not in recent_themes]
    if not available:
        available = CUISINE_THEMES
    return random.choice(available)


def _format_recent_meals(history: list) -> str:
    if not history:
        return "None — this is the first week, so feel free to start anywhere."
    lines = []
    for week in history:
        lines.append(f"  Week of {week['week_of']}: {', '.join(week['meals'])}")
    return "\n".join(lines)


def generate_meal_plan():
    """Call Claude to generate a full weekly meal plan."""
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
    plan["all_ingredients"] = rebuild_all_ingredients(plan.get("meals", []))
    plan["cuisine_theme"] = cuisine_theme
    save_plan(plan)

    meal_names = [m["name"] for m in plan.get("meals", []) if m["name"] != "—"]
    save_history(week_of, meal_names, cuisine_theme)

    log.info(f"Generated meal plan for week of {week_of} (theme: {cuisine_theme})")
    return plan


def generate_recipe(day: str) -> dict:
    """Generate and cache a recipe for the given day's meal."""
    plan = load_plan()
    meals = plan.get("meals", [])

    meal = next((m for m in meals if m["day"].lower() == day.lower()), None)
    if not meal or meal["name"] == "—":
        raise ValueError(f"No meal found for {day}")

    if meal.get("recipe"):
        return meal["recipe"]

    ingredients_text = "\n".join(f"- {i}" for i in meal.get("ingredients", []))
    prompt = RECIPE_PROMPT.format(name=meal["name"], ingredients=ingredients_text)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    recipe = parse_ai_json(message.content[0].text)
    meal["recipe"] = recipe
    save_plan(plan)
    return recipe


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
        day=meal["day"],
        old_name=meal["name"],
        disliked_note=disliked_note,
        other_note=other_note,
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    new_meal = parse_ai_json(message.content[0].text)

    new_meal.pop("recipe", None)
    meals[meal_index] = new_meal
    plan["meals"] = meals
    plan["all_ingredients"] = rebuild_all_ingredients(meals)
    save_plan(plan)

    return new_meal
