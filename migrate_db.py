"""
Migration script to add skill columns to existing LEX_PLAYERS table
Run this once to update your database schema
"""
import os
import dotenv
from sqlalchemy import create_engine, text

dotenv.load_dotenv()

DATABASE_URL = os.environ.get("SUPABASE_CONN_STR")
if not DATABASE_URL:
    print("ERROR: SUPABASE_CONN_STR environment variable is not set!")
    raise SystemExit(1)

engine = create_engine(DATABASE_URL)

# SQL commands to add new columns
migrations = [
    'ALTER TABLE "LEX_PLAYERS" ADD COLUMN IF NOT EXISTS skill DOUBLE PRECISION',
    'ALTER TABLE "LEX_PLAYERS" ADD COLUMN IF NOT EXISTS "skillUncertainty" DOUBLE PRECISION',
    'ALTER TABLE "LEX_PLAYERS" ADD COLUMN IF NOT EXISTS "lastStatsUpdate" TIMESTAMP'
]

print("Starting database migration...")
with engine.connect() as conn:
    for migration in migrations:
        try:
            print(f"Executing: {migration}")
            conn.execute(text(migration))
            conn.commit()
            print("✓ Success")
        except Exception as e:
            print(f"✗ Error: {e}")
            conn.rollback()

print("\nMigration complete!")
print("The following columns have been added to LEX_PLAYERS:")
print("  - skill (DOUBLE PRECISION)")
print("  - skillUncertainty (DOUBLE PRECISION)")
print("  - lastStatsUpdate (TIMESTAMP)")
