import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from functools import lru_cache

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
load_dotenv(HERE / ".env")

def now():
    return datetime.now(timezone.utc)

@lru_cache
def database():
    from pymongo import MongoClient
    return MongoClient(os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017"),
                       serverSelectionTimeoutMS=5000)[os.getenv("MONGO_DB", "campusiq")]

def store():
    path = Path(os.getenv("DOCUMENT_STORE", "../var/documents"))
    return (HERE / path).resolve()

def secret():
    value = os.getenv("INTERNAL_SECRET", "")
    if len(value) < 32:
        raise RuntimeError("Configure INTERNAL_SECRET with at least 32 random characters.")
    return value

