#!/bin/bash
# Run this once from your terminal to create the GitHub repo and push everything.
# Requires: gh CLI (https://cli.github.com) and git

set -e

REPO_NAME="meal-planner"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "→ Initialising git repo..."
cd "$DIR"
git init
git add .
git commit -m "Initial commit — grocery app and meal planner"

echo "→ Creating GitHub repo..."
gh repo create "$REPO_NAME" --private --source=. --remote=origin --push

echo ""
echo "✓ Done! Repo created at: https://github.com/$(gh api user --jq '.login')/$REPO_NAME"
