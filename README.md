# Canvas Task Planner TUI

A terminal UI for viewing and creating Canvas LMS tasks.

## Requirements

- Python 3.10+
- `pip`

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Create `~/.config/canvas-tui/config.json`:

```json
{
  "canvas_base_url": "https://your-canvas-instance.instructure.com",
  "canvas_token": "your_api_token_here"
}
```

## Usage

```bash
python3 canvas_tui.py
```

Keybindings:

- `a` – Add task
- `r` – Refresh
- `q` – Quit
