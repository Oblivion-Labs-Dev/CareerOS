import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from dotenv import load_dotenv
load_dotenv(".env")
load_dotenv("apps/api/.env")

from app.services.application_assistant.llm_client import create_llm_client

async def test_llm():
    settings = {
        "llm": {
            "enabled": True,
            "provider": "ollama",
            "model": "mistral-small3.2:24b",
            "baseUrl": "http://localhost:11434/v1",
            "timeout": 30,
            "maxRetries": 1,
        }
    }
    client = create_llm_client(settings)
    print("Testing client with model:", client.model, "fallback:", client.fallback.model if client.fallback else None)
    res = await client.complete("Hello, return JSON: {\"status\": \"ok\"}")
    print("Result:", res)

if __name__ == "__main__":
    asyncio.run(test_llm())
