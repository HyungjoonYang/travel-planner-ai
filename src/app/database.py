from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    _apply_migrations()


def _apply_migrations():
    """Apply incremental schema changes that create_all cannot handle (existing tables)."""
    with engine.connect() as conn:
        # #102: add label column to day_itineraries
        try:
            conn.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE day_itineraries ADD COLUMN label VARCHAR(200)"
                )
            )
            conn.commit()
        except Exception:
            pass  # column already exists — ignore
