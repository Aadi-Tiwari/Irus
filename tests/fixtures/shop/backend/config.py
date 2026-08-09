import os

DATABASE_URL = os.environ["DATABASE_URL"]
PORT = os.getenv("PORT", "8000")
SENTRY = os.environ.get("SENTRY_DSN", "")
