import json
import urllib.request
import os

def test_ollama_mistral():
    print("Testing Ollama Mistral (mistral-small3.2:24b)...")
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=json.dumps({
            "model": "mistral-small3.2:24b",
            "prompt": "Say hello in 5 words",
            "stream": False
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print("SUCCESS! Mistral response:", data.get("response"))
            return True
    except Exception as e:
        print("FAILED Mistral:", e)
        return False

def test_gemini():
    print("\nTesting Gemini...")
    key = os.environ.get("GEMINI_API_KEY", "")
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        data=json.dumps({
            "model": "gemini-2.5-flash",
            "messages": [{"role": "user", "content": "Say hello in 5 words"}],
            "max_tokens": 50
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print("SUCCESS! Gemini response:", data["choices"][0]["message"]["content"])
            return True
    except Exception as e:
        print("FAILED Gemini:", e)
        return False

if __name__ == "__main__":
    m_ok = test_ollama_mistral()
    g_ok = test_gemini()
