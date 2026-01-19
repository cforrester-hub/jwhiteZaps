"""
JWhite Employee Status Monitor - Desktop Application

A small floating window that displays employee clock status in real-time.
Connects to the dashboard-service WebSocket for live updates.
"""

import json
import logging
import os
import sys
import threading
import winreg
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

import tkinter as tk
from tkinter import messagebox

try:
    from PIL import Image, ImageDraw
    import pystray
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False
    pystray = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

CONFIG_FILE = Path.home() / ".jwhite_employee_status" / "config.json"
APP_NAME = "JWhite Employee Status"
REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


@dataclass
class AppConfig:
    """Application configuration."""
    server_url: str = ""
    api_key: str = ""
    auto_start: bool = True
    always_on_top: bool = True
    window_x: int = 100
    window_y: int = 100
    opacity: float = 0.95

    @classmethod
    def load(cls) -> "AppConfig":
        """Load config from file."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    data = json.load(f)
                    return cls(**data)
            except Exception as e:
                logger.warning(f"Failed to load config: {e}")
        return cls()

    def save(self):
        """Save config to file."""
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.__dict__, f, indent=2)


# =============================================================================
# Status Types
# =============================================================================

class ClockStatus(str, Enum):
    CLOCKED_IN = "clocked_in"
    CLOCKED_OUT = "clocked_out"
    ON_BREAK = "on_break"
    UNKNOWN = "unknown"


STATUS_COLORS = {
    ClockStatus.CLOCKED_IN: "#22c55e",    # Green
    ClockStatus.CLOCKED_OUT: "#ef4444",   # Red
    ClockStatus.ON_BREAK: "#f59e0b",      # Amber/Orange
    ClockStatus.UNKNOWN: "#6b7280",       # Gray
}

STATUS_LABELS = {
    ClockStatus.CLOCKED_IN: "In",
    ClockStatus.CLOCKED_OUT: "Out",
    ClockStatus.ON_BREAK: "Break",
    ClockStatus.UNKNOWN: "?",
}


@dataclass
class Employee:
    """Employee status data."""
    employee_id: str
    name: str
    clock_status: ClockStatus
    last_updated: str = ""


# =============================================================================
# WebSocket Client
# =============================================================================

class WebSocketClient:
    """Handles WebSocket connection to dashboard-service."""

    def __init__(
        self,
        url: str,
        api_key: str,
        on_message: Callable[[dict], None],
        on_connect: Callable[[], None],
        on_disconnect: Callable[[], None],
        on_error: Callable[[str], None],
    ):
        self.url = url
        self.api_key = api_key
        self.on_message = on_message
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_error = on_error
        self._ws = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def connect(self):
        """Start WebSocket connection in background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def disconnect(self):
        """Stop WebSocket connection."""
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def _run(self):
        """WebSocket connection loop with auto-reconnect."""
        import websocket

        ws_url = f"{self.url}?api_key={self.api_key}"
        logger.info(f"Connecting to WebSocket: {self.url}")

        while self._running:
            try:
                self._ws = websocket.WebSocketApp(
                    ws_url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_ws_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(ping_interval=30, ping_timeout=10)

            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                self.on_error(str(e))

            if self._running:
                logger.info("Reconnecting in 5 seconds...")
                import time
                time.sleep(5)

    def _on_open(self, ws):
        logger.info("WebSocket connected")
        self.on_connect()

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            self.on_message(data)
        except Exception as e:
            logger.error(f"Failed to parse message: {e}")

    def _on_ws_error(self, ws, error):
        logger.error(f"WebSocket error: {error}")
        self.on_error(str(error))

    def _on_close(self, ws, close_status_code, close_msg):
        logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")
        self.on_disconnect()


# =============================================================================
# Auto-Start Management
# =============================================================================

def get_exe_path() -> str:
    """Get path to the executable (works for both .py and .exe)."""
    if getattr(sys, 'frozen', False):
        # Running as compiled exe
        return sys.executable
    else:
        # Running as script
        return sys.executable + ' "' + os.path.abspath(__file__) + '"'


def is_auto_start_enabled() -> bool:
    """Check if auto-start is enabled in registry."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, APP_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def set_auto_start(enabled: bool):
    """Enable or disable auto-start at Windows login."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, winreg.KEY_SET_VALUE)
        if enabled:
            exe_path = get_exe_path()
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe_path)
            logger.info(f"Auto-start enabled: {exe_path}")
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
                logger.info("Auto-start disabled")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        logger.error(f"Failed to set auto-start: {e}")


