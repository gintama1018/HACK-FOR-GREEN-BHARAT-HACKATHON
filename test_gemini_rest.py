import os
import requests
import base64
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv('GEMINI_API_KEY')

if not API_KEY:
    print("NO API KEY")
    exit(1)

with open("mcd_bin_test.jpg", "rb") as f:
    img_data = base64.b64encode(f.read()).decode('utf-8')

url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={API_KEY}"
headers = {'Content-Type': 'application/json'}
payload = {
  "contents": [{
    "parts": [
      {"text": "Extract the MCD dustbin ID from this image. Return ONLY the ID string."},
      {"inline_data": {"mime_type": "image/jpeg", "data": img_data}}
    ]
  }]
}

print("SENDING DIRECT REST REQUEST...")
try:
    resp = requests.post(url, headers=headers, json=payload, timeout=10)
    print("STATUS:", resp.status_code)
    print("RESPONSE:", resp.json())
except Exception as e:
    print("ERROR:", e)
