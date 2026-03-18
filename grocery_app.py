"""
grocery_app.py — Weekly Meal Plan & Grocery List Builder

Runs on Railway with APScheduler for automatic Sunday meal generation
and Resend for email delivery.

Env vars needed:
    ANTHROPIC_API_KEY   — Claude API key for meal generation
    RESEND_API_KEY      — Resend API key for email delivery
    NOTIFY_EMAIL        — Email to send meal plans to
    EMAIL_FROM          — (optional) Sender address, defaults to onboarding@resend.dev
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import resend
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template_string, request

load_dotenv(Path(__file__).parent / ".env")

log = logging.getLogger("meal-planner")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = Flask(__name__)

ET = ZoneInfo("America/New_York")

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
resend.api_key    = os.environ["RESEND_API_KEY"]
NOTIFY_EMAIL      = os.environ["NOTIFY_EMAIL"]
EMAIL_FROM        = os.environ.get("EMAIL_FROM", "Meal Planner <onboarding@resend.dev>")

BASE_DIR       = Path(__file__).parent
MEAL_PLAN_FILE = BASE_DIR / "current_meal_plan.json"

PLACEHOLDER = {
    "week_of": "Not yet generated",
    "meals": [
        {
            "day": d,
            "name": "—",
            "description": "Check back after Sunday's meal plan runs.",
            "ingredients": [],
        }
        for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    ],
    "snacks": ["Check back after Sunday's meal plan runs."],
    "all_ingredients": [],
}

GENERATION_PROMPT = """Generate a weekly meal plan (Monday–Sunday dinners) for 2 people.

**Meal Structure:**
- Each dinner = 1 protein + 2 vegetable sides

**Dislikes (never include):**
- Arugula, Tuna salad, Pickled anything, Raw/uncooked onions, Feta cheese
- Bone-in chicken — always use boneless (thighs or breasts)

**Grocery Strategy:**
- Minimize total groceries — reuse ingredients across meals throughout the week
- Use full pack sizes (e.g. if chicken thighs come in a 6-pack, plan 2-3 chicken meals to use them all)
- For salads, use salad kits instead of plain lettuce

**Recipe Style:**
- Flavorful and satisfying but not technically complicated
- Vary spice profiles so reused ingredients feel like different meals
- Emphasize bold, well-seasoned flavors
- Vegetable sides must be flavorful — roast, char, glaze, or season them well (no plain steamed veggies)
- Examples of good sides: garlic-parmesan roasted broccoli, honey-glazed carrots, charred lemon asparagus, cajun corn, sesame green beans

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


# ─────────────────────────────────────────────
# DATA HELPERS
# ─────────────────────────────────────────────

def load_plan():
    if MEAL_PLAN_FILE.exists():
        with open(MEAL_PLAN_FILE) as f:
            return json.load(f)
    return PLACEHOLDER


def save_plan(plan):
    MEAL_PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MEAL_PLAN_FILE, "w") as f:
        json.dump(plan, f, indent=2)


def rebuild_all_ingredients(meals):
    """Deduplicate and consolidate ingredients across all meals."""
    seen = {}
    for meal in meals:
        for ing in meal.get("ingredients", []):
            key = ing.lower().split("x")[0].split("×")[0].strip()
            if key not in seen:
                seen[key] = ing
    return list(seen.values())


def _send_email(subject: str, html_body: str):
    """Send email via Resend HTTP API."""
    resend.Emails.send({
        "from":    EMAIL_FROM,
        "to":      [NOTIFY_EMAIL],
        "subject": subject,
        "html":    html_body,
    })


