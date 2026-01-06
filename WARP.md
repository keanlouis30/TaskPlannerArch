# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

Canvas Task Planner TUI is a small Python 3.10+ terminal UI (built with the [Textual](https://github.com/Textualize/textual) framework) for viewing and creating tasks in a Canvas LMS instance. It reads Canvas API credentials from a user config file and presents a unified task list combining planner notes, calendar events, and assignments.

The entire application logic currently lives in `canvas_tui.py`, organized into logical layers (API client, configuration, UI screens, and application shell).

## Setup & Environment

### Python environment

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

This matches the instructions in `README.md` and installs `textual`, `requests`, and `python-dateutil`.

### Canvas configuration

The app expects a JSON configuration file at `~/.config/canvas-tui/config.json` with at least:

```json
{
  "canvas_base_url": "https://your-canvas-instance.instructure.com",
  "canvas_token": "your_api_token_here"
}
```

The `Config` class in `canvas_tui.py` is the single source of truth for where configuration is loaded and saved.

## Running the application

From the repo root with the virtualenv activated and config file in place:

```bash
python3 canvas_tui.py
```

This starts the Textual TUI with the following key bindings:
- `a` – open the "Add Task" modal
- `r` – refresh tasks from Canvas
- `Enter` – open the selected task in a browser (if it has a URL)
- `q` – quit the app

## Testing & Linting

- There is currently no committed test suite, `tests/` directory, or explicit linting/formatting configuration in this repository.
- If you add tests (for example using `pytest`) or linting tools (`ruff`, `flake8`, `black`, etc.), update this section with the concrete commands (including how to run a single test case).

## Architecture Overview

All code is in `canvas_tui.py`, but it is structured into clear concerns that are useful to understand before making changes.

### CanvasAPI – Canvas LMS client

`CanvasAPI` encapsulates all HTTP interactions with Canvas:
- Token validation via `/api/v1/users/self` to confirm credentials and capture `user_id`.
- Fetching data:
  - Active courses for the current user (`/api/v1/courses` with `enrollment_state=active`).
  - Assignments per course (`/api/v1/courses/{course_id}/assignments`).
  - Planner notes (`/api/v1/planner_notes`).
  - Calendar events (`/api/v1/calendar_events`).
- Creating tasks using a three-level fallback (`create_task`):
  1. Create a planner note (`create_planner_note`).
  2. If that fails, create a calendar event (`create_calendar_event`).
  3. If both fail, return a structured error.

All Canvas-related behavior (URLs, headers, pagination parameters, payload shapes) should go through `CanvasAPI` so the rest of the app can treat it as a black box.

### Config – user configuration manager

`Config` is responsible for reading and writing the JSON config at `~/.config/canvas-tui/config.json`:
- `load_config` lazily reads the file if present.
- `save_config` ensures the directory exists and writes a fully replaced JSON document.
- `is_configured` is the single gatekeeper used by the UI to decide whether Canvas credentials exist.

If you introduce additional settings (e.g., default timezone, filtering options), keep their schema and defaults centralized in this class so the rest of the code relies on `Config.get(...)` instead of hardcoding paths or JSON keys.

### AddTaskScreen – modal for creating tasks

`AddTaskScreen` is a `ModalScreen` that collects user input for new tasks:
- Receives the list of active courses from `CanvasTUI` and builds a `Select` menu with a "None (Personal Task)" option.
- Renders inputs for title, description, and due date (`YYYY-MM-DD HH:MM`), prefilled with `datetime.now()`.
- On "Create Task":
  - Validates that a title is present and the date parses correctly.
  - Normalizes `course_id` to an `int` or `None` before returning.
  - Dismisses with a dict containing `title`, `description`, `due_date` (a `datetime`), and `course_id`.

All validation and normalization of new-task form data should happen here before it reaches the API layer.

### CanvasTUI – main Textual application

`CanvasTUI` subclasses `textual.app.App` and wires together configuration, API access, task aggregation, and UI presentation.

Key responsibilities:
- **Startup (`on_mount`)**
  - Ensures configuration exists via `Config.is_configured()`; otherwise shows a notification and returns early.
  - Instantiates `CanvasAPI` with values from `Config` and validates the token.
  - Configures the `DataTable` columns and cursor behavior.
  - Triggers the initial `refresh_tasks()`.

- **Task aggregation (`refresh_tasks`)**
  - Fetches active courses, planner notes, calendar events (within a ±30-day window), and assignments for all courses.
  - Normalizes all of these into a flat `self.tasks` list with a common shape: `title`, `due_date`, `course`, `type`, `url`, and `raw` (original payload).
  - Applies timezone handling centered on Asia/Manila:
    - Converts ISO timestamps with or without tzinfo to `ZoneInfo('Asia/Manila')`.
    - Stores `due_date` as a *naive* `datetime` in Manila local time for comparison and display.
    - Filters out items outside the configured window and anything already past `now` in Manila.
  - Populates the `DataTable` rows with human-friendly strings while keeping a stable mapping from row key → task index.
  - Computes a simple "Today" vs. "Upcoming" status based on the (Manila) `due_date`.

- **User actions (bindings)**
  - `a` → `action_add_task`: pushes `AddTaskScreen` and, on success, calls `create_canvas_task`.
  - `r` → `action_refresh`: refetches Canvas data and rebuilds the task table.
  - `Enter` → `action_open_task`: opens the selected task's `url` in the system browser using `webbrowser.open`, with defensive checks around selection and mapping.
  - `q` → standard Textual quit behavior.

- **Task creation (`create_canvas_task`)**
  - Receives the dict from `AddTaskScreen` and passes its fields directly to `CanvasAPI.create_task`.
  - Surfaces which backend method succeeded (planner note vs calendar event) via notifications and refreshes the task list on success.

### Timezone and date handling

A non-obvious architectural choice is that the app normalizes all due dates into Asia/Manila local time and compares them as *naive* datetimes:
- `now_manila` is computed with `ZoneInfo('Asia/Manila')` but then stripped of `tzinfo`.
- Cutoff and future bounds are derived similarly.
- Planner notes, calendar events, and assignments all go through this conversion pipeline before filtering and storage.

If you change time handling (e.g., to support user-selectable timezones or fully timezone-aware comparisons), do it consistently across:
- Planner notes, calendar events, and assignments in `refresh_tasks`.
- Status calculations ("Today" vs "Upcoming").

## Extending the Application

When adding features, keep these boundaries in mind:
- **All Canvas HTTP behavior** should be encapsulated in `CanvasAPI`.
- **All configuration** should flow through `Config`.
- **All user interaction and validation** for new tasks should live in `AddTaskScreen`.
- **Task aggregation, filtering, and display** should be handled in `CanvasTUI.refresh_tasks` and related helper logic.

Maintaining these separations will make it easier for future Warp agents (and humans) to reason about changes without breaking unrelated parts of the TUI.