import sys, base64
sys.path.insert(0, 'd:/FPT/Application/app/src/main/python')
import resfes
app = resfes.app
client = app.test_client()

r = client.post('/analyze', json={'image': 123})
print('TEST_INVALID_TYPE', r.status_code)
print(r.get_data(as_text=True))

big = 'A' * (resfes._ANALYZE_IMAGE_MAX_CHARS + 1)
r = client.post('/analyze', json={'image': big})
print('TEST_OVERSIZE', r.status_code)
print(r.get_data(as_text=True))

b64 = base64.b64encode(b'hello').decode()
r = client.post('/analyze', json={'image': b64})
print('TEST_VALID_BUT_GROQ_MISSING', r.status_code)
print(r.get_data(as_text=True))
