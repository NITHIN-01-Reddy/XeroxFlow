import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-this-secret")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'xeroxflow.db'}")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "15"))
