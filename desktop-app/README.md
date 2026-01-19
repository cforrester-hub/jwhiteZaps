# JWhite Employee Status Monitor

A small floating desktop application that displays employee clock status in real-time.

## Features

- Real-time status updates via WebSocket
- System tray icon with context menu
- Auto-start at Windows login (optional)
- Always-on-top floating window
- Draggable window positioning
- Connection status indicator

## Status Colors

- **Green** - Clocked In
- **Red** - Clocked Out
- **Orange** - On Break
- **Gray** - Unknown

## Building

### Prerequisites

- Python 3.11 or later
- Windows 10/11

### Build Steps

1. Generate the icon:
   ```
   python create_icon.py
   ```

2. Run the build script:
   ```
   build.bat
   ```

3. The executable will be in `dist\JWhiteEmployeeStatus.exe`

### Manual Build

If you prefer to build manually:

```bash
# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install pyinstaller

# Create icon
python create_icon.py

# Build
pyinstaller --onefile --noconsole --name "JWhiteEmployeeStatus" --icon "icon.ico" --hidden-import=pystray._win32 --hidden-import=PIL._tkinter_finder employee_status_app.py
```

## Configuration

On first run, you'll be prompted to enter:

- **Server URL**: `https://jwhitezaps.atoaz.com`
- **API Key**: The key provided by your administrator

Configuration is stored in `%USERPROFILE%\.jwhite_employee_status\config.json`

## Usage

- **Drag** the title bar to move the window
- **Right-click** anywhere for context menu
- **Minimize button (—)** hides to system tray
- **Close button (×)** exits the application
- **System tray icon** double-click to show, right-click for menu

## Deployment via Jumpcloud

For mass deployment:

1. Build the executable
2. Create a Jumpcloud command to:
   - Copy the exe to a standard location (e.g., `C:\Program Files\JWhite\EmployeeStatus\`)
   - Create a startup shortcut or registry entry
   - Pre-configure the config.json with the API key

Example registry entry for auto-start:
```
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run
"JWhite Employee Status" = "C:\Program Files\JWhite\EmployeeStatus\JWhiteEmployeeStatus.exe"
```
