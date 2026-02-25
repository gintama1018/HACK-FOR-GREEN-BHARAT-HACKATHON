import requests
resp = requests.post('http://localhost:8000/api/report/dustbin/detect')
print("Empty POST:", resp.status_code, resp.text)

resp2 = requests.post('http://localhost:8000/api/report/dustbin/detect', files={'file': ('', '')})
print("Empty File POST:", resp2.status_code, resp2.text)
