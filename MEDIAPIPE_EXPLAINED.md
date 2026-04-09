# 📚 Giải Thích: vision_bundle.js

## ❓ vision_bundle.js là gì?

**MediaPipe Tasks Vision** - Thư viện JavaScript từ Google để:
- 👋 Nhận dạng cử chỉ tay (gesture recognition)
- 🖐️ Theo dõi bàn tay (hand tracking) - 21 điểm landmarks
- 👆 Phát hiện ngón tay (finger detection)
- ✌️ Nhận dạng ký hiệu: Victory, Open Palm, Pointing, v.v.

Kích thước: **~8-10 MB**

---

## 🌐 Đang Load Từ Đâu?

### KHÔNG có trong project của bạn!

Đang load từ **CDN** (Content Delivery Network):
```
https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/vision_bundle.js
```

### Flow khi mở trang:

```
1. User mở: https://192.168.1.22:5000
2. Browser load HTML từ resfes.py
3. HTML có dòng:
   <script src="https://cdn.jsdelivr.net/npm/.../vision_bundle.js">
4. Browser tự động download từ CDN
5. MediaPipe ready → Gesture control hoạt động!
```

---

## ✅ Có Cần Tải Về Project?

### KHÔNG CẦN! 

**Lý do:**

1. **CDN nhanh hơn**
   - Servers CDN ở khắp thế giới
   - Browser tự động chọn server gần nhất
   - Faster than local file

2. **Tiết kiệm dung lượng**
   - vision_bundle.js: ~8-10 MB
   - Không cần commit vào Git
   - Project gọn nhẹ

3. **Luôn cập nhật**
   - Dùng `@latest` → version mới nhất
   - Không cần update thủ công
   - Bug fixes tự động

4. **Browser cache**
   - Lần đầu: download từ CDN
   - Lần sau: dùng cache → instant load

---

## 📁 Files Trong Project (Hiện Tại)

```
D:\FPT\ResFes2026\
├── resfes.py              ← Server Python (chính)
├── vision_module.py       ← AI processing (Groq)
├── test_camera.html       ← Test camera
├── cert.pem, key.pem      ← HTTPS certificates
├── static/
│   ├── app.js             ← JavaScript cho app cũ
│   ├── index.html         ← Giao diện web cũ
│   ├── hand_controller.html
│   └── ar_glasses_full.html
└── [KHÔNG CÓ vision_bundle.js]  ← Load từ CDN!
```

---

## 🔄 Cách Hoạt Động

### resfes.py (trang chính):

```html
<!-- Load MediaPipe từ CDN -->
<script src="https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/vision_bundle.js"></script>

<script type="module">
  // MediaPipe đã load → dùng ngay
  let HandLandmarker = window.HandLandmarker;
  let GestureRecognizer = window.GestureRecognizer;
  
  // Init MediaPipe
  const vision = await FilesetResolver.forVisionTasks(...);
  handLandmarker = await HandLandmarker.createFromOptions(vision, {...});
  
  // Bắt đầu nhận dạng cử chỉ!
</script>
```

### test_camera.html:

```html
<!-- KHÔNG load MediaPipe -->
<!-- Chỉ test camera thuần -->
<script>
  // Chỉ dùng getUserMedia
  const stream = await navigator.mediaDevices.getUserMedia({video: true});
</script>
```

---

## 🔍 Kiểm Tra MediaPipe Đã Load

Mở Console (F12) trên trang chính, gõ:

```javascript
// Check 1: Script đã load?
console.log(window.HandLandmarker);
// Output: function HandLandmarker() {...} hoặc undefined

// Check 2: MediaPipe globals
console.log(window.__mpLoaded);
// Output: true (đã load) hoặc false

// Check 3: Version info
console.log(typeof FilesetResolver);
// Output: "function" (OK) hoặc "undefined" (lỗi)
```

---

## 🚨 Khi Nào Thấy Lỗi?

### Lỗi: "failed to load resource: vision_bundle.js"

**Nguyên nhân:**
- CDN path sai (đã fix: dùng `@latest`)
- Không có internet
- Firewall chặn CDN
- Browser offline mode

**Giải pháp:**
- ✅ Đã fix: dùng `@latest` thay vì version cụ thể
- Kiểm tra internet connection
- Tắt firewall/antivirus thử

**Fallback:**
- Code đã có fallback: nếu CDN fail → gesture tắt
- Vẫn dùng được nút bấm và giọng nói!

---

## 💡 Nếu Muốn Lưu Local (Không Khuyến Khích)

Nếu thực sự muốn tải về (không nên):

```bash
# Tải vision_bundle.js
curl https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/vision_bundle.js -o static/vision_bundle.js

# Tải wasm files
mkdir static/wasm
curl https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm/vision_wasm_internal.js -o static/wasm/vision_wasm_internal.js
curl https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm/vision_wasm_internal.wasm -o static/wasm/vision_wasm_internal.wasm
# ... còn nhiều files khác

# Sửa resfes.py
<script src="/static/vision_bundle.js"></script>
```

**Nhược điểm:**
- Tốn ~50MB với tất cả wasm files
- Phải update thủ công
- Chậm hơn CDN
- Phức tạp khi deploy

**→ KHÔNG NÊN LÀM!** Để CDN lo.

---

## 📊 Tóm Tắt

| | vision_bundle.js |
|---|---|
| **Là gì?** | Thư viện MediaPipe (Google) cho gesture control |
| **Kích thước** | ~8-10 MB |
| **Đang ở đâu?** | CDN - không trong project |
| **Có cần tải?** | ❌ KHÔNG - load từ CDN tự động |
| **Khi nào dùng?** | Chỉ trang chính (/) - gesture control |
| **Test page?** | Không dùng - chỉ test camera thuần |
| **Đã fix lỗi?** | ✅ Dùng @latest thay vì version cũ |

---

## ✅ Kết Luận

**vision_bundle.js:**
- ❌ KHÔNG có trong project
- ✅ Load từ CDN tự động
- ✅ KHÔNG cần tải về
- ✅ Đã hoạt động OK với `@latest`

**Bạn không cần làm gì cả!** Để CDN tự động load. 🚀
