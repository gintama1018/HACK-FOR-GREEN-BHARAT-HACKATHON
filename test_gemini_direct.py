import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
key = os.getenv('GEMINI_API_KEY')
print(f"Key loaded: {'YES' if key else 'NO'} (Length: {len(key) if key else 0})")

if not key:
    print("NO KEY FOUND")
    exit(1)

genai.configure(api_key=key)

try:
    print("Testing basic generation...")
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content("Hello, reply with exactly 'OK'")
    print("Text response:", response.text)
    
    print("Testing image extraction...")
    with open("mcd_bin_test.jpg", "rb") as f:
        image_bytes = f.read()
        
    response2 = model.generate_content([
        "Extract the MCD dustbin ID from this image. Return ONLY the ID string.",
        {"mime_type": "image/jpeg", "data": image_bytes},
    ])
    print("Image response:", response2.text)
except Exception as e:
    print(f"Error: {e}")
