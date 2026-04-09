# 🔧 Debug Guide - Camera & Gesture Issues

## 🐛 Vấn đề đã fix

### ✅ Fix 1: Camera bị lật ngược
**Nguyên nhân:** CSS `transform: scaleX(-1)` mirror video cho TẤT CẢ camera, kể cả rear camera.

**Giải pháp:** Đã XÓA `scaleX(-1)` vì:
- Rear camera (`facingMode: environment`) KHÔNG cần mirror
- Chỉ front camera mới cần mirror
- Landmarks và video giờ đã khớp nhau

### ✅ Fix 2: Gesture không nhận diện được
**Nguyên nhân:** 
1. Ngưỡng confidence quá cao (0.6)
2. Thiếu debug logging
3. Mismatch giữa video display và landmark coordinates

**Giải pháp:**
1. Giảm confidence từ 0.6 → 0.4 (nhạy hơn)
2. Thêm debug logging console
3. Fix mirror để landmarks khớp với visual

---

## 🧪 Cách kiểm tra

### 1️⃣ Chạy server
```bash
python resfes.py
```

### 2️⃣ Mở trên điện thoại
- Laptop và phone cùng WiFi
- Truy cập: `https://192.168.x.x:5000`
- **Chấp nhận certificate warning** (quan trọng!)

### 3️⃣ Check Console (DevTools)
Mở DevTools trên điện thoại:
- Chrome Android: `chrome://inspect` hoặc `about:inspect`
- Safari iOS: Settings → Safari → Advanced → Web Inspector

**Logs cần thấy:**
```
✅ MediaPipe loaded via .mjs import
🎬 Starting camera...
✅ Camera permission granted!
✅ Camera started successfully
⏳ Initializing MediaPipe...
✅ Vision tasks loaded
✅ HandLandmarker ready
✅ GestureRecognizer ready
🚀 MediaPipe fully initialized!
🔄 Hand detection loop started
```

**Khi giơ tay lên:**
```
👋 Hand detected: YES
✋ Gesture: Open_Palm score: 0.89
```

### 4️⃣ Kiểm tra visual

**Camera:**
- [ ] Hình ảnh KHÔNG bị lật ngược
- [ ] Khi hướng camera sang trái, hình ảnh di chuyển sang trái (không ngược)
- [ ] Văn bản trên giấy đọc được (không mirror)

**Hand tracking:**
- [ ] Thấy các chấm xanh lá + đường nối trên tay
- [ ] Cursor xanh lá theo đầu ngón trỏ
- [ ] Chỉ tay sang trái → cursor sang trái (không ngược)

**Gestures:**
- [ ] ☝️ **Point** (chỉ 1 ngón): cursor di chuyển
- [ ] 🤏 **Pinch** (nhón 2 ngón): cursor nhỏ lại
- [ ] 🖐️ **Open Palm** (mở bàn tay): toast "🖐️ Giọng nói!"
- [ ] ✌️ **Victory** (chữ V): toast "✌️ Scan!"

---

## ❌ Nếu vẫn không hoạt động

### Lỗi: Camera không mở
```
❌ LỖI BẢO MẬT: Cần HTTPS!
```

**Fix:**
1. Check URL có `https://` (KHÔNG phải `http://`)
2. Chấp nhận certificate warning (click "Advanced" → "Proceed")
3. **RELOAD trang** (F5)
4. Check console log: `isSecureContext: true`

### Lỗi: MediaPipe không load
```
❌ MediaPipe load failed
```

**Fix:**
1. Check internet connection (cần CDN)
2. Thử reload trang
3. Check console có CORS errors không
4. Thử browser khác (Chrome/Safari)

### Lỗi: Hand không detect
```
👋 Hand detected: NO
```

**Check:**
1. Tay ở giữa camera (không quá gần/xa)
2. Lighting đủ sáng
3. Chỉ giơ 1 tay (code chỉ track 1 hand)
4. Giơ thẳng bàn tay, ngón tay rõ ràng
5. Video đang chạy (không bị freeze)

### Lỗi: Gesture không nhận
```
👋 Hand detected: YES
✋ Gesture:  score: undefined
```

**Try:**
1. Làm cử chỉ rõ ràng hơn, giữ 1-2 giây
2. Tay không bị che khuất
3. Victory (✌️): Chỉ 2 ngón trỏ + giữa, các ngón khác khép
4. Open Palm (🖐️): Mở hết 5 ngón
5. Pinch (🤏): Nhón ngón cái + trỏ sát nhau

---

## 📊 So sánh trước/sau

### ❌ TRƯỚC (lỗi)
- CSS: `transform: scaleX(-1)` → video mirror
- Confidence: `0.6` → khó detect
- Landmarks: không khớp với visual
- Debug: không có logs

### ✅ SAU (đã fix)
- CSS: KHÔNG mirror → video tự nhiên
- Confidence: `0.4` → dễ detect hơn
- Landmarks: khớp hoàn toàn
- Debug: full console logs

---

## 🎯 Expected behavior

Khi hoạt động ĐÚNG:
1. Camera mở, hình ảnh tự nhiên (không mirror)
2. Console logs "MediaPipe fully initialized"
3. Giơ tay → thấy chấm xanh + đường nối
4. Chỉ ngón trỏ → cursor xanh theo
5. Làm cử chỉ → toast hiện
6. Chỉ vào nút → hover effect
7. Nhón (pinch) → click nút

---

## 🆘 Nếu vẫn không xong

Chụp screenshot console logs và gửi lên để debug thêm!

Cần check:
- [ ] Full console output (từ đầu đến khi lỗi)
- [ ] Network tab (MediaPipe CDN requests)
- [ ] Camera permission status
- [ ] Browser & OS version
- [ ] WiFi connection stable
