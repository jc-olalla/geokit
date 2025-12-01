# src/geokit/config.py
from pathlib import Path
from dataclasses import dataclass
from .secrets import get_secret

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"

DEFAULT_CRS = "EPSG:28992"

@dataclass
class Credentials:
    db_user: str = get_secret("DB_USER")
    db_password: str = get_secret("DB_PASSWORD")
    internal_api_key: str = get_secret("INTERNAL_API_KEY")

CREDS = Credentials()

