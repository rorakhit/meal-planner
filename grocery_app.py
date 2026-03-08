"""
grocery_app.py — Weekly Meal Plan & Grocery List Builder

Run with:
    pip install flask --break-system-packages
    python3 grocery_app.py

Then open http://localhost:8001 in your browser.

The Sunday meal planner saves this week's plan to:
    ~/Documents/Claude/MealPlanner/current_meal_plan.json
This app reads from that file automatically.
"""

import json
from pathlib import Path
from flask import Flask, render_template_string, jsonify, request

app = Flask(__name__)

MEAL_PLAN_FILE = Path.home() / "Documents/Claude/MealPlanner/current_meal_plan.json"

PLACEHOLDER = {
    "week_of": "Not yet generated",
    "meals": [
        {"day": d, "name": "—", "description": "Check back after Sunday's meal plan runs.", "ingredients": []}
        for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    ],
    "snacks": ["Check back after Sunday's meal plan runs."],
    "all_ingredients": []
}

def load_plan():
    if MEAL_PLAN_FILE.exists():
        with open(MEAL_PLAN_FILE) as f:
            return json.load(f)
    return PLACEHOLDER


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
      padding: 28px 36px;
      color: white;
    }
    .header p { color: #94a3b8; font-size: 13px; letter-spacing: .08em; text-transform: uppercase; margin-bottom: 4px; }
    .header h1 { font-size: 26px; font-weight: 700; }
    .header .week { color: #64a7d8; font-size: 15px; margin-top: 6px; }

    .container { max-width: 900px; margin: 32px auto; padding: 0 20px 60px; }

    h2 { font-size: 17px; font-weight: 700; color: #0f172a; margin: 32px 0 14px; }

    /* Meal cards */
    .meals-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; }
    .meal-card {
      background: white;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      padding: 16px;
      transition: box-shadow .15s;
    }
    .meal-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,.08); }
    .meal-card .day { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: #64748b; margin-bottom: 6px; }
    .meal-card .name { font-size: 15px; font-weight: 700; color: #0f172a; margin-bottom: 6px; }
    .meal-card .desc { font-size: 13px; color: #475569; line-height: 1.5; }

    /* Snacks */
    .snacks { background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px 20px; }
    .snack-item { font-size: 14px; color: #475569; padding: 5px 0; border-bottom: 1px solid #f1f5f9; }
    .snack-item:last-child { border-bottom: none; }

    /* Grocery section */
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
      margin-top: 14px;
      width: 100%;
      padding: 10px;
      background: #2563eb;
      color: white;
      border: none;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      transition: background .15s;
    }
    .btn-copy:hover { background: #1d4ed8; }
    .btn-copy.copied { background: #16a34a; }

    .btn-clear { background: none; border: 1px solid #e2e8f0; color: #64748b; padding: 8px 14px; border-radius: 8px; font-size: 12px; cursor: pointer; margin-top: 10px; width: 100%; }
    .btn-clear:hover { background: #f8fafc; }

    .badge { display: inline-block; background: #eff6ff; color: #2563eb; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 9999px; margin-left: 6px; }
  </style>
</head>
<body>

<div class="header">
  <p>Weekly Meal Planner</p>
  <h1>🍽️ Dinners This Week</h1>
  <div class="week">Week of {{ week_of }}</div>
</div>

<div class="container">

  <h2>Dinners</h2>
  <div class="meals-grid">
    {% for meal in meals %}
    <div class="meal-card">
      <div class="day">{{ meal.day }}</div>
      <div class="name">{{ meal.name }}</div>
      <div class="desc">{{ meal.description }}</div>
    </div>
    {% endfor %}
  </div>

  <h2>Snack Ideas</h2>
  <div class="snacks">
    {% for snack in snacks %}
    <div class="snack-item">{{ snack }}</div>
    {% endfor %}
  </div>

  <h2>Grocery List Builder</h2>
  <div class="grocery-wrapper">

    <div class="panel">
      <h3>What do you already have? <span class="badge" id="have-count">0</span></h3>
      <div id="ingredient-list">
        {% for item in all_ingredients %}
        <div class="ingredient-item" id="row-{{ loop.index }}" onclick="toggle('{{ item|replace("'","\\'")|replace('"','\\"') }}', {{ loop.index }})">
          <input type="checkbox" id="chk-{{ loop.index }}" onclick="event.stopPropagation(); toggle('{{ item|replace("'","\\'")|replace('"','\\"') }}', {{ loop.index }})">
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

<script>
  const STORAGE_KEY = 'groceries_checked_{{ week_of|replace(" ","_") }}';
  let checked = new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'));

  function restoreState() {
    checked.forEach(item => {
      // Find matching checkbox by label text
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
    const haveCount = checked.size;
    const needCount = total - haveCount;
    document.getElementById('have-count').textContent = haveCount;
    document.getElementById('need-count').textContent = needCount;
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
      if (el.style.display !== 'none') {
        items.push(el.textContent.trim());
      }
    });
    const text = items.join('\\n');
    navigator.clipboard.writeText(text).then(() => {
      const btn = document.getElementById('copy-btn');
      btn.textContent = '✓ Copied!';
      btn.classList.add('copied');
      setTimeout(() => { btn.textContent = 'Copy grocery list'; btn.classList.remove('copied'); }, 2000);
    });
  }

  restoreState();
</script>

</body>
</html>"""


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


@app.route("/plan")
def get_plan():
    return jsonify(load_plan())


if __name__ == "__main__":
    print("\n🍽️  Grocery List App")
    print("   Open http://localhost:8001 in your browser\n")
    app.run(port=8001, debug=False)