def parse_ai_json(raw: str) -> dict:
    """Strip markdown fences from AI response and parse JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


# ─────────────────────────────────────────────
# MEAL GENERATION
# ─────────────────────────────────────────────

def generate_meal_plan():
    """Call Claude to generate a full weekly meal plan."""
    now = datetime.now(ET)
    # Week starts next Monday
    import calendar
    days_until_monday = (7 - now.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 1  # if it's Monday, plan for tomorrow
    from datetime import timedelta
    next_monday = now.date() + timedelta(days=days_until_monday)
    week_of = next_monday.strftime("%B %-d, %Y")

    prompt = GENERATION_PROMPT.replace("WEEK_OF_DATE", week_of)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    plan = parse_ai_json(message.content[0].text)
    plan["all_ingredients"] = rebuild_all_ingredients(plan.get("meals", []))
    save_plan(plan)
    log.info(f"Generated meal plan for week of {week_of}")
    return plan


DAY_ABBR = {
    "Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed",
    "Thursday": "Thu", "Friday": "Fri", "Saturday": "Sat", "Sunday": "Sun",
}


def build_email_html(plan: dict) -> str:
    """Build a styled HTML email from a meal plan."""
    week_of     = plan.get("week_of", "this week")
    meals       = plan.get("meals", [])
    snacks      = plan.get("snacks", [])
    ingredients = plan.get("all_ingredients", [])

    meal_rows = ""
    for meal in meals:
        abbr = DAY_ABBR.get(meal.get("day", ""), meal.get("day", "")[:3])
        meal_rows += f"""
        <div style="display:flex;gap:14px;margin-bottom:16px;align-items:flex-start">
          <div style="min-width:40px;height:36px;background:#eff6ff;border-radius:8px;
                      display:flex;align-items:center;justify-content:center;
                      font-size:11px;font-weight:700;color:#2563eb;
                      text-transform:uppercase;flex-shrink:0">{abbr}</div>
          <div style="flex:1">
            <p style="font-size:15px;font-weight:700;color:#0f172a;margin:0 0 3px">{meal.get('name', '')}</p>
            <p style="font-size:13px;color:#64748b;margin:0;line-height:1.5">{meal.get('description', '')}</p>
          </div>
        </div>"""

    snack_pills = "".join(
        f'<span style="background:#f1f5f9;border-radius:20px;padding:6px 14px;'
        f'font-size:13px;color:#475569;display:inline-block;margin:0 6px 6px 0">{s}</span>'
        for s in snacks
    )

    grocery_items = "".join(
        f'<p style="font-size:13px;color:#374151;padding:3px 0;margin:0">'
        f'<span style="color:#2563eb;font-weight:700">· </span>{i}</p>'
        for i in ingredients
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f8fafc;color:#1e293b;margin:0;padding:0">
<div style="max-width:620px;margin:0 auto;background:white">
  <div style="background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%);padding:32px 36px;color:white">
    <p style="color:#94a3b8;font-size:12px;letter-spacing:.08em;text-transform:uppercase;margin:0 0 4px">Weekly Meal Planner</p>
    <h1 style="font-size:24px;font-weight:700;margin:0 0 6px;color:white">🍽️ Dinners This Week</h1>
    <p style="color:#64a7d8;font-size:14px;margin:0">Week of {week_of}</p>
  </div>
  <div style="padding:28px 36px">
    <h2 style="font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#64748b;margin:0 0 14px;padding-bottom:8px;border-bottom:1px solid #e2e8f0">This Week's Dinners</h2>
    {meal_rows}
    <h2 style="font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#64748b;margin:28px 0 14px;padding-bottom:8px;border-bottom:1px solid #e2e8f0">Snack Ideas</h2>
    <div style="margin-bottom:8px">{snack_pills}</div>
    <h2 style="font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#64748b;margin:28px 0 14px;padding-bottom:8px;border-bottom:1px solid #e2e8f0">Grocery List</h2>
    <div style="background:#f8fafc;border-radius:12px;padding:20px 24px">{grocery_items}</div>
  </div>
  <div style="padding:20px 36px;border-top:1px solid #e2e8f0">
    <p style="font-size:12px;color:#94a3b8;margin:0">Generated by Meal Planner Bot</p>
  </div>
</div>
</body></html>"""


# ─────────────────────────────────────────────
# SCHEDULED JOBS
# ─────────────────────────────────────────────

scheduler = BackgroundScheduler(timezone=ET)


@scheduler.scheduled_job("cron", day_of_week="sun", hour=9, minute=0)
def weekly_meal_plan_job():
    """Generate a meal plan and email it every Sunday at 9am ET."""
    try:
        plan = generate_meal_plan()
        html = build_email_html(plan)
        week_of = plan.get("week_of", "this week")
        _send_email(f"🍽️ Meal Plan – Week of {week_of}", html)
        log.info(f"Meal plan email sent for week of {week_of}")
    except Exception as e:
        log.error(f"weekly_meal_plan_job failed: {e}", exc_info=True)


