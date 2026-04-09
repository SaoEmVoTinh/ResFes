[app]

title = ResFes AR
package.name = resfesar
package.domain = com.resfes.ar

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,html,txt,pem
source.exclude_dirs = tests, bin, venv, .venv, __pycache__, .git, knowledge, app_data

version = 0.1

# ── Requirements ──────────────────────────────────────────────────────────────
# Chỉ dùng các package có recipe trong python-for-android
requirements = python3,kivy,flask,flask-cors,pyopenssl,python-dotenv,requests,urllib3,pillow,groq

# ── Android ───────────────────────────────────────────────────────────────────
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,CAMERA,RECORD_AUDIO

android.api = 33
android.minapi = 26
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a

android.allow_backup = True

# Giữ màn hình sáng khi server đang chạy
android.wakelock = True

# Orientation
orientation = portrait
fullscreen = 0

# ── p4a ───────────────────────────────────────────────────────────────────────
p4a.branch = master

# ── Buildozer ─────────────────────────────────────────────────────────────────
[buildozer]
log_level = 2
warn_on_root = 1
