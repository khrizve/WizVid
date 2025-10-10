import sys
import re
import yt_dlp
import os
import urllib.request
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QTextEdit, QPushButton, QFileDialog, \
    QProgressBar, QComboBox, QGraphicsOpacityEffect, QHBoxLayout, QDialog, QMessageBox
from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, Qt, QUrl, QThread, pyqtSignal, QObject, QSettings
from PyQt6.QtGui import QPixmap, QDesktopServices
import time


class DownloadCancelledException(Exception):
    pass


class DownloadWorker(QObject):
    progress_signal = pyqtSignal(dict)
    finished_signal = pyqtSignal(bool)
    error_signal = pyqtSignal(str)
    playlist_name_signal = pyqtSignal(str)
    paused_signal = pyqtSignal()
    resumed_signal = pyqtSignal()
    cancelled_signal = pyqtSignal()

    def __init__(self, urls, options):
        super().__init__()
        self.urls = urls
        self.options = options
        self.is_playlist = False
        self._is_paused = False
        self._is_cancelled = False
        self.ydl_instance = None

    def run(self):
        try:
            self.options['progress_hooks'] = [self.progress_hook]
            temp_options = self.options.copy()
            temp_options['quiet'] = True
            temp_options['extract_flat'] = True
            with yt_dlp.YoutubeDL(temp_options) as ydl_info:
                info = ydl_info.extract_info(self.urls[0], download=False)
                if info and info.get('_type') == 'playlist' and ('entries' in info):
                    playlist_title = info.get('title')
                    if playlist_title:
                        self.is_playlist = True
                        self.playlist_name_signal.emit(playlist_title)
                        safe_playlist_name = re.sub('[\\\\/:*?\"<>|]', '', playlist_title)
                        base_path = self.options['outtmpl']
                        original_download_dir = os.path.dirname(base_path)
                        if not original_download_dir:
                            original_download_dir = '.'
                        self.options['outtmpl'] = os.path.join(original_download_dir, safe_playlist_name,
                                                               '%(title)s.%(ext)s')
                        self.options['yes_playlist'] = True
                        self.options['ignoreerrors'] = True
            self.ydl_instance = yt_dlp.YoutubeDL(self.options)
            with self.ydl_instance as ydl:
                ydl.download(self.urls)
            self.finished_signal.emit(self.is_playlist)
        except DownloadCancelledException:
            self.cancelled_signal.emit()
        except Exception as e:
            self.error_signal.emit(str(e))

    def progress_hook(self, d):
        if self._is_cancelled:
            raise DownloadCancelledException('Download cancelled by user.')
        if self._is_paused:
            while self._is_paused:
                time.sleep(0.1)
        if d['status'] in ('downloading', 'finished', 'error', 'postprocessing'):
            self.progress_signal.emit(d)
        return None

    def pause(self):
        self._is_paused = True
        self.paused_signal.emit()

    def resume(self):
        self._is_paused = False
        self.resumed_signal.emit()

    def cancel(self):
        self._is_cancelled = True


class PreviewWorker(QObject):
    preview_ready = pyqtSignal(dict)
    error_signal = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'socket_timeout': 10}) as ydl:
                info = ydl.extract_info(self.url, download=False)
                thumbnail_url = info.get('thumbnail', '')
                if thumbnail_url:
                    with urllib.request.urlopen(thumbnail_url) as response:
                        info['thumbnail_data'] = response.read()
                self.preview_ready.emit(info)
        except Exception as e:
            self.error_signal.emit(f"Failed to fetch info for '{self.url}': {str(e)}")