scheduler.start()


# ─────────────────────────────────────────────
# WEB UI — HTML TEMPLATE
# ─────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Meal Plan & Grocery List</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1e293b; }

    .header {
      background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
      padding: 28px 36px; color: white;
    }
    .header p { color: #94a3b8; font-size: 13px; letter-spacing: .08em; text-transform: uppercase; margin-bottom: 4px; }
    .header h1 { font-size: 26px; font-weight: 700; }
    .header .week { color: #64a7d8; font-size: 15px; margin-top: 6px; }

    .container { max-width: 900px; margin: 32px auto; padding: 0 20px 60px; }
    h2 { font-size: 17px; font-weight: 700; color: #0f172a; margin: 32px 0 14px; }

    .meals-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; }
    .meal-card {
      background: white; border: 1px solid #e2e8f0; border-radius: 12px;
      padding: 16px; transition: box-shadow .15s; position: relative;
    }
    .meal-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,.08); }
    .meal-card .day { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: #64748b; margin-bottom: 6px; }
    .meal-card .name { font-size: 15px; font-weight: 700; color: #0f172a; margin-bottom: 6px; }
    .meal-card .desc { font-size: 13px; color: #475569; line-height: 1.5; }

    .btn-regen {
      margin-top: 12px; width: 100%; padding: 7px 10px;
      background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 7px;
      font-size: 12px; font-weight: 600; color: #475569;
      cursor: pointer; transition: background .15s;
      display: flex; align-items: center; justify-content: center; gap: 5px;
    }
    .btn-regen:hover { background: #e2e8f0; color: #0f172a; }
    .btn-regen.loading { opacity: .6; pointer-events: none; }

    .regen-form { margin-top: 10px; display: none; }
    .regen-form.open { display: block; }
    .regen-form input {
      width: 100%; padding: 8px 10px; border: 1px solid #cbd5e1; border-radius: 7px;
      font-size: 12px; color: #1e293b; outline: none;
    }
    .regen-form input:focus { border-color: #2563eb; }
    .regen-form-actions { display: flex; gap: 6px; margin-top: 7px; }
    .btn-submit-regen {
      flex: 1; padding: 7px; background: #2563eb; color: white;
      border: none; border-radius: 7px; font-size: 12px; font-weight: 600; cursor: pointer;
    }
    .btn-submit-regen:hover { background: #1d4ed8; }
    .btn-cancel-regen {
      padding: 7px 12px; background: none; border: 1px solid #e2e8f0;
      border-radius: 7px; font-size: 12px; color: #64748b; cursor: pointer;
    }

    .snacks { background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px 20px; }
    .snack-item { font-size: 14px; color: #475569; padding: 5px 0; border-bottom: 1px solid #f1f5f9; }
    .snack-item:last-child { border-bottom: none; }

    .grocery-wrapper { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    @media (max-width: 600px) { .grocery-wrapper { grid-template-columns: 1fr; } }

    .panel { background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; }
    .panel h3 { font-size: 14px; font-weight: 700; color: #0f172a; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid #f1f5f9; }

    .ingredient-item { display: flex; align-items: center; gap: 10px; padding: 7px 0; border-bottom: 1px solid #f8fafc; cursor: pointer; }
    .ingredient-item:last-child { border-bottom: none; }
    .ingredient-item input[type=checkbox] { width: 16px; height: 16px; cursor: pointer; accent-color: #2563eb; flex-shrink: 0; }
    .ingredient-item label { font-size: 13px; color: #374151; cursor: pointer; flex: 1; }
    .ingredient-item.checked label { text-decoration: line-through; color: #9ca3af; }

    .need-list { min-height: 60px; }
    .need-item { font-size: 13px; color: #1e293b; padding: 7px 0; border-bottom: 1px solid #f8fafc; display: flex; align-items: center; gap: 8px; }
    .need-item:last-child { border-bottom: none; }
    .need-item::before { content: '•'; color: #2563eb; font-weight: 700; }
    .empty-msg { font-size: 13px; color: #94a3b8; padding: 12px 0; }

    .btn-copy {
      margin-top: 14px; width: 100%; padding: 10px;
      background: #2563eb; color: white; border: none;
      border-radius: 8px; font-size: 13px; font-weight: 600;
      cursor: pointer; transition: background .15s;
    }
    .btn-copy:hover { background: #1d4ed8; }
    .btn-copy.copied { background: #16a34a; }

    .btn-clear { background: none; border: 1px solid #e2e8f0; color: #64748b; padding: 8px 14px; border-radius: 8px; font-size: 12px; cursor: pointer; margin-top: 10px; width: 100%; }
    .btn-clear:hover { background: #f8fafc; }

    .badge { display: inline-block; background: #eff6ff; color: #2563eb; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 9999px; margin-left: 6px; }

    .toast {
      position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
      background: #0f172a; color: white; padding: 10px 20px; border-radius: 9999px;
      font-size: 13px; font-weight: 600; opacity: 0; transition: opacity .2s;
      pointer-events: none; z-index: 999;
    }
    .toast.show { opacity: 1; }

    .btn-actions { display: flex; gap: 10px; margin-top: 14px; }
    .btn-print, .btn-generate {
      padding: 8px 16px;
      background: rgba(255,255,255,.15); color: white; border: 1px solid rgba(255,255,255,.25);
      border-radius: 8px; font-size: 13px; font-weight: 600;
      cursor: pointer; transition: background .15s;
    }
    .btn-print:hover, .btn-generate:hover { background: rgba(255,255,255,.25); }
    .btn-generate.loading { opacity: .6; pointer-events: none; }

    @media print {
      body { background: white; }
      .header { background: none !important; color: #0f172a; padding: 20px 0; }
      .header p { color: #64748b; }
      .header h1 { color: #0f172a; }
      .header .week { color: #475569; }
      .btn-print, .btn-generate, .btn-regen, .regen-form, .grocery-wrapper,
      .grocery-heading, .toast, .btn-actions { display: none !important; }
      .container { margin: 0; padding: 0; }
      .meals-grid { grid-template-columns: 1fr 1fr; gap: 10px; }
      .meal-card { border: 1px solid #ccc; box-shadow: none; break-inside: avoid; }
      .snacks { border: 1px solid #ccc; }
      h2 { margin-top: 20px; }
    }
  </style>
</head>
<body>

<div class="header">
  <p>Weekly Meal Planner</p>
  <h1>🍽️ Dinners This Week</h1>
  <div class="week">Week of {{ week_of }}</div>
  <div class="btn-actions">
    <button class="btn-print" onclick="window.print()">Print Meal Plan</button>
    <button class="btn-generate" id="btn-generate" onclick="generateNew()">↺ Generate New Plan</button>
  </div>
</div>

<div class="container">

  <h2>Dinners</h2>
  <div class="meals-grid" id="meals-grid">
    {% for meal in meals %}
    <div class="meal-card" id="card-{{ loop.index0 }}">
      <div class="day">{{ meal.day }}</div>
      <div class="name">{{ meal.name }}</div>
      <div class="desc">{{ meal.description }}</div>
      <button class="btn-regen" onclick="toggleRegenForm({{ loop.index0 }})">
        ↺ Regenerate
      </button>
      <div class="regen-form" id="regen-form-{{ loop.index0 }}">
        <input type="text" id="regen-input-{{ loop.index0 }}"
               placeholder="What don't you like? e.g. salmon, avocado"
               onkeydown="if(event.key==='Enter') submitRegen({{ loop.index0 }})">
        <div class="regen-form-actions">
          <button class="btn-submit-regen" onclick="submitRegen({{ loop.index0 }})">Regenerate</button>
          <button class="btn-cancel-regen" onclick="toggleRegenForm({{ loop.index0 }})">Cancel</button>
        </div>
      </div>
    </div>
    {% endfor %}
  </div>

  <h2>Snack Ideas</h2>
  <div class="snacks">
    {% for snack in snacks %}
    <div class="snack-item">{{ snack }}</div>
    {% endfor %}
  </div>

  <h2 class="grocery-heading">Grocery List Builder</h2>
  <div class="grocery-wrapper">
    <div class="panel">
      <h3>What do you already have? <span class="badge" id="have-count">0</span></h3>
      <div id="ingredient-list">
        {% for item in all_ingredients %}
        <div class="ingredient-item" id="row-{{ loop.index }}"
             onclick="toggle('{{ item|replace("'","\\'")|replace('"','\\"') }}', {{ loop.index }})">
          <input type="checkbox" id="chk-{{ loop.index }}"
                 onclick="event.stopPropagation(); toggle('{{ item|replace("'","\\'")|replace('"','\\"') }}', {{ loop.index }})">
          <label for="chk-{{ loop.index }}">{{ item }}</label>
        </div>
        {% endfor %}
        {% if not all_ingredients %}
        <p class="empty-msg">No meal plan loaded yet — check back after Sunday.</p>
        {% endif %}
      </div>
      <button class="btn-clear" onclick="clearAll()">Clear all</button>
    </div>

    <div class="panel">
      <h3>What you need to buy <span class="badge" id="need-count">{{ all_ingredients|length }}</span></h3>
      <div class="need-list" id="need-list">
        {% for item in all_ingredients %}
        <div class="need-item" id="need-{{ loop.index }}">{{ item }}</div>
        {% endfor %}
        {% if not all_ingredients %}
        <p class="empty-msg">Your grocery list will appear here.</p>
        {% endif %}
      </div>
      <button class="btn-copy" id="copy-btn" onclick="copyList()">Copy grocery list</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
  const STORAGE_KEY = 'groceries_checked_{{ week_of|replace(" ","_") }}';
  let checked = new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'));

  function showToast(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2500);
  }

  function restoreState() {
    checked.forEach(item => {
      document.querySelectorAll('.ingredient-item label').forEach(label => {
        if (label.textContent.trim() === item) {
          const row = label.closest('.ingredient-item');
          const idx = row.id.replace('row-', '');
          row.classList.add('checked');
          document.getElementById('chk-' + idx).checked = true;
          const needEl = document.getElementById('need-' + idx);
          if (needEl) needEl.style.display = 'none';
        }
      });
    });
    updateCounts();
  }

  function toggle(item, idx) {
    const row = document.getElementById('row-' + idx);
    const chk = document.getElementById('chk-' + idx);
    const needEl = document.getElementById('need-' + idx);
    if (checked.has(item)) {
      checked.delete(item);
      row.classList.remove('checked');
      chk.checked = false;
      if (needEl) needEl.style.display = '';
    } else {
      checked.add(item);
      row.classList.add('checked');
      chk.checked = true;
      if (needEl) needEl.style.display = 'none';
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...checked]));
    updateCounts();
  }

  function updateCounts() {
    const total = document.querySelectorAll('.ingredient-item').length;
    document.getElementById('have-count').textContent = checked.size;
    document.getElementById('need-count').textContent = total - checked.size;
  }

  function clearAll() {
    checked.clear();
    localStorage.setItem(STORAGE_KEY, '[]');
    document.querySelectorAll('.ingredient-item').forEach(row => {
      row.classList.remove('checked');
      row.querySelector('input').checked = false;
    });
    document.querySelectorAll('.need-item').forEach(el => el.style.display = '');
    updateCounts();
  }

  function copyList() {
    const items = [];
    document.querySelectorAll('.need-item').forEach(el => {
      if (el.style.display !== 'none') items.push(el.textContent.trim());
    });
    navigator.clipboard.writeText(items.join('\\n')).then(() => {
      const btn = document.getElementById('copy-btn');
      btn.textContent = '✓ Copied!';
      btn.classList.add('copied');
      setTimeout(() => { btn.textContent = 'Copy grocery list'; btn.classList.remove('copied'); }, 2000);
    });
  }

  function toggleRegenForm(idx) {
    const form = document.getElementById('regen-form-' + idx);
    form.classList.toggle('open');
    if (form.classList.contains('open')) {
      document.getElementById('regen-input-' + idx).focus();
    }
  }

  async function submitRegen(idx) {
    const input = document.getElementById('regen-input-' + idx);
    const disliked = input.value.trim();
    const btn = document.querySelector('#card-' + idx + ' .btn-regen');

    btn.textContent = '↺ Regenerating…';
    btn.classList.add('loading');

    try {
      const res = await fetch('/regenerate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ meal_index: idx, disliked: disliked })
      });
      const data = await res.json();

      if (data.error) { showToast('Error: ' + data.error); return; }

      document.querySelector('#card-' + idx + ' .name').textContent = data.name;
      document.querySelector('#card-' + idx + ' .desc').textContent = data.description;
      document.getElementById('regen-form-' + idx).classList.remove('open');
      input.value = '';
      showToast('✓ ' + data.day + ' updated!');

      setTimeout(() => location.reload(), 1200);

    } catch (e) {
      showToast('Something went wrong — try again');
    } finally {
      btn.textContent = '↺ Regenerate';
      btn.classList.remove('loading');
    }
  }

  async function generateNew() {
    const btn = document.getElementById('btn-generate');
    btn.textContent = '↺ Generating…';
    btn.classList.add('loading');

    try {
      const res = await fetch('/generate', { method: 'POST' });
      const data = await res.json();
      if (data.error) { showToast('Error: ' + data.error); return; }
      showToast('✓ New meal plan generated!');
      setTimeout(() => location.reload(), 1000);
    } catch (e) {
      showToast('Something went wrong — try again');
    } finally {
      btn.textContent = '↺ Generate New Plan';
      btn.classList.remove('loading');
    }
  }

  restoreState();
</script>
</body>
</html>"""


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.route("/")
def index():
    data = load_plan()
    return render_template_string(
        HTML,
        week_of=data.get("week_of", "—"),
        meals=data.get("meals", []),
        snacks=data.get("snacks", []),
        all_ingredients=data.get("all_ingredients", []),
    )


@app.route("/generate", methods=["POST"])
def generate():
    """Manually trigger a new meal plan generation."""
    try:
        plan = generate_meal_plan()
        return jsonify({"status": "ok", "week_of": plan.get("week_of")})
    except Exception as e:
        log.error(f"generate failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/regenerate", methods=["POST"])
def regenerate():
    body = request.get_json()
    meal_index = body.get("meal_index")
    disliked = body.get("disliked", "").strip()

    plan = load_plan()
    meals = plan.get("meals", [])

    if meal_index is None or meal_index >= len(meals):
        return jsonify({"error": "Invalid meal index"}), 400

    meal = meals[meal_index]
    other_meals = [m["name"] for i, m in enumerate(meals) if i != meal_index and m["name"] != "—"]

    disliked_note = f"The user dislikes: {disliked}. Avoid these entirely." if disliked else ""
    other_note = f"Already on the plan this week (don't repeat): {', '.join(other_meals)}." if other_meals else ""

    prompt = f"""Generate a replacement dinner for {meal['day']} to swap out: {meal['name']}.

Rules:
- Serves 2 people — scale all ingredient quantities for 2 servings
- Flavorful and satisfying but not technically complicated
- All ingredients must be available at a standard Market Basket supermarket
- NEVER include: arugula, tuna salad, pickled anything, raw/uncooked onions, feta cheese, or bone-in chicken
- Vegetable sides must be flavorful — roast, char, glaze, or season them (no plain steamed veggies)
- When possible, reuse ingredients already in this week's meal plan to minimize waste
- Use full grocery store pack sizes across the week (e.g. if chicken thighs come 6 per pack, plan to use all 6 across meals)
- For salads, use salad kits instead of plain lettuce
{disliked_note}
{other_note}

Return ONLY a JSON object with no markdown formatting:
{{
  "day": "{meal['day']}",
  "name": "Dish Name",
  "description": "One sentence describing the dish and how it's cooked. Serves 2.",
  "ingredients": ["ingredient x qty", "ingredient x qty"]
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    new_meal = parse_ai_json(message.content[0].text)

    meals[meal_index] = new_meal
    plan["meals"] = meals
    plan["all_ingredients"] = rebuild_all_ingredients(meals)
    save_plan(plan)

    return jsonify(new_meal)


@app.route("/plan")
def get_plan():
    return jsonify(load_plan())


@app.route("/health")
def health():
    return jsonify({"status": "ok", "jobs": [str(j) for j in scheduler.get_jobs()]})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    app.run(host="0.0.0.0", port=port, debug=False)
