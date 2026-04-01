#!/usr/bin/env python
"""CLI script to seed the travel planner database with sample data.

Usage:
    python scripts/seed_db.py              # skip if data already exists
    python scripts/seed_db.py --force      # re-seed even if data exists
"""
import argparse
import sys
from pathlib import Path

# Make sure src/ is on the path when run from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from app.database import SessionLocal, init_db
from app.seed import seed_database
import app.models  # noqa: F401 — register models with Base.metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the travel planner database")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-seed even when rows already exist",
    )
    args = parser.parse_args()

    init_db()

    db = SessionLocal()
    try:
        inserted = seed_database(db, skip_if_exists=not args.force)
        if inserted == 0:
            print("Seed skipped — database already contains data. Use --force to re-seed.")
        else:
            print(f"Seeded {inserted} travel plan(s) successfully.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
