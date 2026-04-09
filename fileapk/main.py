"""
main.py — ResFes AR Launcher (Kivy + Android)
==============================================
Chạy Flask server (resfes.py) trong background thread thay vì subprocess.
Hiển thị IP + URL để kính/điện thoại kết nối.
Upload tài liệu vào Knowledge Base local.
"""

import os
import socket
import threading
import webbrowser
from pathlib import Path

import urllib3
from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

# ── Paths & env ───────────────────────────────────────────────────────────────

PROJECT_DIR = Path(__file__).resolve().parent
PORT = 5050

# Android: dùng app_data trong thư mục app; desktop: cạnh main.py
try:
    from android.storage import app_storage_path  # type: ignore
    DATA_DIR = Path(app_storage_path()) / "resfes_data"
except Exception:
    DATA_DIR = PROJECT_DIR / "app_data"

os.environ["RESFES_DATA_DIR"] = str(DATA_DIR)
DATA_DIR.mkdir(parents=True, exist_ok=True)

import knowledge_base as kb  # noqa: E402  (needs env set first)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Flask server runner ───────────────────────────────────────────────────────

_flask_started = False
_flask_scheme = "http"


def _run_flask():
    """Chạy Flask app từ resfes.py trong thread hiện tại."""
    global _flask_scheme

    # Import resfes module (không chạy __main__)
    import importlib.util, sys

    spec = importlib.util.spec_from_file_location(
        "resfes", str(PROJECT_DIR / "resfes.py")
    )
    resfes = importlib.util.module_from_spec(spec)
    sys.modules["resfes"] = resfes
    spec.loader.exec_module(resfes)

    flask_app = resfes.app  # Flask instance

    # Thử HTTPS trước
    cert_file = str(PROJECT_DIR / "cert.pem")
    key_file  = str(PROJECT_DIR / "key.pem")

    if os.path.exists(cert_file) and os.path.exists(key_file):
        _flask_scheme = "https"
        ssl_ctx = (cert_file, key_file)
    else:
        # Tự tạo cert nếu có pyOpenSSL
        try:
            local_ip = _get_ip()
            resfes.create_self_signed_cert(cert_file, key_file, local_ip)
            _flask_scheme = "https"
            ssl_ctx = (cert_file, key_file)
        except Exception:
            _flask_scheme = "http"
            ssl_ctx = None

    flask_app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
        ssl_context=ssl_ctx,
    )


def _get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _detect_file_type(file_name):
    ext = Path(file_name).suffix.lower()
    if ext == ".txt":   return "txt"
    if ext == ".pdf":   return "pdf"
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}: return "image"
    return "txt"


# ── Kivy UI ───────────────────────────────────────────────────────────────────

