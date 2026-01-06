#!/usr/bin/env python3
"""
Canvas TUI - A terminal interface for managing Canvas LMS tasks

Installation:
    pip install textual requests python-dateutil

Configuration:
    Create ~/.config/canvas-tui/config.json with:
    {
        "canvas_base_url": "https://your-canvas-instance.instructure.com",
        "canvas_token": "your_api_token_here"
    }

Usage:
    python canvas_tui.py

Keybindings:
    a - Add new task
    r - Refresh tasks from Canvas
    d - View task details
    q - Quit
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
import requests
from dateutil import parser as date_parser
from zoneinfo import ZoneInfo
import webbrowser

from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import (
    Header, Footer, Static, DataTable, Input, Button, 
    TextArea, Select, Label
)
from textual.binding import Binding
from textual.screen import ModalScreen
from textual import on


# ============================================================================
# Canvas API Client
# ============================================================================

class CanvasAPI:
    """Handle all Canvas API interactions"""
    
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        self.user_id = None
    
    def validate_token(self) -> bool:
        """Validate Canvas token by fetching user info"""
        try:
            response = requests.get(
                f'{self.base_url}/api/v1/users/self',
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                user_data = response.json()
                self.user_id = user_data.get('id')
                return True
            return False
        except Exception as e:
            print(f"Token validation failed: {e}")
            return False
    
    def get_active_courses(self) -> List[Dict[str, Any]]:
        """Fetch active courses for the user"""
        try:
            response = requests.get(
                f'{self.base_url}/api/v1/courses',
                headers=self.headers,
                params={'enrollment_state': 'active', 'per_page': 50},
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            print(f"Failed to fetch courses: {e}")
            return []
    
    def get_assignments(self, course_id: int) -> List[Dict[str, Any]]:
        """Fetch assignments for a specific course"""
        try:
            response = requests.get(
                f'{self.base_url}/api/v1/courses/{course_id}/assignments',
                headers=self.headers,
                params={'per_page': 50, 'order_by': 'due_at'},
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            print(f"Failed to fetch assignments for course {course_id}: {e}")
            return []
    
    def get_planner_notes(self) -> List[Dict[str, Any]]:
        """Fetch user's planner notes"""
        try:
            response = requests.get(
                f'{self.base_url}/api/v1/planner_notes',
                headers=self.headers,
                params={'per_page': 50},
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            print(f"Failed to fetch planner notes: {e}")
            return []
    
    def get_calendar_events(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Fetch user's calendar events between two dates"""
        params = {
            'type': 'event',
            'start_date': start_date.date().isoformat(),
            'end_date': end_date.date().isoformat(),
            'per_page': 50,
        }
        try:
            response = requests.get(
                f'{self.base_url}/api/v1/calendar_events',
                headers=self.headers,
                params=params,
                timeout=10,
            )
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            print(f"Failed to fetch calendar events: {e}")
            return []
    
    def create_planner_note(self, title: str, details: str, 
                           todo_date: str, course_id: Optional[int] = None) -> Dict[str, Any]:
        """Create a planner note (preferred method)"""
        payload = {
            'title': title,
            'details': details,
            'todo_date': todo_date
        }
        if course_id:
            payload['course_id'] = course_id
        
        try:
            response = requests.post(
                f'{self.base_url}/api/v1/planner_notes',
                headers=self.headers,
                json=payload,
                timeout=10
            )
            if response.status_code in [200, 201]:
                return {'success': True, 'data': response.json(), 'method': 'planner_note'}
            return {'success': False, 'error': response.text}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def create_calendar_event(self, title: str, description: str,
                             start_at: str, course_id: Optional[int] = None) -> Dict[str, Any]:
        """Create a calendar event (fallback method)"""
        end_at = (datetime.fromisoformat(start_at.replace('Z', '+00:00')) + 
                  timedelta(hours=1)).isoformat()
        
        payload = {
            'calendar_event': {
                'title': f'📋 {title}',
                'description': f'Task: {title}\n\n{description}',
                'start_at': start_at,
                'end_at': end_at,
                'all_day': False
            }
        }
        
        if course_id:
            payload['calendar_event']['context_code'] = f'course_{course_id}'
        
        try:
            response = requests.post(
                f'{self.base_url}/api/v1/calendar_events',
                headers=self.headers,
                json=payload,
                timeout=10
            )
            if response.status_code in [200, 201]:
                return {'success': True, 'data': response.json(), 'method': 'calendar_event'}
            return {'success': False, 'error': response.text}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def create_task(self, title: str, description: str, 
                   due_date: datetime, course_id: Optional[int] = None) -> Dict[str, Any]:
        """Create task using 3-tier fallback: planner note → calendar event → assignment"""
        iso_date = due_date.isoformat()
        
        # Try planner note first
        result = self.create_planner_note(title, description, iso_date, course_id)
        if result['success']:
            return result
        
        # Fallback to calendar event
        result = self.create_calendar_event(title, description, iso_date, course_id)
        if result['success']:
            return result
        
        return {'success': False, 'error': 'All methods failed', 'method': 'none'}


# ============================================================================
# Configuration Manager
# ============================================================================

class Config:
    """Manage Canvas TUI configuration"""
    
    def __init__(self):
        self.config_dir = Path.home() / '.config' / 'canvas-tui'
        self.config_file = self.config_dir / 'config.json'
        self.config = self.load_config()
    
    def load_config(self) -> Dict[str, str]:
        """Load configuration from file"""
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                return json.load(f)
        return {}
    
    def save_config(self, config: Dict[str, str]):
        """Save configuration to file"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=2)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        return self.config.get(key, default)
    
    def is_configured(self) -> bool:
        """Check if Canvas credentials are configured"""
        return bool(self.config.get('canvas_base_url') and 
                   self.config.get('canvas_token'))


# ============================================================================
# Add Task Modal Screen
# ============================================================================

class AddTaskScreen(ModalScreen):
    """Modal screen for adding a new task"""
    
    CSS = """
    AddTaskScreen {
        align: center middle;
    }
    
    #add_task_dialog {
        width: 80;
        height: auto;
        border: thick $background 80%;
        background: $surface;
        padding: 1;
    }
    
    #form_container {
        width: 100%;
        height: auto;
    }
    
    .form_row {
        height: auto;
        margin: 1 0;
    }
    
    Button {
        margin: 0 1;
    }
    """
    
    def __init__(self, courses: List[Dict[str, Any]]):
        super().__init__()
        self.courses = courses
    
    def compose(self) -> ComposeResult:
        course_options = [("None (Personal Task)", None)]
        course_options.extend([(c['name'], str(c['id'])) for c in self.courses])
        
        with Vertical(id="add_task_dialog"):
            yield Label("Add New Task", id="dialog_title")
            with Vertical(id="form_container"):
                with Vertical(classes="form_row"):
                    yield Label("Title:")
                    yield Input(placeholder="Task title", id="task_title")
                
                with Vertical(classes="form_row"):
                    yield Label("Description:")
                    yield TextArea(id="task_description")
                
                with Vertical(classes="form_row"):
                    yield Label("Due Date (YYYY-MM-DD HH:MM):")
                    yield Input(
                        placeholder="2025-01-10 15:00",
                        id="task_due_date",
                        value=datetime.now().strftime("%Y-%m-%d %H:%M")
                    )
                
                with Vertical(classes="form_row"):
                    yield Label("Course:")
                    yield Select(course_options, id="task_course")
                
                with Horizontal():
                    yield Button("Create Task", variant="primary", id="create_button")
                    yield Button("Cancel", variant="default", id="cancel_button")
    
    @on(Button.Pressed, "#create_button")
    def handle_create(self):
        """Handle create button press"""
        title = self.query_one("#task_title", Input).value
        description = self.query_one("#task_description", TextArea).text
        due_date_str = self.query_one("#task_due_date", Input).value
        course_id = self.query_one("#task_course", Select).value
        
        if not title:
            self.app.notify("Title is required", severity="error")
            return
        
        try:
            due_date = datetime.strptime(due_date_str, "%Y-%m-%d %H:%M")
        except ValueError:
            self.app.notify("Invalid date format. Use YYYY-MM-DD HH:MM", severity="error")
            return
        
        course_id_int = int(course_id) if course_id and course_id != "None" else None
        
        self.dismiss({
            'title': title,
            'description': description,
            'due_date': due_date,
            'course_id': course_id_int
        })
    
    @on(Button.Pressed, "#cancel_button")
    def handle_cancel(self):
        """Handle cancel button press"""
        self.dismiss(None)


# ============================================================================
# Main TUI Application
# ============================================================================

class CanvasTUI(App):
    """Canvas Task Manager TUI Application"""
    
    CSS = """
    Screen {
        background: $background;
    }
    
    #main_container {
        width: 100%;
        height: 100%;
    }
    
    #status_bar {
        dock: top;
        height: 3;
        background: $primary;
        padding: 1;
    }
    
    #tasks_table {
        width: 100%;
        height: 1fr;
    }
    
    DataTable {
        height: 100%;
    }
    """
    
    BINDINGS = [
        Binding("a", "add_task", "Add Task"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "open_task", "Open Task"),
        Binding("q", "quit", "Quit"),
    ]
    
    def __init__(self):
        super().__init__()
        self.config = Config()
        self.canvas = None
        self.courses = []
        self.tasks = []
    
    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main_container"):
            yield Static("Loading Canvas tasks...", id="status_bar")
            yield DataTable(id="tasks_table")
        yield Footer()
    
    def on_mount(self):
        """Initialize the application"""
        # Check configuration
        if not self.config.is_configured():
            self.notify(
                "Canvas not configured. Edit ~/.config/canvas-tui/config.json",
                severity="error",
                timeout=10
            )
            return
        
        # Initialize Canvas API
        self.canvas = CanvasAPI(
            self.config.get('canvas_base_url'),
            self.config.get('canvas_token')
        )
        
        # Validate token
        if not self.canvas.validate_token():
            self.notify("Invalid Canvas token", severity="error")
            return
        
        # Setup table
        table = self.query_one("#tasks_table", DataTable)
        table.add_columns("Due", "Status", "Course", "Title", "Type")
        table.cursor_type = "row"
        
        # Load initial data
        self.refresh_tasks()
    
    def refresh_tasks(self):
        """Fetch and display tasks from Canvas"""
        self.query_one("#status_bar", Static).update("Fetching tasks from Canvas...")
        
        # Fetch courses
        self.courses = self.canvas.get_active_courses()

        # Normalize and filter tasks
        self.tasks = []
        now = datetime.now()
        cutoff = now - timedelta(days=30)
        future = now + timedelta(days=30)
        # Current time in Manila (naive)
        now_manila = datetime.now(ZoneInfo('Asia/Manila')).replace(tzinfo=None)
        
        # Fetch planner notes
        planner_notes = self.canvas.get_planner_notes()

        # Fetch calendar events in same window
        calendar_events = self.canvas.get_calendar_events(cutoff, future)
        
        # Fetch assignments from all courses
        all_assignments = []
        for course in self.courses:
            assignments = self.canvas.get_assignments(course['id'])
            for assignment in assignments:
                assignment['course_name'] = course['name']
            all_assignments.extend(assignments)
        
        # Add planner notes (only active and future)
        for note in planner_notes:
            # Skip resolved / inactive notes
            if note.get('workflow_state') not in (None, 'active'):
                continue

            if note.get('todo_date'):
                try:
                    # Build URL for planner note if possible
                    note_url = None
                    if note.get('course_id'):
                        note_url = f"{self.canvas.base_url}/courses/{note['course_id']}/planner_items?filter=planner_note_{note['id']}"
                    due = date_parser.isoparse(note['todo_date'])
                    # Convert to Manila time
                    if due.tzinfo is not None:
                        due = due.astimezone(ZoneInfo('Asia/Manila'))
                    else:
                        due = due.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Manila'))
                    # Make naive for comparison and storage
                    due_naive = due.replace(tzinfo=None)
                    cutoff_manila = (
                        cutoff.replace(tzinfo=timezone.utc)
                        .astimezone(ZoneInfo("Asia/Manila"))
                        .replace(tzinfo=None)
                    )
                    future_manila = (
                        future.replace(tzinfo=timezone.utc)
                        .astimezone(ZoneInfo("Asia/Manila"))
                        .replace(tzinfo=None)
                    )

                    # Filter out past tasks: require due >= now (Manila)
                    if now_manila <= due_naive <= future_manila:
                        self.tasks.append({
                            'title': note['title'],
                            'due_date': due_naive,
'course': note.get('course_id', 'Personal'),
                            'type': 'Planner Note',
                            'url': note_url,
                            'raw': note,
                        })
                except Exception:
                    pass
        
        # Add calendar events
        for event in calendar_events:
            try:
                event_url = event.get('html_url')
                if event.get('start_at'):
                    due = date_parser.isoparse(event['start_at'])
                elif event.get('all_day_date'):
                    # all-day events use a date string
                    due = date_parser.isoparse(event['all_day_date'])
                else:
                    continue

                # Convert to Manila time
                if due.tzinfo is not None:
                    due = due.astimezone(ZoneInfo('Asia/Manila'))
                else:
                    due = due.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Manila'))
                # Make naive for comparison and storage
                due_naive = due.replace(tzinfo=None)
                cutoff_manila = cutoff.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Manila')).replace(tzinfo=None)
                future_manila = future.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Manila')).replace(tzinfo=None)

                # Filter out past events
                if now_manila <= due_naive <= future_manila:
                    # Prefer context name if available, else use context code or "Calendar"
                    context = event.get('context_name') or event.get('context_code', 'Calendar')
                    self.tasks.append({
                        'title': event.get('title', 'Untitled Event'),
                        'due_date': due_naive,
'course': context,
                        'type': 'Calendar Event',
                        'url': event_url,
                        'raw': event,
                    })
            except Exception:
                pass

            # Add assignments (skip submitted / graded, only future)
        for assignment in all_assignments:
            # Skip completed assignments
            submission = assignment.get("submission") or {}
            if assignment.get("has_submitted_submissions") or submission.get(
                "workflow_state"
            ) in {"submitted", "graded", "complete"}:
                continue

            if assignment.get("due_at"):
                try:
                    # Assignment URL
                    assignment_url = (
                        f"{self.canvas.base_url}/courses/{assignment['course_id']}"
                        f"/assignments/{assignment['id']}"
                        if assignment.get("course_id") and assignment.get("id")
                        else None
                    )
                    due = date_parser.isoparse(assignment["due_at"])
                    # Convert to Manila time
                    if due.tzinfo is not None:
                        due = due.astimezone(ZoneInfo("Asia/Manila"))
                    else:
                        due = due.replace(tzinfo=timezone.utc).astimezone(
                            ZoneInfo("Asia/Manila")
                        )
                    # Make naive for comparison and storage
                    due_naive = due.replace(tzinfo=None)
                    cutoff_manila = (
                        cutoff.replace(tzinfo=timezone.utc)
                        .astimezone(ZoneInfo("Asia/Manila"))
                        .replace(tzinfo=None)
                    )
                    future_manila = (
                        future.replace(tzinfo=timezone.utc)
                        .astimezone(ZoneInfo("Asia/Manila"))
                        .replace(tzinfo=None)
                    )

                    # Only future (or today) assignments
                    if now_manila <= due_naive <= future_manila:
                        self.tasks.append(
                            {
                                "title": assignment["name"],
                                "due_date": due_naive,
                                "course": assignment.get("course_name", "Unknown"),
                                "type": "Assignment",
                                "url": assignment_url,
                                "raw": assignment,
                            }
                        )
                except Exception:
                    pass
        
        # Sort by due date
        self.tasks.sort(key=lambda x: x['due_date'])
        
        # Update table
        table = self.query_one("#tasks_table", DataTable)
        table.clear()
        
        for idx, task in enumerate(self.tasks):
            due_str = task["due_date"].strftime("%m/%d %H:%M")
            # Simple status indicator based on Manila date
            if task["due_date"].date() == now_manila.date():
                status = "Today"
            else:
                status = "Upcoming"

            course_str = str(task["course"])[:20]
            title_str = task["title"][:50]
            
            # Store the index as the row key so we can map back to tasks
            table.add_row(due_str, status, course_str, title_str, task["type"], key=idx)
        
        self.query_one("#status_bar", Static).update(
            f"📚 {len(self.tasks)} tasks loaded | Press 'a' to add, 'r' to refresh, 'q' to quit"
        )
        self.notify(f"Loaded {len(self.tasks)} tasks")
    
    def action_refresh(self):
        """Refresh tasks from Canvas"""
        self.refresh_tasks()
    
    def action_add_task(self):
        """Show add task modal"""
        if not self.canvas:
            self.notify("Canvas not connected", severity="error")
            return
        
        def handle_result(result):
            if result:
                self.create_canvas_task(result)
        
        self.push_screen(AddTaskScreen(self.courses), handle_result)

    def action_open_task(self):
        """Open the selected task in the browser, if it has a URL"""
        table = self.query_one("#tasks_table", DataTable)
        if table.cursor_row is None:
            self.notify("No task selected", severity="warning")
            return

        row_key = table.row_key(table.cursor_row)
        if row_key is None:
            self.notify("Unable to determine selected task", severity="error")
            return

        try:
            task = self.tasks[row_key]
        except (IndexError, TypeError):
            self.notify("Selected task not found", severity="error")
            return

        url = task.get('url')
        if not url:
            self.notify("No URL available for this task", severity="warning")
            return

        try:
            webbrowser.open(url)
            self.notify("Opened task in browser", severity="information")
        except Exception as e:
            self.notify(f"Failed to open browser: {e}", severity="error")
    
    def create_canvas_task(self, task_data: Dict[str, Any]):
        """Create task in Canvas using API"""
        self.notify("Creating task in Canvas...")
        
        result = self.canvas.create_task(
            title=task_data['title'],
            description=task_data['description'],
            due_date=task_data['due_date'],
            course_id=task_data['course_id']
        )
        
        if result['success']:
            method = result['method'].replace('_', ' ').title()
            self.notify(f"Task created as {method}!", severity="information")
            self.refresh_tasks()
        else:
            self.notify(f"Failed to create task: {result.get('error', 'Unknown error')}", 
                       severity="error")


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    app = CanvasTUI()
    app.run()