class VideoPreviewDialog(QDialog):
    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self.setWindowTitle('✨ Video Preview ✨')
        self.setGeometry(300, 100, 650, 500)
        self.setStyleSheet(self.fantasy_style_preview())
        layout = QVBoxLayout()
        self.title_label = QLabel(info.get('title', 'No title available'))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet('font-size: 20px; color: #e0f7ff; font-weight: bold;')
        layout.addWidget(self.title_label)
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.thumbnail_label)
        duration = info.get('duration', 0)
        minutes, seconds = divmod(duration, 60)
        self.duration_label = QLabel(f'⏱️ Duration: {minutes}:{seconds:02d}')
        self.duration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.duration_label)
        self.view_button = QPushButton('🌐 View on YouTube')
        self.view_button.clicked.connect(self.open_in_browser)
        layout.addWidget(self.view_button)
        self.close_button = QPushButton('🔮 Close Preview')
        self.close_button.clicked.connect(self.close)
        layout.addWidget(self.close_button)
        self.setLayout(layout)
        if 'thumbnail_data' in info:
            pixmap = QPixmap()
            pixmap.loadFromData(info['thumbnail_data'])
            self.thumbnail_label.setPixmap(pixmap.scaled(400, 225, Qt.AspectRatioMode.KeepAspectRatio))

    def fantasy_style_preview(self):
        return """
            QDialog {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #0a0f14, stop:1 #1a2233);
                color: #a9cfe7;
                font-family: 'Segoe UI', sans-serif;
                border: 1px solid #3a4a6b;
                border-radius: 10px;
            }
            QLabel {
                color: #e0f7ff;
                font-weight: bold; 
                font-size: 16px;
                margin: 10px;
            }
            QPushButton {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #1e2d44, stop:1 #0c1829);
                border: 1px solid #5b93c6;
                color: #f0f8ff;
                font-weight: bold;
                padding: 10px;
                border-radius: 8px;
                font-size: 16px;
                margin: 10px;
                min-width: 200px;
            }
            QPushButton:hover {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #2f4f6a, stop:1 #19334d);
                color: #ffffff;
                border: 1px solid #6cb2e2;
            }
        """

    def open_in_browser(self):
        QDesktopServices.openUrl(QUrl(self.info['webpage_url']))


