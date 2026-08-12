# IPTV Player - Copilot Instructions

## Project Type
Python IPTV Player with PySide6 GUI and VLC integration

## Setup
- Dependencies: `pip install -r requirements.txt`
- Run: `python main.py`
- Requires VLC media player installed on system

## Architecture
- `main.py` - Entry point
- `config/settings.py` - App settings (JSON-based)
- `src/core/` - Data models (Channel, Playlist, EPG) and SQLite database
- `src/parsers/` - M3U, Xtream Codes API, and Stalker Portal parsers
- `src/player/` - VLC-based media player wrapper
- `src/ui/` - PySide6 Qt6 UI components
- `src/utils/` - Helpers and logging

## Coding Conventions
- Python 3.9+
- Type hints on all functions
- Google-style docstrings
- Qt signals/slots for async UI updates
- Worker threads for network operations
- Dark theme UI stylesheet
- Portuguese UI labels
