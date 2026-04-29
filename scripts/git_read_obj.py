import sys, zlib
p = sys.argv[1]
with open(p, 'rb') as f:
    data = f.read()
try:
    out = zlib.decompress(data)
    print(out.decode('utf-8', errors='replace'))
except Exception as e:
    print('decompress error', e)
    sys.exit(1)
