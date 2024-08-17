from dotenv import load_dotenv
import os

load_dotenv()

NOTION_SECRET_KEY = os.getenv("NOTION_SECRET_KEY")
LOG_LEVEL = os.getenv("LOG_LEVEL")
