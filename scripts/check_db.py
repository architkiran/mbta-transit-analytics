import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.environ["PG_URL"])

with engine.connect() as conn:
    row = conn.execute(text("SELECT current_user, current_database()")).one()
    print(f"Connected as {row[0]} to database {row[1]}")