class ResFesManager(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", spacing=8, padding=12, **kwargs)
        self._server_thread = None

        # Title
        self.add_widget(Label(
            text="🥽 ResFes AR — Knowledge Host",
            size_hint_y=None, height=40, bold=True, font_size="17sp"
        ))

        # Status
        self.lbl_status = Label(
            text="⏳ Đang khởi động server...",
            size_hint_y=None, height=28, font_size="13sp"
        )
        self.add_widget(self.lbl_status)

        # URL
        self.lbl_url = Label(
            text="AR URL: đang lấy IP...",
            size_hint_y=None, height=28, font_size="13sp", color=(0.32, 0.85, 0.75, 1)
        )
        self.add_widget(self.lbl_url)

        # Buttons
        btn_row = BoxLayout(size_hint_y=None, height=46, spacing=6)
        btn_open = Button(text="🌐 Mở AR")
        btn_open.bind(on_release=lambda _: self._open_browser())
        btn_upload = Button(text="📁 Upload tài liệu")
        btn_upload.bind(on_release=lambda _: self._open_upload())
        btn_refresh = Button(text="🔄 Làm mới")
        btn_refresh.bind(on_release=lambda _: self._refresh_docs())
        btn_row.add_widget(btn_open)
        btn_row.add_widget(btn_upload)
        btn_row.add_widget(btn_refresh)
        self.add_widget(btn_row)

        # Doc count
        self.lbl_docs = Label(
            text="Tài liệu: 0", size_hint_y=None, height=26, font_size="12sp"
        )
        self.add_widget(self.lbl_docs)

        # Doc list
        scroll = ScrollView()
        self.docs_box = BoxLayout(
            orientation="vertical", spacing=5, size_hint_y=None
        )
        self.docs_box.bind(minimum_height=self.docs_box.setter("height"))
        scroll.add_widget(self.docs_box)
        self.add_widget(scroll)

        # Auto-start
        Clock.schedule_once(lambda _dt: self._start_server(), 0.3)
        Clock.schedule_once(lambda _dt: self._refresh_docs(), 0.5)
        Clock.schedule_interval(self._poll_server, 3.0)

    # ── Server ────────────────────────────────────────────────────────────────

    def _start_server(self):
        global _flask_started
        if _flask_started:
            return
        _flask_started = True
        t = threading.Thread(target=_run_flask, daemon=True)
        t.start()
        self._server_thread = t
        self._set_status("⏳ Server đang khởi động...")

    def _poll_server(self, _dt):
        """Kiểm tra server có online chưa (chạy trong background thread)."""
        threading.Thread(target=self._check_server, daemon=True).start()

    def _check_server(self):
        import urllib.request, ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        for scheme in ("https", "http"):
            try:
                url = f"{scheme}://127.0.0.1:{PORT}/health"
                urllib.request.urlopen(url, timeout=1.5, context=ctx if scheme == "https" else None)
                ip = _get_ip()
                self._set_status("✅ Server online")
                self._set_url(f"{scheme}://{ip}:{PORT}")
                return
            except Exception:
                continue
        self._set_status("⏳ Server đang khởi động...")

    @mainthread
    def _set_status(self, text):
        self.lbl_status.text = text

    @mainthread
    def _set_url(self, url):
        self.lbl_url.text = f"AR URL: {url}"

    def _open_browser(self):
        ip = _get_ip()
        url = f"{_flask_scheme}://{ip}:{PORT}"
        webbrowser.open(url)

    # ── Documents ─────────────────────────────────────────────────────────────

    def _refresh_docs(self):
        threading.Thread(target=self._load_docs_bg, daemon=True).start()

    def _load_docs_bg(self):
        docs = kb.list_documents()
        self._render_docs(docs)

    @mainthread
    def _render_docs(self, docs):
        self.lbl_docs.text = f"Tài liệu: {len(docs)}"
        self.docs_box.clear_widgets()

        if not docs:
            self.docs_box.add_widget(
                Label(text="Chưa có tài liệu nào", size_hint_y=None, height=36,
                      color=(0.6, 0.6, 0.6, 1))
            )
            return

        for doc in docs:
            row = BoxLayout(size_hint_y=None, height=44, spacing=6)
            subject = doc.get("subject") or "Không có môn"
            size_kb = (doc.get("file_size") or 0) / 1024
            lbl = Label(
                text=f"📄 {doc['original_name']}  [{subject}]  {size_kb:.1f}KB",
                halign="left", valign="middle", font_size="11sp"
            )
            lbl.bind(size=lambda w, _: setattr(w, "text_size", w.size))
            del_btn = Button(text="Xóa", size_hint_x=None, width=70,
                             background_color=(0.8, 0.2, 0.2, 1))
            doc_id = doc["id"]
            del_btn.bind(on_release=lambda _, did=doc_id: self._delete_doc(did))
            row.add_widget(lbl)
            row.add_widget(del_btn)
            self.docs_box.add_widget(row)

    def _delete_doc(self, doc_id):
        kb.delete_document(doc_id)
        self._refresh_docs()

    # ── Upload popup ──────────────────────────────────────────────────────────

    def _open_upload(self):
        root = BoxLayout(orientation="vertical", spacing=8, padding=8)

        chooser = FileChooserListView(path=str(Path.home()))
        chooser.filters = ["*.pdf", "*.txt", "*.jpg", "*.jpeg", "*.png"]
        root.add_widget(chooser)

        subject_in = TextInput(
            hint_text="Môn học (vd: Toán, Lý, Hóa...)",
            multiline=False, size_hint_y=None, height=38
        )
        root.add_widget(subject_in)

        btn_row = BoxLayout(size_hint_y=None, height=44, spacing=6)
        btn_import = Button(text="✅ Import")
        btn_close  = Button(text="Đóng")
        btn_row.add_widget(btn_import)
        btn_row.add_widget(btn_close)
        root.add_widget(btn_row)

        popup = Popup(
            title="Upload tài liệu vào Knowledge Base",
            content=root, size_hint=(0.96, 0.92)
        )

        def do_import(_):
            selected = chooser.selection
            if not selected:
                self._set_status("⚠️ Chưa chọn file!")
                return
            count = 0
            for fp in selected:
                try:
                    with open(fp, "rb") as f:
                        data = f.read()
                    kb.save_file(
                        file_data=data,
                        original_name=Path(fp).name,
                        file_type=_detect_file_type(fp),
                        subject=subject_in.text.strip(),
                    )
                    count += 1
                except Exception as e:
                    self._set_status(f"❌ Lỗi: {e}")
            self._set_status(f"✅ Đã import {count} file")
            self._refresh_docs()
            popup.dismiss()

        btn_import.bind(on_release=do_import)
        btn_close.bind(on_release=lambda _: popup.dismiss())
        popup.open()


class ResFesApp(App):
    def build(self):
        return ResFesManager()


if __name__ == "__main__":
    ResFesApp().run()