# =============================================================================
# System Tray Icon
# =============================================================================

def create_tray_icon_image(connected: bool = False) -> "Image.Image":
    """Create the system tray icon image."""
    # Create a simple icon with status indicator
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Main circle (dark blue background)
    draw.ellipse([4, 4, size - 4, size - 4], fill="#1a1a2e", outline="#3b82f6", width=3)

    # Status dot in center
    dot_color = "#22c55e" if connected else "#ef4444"
    dot_size = 20
    offset = (size - dot_size) // 2
    draw.ellipse(
        [offset, offset, offset + dot_size, offset + dot_size],
        fill=dot_color,
    )

    return image


# =============================================================================
# Main Application Window
# =============================================================================

class EmployeeStatusApp:
    """Main application window showing employee status."""

    def __init__(self):
        self.config = AppConfig.load()
        self.employees: dict[str, Employee] = {}
        self.ws_client: Optional[WebSocketClient] = None
        self.connected = False
        self.tray_icon: Optional[pystray.Icon] = None
        self.hidden = False

        # Create main window
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.configure(bg="#1a1a2e")

        # Remove window decorations for floating style, but keep it movable
        self.root.overrideredirect(True)

        # Set window attributes
        self.root.attributes("-topmost", self.config.always_on_top)
        self.root.attributes("-alpha", self.config.opacity)

        # Position window
        self.root.geometry(f"+{self.config.window_x}+{self.config.window_y}")

        # Build UI
        self._build_ui()

        # Make window draggable
        self._make_draggable()

        # Bind right-click for context menu
        self.root.bind("<Button-3>", self._show_context_menu)

        # Setup system tray
        if HAS_TRAY:
            self._setup_tray()

        # Check if configured
        if not self.config.server_url or not self.config.api_key:
            self.root.after(100, self._show_settings)
        else:
            self.root.after(100, self._connect)

        # Save window position on close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        """Build the main UI."""
        # Main frame with border
        self.main_frame = tk.Frame(
            self.root,
            bg="#1a1a2e",
            highlightbackground="#3b82f6",
            highlightthickness=2,
        )
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # Title bar
        self.title_bar = tk.Frame(self.main_frame, bg="#16213e", height=24)
        self.title_bar.pack(fill=tk.X)
        self.title_bar.pack_propagate(False)

        # Status indicator (connection status)
        self.status_indicator = tk.Canvas(
            self.title_bar, width=10, height=10, bg="#16213e", highlightthickness=0
        )
        self.status_indicator.pack(side=tk.LEFT, padx=(8, 4), pady=7)
        self._draw_status_indicator(False)

        # Title label
        self.title_label = tk.Label(
            self.title_bar,
            text="Employee Status",
            bg="#16213e",
            fg="#ffffff",
            font=("Segoe UI", 9, "bold"),
        )
        self.title_label.pack(side=tk.LEFT, pady=2)

        # Minimize button
        self.min_btn = tk.Label(
            self.title_bar,
            text="—",
            bg="#16213e",
            fg="#ffffff",
            font=("Segoe UI", 10),
            cursor="hand2",
        )
        self.min_btn.pack(side=tk.RIGHT, padx=4)
        self.min_btn.bind("<Button-1>", lambda e: self._minimize_to_tray())
        self.min_btn.bind("<Enter>", lambda e: self.min_btn.config(bg="#374151"))
        self.min_btn.bind("<Leave>", lambda e: self.min_btn.config(bg="#16213e"))

        # Close button
        self.close_btn = tk.Label(
            self.title_bar,
            text="×",
            bg="#16213e",
            fg="#ffffff",
            font=("Segoe UI", 12),
            cursor="hand2",
        )
        self.close_btn.pack(side=tk.RIGHT, padx=4)
        self.close_btn.bind("<Button-1>", lambda e: self._quit())
        self.close_btn.bind("<Enter>", lambda e: self.close_btn.config(bg="#ef4444"))
        self.close_btn.bind("<Leave>", lambda e: self.close_btn.config(bg="#16213e"))

        # Employee list frame
        self.list_frame = tk.Frame(self.main_frame, bg="#1a1a2e")
        self.list_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Employee widgets container
        self.employee_widgets: dict[str, dict] = {}

        # Initial message
        self.status_label = tk.Label(
            self.list_frame,
            text="Connecting...",
            bg="#1a1a2e",
            fg="#6b7280",
            font=("Segoe UI", 9),
        )
        self.status_label.pack(pady=20)

    def _draw_status_indicator(self, connected: bool):
        """Draw connection status indicator."""
        self.status_indicator.delete("all")
        color = "#22c55e" if connected else "#ef4444"
        self.status_indicator.create_oval(1, 1, 9, 9, fill=color, outline=color)

    def _make_draggable(self):
        """Make the window draggable."""
        self._drag_data = {"x": 0, "y": 0}

        def start_drag(event):
            self._drag_data["x"] = event.x
            self._drag_data["y"] = event.y

        def drag(event):
            x = self.root.winfo_x() + (event.x - self._drag_data["x"])
            y = self.root.winfo_y() + (event.y - self._drag_data["y"])
            self.root.geometry(f"+{x}+{y}")

        # Bind to title bar and main frame
        for widget in [self.title_bar, self.title_label, self.main_frame]:
            widget.bind("<Button-1>", start_drag)
            widget.bind("<B1-Motion>", drag)

    def _setup_tray(self):
        """Setup system tray icon."""
        if not HAS_TRAY:
            return

        def on_show(icon, item):
            self.root.after(0, self._show_window)

        def on_settings(icon, item):
            self.root.after(0, self._show_settings)

        def on_reconnect(icon, item):
            self.root.after(0, self._reconnect)

        def on_quit(icon, item):
            self.root.after(0, self._quit)

        menu = pystray.Menu(
            pystray.MenuItem("Show", on_show, default=True),
            pystray.MenuItem("Settings", on_settings),
            pystray.MenuItem("Reconnect", on_reconnect),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", on_quit),
        )

        self.tray_icon = pystray.Icon(
            APP_NAME,
            create_tray_icon_image(False),
            APP_NAME,
            menu,
        )

        # Run tray icon in background thread
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _update_tray_icon(self, connected: bool):
        """Update the tray icon to reflect connection status."""
        if self.tray_icon and HAS_TRAY:
            self.tray_icon.icon = create_tray_icon_image(connected)

    def _show_context_menu(self, event):
        """Show right-click context menu."""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Settings...", command=self._show_settings)
        menu.add_separator()
        menu.add_checkbutton(
            label="Always on Top",
            variable=tk.BooleanVar(value=self.config.always_on_top),
            command=self._toggle_always_on_top,
        )
        menu.add_checkbutton(
            label="Start at Login",
            variable=tk.BooleanVar(value=is_auto_start_enabled()),
            command=self._toggle_auto_start,
        )
        menu.add_separator()
        menu.add_command(label="Reconnect", command=self._reconnect)
        menu.add_separator()
        menu.add_command(label="Exit", command=self._quit)

        menu.tk_popup(event.x_root, event.y_root)

    def _toggle_always_on_top(self):
        """Toggle always on top setting."""
        self.config.always_on_top = not self.config.always_on_top
        self.root.attributes("-topmost", self.config.always_on_top)
        self.config.save()

    def _toggle_auto_start(self):
        """Toggle auto-start at login."""
        current = is_auto_start_enabled()
        set_auto_start(not current)

    def _show_settings(self):
        """Show settings dialog."""
        # Make sure window is visible first
        if self.hidden:
            self._show_window()

        dialog = SettingsDialog(self.root, self.config)
        self.root.wait_window(dialog.top)

        if dialog.result:
            self.config = dialog.result
            self.config.save()
            self._reconnect()

    def _connect(self):
        """Connect to WebSocket server."""
        if self.ws_client:
            self.ws_client.disconnect()

        # Build WebSocket URL from server URL
        server_url = self.config.server_url.rstrip("/")
        if server_url.startswith("https://"):
            ws_url = server_url.replace("https://", "wss://")
        elif server_url.startswith("http://"):
            ws_url = server_url.replace("http://", "ws://")
        else:
            ws_url = "wss://" + server_url

        ws_url += "/api/dashboard/employee-status/ws"

        self.ws_client = WebSocketClient(
            url=ws_url,
            api_key=self.config.api_key,
            on_message=self._on_ws_message,
            on_connect=self._on_ws_connect,
            on_disconnect=self._on_ws_disconnect,
            on_error=self._on_ws_error,
        )
        self.ws_client.connect()

    def _reconnect(self):
        """Reconnect to server."""
        self.status_label.config(text="Reconnecting...")
        self.status_label.pack(pady=20)
        self._connect()

    def _on_ws_connect(self):
        """Handle WebSocket connection."""
        self.connected = True
        self.root.after(0, lambda: self._draw_status_indicator(True))
        self.root.after(0, lambda: self._update_tray_icon(True))
        logger.info("Connected to server")

    def _on_ws_disconnect(self):
        """Handle WebSocket disconnection."""
        self.connected = False
        self.root.after(0, lambda: self._draw_status_indicator(False))
        self.root.after(0, lambda: self._update_tray_icon(False))
        logger.info("Disconnected from server")

    def _on_ws_error(self, error: str):
        """Handle WebSocket error."""
        logger.error(f"WebSocket error: {error}")
        self.root.after(0, lambda: self.status_label.config(text=f"Error: {error[:30]}..."))

    def _on_ws_message(self, data: dict):
        """Handle incoming WebSocket message."""
        msg_type = data.get("type", "")

        if msg_type == "all_statuses":
            # Initial status dump
            employees = data.get("employees", [])
            self.root.after(0, lambda: self._update_all_employees(employees))

        elif msg_type == "status_update":
            # Single employee update
            self.root.after(0, lambda: self._update_employee(data))

        elif msg_type == "pong":
            pass  # Keepalive response

    def _update_all_employees(self, employees: list):
        """Update all employee statuses."""
        # Hide status label
        self.status_label.pack_forget()

        # Clear existing widgets
        for widget_data in self.employee_widgets.values():
            widget_data["frame"].destroy()
        self.employee_widgets.clear()
        self.employees.clear()

        # Sort employees by name
        employees = sorted(employees, key=lambda e: e.get("name", ""))

        # Create widgets for each employee
        for emp_data in employees:
            employee = Employee(
                employee_id=emp_data.get("employee_id", ""),
                name=emp_data.get("name", "Unknown"),
                clock_status=ClockStatus(emp_data.get("clock_status", "unknown")),
                last_updated=emp_data.get("last_updated", ""),
            )
            self.employees[employee.employee_id] = employee
            self._create_employee_widget(employee)

        # Resize window to fit content
        self.root.update_idletasks()
        self.root.geometry("")

    def _update_employee(self, data: dict):
        """Update a single employee's status."""
        employee_id = data.get("employee_id", "")
        if employee_id in self.employees:
            self.employees[employee_id].clock_status = ClockStatus(
                data.get("clock_status", "unknown")
            )
            self.employees[employee_id].last_updated = data.get("timestamp", "")
            self._refresh_employee_widget(employee_id)
        else:
            # New employee, add them
            employee = Employee(
                employee_id=employee_id,
                name=data.get("name", "Unknown"),
                clock_status=ClockStatus(data.get("clock_status", "unknown")),
                last_updated=data.get("timestamp", ""),
            )
            self.employees[employee_id] = employee
            self._create_employee_widget(employee)

    def _create_employee_widget(self, employee: Employee):
        """Create widget for an employee."""
        frame = tk.Frame(self.list_frame, bg="#1a1a2e")
        frame.pack(fill=tk.X, pady=1)

        # Status circle
        canvas = tk.Canvas(frame, width=14, height=14, bg="#1a1a2e", highlightthickness=0)
        canvas.pack(side=tk.LEFT, padx=(4, 6))

        color = STATUS_COLORS.get(employee.clock_status, "#6b7280")
        canvas.create_oval(2, 2, 12, 12, fill=color, outline=color)

        # Name label
        name_label = tk.Label(
            frame,
            text=employee.name,
            bg="#1a1a2e",
            fg="#e4e4e4",
            font=("Segoe UI", 9),
            anchor="w",
        )
        name_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Status text
        status_label = tk.Label(
            frame,
            text=STATUS_LABELS.get(employee.clock_status, "?"),
            bg="#1a1a2e",
            fg=color,
            font=("Segoe UI", 8),
            width=5,
        )
        status_label.pack(side=tk.RIGHT, padx=4)

        self.employee_widgets[employee.employee_id] = {
            "frame": frame,
            "canvas": canvas,
            "name_label": name_label,
            "status_label": status_label,
        }

    def _refresh_employee_widget(self, employee_id: str):
        """Refresh an employee's widget with current status."""
        if employee_id not in self.employee_widgets:
            return

        employee = self.employees[employee_id]
        widgets = self.employee_widgets[employee_id]

        color = STATUS_COLORS.get(employee.clock_status, "#6b7280")

        # Update circle
        widgets["canvas"].delete("all")
        widgets["canvas"].create_oval(2, 2, 12, 12, fill=color, outline=color)

        # Update status text
        widgets["status_label"].config(
            text=STATUS_LABELS.get(employee.clock_status, "?"),
            fg=color,
        )

    def _show_window(self):
        """Show the main window."""
        self.hidden = False
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _minimize_to_tray(self):
        """Minimize to system tray."""
        self.hidden = True
        self.root.withdraw()

    def _on_close(self):
        """Handle window close."""
        # Save window position
        self.config.window_x = self.root.winfo_x()
        self.config.window_y = self.root.winfo_y()
        self.config.save()
        self._quit()

    def _quit(self):
        """Quit the application."""
        if self.ws_client:
            self.ws_client.disconnect()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.quit()

    def run(self):
        """Start the application."""
        self.root.mainloop()


