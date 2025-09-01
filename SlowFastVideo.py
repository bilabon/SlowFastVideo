# python3.10 -m venv venv && source venv/bin/activate && pip freeze && python3.10 -V && pip --no-cache-dir install -U pip && pip --no-cache-dir install -U setuptools && pip --no-cache-dir install -U wheel
# python3 -m venv venv
# source venv/bin/activate
# python -m pip install -U pip wheel setuptools
# python -m pip install pyinstaller PyQt5
# # Download latest snapshot static ARM64 builds
# curl -L -o ffmpeg.zip  https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/snapshot/ffmpeg.zip
# curl -L -o ffprobe.zip https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/snapshot/ffprobe.zip

# # Unzip just the binaries into the project root
# unzip -j ffmpeg.zip  -d .
# unzip -j ffprobe.zip -d .

# # Make them runnable & remove quarantine
# chmod +x ffmpeg ffprobe
# xattr -dr com.apple.quarantine ffmpeg ffprobe

# # Quick check — these should print versions without “Library not loaded” errors
# ./ffmpeg -version
# ./ffprobe -version

# # (Optional) sanity check for external deps — should NOT show /opt/homebrew/...
# otool -L ffmpeg
# otool -L ffprobe

## Build the .app
# pyinstaller SlowFastVideo.spec

import sys
import os
import re
import json
import shutil
import stat
import subprocess
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout,
    QPushButton, QHBoxLayout, QSlider, QFileDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

APP_NAME = "SlowFastVideo"


# ---------- PATH HELPERS ----------
def is_windows():
    return os.name == "nt"

def resource_dir():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

