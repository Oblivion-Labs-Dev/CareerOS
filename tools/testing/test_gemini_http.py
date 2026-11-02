import os
import httpx
from dotenv import load_dotenv
load_dotenv('.env')
load_dotenv('apps/api/.env')
api_key = os.environ.get('GEMINI_API_KEY')
url = f'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'
headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
payload = {
    'model': 'gemini-2.5-flash',
    'messages': [{'role': 'user', 'content': 'Hello, reply with JSON: [\"ok\"]'}]
}
try:
    resp = httpx.post(url, headers=headers, json=payload, timeout=20)
    print('Status:', resp.status_code)
    print('Response:', resp.text[:400])
except Exception as e:
    print('Error:', e)
