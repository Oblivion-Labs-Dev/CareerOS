import os, httpx
from dotenv import load_dotenv
load_dotenv('.env')
load_dotenv('apps/api/.env')
api_key = os.environ.get('GEMINI_API_KEY')
url = 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'
headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
payload = {
    'model': 'gemini-2.5-flash',
    'messages': [{'role': 'user', 'content': 'Respond with valid JSON: [\"ok\"]'}]
}
# Try models:
for m in ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-flash-latest']:
    payload['model'] = m
    resp = httpx.post(url, headers=headers, json=payload, timeout=20)
    print(m, resp.status_code, resp.text[:100])
