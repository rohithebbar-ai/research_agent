"""Set dummy env vars before any test imports config.py (which fails fast if unset)."""

import os

for _k, _v in {
    "COSMOS_ENDPOINT": "https://cosmos.test",
    "COSMOS_KEY": "dGVzdC1rZXk=",
    "COSMOS_DATABASE": "test-db",
    "AZURE_OPENAI_ENDPOINT": "https://aoai.test",
    "AZURE_OPENAI_KEY": "test-key",
    "AZURE_OPENAI_CHAT_DEPLOYMENT": "test-chat",
}.items():
    os.environ.setdefault(_k, _v)