# =============================================================================
# Settings Dialog
# =============================================================================

class SettingsDialog:
    """Settings configuration dialog."""

    def __init__(self, parent, config: AppConfig):
        self.result: Optional[AppConfig] = None

        self.top = tk.Toplevel(parent)
        self.top.title("Settings")
        self.top.configure(bg="#1a1a2e")
        self.top.geometry("400x200")
        self.top.resizable(False, False)
        self.top.transient(parent)
        self.top.grab_set()

        # Center on parent
        self.top.geometry(
            f"+{parent.winfo_x() + 50}+{parent.winfo_y() + 50}"
        )

        # Form
        form = tk.Frame(self.top, bg="#1a1a2e", padx=20, pady=20)
        form.pack(fill=tk.BOTH, expand=True)

        # Server URL
        tk.Label(
            form, text="Server URL:", bg="#1a1a2e", fg="#e4e4e4", font=("Segoe UI", 9)
        ).grid(row=0, column=0, sticky="w", pady=5)

        self.server_url_var = tk.StringVar(value=config.server_url)
        self.server_entry = tk.Entry(
            form, textvariable=self.server_url_var, width=35, font=("Segoe UI", 9)
        )
        self.server_entry.grid(row=0, column=1, pady=5, padx=(10, 0))

        # API Key
        tk.Label(
            form, text="API Key:", bg="#1a1a2e", fg="#e4e4e4", font=("Segoe UI", 9)
        ).grid(row=1, column=0, sticky="w", pady=5)

        self.api_key_var = tk.StringVar(value=config.api_key)
        self.api_key_entry = tk.Entry(
            form, textvariable=self.api_key_var, width=35, font=("Segoe UI", 9), show="*"
        )
        self.api_key_entry.grid(row=1, column=1, pady=5, padx=(10, 0))

        # Placeholder text
        if not config.server_url:
            self.server_entry.delete(0, tk.END)
            self.server_entry.insert(0, "https://jwhitezaps.atoaz.com")

        # Buttons
        btn_frame = tk.Frame(form, bg="#1a1a2e")
        btn_frame.grid(row=3, column=0, columnspan=2, pady=20)

        tk.Button(
            btn_frame,
            text="Save",
            command=self._save,
            bg="#3b82f6",
            fg="white",
            font=("Segoe UI", 9),
            width=10,
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            btn_frame,
            text="Cancel",
            command=self.top.destroy,
            bg="#4b5563",
            fg="white",
            font=("Segoe UI", 9),
            width=10,
        ).pack(side=tk.LEFT, padx=5)

    def _save(self):
        """Save settings."""
        server_url = self.server_url_var.get().strip()
        api_key = self.api_key_var.get().strip()

        if not server_url:
            messagebox.showerror("Error", "Server URL is required")
            return

        if not api_key:
            messagebox.showerror("Error", "API Key is required")
            return

        self.result = AppConfig(
            server_url=server_url,
            api_key=api_key,
        )
        self.top.destroy()


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    """Main entry point."""
    try:
        app = EmployeeStatusApp()
        app.run()
    except Exception as e:
        logger.exception("Application error")
        messagebox.showerror("Error", f"Application error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
