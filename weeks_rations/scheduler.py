import logging

from apscheduler.schedulers.background import BackgroundScheduler

from .config import ET
from .email import build_email_html, send_email
from .generator import generate_meal_plan

log = logging.getLogger("meal-planner")

scheduler = BackgroundScheduler(timezone=ET)


@scheduler.scheduled_job("cron", day_of_week="sun", hour=9, minute=0)
def weekly_meal_plan_job():
    """Generate a meal plan and email it every Sunday at 9am ET."""
    try:
        plan = generate_meal_plan()
        html = build_email_html(plan)
        week_of = plan.get("week_of", "this week")
        send_email(f"🍽️ Meal Plan – Week of {week_of}", html)
        log.info(f"Meal plan email sent for week of {week_of}")
    except Exception as e:
        log.error(f"weekly_meal_plan_job failed: {e}", exc_info=True)
