import requests

url = 'http://localhost:8000/api/report/dustbin/detect'
try:
    with open('mcd_bin_test.jpg', 'rb') as f:
        print("Sending request to Gemini...")
        response = requests.post(url, files={'file': f})
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
except Exception as e:
    print(f"Error: {e}")
