import urllib.request
import urllib.error

req = urllib.request.Request(
    'http://127.0.0.1:8000/sessions/ses_0000009c231e890b8Aniw2bOnR',
    data=b'{"mode":"edit"}',
    headers={'Content-Type': 'application/json'},
    method='PATCH'
)

try:
    res = urllib.request.urlopen(req)
    val = res.read().decode()
    with open('test_out.txt', 'w') as f:
        f.write("OK: " + val)
except urllib.error.HTTPError as e:
    with open('test_out.txt', 'w') as f:
        f.write("ERR: " + str(e.code) + " " + e.read().decode())
except Exception as e:
    with open('test_out.txt', 'w') as f:
        f.write("EXC: " + str(e))
