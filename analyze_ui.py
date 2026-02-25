import base64
import requests
import os
import json
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv('GEMINI_API_KEY')

# We'll use Gemini Vision to read the hex codes straight from the images
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={API_KEY}"
headers = {'Content-Type': 'application/json'}

def analyze_image(path, prompt):
    with open(path, "rb") as f:
        img_data = base64.b64encode(f.read()).decode('utf-8')
        
    payload = {
      "contents": [{
        "parts": [
          {"text": prompt},
          {"inline_data": {"mime_type": "image/png", "data": img_data}}
        ]
      }]
    }
    resp = requests.post(url, headers=headers, json=payload)
    print(f"--- Analysis for {os.path.basename(path)} ---")
    try:
        print(resp.json()['candidates'][0]['content']['parts'][0]['text'])
    except Exception as e:
        print("Error reading response:", resp.text)

prompt = """
Analyze this UI mockup and extract the exact CSS properties. I need:
1. The EXACT hex code for the main background (outermost dark area).
2. The EXACT hex code for the inner component backgrounds (the cards/panels).
3. The EXACT hex code for the bright blue primary button/accents.
4. The estimated border-radius (in px) used on the cards.
5. The EXACT hex code for the borders surrounding the cards.
Be as precise as possible. Return just the values in a list.
"""

# The user attached the images, let's find them
img_dir = "C:/Users/hp/.gemini/antigravity/brain/62205b6b-ef4f-4899-b6a5-255a0e8a4cab"
for f in os.listdir(img_dir):
    if f.startswith("media__") and f.endswith(".png"): # Assuming the attached images were saved here
        analyze_image(os.path.join(img_dir, f), prompt)
