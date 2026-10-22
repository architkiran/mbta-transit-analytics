"""Project settings, read from the environment (.env locally). No secrets in code."""
import os

from dotenv import load_dotenv

load_dotenv()

PG_URL = os.environ["PG_URL"]
