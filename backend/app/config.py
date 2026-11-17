"""
config.py - Central Configuration for Fresher Jobs India
"""

import os

# --- General & Service ---
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "beep-fresher-jobs")
REGION = os.environ.get("GCP_REGION", "asia-south1")
PORT = int(os.environ.get("PORT", "8080"))
ENV = os.environ.get("ENV", "development")

# User agent for compliant API calls & scraping
USER_AGENT = os.environ.get(
    "USER_AGENT",
    "FresherJobsIndiaBot/1.0 (India fresher jobs aggregator; open education assessment; contact: team@example.com)"
)

# --- Database Configuration ---
# Supports standard DATABASE_URL, Cloud SQL Unix Socket, or component env vars
DATABASE_URL = os.environ.get("DATABASE_URL")

DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "jobs_db")
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
INSTANCE_CONNECTION_NAME = os.environ.get("INSTANCE_CONNECTION_NAME")  # e.g., project:asia-south1:instance

def get_database_url() -> str:
    """Returns database connection URL or constructs one from Cloud SQL / local variables."""
    if DATABASE_URL:
        return DATABASE_URL
    if INSTANCE_CONNECTION_NAME:
        # Cloud Run connects to Cloud SQL via Unix socket
        return f"postgresql://{DB_USER}:{DB_PASSWORD}@/{DB_NAME}?host=/cloudsql/{INSTANCE_CONNECTION_NAME}"
    return f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# --- Canonical Taxonomies ---
CANONICAL_ROLES = [
    "SDE",
    "Data/ML",
    "Design",
    "Marketing",
    "Sales",
    "Ops",
    "Finance",
    "HR",
    "Other"
]

CANONICAL_CITIES = [
    "Bangalore",
    "Mumbai",
    "Pune",
    "Hyderabad",
    "Gurugram",
    "Delhi",
    "Noida",
    "Chennai",
    "Kolkata",
    "Ahmedabad",
    "Jaipur",
    "Kochi",
    "Coimbatore",
    "Remote"
]

# --- LLM & Vertex AI Settings ---
VERTEX_AI_MODEL = os.environ.get("VERTEX_AI_MODEL", "gemini-2.0-flash-lite-preview-02-05")
VERTEX_AI_FALLBACK_MODEL = os.environ.get("VERTEX_AI_FALLBACK_MODEL", "gemini-1.5-flash")

# Model pricing in USD per 1M tokens
PRICING_PER_MILLION = {
    "gemini-2.0-flash-lite-preview-02-05": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-1.5-flash-8b": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.0-flash": {"input": 0.15, "output": 0.60},
    "default": {"input": 0.10, "output": 0.40}
}

