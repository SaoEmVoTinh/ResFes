import os
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path

import requests
import urllib3
from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

PROJECT_DIR = Path(__file__).resolve().parent
RESFES_FILE = PROJECT_DIR / "resfes.py"
PORT = 5050

# Shared data root for app manager + resfes.py + knowledge_base.py
DATA_DIR = Path(os.getenv("RESFES_DATA_DIR", str(PROJECT_DIR / "app_data"))).resolve()
os.environ["RESFES_DATA_DIR"] = str(DATA_DIR)

import knowledge_base as kb

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def detect_file_type(file_name):
    ext = Path(file_name).suffix.lower()
    if ext == ".txt":
        return "txt"
    if ext == ".pdf":
        return "pdf"
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        return "image"
    return "txt"


def get_local_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


class ResFesManager(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", spacing=8, padding=10, **kwargs)
        self.proc = None
        self.server_online = False
        self.server_scheme = "https"

        DATA_DIR.mkdir(parents=True, exist_ok=True)

        self.title = Label(
            text="ResFes Launcher - AR Host + Document Manager",
            size_hint_y=None,
            height=36,
            bold=True,
        )
        self.add_widget(self.title)

        self.status = Label(
            text="Server: starting...",
            size_hint_y=None,
            height=28,
        )
        self.add_widget(self.status)

        self.url_label = Label(
            text="AR URL: resolving...",
            size_hint_y=None,
            height=28,
        )
        self.add_widget(self.url_label)

        action_row = BoxLayout(size_hint_y=None, height=42, spacing=6)
        self.start_btn = Button(text="Start ResFes")
        self.start_btn.bind(on_release=lambda _x: self.start_server())
        self.stop_btn = Button(text="Stop ResFes")
        self.stop_btn.bind(on_release=lambda _x: self.stop_server())
        self.open_btn = Button(text="Open AR URL")
        self.open_btn.bind(on_release=lambda _x: self.open_ar_url())
        self.upload_btn = Button(text="Upload Document")
        self.upload_btn.bind(on_release=lambda _x: self.open_upload_popup())
        action_row.add_widget(self.start_btn)
        action_row.add_widget(self.stop_btn)
        action_row.add_widget(self.open_btn)
        action_row.add_widget(self.upload_btn)
        self.add_widget(action_row)

        self.subject_input = TextInput(
            hint_text="Subject (optional), example: Toan",
            multiline=False,
            size_hint_y=None,
            height=36,
        )
        self.add_widget(self.subject_input)

        self.docs_info = Label(text="Documents: 0", size_hint_y=None, height=26)
        self.add_widget(self.docs_info)

        self.scroll = ScrollView()
        self.docs_box = BoxLayout(orientation="vertical", spacing=6, size_hint_y=None)
        self.docs_box.bind(minimum_height=self.docs_box.setter("height"))
        self.scroll.add_widget(self.docs_box)
        self.add_widget(self.scroll)

        Clock.schedule_once(lambda _dt: self.start_server(), 0.2)
        Clock.schedule_once(lambda _dt: self.refresh_documents(), 0.3)
        Clock.schedule_interval(self.poll_server, 2.0)

    def _update_status(self, text):
        self.status.text = text

    def _env_for_resfes(self):
        env = os.environ.copy()
        env["RESFES_DATA_DIR"] = str(DATA_DIR)
        env["RESFES_KB_MODE"] = "local"
        return env

    def start_server(self):
        if self.proc and self.proc.poll() is None:
            self._update_status("Server: already running")
            return

        if not RESFES_FILE.exists():
            self._update_status("Server error: resfes.py not found")
            return

        self.proc = subprocess.Popen(
            [sys.executable, str(RESFES_FILE)],
            cwd=str(PROJECT_DIR),
            env=self._env_for_resfes(),
        )
        self._update_status("Server: launching resfes.py...")

    def stop_server(self):
        if not self.proc or self.proc.poll() is not None:
            self._update_status("Server: not running")
            return

        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self._update_status("Server: stopped")

    def _probe(self, scheme):
        url = f"{scheme}://127.0.0.1:{PORT}/health"
        try:
            res = requests.get(url, timeout=1.2, verify=False)
            return res.ok
        except Exception:
            return False

    def poll_server(self, _dt):
        https_ok = self._probe("https")
        http_ok = self._probe("http")
        self.server_online = https_ok or http_ok
        self.server_scheme = "https" if https_ok else "http"

        if self.server_online:
            ip = get_local_ip()
            self.url_label.text = f"AR URL: {self.server_scheme}://{ip}:{PORT}"
            self._update_status("Server: online")
        else:
            self._update_status("Server: offline or starting")

    def open_ar_url(self):
        ip = get_local_ip()
        url = f"{self.server_scheme}://{ip}:{PORT}"
        webbrowser.open(url)

    def refresh_documents(self):
        docs = kb.list_documents()
        self.docs_info.text = f"Documents: {len(docs)} | Data dir: {DATA_DIR}"
        self.docs_box.clear_widgets()

        if not docs:
            self.docs_box.add_widget(Label(text="No documents uploaded", size_hint_y=None, height=36))
            return

        for doc in docs:
            row = BoxLayout(size_hint_y=None, height=42, spacing=6)
            subject = doc.get("subject") or "No subject"
            size_kb = (doc.get("file_size") or 0) / 1024
            text = f"[{doc['id']}] {doc['original_name']} | {subject} | {size_kb:.1f} KB"
            lbl = Label(text=text, halign="left", valign="middle")
            lbl.bind(size=lambda inst, _v: setattr(inst, "text_size", inst.size))
            delete_btn = Button(text="Delete", size_hint_x=None, width=90)
            delete_btn.bind(on_release=lambda _x, doc_id=doc["id"]: self.delete_document(doc_id))
            row.add_widget(lbl)
            row.add_widget(delete_btn)
            self.docs_box.add_widget(row)

    def delete_document(self, doc_id):
        kb.delete_document(doc_id)
        self.refresh_documents()

    def open_upload_popup(self):
        root = BoxLayout(orientation="vertical", spacing=8, padding=8)
        chooser = FileChooserListView(path=str(Path.home()))
        chooser.filters = ["*.pdf", "*.txt", "*.jpg", "*.jpeg", "*.png"]
        root.add_widget(chooser)

        subject_input = TextInput(
            text=self.subject_input.text,
            hint_text="Subject (optional)",
            multiline=False,
            size_hint_y=None,
            height=36,
        )
        root.add_widget(subject_input)

        action_row = BoxLayout(size_hint_y=None, height=42, spacing=6)
        import_btn = Button(text="Import selected")
        close_btn = Button(text="Close")
        action_row.add_widget(import_btn)
        action_row.add_widget(close_btn)
        root.add_widget(action_row)

        popup = Popup(title="Import documents to local KB", content=root, size_hint=(0.95, 0.95))

        def do_import(_instance):
            selected = chooser.selection
            if not selected:
                self._update_status("Upload: no file selected")
                return

            imported = 0
            for file_path in selected:
                try:
                    with open(file_path, "rb") as fh:
                        content = fh.read()
                    kb.save_file(
                        file_data=content,
                        original_name=Path(file_path).name,
                        file_type=detect_file_type(file_path),
                        subject=subject_input.text.strip(),
                    )
                    imported += 1
                except Exception as exc:
                    self._update_status(f"Upload error: {exc}")

            self.subject_input.text = subject_input.text.strip()
            self._update_status(f"Upload: imported {imported} file(s)")
            self.refresh_documents()
            popup.dismiss()

        import_btn.bind(on_release=do_import)
        close_btn.bind(on_release=lambda _x: popup.dismiss())
        popup.open()


class ResFesLauncherApp(App):
    def build(self):
        return ResFesManager()

    def on_stop(self):
        if self.root:
            self.root.stop_server()


if __name__ == "__main__":
    ResFesLauncherApp().run()