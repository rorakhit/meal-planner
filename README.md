# WeeksRations 🔥

An AI-powered weekly meal planner that generates 3 dinners, builds a grocery list, and emails the plan every Sunday. Includes a web UI for viewing meals, swapping individual meals, and checking off groceries. Deployed on Railway.

## How it works

1. **Every Sunday at 9am ET**, the bot calls Claude to generate 3 dinners + snack ideas
2. **Emails the plan** with a styled HTML summary via Resend
3. **Web UI** lets you view the plan, swap any meal, and build your grocery list
4. **Swap meals** — replace a meal entirely, or keep the same recipe and substitute one ingredient

## Features

- **Auto-generated weekly plan** — Claude creates 3 dinners + snacks every Sunday with a rotating cuisine theme
- **Email digest** — styled HTML email with meals and full grocery list
- **Web dashboard** — browse the week's meals from any device
- **Swap any meal** — click "Swap this meal", optionally specify what to avoid
- **Swap an ingredient** — keep the same recipe but substitute one ingredient
- **Generate New Plan** button — create a fresh plan on demand
- **Grocery list builder** — check off what you already have, see what you need to buy
- **Copy to clipboard** — one-click copy of your shopping list

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Web UI — meal plan + grocery list |
| `GET /plan` | Current meal plan as JSON |
| `POST /generate` | Generate a new weekly plan |
| `POST /regenerate` | Swap one meal (body: `{"meal_index": 0, "disliked": "salmon"}`) |
| `POST /swap-ingredient` | Substitute one ingredient (body: `{"meal_index": 0, "ingredient": "salmon"}`) |
| `GET /health` | Server status + scheduler info |
