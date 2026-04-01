import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./travel_planner.db")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
