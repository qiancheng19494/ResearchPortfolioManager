"""Runtime paths shared by source entry and the installed Windows executable."""
from __future__ import annotations

import os
from pathlib import Path
import sys


def default_data_dir() -> Path:
    """Keep user data outside the program installation when frozen."""
    if getattr(sys, 'frozen', False):
        local_app_data = os.environ.get('LOCALAPPDATA')
        base = Path(local_app_data) if local_app_data else Path.home() / 'AppData' / 'Local'
        return base / 'ResearchPortfolioManager' / 'user_data'
    return Path(__file__).resolve().parent / 'user_data'


def restore_launch_command(data_dir: str | Path) -> str:
    """PowerShell launch command for the restored data directory."""
    quoted = lambda value: "'" + str(value).replace("'", "''") + "'"
    executable = quoted(sys.executable)
    target = quoted(data_dir)
    if getattr(sys, 'frozen', False):
        return f'& {executable} --data-dir {target}'
    entry = Path(__file__).resolve().parent / 'main.py'
    return f'& {executable} {quoted(entry)} --data-dir {target}'
