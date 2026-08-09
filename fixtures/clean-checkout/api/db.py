import os

DATABASE_URL = os.environ["DATABASE_URL"]
POOL_SIZE = int(os.getenv("POOL_SIZE", "5"))
