import asyncio
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))
from dotenv import load_dotenv
load_dotenv(".env")
load_dotenv("apps/api/.env")

from app.services.application_assistant.llm_client import create_llm_client

async def test():
    # Force Gemini with gemini-2.5-flash or gemini-1.5-flash or gemini-2.0-flash
    for model_name in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash"]:
        gemini_client = create_llm_client({
            "llm": {
                "enabled": True,
                "provider": "gemini",
                "model": model_name,
                "timeout": 30,
            }
        })
        res = await gemini_client.complete("Respond ONLY with valid JSON: [\"hello\", \"world\"]")
        print(f"Model {model_name} result success={res.get('success')}: {res.get('data') or res.get('error')[:80]}")
        if res.get('success'):
            break

if __name__ == "__main__":
    asyncio.run(test())
