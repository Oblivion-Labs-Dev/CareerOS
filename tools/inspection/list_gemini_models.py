import os
import httpx
from dotenv import load_dotenv
load_dotenv('.env')
load_dotenv('apps/api/.env')

api_key = os.environ.get('GEMINI_API_KEY')
url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
resp = httpx.get(url)
print("Status:", resp.status_code)
if resp.status_code == 200:
    models = [m['name'] for m in resp.json().get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
    print("Supported models:", models[:10])
else:
    print("Error:", resp.text)
