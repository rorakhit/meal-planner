import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
NOTIFY_EMAIL = os.environ["NOTIFY_EMAIL"]
EMAIL_FROM = os.environ.get("EMAIL_FROM", "Meal Planner <onboarding@resend.dev>")

BASE_DIR = Path(__file__).parent.parent
MEAL_PLAN_FILE = BASE_DIR / "current_meal_plan.json"
MEAL_HISTORY_FILE = BASE_DIR / "meal_history.json"

ET = ZoneInfo("America/New_York")

PLACEHOLDER = {
    "week_of": "Not yet generated",
    "meals": [
        {"name": "—", "description": "Check back after Sunday's meal plan runs.", "ingredients": [], "time": ""}
        for _ in range(3)
    ],
    "snacks": ["Check back after Sunday's meal plan runs."],
    "all_ingredients": {},
}