class VideoDownloader(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings('MyOrganization', 'WizVid')
        self.download_path = self.settings.value('download_path', os.path.expanduser('~'))
        self.ffmpeg_path = self.get_ffmpeg_path()
        self.init_ui()
        self.download_thread = None
        self.download_worker = None
        self.preview_thread = None
        self.current_playlist_folder = None

    def get_ffmpeg_path(self):
        if sys.platform == "win32":
            return os.path.join(os.path.dirname(__file__), "ffmpeg", "bin", "ffmpeg.exe")
        elif sys.platform == "darwin":
            return os.path.join(os.path.dirname(__file__), "ffmpeg", "bin", "ffmpeg")
        else:
            return os.path.join(os.path.dirname(__file__), "ffmpeg", "bin", "ffmpeg")


    def init_ui(self):
        self.setWindowTitle('✨ WizVid - Fantasy Downloader ✨')
        self.setGeometry(300, 50, 600, 500)
        self.setStyleSheet(self.fantasy_style())
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        self.title_label = QLabel('✨ WizVid - Fantasy Downloader ✨')
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("""
            font-size: 24px; 
            color: #e0f7ff; 
            font-weight: bold;
            margin-bottom: 15px;
        """)
        layout.addWidget(self.title_label)
        self.setup_fade_effect(self.title_label)
        url_container = QVBoxLayout()
        url_container.setSpacing(5)
        self.label = QLabel('Enter Video/Playlist URLs (one per line):')
        url_container.addWidget(self.label)
        self.url_input = QTextEdit(self)
        self.url_input.setMinimumHeight(100)
        url_container.addWidget(self.url_input)
        layout.addLayout(url_container)
        settings_container = QHBoxLayout()
        settings_container.setSpacing(15)
        path_container = QVBoxLayout()
        path_container.setSpacing(5)
        self.path_label = QLabel('Download Folder:')
        display_path = self.download_path
        if len(display_path) > 40:
            display_path = f'{display_path[:15]}...{display_path[(-20):]}'
        self.path_label.setText(f'Folder: {display_path}')
        path_container.addWidget(self.path_label)
        self.path_button = QPushButton('📂 Browse')
        self.path_button.setFixedWidth(120)
        self.path_button.clicked.connect(self.select_folder)
        path_container.addWidget(self.path_button)
        settings_container.addLayout(path_container)
        format_container = QVBoxLayout()
        format_container.setSpacing(5)
        format_label = QLabel('Download Format:')
        format_container.addWidget(format_label)
        self.format_dropdown = QComboBox(self)
        self.format_dropdown.addItems(
            ['Best Video', 'Best Audio', 'MP4 720p', 'MP4 1080p', 'MP4 1440p', 'MP4 4K', 'MP3'])
        preferred_format = self.settings.value('download_format', 'Best Video')
        index = self.format_dropdown.findText(preferred_format)
        if index != (-1):
            self.format_dropdown.setCurrentIndex(index)
        self.format_dropdown.setFixedWidth(150)
        self.format_dropdown.currentIndexChanged.connect(self.save_preferences)
        format_container.addWidget(self.format_dropdown)
        settings_container.addLayout(format_container)
        layout.addLayout(settings_container)
        button_container = QHBoxLayout()
        button_container.setSpacing(15)
        self.download_button = QPushButton('🌟 Download Video')
        self.download_button.setFixedHeight(40)
        self.download_button.clicked.connect(self.start_download)
        button_container.addWidget(self.download_button)
        self.preview_button = QPushButton('🔮 Preview Video')
        self.preview_button.setFixedHeight(40)
        self.preview_button.clicked.connect(self.preview_video)
        button_container.addWidget(self.preview_button)
        layout.addLayout(button_container)
        control_button_container = QHBoxLayout()
        control_button_container.setSpacing(10)
        self.pause_button = QPushButton('⏸️ Pause')
        self.pause_button.setFixedHeight(35)
        self.pause_button.setFixedWidth(100)
        self.pause_button.clicked.connect(self.pause_download)
        self.pause_button.setEnabled(False)
        control_button_container.addWidget(self.pause_button)
        self.resume_button = QPushButton('▶️ Resume')
        self.resume_button.setFixedHeight(35)
        self.resume_button.setFixedWidth(100)
        self.resume_button.clicked.connect(self.resume_download)
        self.resume_button.setEnabled(False)
        control_button_container.addWidget(self.resume_button)
        self.cancel_button = QPushButton('❌ Cancel')
        self.cancel_button.setFixedHeight(35)
        self.cancel_button.setFixedWidth(100)
        self.cancel_button.clicked.connect(self.cancel_download)
        self.cancel_button.setEnabled(False)
        control_button_container.addWidget(self.cancel_button)
        layout.addLayout(control_button_container)
        progress_container = QVBoxLayout()
        progress_container.setSpacing(5)
        self.speed_label = QLabel('⚡ Speed: N/A')
        self.speed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.speed_label.setStyleSheet('font-size: 14px; font-weight: bold; color: #6cb2e2;')
        progress_container.addWidget(self.speed_label)
        self.progress = QProgressBar(self)
        self.progress.setValue(0)
        self.progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #3a4a6b;
                border-radius: 5px;
                text-align: center;
                height: 20px;
            }
            QProgressBar::chunk {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0,
                                            stop:0 #4facfe, stop:1 #00f2fe);
                border-radius: 5px;
            }
        """)
        progress_container.addWidget(self.progress)
        layout.addLayout(progress_container)
        self.status = QTextEdit(self)
        self.status.setReadOnly(True)
        self.status.setStyleSheet("""
            background-color: rgba(10, 20, 40, 0.5);
            border: 1px solid #3a4a6b;
            border-radius: 5px;
            padding: 10px;
            color: #e0f7ff;
        """)
        self.status.setMinimumHeight(100)
        layout.addWidget(self.status)
        self.footer_label = QLabel(
            '<p align="center" style="font-size:14px;">Created by <a href="https://rizve.netlify.app/" style="color:#6cb2e2; text-decoration:none;">Sorcerer</a></p>')
        self.footer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.footer_label.setOpenExternalLinks(True)
        layout.addWidget(self.footer_label)
        self.setLayout(layout)

    def fantasy_style(self):
        return """
            QWidget {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1, 
                                            stop:0 #0a0f1f, stop:1 #121a2e);
                color: #e0f7ff;
                font-family: 'Segoe UI', sans-serif;
            }
            QLabel {
                color: #e0f7ff;
                font-weight: bold;
                font-size: 14px;
            }
            QLineEdit, QTextEdit {
                background-color: rgba(20, 30, 50, 0.5);
                border: 1px solid #3a4a6b;
                color: #e0f7ff;
                padding: 8px;
                border-radius: 5px;
                font-weight: normal;
            }
            QComboBox {
                background-color: rgba(20, 30, 50, 0.5);
                border: 1px solid #3a4a6b;
                color: #e0f7ff;
                padding: 5px;
                border-radius: 5px;
                font-weight: normal;
                min-width: 120px;
            }
            QComboBox QAbstractItemView {
                background-color: #121a2e;
                border: 1px solid #3a4a6b;
                color: #e0f7ff;
                selection-background-color: #3a4a6b;
            }
            QPushButton {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, 
                                            stop:0 #1b2a49, stop:1 #243b55);
                border: 1px solid #3a4a6b;
                color: #ffffff;
                font-weight: bold;
                padding: 8px;
                border-radius: 5px;
                font-size: 14px;
                min-width: 100px;
            }
            QPushButton:hover {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, 
                                            stop:0 #2c3e5d, stop:1 #3c5e80);
                color: #ffffff;
                border: 1px solid #4facfe;
            }
            QPushButton:pressed {
                background: #182538;
                color: #8ecae6;
            }
        """

    def setup_fade_effect(self, widget):
        self.opacity_effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(self.opacity_effect)
        self.fade_animation = QPropertyAnimation(self.opacity_effect, b'opacity')
        self.fade_animation.setDuration(3000)
        self.fade_animation.setStartValue(0.5)
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.fade_animation.setDirection(QPropertyAnimation.Direction.Forward)
        self.fade_animation.finished.connect(self.reverse_fade)
        self.fade_animation.start()

    def reverse_fade(self):
        if self.fade_animation.direction() == QPropertyAnimation.Direction.Forward:
            self.fade_animation.setDirection(QPropertyAnimation.Direction.Backward)
        else:
            self.fade_animation.setDirection(QPropertyAnimation.Direction.Forward)
        self.fade_animation.start()

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Select Download Folder', self.download_path)
        if folder:
            self.download_path = folder
            display_path = self.download_path
            if len(display_path) > 40:
                display_path = f'{display_path[:15]}...{display_path[(-20):]}'
            self.path_label.setText(f'Folder: {display_path}')
            self.save_preferences()

    def save_preferences(self):
        self.settings.setValue('download_path', self.download_path)
        self.settings.setValue('download_format', self.format_dropdown.currentText())
        self.status.append('⚙️ Preferences saved!')

    def preview_video(self):
        urls = [url for url in self.url_input.toPlainText().strip().split('\n') if url]
        if not urls:
            QMessageBox.warning(self, 'Input Error', '⚠️ Please enter a video URL first!')
            self.status.append('⚠️ Please enter a video URL first!')
            return None
        url = urls[0]
        self.preview_button.setEnabled(False)
        self.status.append(f'🔮 Fetching preview for: {url}')
        self.preview_thread = QThread()
        self.preview_worker = PreviewWorker(url)
        self.preview_worker.moveToThread(self.preview_thread)
        self.preview_thread.started.connect(self.preview_worker.run)
        self.preview_worker.preview_ready.connect(self.show_preview)
        self.preview_worker.error_signal.connect(self.preview_error)
        self.preview_worker.preview_ready.connect(self.preview_thread.quit)
        self.preview_worker.error_signal.connect(self.preview_thread.quit)
        self.preview_thread.finished.connect(self.preview_worker.deleteLater)
        self.preview_thread.finished.connect(self.preview_thread.deleteLater)
        self.preview_thread.start()

    def show_preview(self, info):
        self.preview_button.setEnabled(True)
        self.preview_dialog = VideoPreviewDialog(info, self)
        self.preview_dialog.exec()

    def preview_error(self, error):
        self.preview_button.setEnabled(True)
        QMessageBox.critical(self, 'Preview Error', f'❌ Failed to get preview: {error}')
        self.status.append(f'❌ Preview error: {error}')

    def remove_ansi_codes(self, text):
        return re.sub('\\x1B(?:[@-Z\\\\-_]|\\[[0-?]*[ -/]*[@-~])', '', text)

    def update_progress(self, d):
        if d['status'] == 'downloading':
            percent_str = self.remove_ansi_codes(d.get('_percent_str', '0.0%'))
            percent = 0.0
            try:
                percent = float(percent_str.replace('%', '').strip())
            except ValueError:
                percent = 0.0
            speed_str = self.remove_ansi_codes(d.get('_speed_str', 'N/A'))
            self.progress.setValue(int(percent))
            self.speed_label.setText(f'⚡ Speed: {speed_str}')
            self.status.append(f'💾 Downloading... {percent:.2f}%')
            QApplication.processEvents()

    def start_download(self):
        urls = [url for url in self.url_input.toPlainText().strip().split('\n') if url]
        if not urls:
            QMessageBox.warning(self, 'Input Error', '⚠️ Please enter at least one video or playlist URL!')
            self.status.append('⚠️ Please enter at least one video or playlist URL!')
            return None
        self.download_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.resume_button.setEnabled(False)
        self.progress.setValue(0)
        self.speed_label.setText('⚡ Speed: Connecting...')
        self.status.clear()
        self.status.append(f'🚀 Starting download for {len(urls)} item(s) to: {self.download_path}')
        selected_format = self.format_dropdown.currentText()
        options = {
            'outtmpl': os.path.join(self.download_path, '%(title)s.%(ext)s'),
            'noprogress': True,
            'external_downloader_args': ['-loglevel', 'error', '-y']
        }
        if self.ffmpeg_path and os.path.exists(self.ffmpeg_path):
            options['ffmpeg_location'] = os.path.dirname(self.ffmpeg_path)
        if selected_format == 'Best Video':
            options['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            options['merge_output_format'] = 'mp4'
        elif selected_format == 'Best Audio':
            options['format'] = 'bestaudio/best'
            options['extract_audio'] = True
            options['audio_format'] = 'mp3'
            options['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192'
            }, {'key': 'FFmpegMetadata'}]
        elif selected_format == 'MP3':
            options['format'] = 'bestaudio/best'
            options['extract_audio'] = True
            options['audio_format'] = 'mp3'
            options['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320'
            }, {'key': 'FFmpegMetadata'}]
        elif 'MP4' in selected_format:
            resolution = selected_format.split(' ')[1][:-1]
            options['format'] = f'bestvideo[ext=mp4][height<={resolution}]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            options['merge_output_format'] = 'mp4'
        self.download_thread = QThread()
        self.download_worker = DownloadWorker(urls, options)
        self.download_worker.moveToThread(self.download_thread)
        self.download_thread.started.connect(self.download_worker.run)
        self.download_worker.progress_signal.connect(self.update_progress)
        self.download_worker.finished_signal.connect(self.download_finished)
        self.download_worker.error_signal.connect(self.download_error)
        self.download_worker.playlist_name_signal.connect(self.set_playlist_folder)
        self.download_worker.paused_signal.connect(self.download_paused)
        self.download_worker.resumed_signal.connect(self.download_resumed)
        self.download_worker.cancelled_signal.connect(self.download_cancelled)
        self.download_worker.finished_signal.connect(self.download_thread.quit)
        self.download_worker.error_signal.connect(self.download_thread.quit)
        self.download_worker.cancelled_signal.connect(self.download_thread.quit)
        self.download_thread.finished.connect(self.download_worker.deleteLater)
        self.download_thread.finished.connect(self.download_thread.deleteLater)
        self.download_thread.start()

    def pause_download(self):
        if self.download_worker:
            self.download_worker.pause()
            self.pause_button.setEnabled(False)
            self.resume_button.setEnabled(True)
            self.status.append('⏸️ Download paused.')

    def resume_download(self):
        if self.download_worker:
            self.download_worker.resume()
            self.resume_button.setEnabled(False)
            self.pause_button.setEnabled(True)
            self.status.append('▶️ Download resumed.')

    def cancel_download(self):
        if self.download_worker:
            self.download_worker.cancel()
            self.status.append('❌ Cancelling download...')

    def download_paused(self):
        self.speed_label.setText('⚡ Speed: Paused')

    def download_resumed(self):
        self.status.append('▶️ Download resumed.')

    def download_cancelled(self):
        self.status.append('❌ Download cancelled.')
        self.download_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.progress.setValue(0)
        self.speed_label.setText('⚡ Speed: Cancelled')
        self.current_playlist_folder = None

    def set_playlist_folder(self, playlist_name):
        safe_playlist_name = re.sub('[\\\\/:*?\"<>|]', '', playlist_name)
        self.current_playlist_folder = os.path.join(self.download_path, safe_playlist_name)
        os.makedirs(self.current_playlist_folder, exist_ok=True)
        self.status.append(
            f'📁 Detected playlist: \'{playlist_name}\'. Videos will be saved in: {self.current_playlist_folder}')

    def download_finished(self, is_playlist_finished):
        self.download_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.progress.setValue(100)
        self.speed_label.setText('✅ Speed: Download Finished')
        message = 'Download finished!'
        folder_path = self.download_path
        if is_playlist_finished and self.current_playlist_folder:
            message = f'All downloads completed! Playlist saved to:\n{self.current_playlist_folder}'
            folder_path = self.current_playlist_folder
        elif not is_playlist_finished:
            message = f'Download finished! File saved to:\n{self.download_path}'
        self.status.append('✅ Download completed successfully!')
        QMessageBox.information(self, 'Download Complete', message)
        self.current_playlist_folder = None

    def download_error(self, error):
        self.download_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.status.append(f'❌ Download error: {error}')
        self.progress.setValue(0)
        self.speed_label.setText('⚡ Speed: Error')
        self.current_playlist_folder = None


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = VideoDownloader()
    window.show()
    sys.exit(app.exec())
