# python3.10 -m venv venv && source venv/bin/activate && pip freeze && python3.10 -V && pip --no-cache-dir install -U pip && pip --no-cache-dir install -U setuptools && pip --no-cache-dir install -U wheel
# pip install pyinstaller
# pip install PyQt5
# cp $(which ffmpeg) ./ffmpeg
# cp $(which ffprobe) ./ffprobe
# arch -arm64 pyinstaller --windowed --name "SlowFastVideo" --add-binary "ffmpeg:./" --icon=SlowFastVideo.icns SlowFastVideo.py
# pyinstaller --windowed --onefile --name "SlowFastVideo" --add-binary "ffmpeg:./" --icon=slowfastvideo.icns  SlowFastVideo.py


import sys
import os
import subprocess
import re
import json
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout,
                             QPushButton, QHBoxLayout, QSlider, QFileDialog)
from PyQt5.QtCore import Qt, QThread, pyqtSignal


def get_ffmpeg_path():
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "ffmpeg")
    return "ffmpeg"


def get_settings_path():
    home_dir = os.path.expanduser("~")
    path = os.path.join(home_dir, "Library", "Application Support", "SlowFastVideo")
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, "settings.json")


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
                self.command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True
            )

            for line in self.process.stdout:
                if self._canceled:
                    self.process.terminate()
                    self.process.wait()
                    self.canceled.emit()
                    return

                line = line.strip()
                if line.startswith("out_time="):
                    timestr = line.split('=', 1)[1].strip()
                    current_time = self.parse_time(timestr)
                    if current_time is not None and self.total_duration > 0:
                        progress = int((current_time / self.total_duration) * 100)
                        self.progress.emit(min(progress, 100))

            self.process.wait()

            if self._canceled:
                self.canceled.emit()
            else:
                if self.process.returncode != 0:
                    self.error.emit("FFmpeg process failed")
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
            h, m, s = timestr.split(':')
            s = float(s)
            return float(h)*3600 + float(m)*60 + s
        except:
            return None


class SlowFastVideo(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SlowFastVideo")
        self.setFixedSize(400, 300)

        # Включаем поддержку Drag & Drop
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
        self.speed_slider.setRange(50, 300)
        self.speed_slider.setValue(self.speed_value)
        self.speed_slider.valueChanged.connect(self.update_speed_label)

        self.speed_value_label = QLabel(f"{self.speed_slider.value() / 100:.1f}x")
        slider_layout.addWidget(QLabel("0.5x"))
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

    def elide_text(self, text, widget, mode=Qt.ElideMiddle):
        fm = widget.fontMetrics()
        max_width = widget.width() - 10
        return fm.elidedText(text, mode, max_width)

    def load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r") as f:
                    settings = json.load(f)
                    self.last_folder = settings.get("last_folder", None)
                    self.speed_value = settings.get("last_speed", 100)
            except:
                pass

    def save_settings(self):
        settings = {"last_folder": self.last_folder, "last_speed": self.speed_slider.value()}
        try:
            with open(self.settings_file, "w") as f:
                json.dump(settings, f)
        except:
            pass

    def select_file(self, event):
        if not self.drop_label.isEnabled():
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", self.last_folder or "", "Video Files (*.mp4 *.mov *.avi *.mkv *.flv *.webm)"
        )
        if file_path:
            self.set_input_file(file_path)

    def set_input_file(self, file_path):
        self.input_file = file_path
        self.last_folder = os.path.dirname(file_path)
        base_name = os.path.basename(file_path)
        elided_text = self.elide_text(f"{base_name}", self.drop_label)
        self.drop_label.setText(elided_text)
        title_text = f"SlowFastVideo - {base_name}"
        elided_title = self.elide_text(title_text, self)
        self.setWindowTitle(elided_title)

    def update_speed_label(self):
        self.speed_value_label.setText(f"{self.speed_slider.value() / 100:.1f}x")

    def convert_or_cancel(self):
        if not self.is_converting:
            self.start_conversion()
        else:
            self.cancel_conversion()

    def start_conversion(self):
        if not self.input_file:
            self.drop_label.setText("Please select a file first!")
            return

        total_duration = self.get_video_duration(self.input_file)
        if total_duration is None:
            self.drop_label.setText("Error reading video duration!")
            return

        speed_factor = self.speed_slider.value() / 100.0
        output_duration = total_duration / speed_factor

        output_file = self.generate_output_filename(self.input_file)

        setpts_value = 1.0 / speed_factor
        atempo_value = speed_factor

        command = [
            get_ffmpeg_path(), "-i", self.input_file,
            "-filter:v", f"setpts={setpts_value}*PTS", "-filter:a", f"atempo={atempo_value}",
            "-progress", "pipe:1", "-y", output_file
        ]

        self.drop_label.setEnabled(False)
        self.convert_button.setEnabled(True)
        self.convert_button.setText("Cancel")
        self.drop_label.setText("0%")
        self.is_converting = True

        self.worker = ConversionWorker(command, output_duration)
        self.worker.progress.connect(self.update_progress_area)
        self.worker.finished.connect(self.conversion_finished)
        self.worker.error.connect(self.conversion_error)
        self.worker.canceled.connect(self.conversion_canceled)
        self.worker.start()

    def cancel_conversion(self):
        if self.worker is not None and self.is_converting:
            self.worker.cancel()

    def get_video_duration(self, file_path):
        cmd = [get_ffmpeg_path(), "-i", file_path]
        try:
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, universal_newlines=True)
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", result.stderr)
            if match:
                h, m, s = match.groups()
                return float(h)*3600 + float(m)*60 + float(s)
        except:
            pass
        return None

    def generate_output_filename(self, input_file):
        base, ext = os.path.splitext(input_file)
        output_file = f"{base}-ffmpeg-1{ext}"
        i = 1
        while os.path.exists(output_file):
            output_file = f"{base}-ffmpeg-{i}{ext}"
            i += 1
        return output_file

    def update_progress_area(self, value):
        self.drop_label.setText(f"{value}%")
        self.drop_label.setStyleSheet(self.get_progress_style(value))

    def get_progress_style(self, progress):
        green_part = progress / 100.0
        return f"""
            QLabel {{
                border: 2px dashed #aaa;
                font-size: 14px;
                color: #333;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #007BFF,
                    stop:{green_part:.2f} #007BFF,
                    stop:{green_part:.2f} white,
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
        self.setWindowTitle("SlowFastVideo")
        self.is_converting = False

    def conversion_finished(self):
        self.drop_label.setText("Conversion completed!")
        self.reset_ui()
        self.save_settings()

    def conversion_error(self, error_message):
        self.drop_label.setText(f"Error: {error_message}")
        self.reset_ui()
        self.save_settings()

    def conversion_canceled(self):
        self.drop_label.setText("Conversion canceled!")
        self.reset_ui()
        self.save_settings()

    # Реализация Drag & Drop:
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        # Обрабатываем все файлы, перетащенные в окно
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.isfile(file_path):
                self.set_input_file(file_path)
        event.acceptProposedAction()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SlowFastVideo()
    window.show()
    sys.exit(app.exec_())
