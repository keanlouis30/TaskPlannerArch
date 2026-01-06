#!/usr/bin/env bash

# Launch Canvas TUI from this project directory.
# Assumes a working virtualenv in .venv.

PROJECT_DIR="/home/keyanluwi/Documents/GitHub/TaskPlannerArch"
VENV_DIR="$PROJECT_DIR/.venv"

cd "$PROJECT_DIR" || exit 1

# Activate virtualenv if it exists
if [ -d "$VENV_DIR" ]; then
  source "$VENV_DIR/bin/activate"
fi

# Run the app
exec "$PROJECT_DIR/canvas_tui.py"
