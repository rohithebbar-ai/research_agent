"""
Centralized configuration, loaded once from .env.

Import `settings` from this module everywhere instead of reading
os.environ directly — keeps all config in one place, and fails fast
at import time if something required is missing, rather than failing
deep inside an agent call with a confusing error.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value

@dataclass(frozen=True)
class Settings:
    # cosmos db
    cosmos_endpoint: str
    cosmos_key: str
    cosmos_database: str

    # Azure openai
    azure_openai_endpoint: str
    azure_openai_key: str
    azure_openai_chat_deployment: str
    azure_openai_embedding_deployment: str
    azure_openai_api_version: str

    # project wide constants 
    embedding_dimensions: int = 512
    chunk_size_tokens: int = 500
    chunk_overlap_tokens: int = 50

    # WhatsApp — optional for now, used later by channels/whatsapp.py
    whatsapp_verify_token: str | None = None
    whatsapp_app_secret: str | None = None
    whatsapp_access_token: str | None = None


def load_settings() -> Settings:
    return Settings(
        cosmos_endpoint=_require("COSMOS_ENDPOINT"),
        cosmos_key=_require("COSMOS_KEY"),
        cosmos_database=_require("COSMOS_DATABASE"),
        azure_openai_endpoint=_require("AZURE_OPENAI_ENDPOINT"),
        azure_openai_key=_require("AZURE_OPENAI_KEY"),
        azure_openai_chat_deployment=_require("AZURE_OPENAI_CHAT_DEPLOYMENT"),
        azure_openai_embedding_deployment=_require("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
        azure_openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        whatsapp_verify_token=os.getenv("WHATSAPP_VERIFY_TOKEN"),
        whatsapp_app_secret=os.getenv("WHATSAPP_APP_SECRET"),
        whatsapp_access_token=os.getenv("WHATSAPP_ACCESS_TOKEN"),
    )

settings = load_settings()