# meal-planner

A weekly meal planning system with two parts:

1. **Sunday scheduled task** — runs every Sunday at 9am via Claude Cowork, checks the [Market Basket weekly flyer](https://www.shopmarketbasket.com/weekly-flyer/), generates 7 personalised dinners + snack ideas, emails a beautiful HTML summary, and saves the plan locally.

2. **Grocery list app** — a local Flask web app at `localhost:8001` that shows the week's meal plan and lets you check off what you already have to build your grocery list.

---

## Setup

### 1. Install dependencies

```bash
pip install flask
```

### 2. Run the grocery list app

```bash
python3 grocery_app.py
```

Then open [http://localhost:8001](http://localhost:8001).

The app reads from `~/Documents/Claude/MealPlanner/current_meal_plan.json`, which is written automatically by the Sunday scheduled task.

---

## How it works

### Sunday task (automated)
- Runs every Sunday at 9am via Claude Cowork scheduled tasks
- Fetches the Market Basket weekly flyer and builds meals around what's on sale
- Saves the meal plan JSON to `~/Documents/Claude/MealPlanner/current_meal_plan.json`
- Sends an HTML email digest with the full plan and grocery list

### Grocery list app
- Reads the current week's meal plan from the JSON file
- Shows all 7 dinners and snack ideas
- Ingredient checklist — tick off what you have, the grocery list updates live
- Remembers your checked items in the browser across the week
- Copy-to-clipboard button for the final grocery list

---

## Meal preferences
- Flavorful but not technically complicated
- No uncooked onions, no pickled anything
- All ingredients sourced from Market Basket
