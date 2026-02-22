import urllib.request
import urllib.error

req = urllib.request.Request(
    'http://127.0.0.1:8000/testpatch',
    data=b'{"mode":"edit"}',
    headers={'Content-Type': 'application/json'},
    method='POST'
)

try:
    res = urllib.request.urlopen(req)
    val = res.read().decode()
    with open('test_dict_out.txt', 'w') as f:
        f.write("OK: " + val)
except urllib.error.HTTPError as e:
    with open('test_dict_out.txt', 'w') as f:
        f.write("ERR: " + str(e.code) + " " + e.read().decode())
except Exception as e:
    with open('test_dict_out.txt', 'w') as f:
        f.write("EXC: " + str(e))
