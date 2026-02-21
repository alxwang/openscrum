import urllib.request
import json
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

req = urllib.request.Request(
    'http://localhost:8000/v1/chat/completions', 
    data=json.dumps({
        "model": "gpt-4",
        "messages": [
            {"role": "user", "content": "Please manually invoke the extract_api_routes and extract_db_schemas tools for me."}
        ]
    }).encode('utf-8'),
    headers={'Content-Type': 'application/json'}
)
try:
    with urllib.request.urlopen(req, context=ctx) as response:
        print(response.read().decode('utf-8'))
except Exception as e:
    print(f"Error: {e}")