def tool_path(name):
    if is_windows() and not name.lower().endswith(".exe"):
        name += ".exe"
    candidate = os.path.join(resource_dir(), name)
    if os.path.exists(candidate):
        try:
            st = os.stat(candidate)
            os.chmod(candidate, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except Exception:
            pass
        return candidate
    found = shutil.which(name)
    return found or name

def get_ffmpeg_path():
    return tool_path("ffmpeg")

def get_ffprobe_path():
    return tool_path("ffprobe")

def get_settings_path():
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support", APP_NAME)
    elif is_windows():
        base = os.path.join(os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming")), APP_NAME)
    else:
        base = os.path.join(home, ".config", APP_NAME)
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "settings.json")


# ---------- ATEMPO CHAIN ----------
def atempo_chain(speed: float) -> str:
    if speed <= 0:
        return "atempo=1.0"
    parts = []
    remain = speed
    if remain >= 1.0:
        while remain > 2.0 + 1e-6:
            parts.append("atempo=2.0")
            remain /= 2.0
        parts.append(f"atempo={remain:.2f}")
    else:
        while remain < 0.5 - 1e-6:
            parts.append("atempo=0.5")
            remain *= 2.0
        parts.append(f"atempo={remain:.2f}")
    return ",".join(parts)


# ---------- WORKER ----------
class ConversionWorker(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    canceled = pyqtSignal()

    def __init__(self, command, total_duration):
        super().__init__()
        self.command = command
        self.total_duration = total_duration
        self.process = None
        self._canceled = False

    def run(self):
        try:
            self.process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )

            for line in self.process.stdout:
                if self._canceled:
                    self.process.terminate()
                    self.process.wait()
                    self.canceled.emit()
                    return
                line = line.strip()
                if line.startswith("out_time="):
                    t = self.parse_time(line.split("=", 1)[1])
                    if t is not None and self.total_duration > 0:
                        progress = int((t / self.total_duration) * 100)
                        self.progress.emit(min(max(progress, 0), 100))

            self.process.wait()
            if self._canceled:
                self.canceled.emit()
            else:
                if self.process.returncode != 0:
                    err = self.process.stderr.read() if self.process.stderr else ""
                    self.error.emit(f"FFmpeg failed: {err[:400]}")
                else:
                    self.finished.emit()

        except Exception as e:
            if not self._canceled:
                self.error.emit(str(e))

    def cancel(self):
        self._canceled = True
        if self.process and self.process.poll() is None:
            self.process.terminate()

    @staticmethod
    def parse_time(timestr):
        try:
            h, m, s = timestr.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
        except Exception:
            return None


# ---------- GUI ----------
class SlowFastVideo(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setFixedSize(430, 320)
        self.setAcceptDrops(True)

        self.settings_file = get_settings_path()
        self.last_folder = None
        self.speed_value = 100
        self.load_settings()

        layout = QVBoxLayout()

        self.drop_label = QLabel("Drag a video file here or click to select.")
        self.drop_label.setAlignment(Qt.AlignCenter)
        self.drop_label.setStyleSheet(self.get_progress_style(0))
        self.drop_label.mousePressEvent = self.select_file
        layout.addWidget(self.drop_label, stretch=3)

        slider_layout = QHBoxLayout()
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(25, 400)   # 0.25x – 4.00x
        self.speed_slider.setSingleStep(10)   # шаг 0.1x
        self.speed_slider.setValue(self.speed_value)
        self.speed_slider.valueChanged.connect(self.update_speed_label)

        self.speed_value_label = QLabel(f"{self.speed_slider.value() / 100:.1f}x")
        slider_layout.addWidget(QLabel("0.25x"))
        slider_layout.addWidget(self.speed_slider)
        slider_layout.addWidget(self.speed_value_label)
        layout.addLayout(slider_layout)

        self.convert_button = QPushButton("Convert")
        self.convert_button.clicked.connect(self.convert_or_cancel)
        layout.addWidget(self.convert_button)

        self.setLayout(layout)
        self.input_file = None
        self.is_converting = False
        self.worker = None

        os.environ["PATH"] = resource_dir() + os.pathsep + os.environ.get("PATH", "")

    # ---- UI helpers ----
    def elide_text(self, text, widget, mode=Qt.ElideMiddle):
        fm = widget.fontMetrics()
        return fm.elidedText(text, mode, widget.width() - 10)

    def update_speed_label(self):
        self.speed_value_label.setText(f"{self.speed_slider.value() / 100:.1f}x")

    def get_progress_style(self, progress):
        green = progress / 100.0
        return f"""
            QLabel {{
                border: 2px dashed #aaa;
                font-size: 14px;
                color: #333;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #007BFF,
                    stop:{green:.2f} #007BFF,
                    stop:{green:.2f} white,
                    stop:1 white
                );
                padding: 10px;
            }}
        """

    def reset_ui(self):
        self.drop_label.setEnabled(True)
        self.convert_button.setEnabled(True)
        self.convert_button.setText("Convert")
        self.input_file = None
        self.is_converting = False
        self.setWindowTitle(APP_NAME)

    # ---- Settings ----
    def load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    s = json.load(f)
                    self.last_folder = s.get("last_folder")
                    self.speed_value = int(s.get("last_speed", 100))
            except Exception:
                pass

    def save_settings(self):
        s = {"last_folder": self.last_folder, "last_speed": self.speed_slider.value()}
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(s, f)
        except Exception:
            pass

    # ---- File selection / DnD ----
    def select_file(self, event):
        if not self.drop_label.isEnabled():
            return
        fpath, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video File",
            self.last_folder or "",
            "Video Files (*.mp4 *.mov *.avi *.mkv *.flv *.webm *.m4v *.mpg *.mpeg)"
        )
        if fpath:
            self.set_input_file(fpath)

    def set_input_file(self, path):
        self.input_file = path
        self.last_folder = os.path.dirname(path)
        base = os.path.basename(path)
        self.drop_label.setText(self.elide_text(base, self.drop_label))
        self.setWindowTitle(self.elide_text(f"{APP_NAME} - {base}", self))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path):
                self.set_input_file(path)
        event.acceptProposedAction()

    # ---- Conversion ----
    def convert_or_cancel(self):
        if not self.is_converting:
            self.start_conversion()
        else:
            self.cancel_conversion()

    def cancel_conversion(self):
        if self.worker and self.is_converting:
            self.worker.cancel()

    def start_conversion(self):
        if not self.input_file:
            self.drop_label.setText("Please select a file first!")
            return

        total = self.get_video_duration(self.input_file)
        if total is None:
            self.drop_label.setText("Error reading video duration!")
            return

        speed = self.speed_slider.value() / 100.0
        output_duration = total / speed
        output_file = self.generate_output_filename(self.input_file)

        setpts = f"{1.0 / speed:.6f}*PTS"
        atempo = atempo_chain(speed)

        cmd = [
            get_ffmpeg_path(),
            "-hide_banner", "-v", "error",
            "-i", self.input_file,
            "-filter:v", f"setpts={setpts}",
            "-filter:a", atempo,
            "-progress", "pipe:1",
            "-y", output_file
        ]

        self.drop_label.setEnabled(False)
        self.convert_button.setText("Cancel")
        self.drop_label.setText("0%")
        self.is_converting = True

        self.worker = ConversionWorker(cmd, output_duration)
        self.worker.progress.connect(self.update_progress_area)
        self.worker.finished.connect(self.conversion_finished)
        self.worker.error.connect(self.conversion_error)
        self.worker.canceled.connect(self.conversion_canceled)
        self.worker.start()

    def update_progress_area(self, val):
        self.drop_label.setText(f"{val}%")
        self.drop_label.setStyleSheet(self.get_progress_style(val))

    def conversion_finished(self):
        self.drop_label.setText("Conversion completed!")
        self.reset_ui()
        self.save_settings()

    def conversion_error(self, msg):
        self.drop_label.setText(f"Error: {msg[:300]}")
        self.reset_ui()
        self.save_settings()

    def conversion_canceled(self):
        self.drop_label.setText("Conversion canceled!")
        self.reset_ui()
        self.save_settings()

    # ---- Helpers ----
    def get_video_duration(self, path):
        cmd = [
            get_ffprobe_path(),
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            if res.returncode == 0:
                txt = res.stdout.strip()
                if txt:
                    return float(txt)
            if res.stderr:
                self.drop_label.setText(f"ffprobe error: {res.stderr[:200]}")
        except Exception as e:
            self.drop_label.setText(f"ffprobe exc: {e}")
        return None

    def generate_output_filename(self, path):
        base, ext = os.path.splitext(path)
        i = 1
        while True:
            out = f"{base}-converted-{i}{ext}"
            if not os.path.exists(out):
                return out
            i += 1


# ---------- MAIN ----------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = SlowFastVideo()
    win.show()
    sys.exit(app.exec_())
