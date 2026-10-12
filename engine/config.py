"""Where things live on disk, and settings read from the environment."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")  # variables already set in the environment win

# COURSE_MONITOR_DB moves the database, e.g. onto a Docker volume
DB_PATH = Path(os.environ.get("COURSE_MONITOR_DB") or ROOT / "course_monitor.db")
