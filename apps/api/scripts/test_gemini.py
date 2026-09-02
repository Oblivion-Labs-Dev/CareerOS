import asyncio
import sys
from pathlib import Path
import httpx

api_key = ""

async def test_gemini():
    print(f"Testing Gemini API Key with OpenAI compatibility endpoint...", flush=True)
    url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gemini-2.0-flash",
        "messages": [
            {"role": "user", "content": "Return valid JSON: {\"status\": \"ok\", \"engine\": \"Gemini connected\"}"}
        ],
        "temperature": 0.2
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=payload, headers=headers)
        print("Status code:", resp.status_code)
        print("Response text:", resp.text)

if __name__ == "__main__":
    asyncio.run(test_gemini())
