#!/usr/bin/env python3
"""Debug startup script to list Flask routes"""

import os
import sys

os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.path.insert(0, r'd:\FPT\Application\app\src\main\python')

from resfes import app, start_resfes_server

print("\n" + "="*70)
print("[STARTUP] Flask Route Map:")
print("="*70)
for rule in app.url_map.iter_rules():
    print(f"{str(rule):50} → methods={rule.methods}")
print("="*70 + "\n")

print("[STARTUP] Looking for new endpoints:")
new_endpoints = ['/kb/statistics', '/extractor/health', '/db/cleanup', '/kb/documents/<']
for endpoint in new_endpoints:
    found = any(endpoint in str(rule) for rule in app.url_map.iter_rules())
    status = "✅" if found else "❌"
    print(f"  {status} {endpoint}")

print("\n[STARTUP] Starting Flask server...\n")
start_resfes_server()
