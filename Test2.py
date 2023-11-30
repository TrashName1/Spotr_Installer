from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel,
    QPushButton, QStackedWidget, QTextEdit, QRadioButton,
    QLineEdit, QFileDialog, QHBoxLayout, QCheckBox, QMessageBox, QStyle, QProgressBar, QSpacerItem, QSizePolicy
)
import os
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl
from PyQt5.QtGui import QPixmap, QDesktopServices
import requests
import zipfile
import sys
import shutil
import subprocess
import time
import webbrowser
import json
import base64
import logging
from yarl import URL
from io import BytesIO


def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS2
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

logging.basicConfig(filename='error.log', level=logging.ERROR)
log = logging.getLogger()
ACCOUNT_URL_SPOTIFY = URL.build(scheme="https", host="accounts.spotify.com")
ACCOUNT_URL_GENIUS = "https://api.genius.com/oauth/authorize"  # Genius Auth URL


class API:
    """API class for sending all requests"""

    def __init__(self, spotify_client_id, spotify_client_secret, directory):
        self.spotify_client_id = spotify_client_id
        self.spotify_client_secret = spotify_client_secret
        self.config_path = os.path.join(directory, 'Spotr', 'config.json')
        # Load existing config if it exists, otherwise start with an empty dictionary
        self.CONFIG = self.load_config()

    def load_config(self):
        """Load configuration from file."""
        try:
            with open(self.config_path, "r") as file:
                return json.load(file)
        except FileNotFoundError:
            return {}

    def write_config(self):
        """Write configuration to file."""
        print(f'Writing config to {self.config_path}: {
              self.CONFIG}')  # Debugging line
        try:
            with open(self.config_path, "w") as file:
                json.dump(self.CONFIG, file, indent=4)
        except Exception as e:
            print(f'Error writing config: {e}')  # Debugging line

    def request(
        self,
        method,
        url,
        headers=None,
        json=None
    ):
        """Spotr request, with deafult headers"""
        if headers is None:
            headers = {"Authorization": f"Bearer {self.CONFIG['key']}"}

        response = requests.request(
            method, url, headers=headers, json=json, timeout=10)

        if response.status_code in (401, 400):
            self.refresh_key()
            headers = {"Authorization": f"Bearer {self.CONFIG['key']}"}
            response = requests.request(
                method, url, headers=headers, json=json, timeout=10)

        if not response.ok:
            log.warning("[bold red]request error - status-code: %d",
                        response.status_code)
            log.info(response.json())
            sys.exit()

        try:
            data = response.json()
        except ValueError:
            return None

        return data

    def refresh_key(self):
        """Refresh API key"""
        url = ACCOUNT_URL_SPOTIFY / "api" / "token"

        response = requests.post(
            url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.CONFIG["refresh_token"],
            },
            headers={"Authorization": "Basic " + self.CONFIG["base_64"]},
            timeout=10,
        )
        if not response.ok:
            log.warning(
                "[bold red]request error - status-code: %d",
                response.status_code,
            )
            log.info(
                "[bold blue]Most likely something wrong with base_64 or refresh_token, try running 'spotr authorise'"
            )
            sys.exit()
        data = response.json()
        self.CONFIG["key"] = data["access_token"]
        self.write_config()

    def authorise_genius(self, genius_access_token=None):
        if genius_access_token:
            self.genius_access_token = genius_access_token
        # Store the Genius access token in your CONFIG
        self.CONFIG["genius_access_token"] = self.genius_access_token
        print(f'Authorising Genius with token: {
              self.genius_access_token}')  # Debugging line
        self.write_config()

    def open_spotify_auth(self):
        """Authenticate with Spotify API"""
        spotify_auth_url = ACCOUNT_URL_SPOTIFY / "authorize"

        spotify_client_id = self.spotify_client_id

        auth_request = requests.get(
            spotify_auth_url,
            {
                "client_id": spotify_client_id,
                "response_type": "code",
                "redirect_uri": "https://www.google.com/",
                "scope": "playlist-read-collaborative playlist-read-private user-read-playback-state user-modify-playback-state user-read-currently-playing user-read-recently-played playlist-modify-private playlist-modify-public",
            },
            timeout=10,
        )
        webbrowser.open_new_tab(auth_request.url)

    def process_spotify_auth(self, auth_code):
        spotify_token_url = ACCOUNT_URL_SPOTIFY / "api" / "token"
        spotify_client_id = self.spotify_client_id
        spotify_client_secret = self.spotify_client_secret

        client_creds = f"{spotify_client_id}:{spotify_client_secret}"
        client_creds_b64 = base64.b64encode(client_creds.encode())

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": "Basic %s" % client_creds_b64.decode(),
        }
        payload = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": "https://www.google.com/",
        }

        access_token_request = requests.post(
            url=spotify_token_url, data=payload, headers=headers, timeout=10
        )

        if not access_token_request.ok:
            log.warning("Request error: %d", access_token_request.status_code)
            sys.exit()

        access_token_response_data = access_token_request.json()

        self.CONFIG["refresh_token"] = access_token_response_data["refresh_token"]
        self.CONFIG["base_64"] = client_creds_b64.decode()
        self.write_config()


class InstallThread(QThread):
    update_progress = pyqtSignal(int)
    update_output = pyqtSignal(str)
    installation_finished = pyqtSignal()

    def __init__(self, directory):
        QThread.__init__(self)
        self.directory = directory

    def run(self):
        self.update_progress.emit(0)
        self.update_output.emit("Starting Installation")
        os.makedirs(self.directory, exist_ok=True)
        zip_url = 'https://github.com/TrashName1/spotr/archive/refs/heads/main.zip'
        zip_path = os.path.join(self.directory, 'file.zip')

        # Use requests to download the file
        response = requests.get(zip_url, stream=True)
        if response.status_code == 200:
            with open(zip_path, 'wb') as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
        else:
            print(f'Failed to download file: {response.status_code}')
            return
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(self.directory)
        os.remove(zip_path)
        extracted_folder = os.path.join(self.directory, 'spotr-main')
        new_folder = os.path.join(self.directory, 'Spotr')
        if os.path.exists(new_folder):
            shutil.rmtree(new_folder)
        os.rename(extracted_folder, new_folder)
        self.update_progress.emit(50)
        time.sleep(0.5)
        self.update_output.emit("Installation Complete")
        self.update_output.emit("Starting Installing Dependencies")
        time.sleep(1.5)
        subprocess.Popen(["pip3", "install", "-r", f"{self.directory}/Spotr/requirements.txt"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
        time.sleep(0.3)
        self.update_progress.emit(90)
        self.update_output.emit("Dependencies installed")
        self.update_output.emit("Creating Bat file")
        time.sleep(0.1)
        self.update_progress.emit(93)
        self.update_output.emit("Created spotr.bat")
        time.sleep(0.1)
        self.update_progress.emit(96)
        self.update_output.emit("Writing spotr.bat")
        time.sleep(0.4)
        bat_path = os.path.join(self.directory, "Spotr", "spotr.bat")
        with open(bat_path, "w") as file:
            file.write(
                f'@echo off\n\n'
                f'python "{os.path.join(
                    self.directory, "Spotr", "spotr.py")}" %1 %2 %3 %4 %5 %6 %7\n'
            )
        self.update_progress.emit(100)
        self.update_output.emit("Finnished writing spotr.bat")
        self.installation_finished.emit()
        subprocess.Popen(["python", f"{self.directory}/Spotr/install.py"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)


class Wizard(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.directory = self.directory_line_edit.text()
        self.api = API('your_spotify_client_id',
                       'your_spotify_client_secret', self.directory)

    def init_ui(self):
        self.stacked_widget = QStackedWidget()
        self.resize(595, 435)

        # Start Layout
        self.start_widget = QWidget()
        self.start_layout = QVBoxLayout()
        self.start_widget.setLayout(self.start_layout)
        image_url = 'https://github.com/TrashName1/spotr/blob/main/Spotr_Logo.png?raw=true'
        response = requests.get(image_url)
        image_bytes = BytesIO(response.content)
        pixmap = QPixmap()
        pixmap.loadFromData(image_bytes.read())
        self.logo_label = QLabel()
        scaled_pixmap = pixmap.scaled(
            48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.logo_label.setPixmap(scaled_pixmap)
        top_hbox = QHBoxLayout()
        top_hbox.addStretch(1)
        top_hbox.addWidget(self.logo_label)
        self.start_layout.insertLayout(0, top_hbox)
        self.start_layout.addWidget(
            QLabel('Welcome to the Spotr Setup Wizard'))
        self.start_layout.addWidget(
            QLabel('This wizard helps you set up the Spotr function to controll your spotify from the terminal'))
        self.start_buttons_layout = QHBoxLayout()
        self.start_layout.addStretch(1)
        self.start_buttons_layout.addStretch(1)
        self.next_button_start = QPushButton('Start')
        self.next_button_start.setMaximumWidth(80)
        self.next_button_start.clicked.connect(self.go_to_license)
        self.start_buttons_layout.addWidget(self.next_button_start)
        self.start_layout.addLayout(self.start_buttons_layout)

        # License Layout
        self.license_widget = QWidget()
        self.license_layout = QVBoxLayout(self.license_widget)
        self.license_first_label = QLabel('License Agreement')
        self.license_first_label.setStyleSheet(
            "margin-left: 10px; font: bold;")
        self.license_second_label = QLabel(
            "Please read the following important information before continuing.")
        self.license_second_label.setStyleSheet(
            "margin-left: 35px; margin-right: 50px; margin-bottom: 30px;")
        self.license_third_label = QLabel(
            "Please read the following License Agreement. You must accept the terms of this agreement before\ncontinuing with the installation.")
        self.license_third_label.setStyleSheet(
            "margin-left: 35px; margin-right: 50px;")
        self.license_layout.addWidget(self.license_first_label)
        self.license_layout.addWidget(self.license_second_label)
        self.license_layout.addWidget(self.license_third_label)
        self.license_text = QTextEdit()
        self.license_text.setReadOnly(True)  # Make it read-only if editing is not required
        self.license_text.setText("""
        MIT License

        Copyright (c) 2023 Havard03

        Permission is hereby granted, free of charge, to any person obtaining a copy
        of this software and associated documentation files (the "Software"), to deal
        in the Software without restriction, including without limitation the rights
        to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
        copies of the Software, and to permit persons to whom the Software is
        furnished to do so, subject to the following conditions:

        The above copyright notice and this permission notice shall be included in all
        copies or substantial portions of the Software.

        THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
        IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
        FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
        AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
        LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
        OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
        SOFTWARE.
        """)
        self.license_text.setStyleSheet(
            "QTextEdit {"
            "margin-left: 35px;"
            "margin-right: 35px;"
            "border: 1px solid;"
            "}"
        )
        self.license_layout.addWidget(self.license_text)
        self.agree_radio = QRadioButton('I accept the agreement')
        self.disagree_radio = QRadioButton('I do not accept the agreement')
        # Apply the same margin style as the second and third labels
        radio_style = "margin-left: 35px;"
        self.agree_radio.setStyleSheet(radio_style)
        self.disagree_radio.setStyleSheet(radio_style)
        self.agree_radio.toggled.connect(self.update_next_button_state)
        self.license_layout.addWidget(self.agree_radio)
        self.license_layout.addWidget(self.disagree_radio)
        self.disagree_radio.setChecked(True)
        self.license_buttons_layout = QHBoxLayout()
        self.license_buttons_layout.addStretch(1)
        self.back_button_license = QPushButton('Back')
        self.back_button_license.setMaximumWidth(80)
        self.back_button_license.clicked.connect(self.go_to_start)
        self.next_button_license = QPushButton('Next')
        self.next_button_license.setMaximumWidth(80)
        self.next_button_license.setEnabled(False)
        self.next_button_license.clicked.connect(self.go_to_directory)
        self.cancel_button_license = QPushButton('Cancel')
        self.cancel_button_license.setMaximumWidth(80)
        self.cancel_button_license.clicked.connect(self.handle_cancel)
        self.license_buttons_layout.addWidget(self.back_button_license)
        self.license_buttons_layout.addWidget(self.next_button_license)
        self.license_buttons_layout.addWidget(self.cancel_button_license)
        self.license_layout.addLayout(self.license_buttons_layout)

        # Directory Layout
        self.directory_widget = QWidget()
        self.directory_layout = QVBoxLayout(self.directory_widget)
        self.directory_first_label = QLabel('Select Destination Location')
        self.directory_first_label.setStyleSheet(
            "margin-left: 10px; font-weight: bold;")
        self.directory_second_label = QLabel(
            "Where should Spotr be installed?")
        self.directory_second_label.setStyleSheet(
            "margin-left: 35px; margin-right: 50px; margin-bottom: 30px;")
        icon_path = resource_path("./Folder_Icon.png")  # Get the path of the icon
        icon_pixmap = QPixmap(icon_path)  # Create a QPixmap object
        directory_third_icon = QLabel()
        directory_third_icon.setPixmap(icon_pixmap.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.directory_third_label_text = QLabel(
            "Setup will install Spotr into the following folder.")
        self.directory_third_label_layout = QHBoxLayout()
        self.directory_third_label_layout.addWidget(
            directory_third_icon)  # Add the icon to the layout
        self.directory_third_label_layout.addWidget(
            self.directory_third_label_text, 1)  # Add the text to the layout
        directory_third_container = QWidget()
        directory_third_container.setLayout(self.directory_third_label_layout)
        directory_third_icon.setStyleSheet(
            "margin-left: 25px;")
        self.directory_fourth_label = QLabel(
            "To continue, click Next. If you would like to select a different folder, click Browse.")
        self.directory_fourth_label.setStyleSheet(
            "margin-left: 35px; margin-right: 50px;")
        self.directory_layout.addWidget(self.directory_first_label)
        self.directory_layout.addWidget(self.directory_second_label)
        self.directory_layout.addWidget(directory_third_container)
        self.directory_layout.addWidget(self.directory_fourth_label)
        self.directory_hlayout = QHBoxLayout()
        self.directory_line_edit = QLineEdit()
        self.directory_line_edit.setMinimumWidth(350)
        directory_path = os.environ.get('LOCALAPPDATA', '')
        self.directory_line_edit.setText(directory_path)
        self.directory_line_edit.setStyleSheet(
            "QLineEdit {"
            "margin-left: 35px;"
            "border-bottom: 1px solid;"
            "padding: 4px;"
            "}"
        )
        self.browse_button = QPushButton('Browse...')
        self.browse_button.clicked.connect(self.browse)
        self.browse_button.setStyleSheet(
            "QPushButton {"
            "padding: 5px;"
            "min-width: 80px;"
            "margin-right: 35px;"
            "}"
        )

        self.directory_hlayout.addWidget(self.directory_line_edit)
        self.directory_hlayout.addWidget(self.browse_button)
        self.directory_layout.addLayout(self.directory_hlayout)
        self.directory_layout.addStretch(1)
        self.directory_buttons_layout = QHBoxLayout()
        self.directory_buttons_layout.addStretch(1)
        self.fifth_label = QLabel(
            "At least 105,1 KB of free disk space required.")
        self.fifth_label.setStyleSheet(
            "margin-left: 35px; margin-bottom: 10px;")
        self.directory_layout.addWidget(self.fifth_label)
        self.back_button_directory = QPushButton('Back')
        self.back_button_directory.setMaximumWidth(80)
        self.back_button_directory.clicked.connect(self.go_to_license)
        self.next_button_directory = QPushButton('Next')
        self.next_button_directory.setMaximumWidth(80)
        self.next_button_directory.clicked.connect(self.go_to_ready)
        self.cancel_button_directory = QPushButton('Cancel')
        self.cancel_button_directory.setMaximumWidth(80)
        self.cancel_button_directory.clicked.connect(self.handle_cancel)
        self.directory_buttons_layout.addWidget(self.back_button_directory)
        self.directory_buttons_layout.addWidget(self.next_button_directory)
        self.directory_buttons_layout.addWidget(self.cancel_button_directory)
        self.directory_layout.addLayout(self.directory_buttons_layout)

        # Ready Layout
        self.ready_widget = QWidget()
        self.ready_layout = QVBoxLayout(self.ready_widget)
        self.ready_first_label = QLabel('Ready to Install')
        self.ready_first_label.setStyleSheet(
            "margin-left: 10px; font: bold;")
        self.ready_second_label = QLabel(
            "Setup is now ready to begin installing Spotr on your computer.")
        self.ready_second_label.setStyleSheet(
            "margin-left: 35px; margin-right: 50px; margin-bottom: 30px;")
        self.ready_third_label = QLabel(
            "Click Install to continue with the installation, or click Back if you want to review or change any settings.")
        self.ready_third_label.setStyleSheet(
            "margin-left: 35px;")
        self.ready_layout.addWidget(self.ready_first_label)
        self.ready_layout.addWidget(self.ready_second_label)
        self.ready_layout.addWidget(self.ready_third_label)
        self.ready_text = QTextEdit()
        self.ready_text.setReadOnly(True)
        self.ready_text.setStyleSheet(
            "QTextEdit {"
            "margin-left: 35px;"
            "margin-right: 35px;"
            "border: 1px solid #c0c0c0;"
            "background-color: #f0f0f0;"
            "color: #000000;"
            "}"
        )
        self.ready_layout.addWidget(self.ready_text)
        self.ready_buttons_layout = QHBoxLayout()
        self.ready_buttons_layout.addStretch(1)
        self.back_button_ready = QPushButton('Back')
        self.back_button_ready.setMaximumWidth(80)
        self.back_button_ready.clicked.connect(self.go_to_directory)
        self.next_button_ready = QPushButton('Install')
        self.next_button_ready.setMaximumWidth(80)
        self.next_button_ready.clicked.connect(self.go_to_install)
        self.cancel_button_ready = QPushButton('Cancel')
        self.cancel_button_ready.setMaximumWidth(80)
        self.cancel_button_ready.clicked.connect(self.handle_cancel)
        self.ready_buttons_layout.addWidget(self.back_button_ready)
        self.ready_buttons_layout.addWidget(self.next_button_ready)
        self.ready_buttons_layout.addWidget(self.cancel_button_ready)
        self.ready_layout.addLayout(self.ready_buttons_layout)

        # Install Layout
        self.install_widget = QWidget()
        self.install_layout = QVBoxLayout(self.install_widget)
        self.install_first_label = QLabel('Installing')
        self.install_first_label.setStyleSheet(
            "margin-left: 10px; font: bold;")
        self.install_second_label = QLabel(
            "Please wait while Spotr Setup installs Spotr on your computer.")
        self.install_second_label.setStyleSheet(
            "margin-left: 35px; margin-right: 50px; margin-bottom: 30px;")
        self.install_layout.addWidget(self.install_first_label)
        self.install_layout.addWidget(self.install_second_label)
        self.output_label = QLabel()
        self.output_label.setStyleSheet(
            "margin-left: 35px; margin-right: 50px;")
        self.output_label.setWordWrap(True)
        self.output_label.setMaximumHeight(20)
        self.output_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.install_layout.addWidget(self.output_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(
            "margin-left: 35px; margin-right: 50px;")
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.install_layout.addWidget(self.progress_bar)
        # Add stretch to push everything to the top
        self.install_layout.addStretch(1)

        # Authentication Layout
        self.auth_widget = QWidget()
        self.auth_layout = QVBoxLayout(self.auth_widget)
        self.auth_first_label = QLabel('Authentication')
        self.auth_first_label.setStyleSheet(
            "margin-left: 10px; font: bold;")
        self.auth_second_label = QLabel(
            "Authenticate your spotify account to use Spotr.")
        self.auth_second_label.setStyleSheet(
            "margin-left: 35px; margin-right: 50px; margin-bottom: 30px;")
        self.auth_third_label = QLabel(
            "Get your Client ID and Client Secret from <a href='https://developer.spotify.com/dashboard/create'>https://developer.spotify.com/dashboard/create</a> and paste \nthem in the fields below.")
        self.auth_third_label.setOpenExternalLinks(True)
        self.auth_third_label.setWordWrap(True)  # Enable word wrap
        self.auth_third_label.setStyleSheet(
            "margin-left: 35px; margin-right:35px; margin-bottom: 10px;")
        self.auth_layout.addWidget(self.auth_first_label)
        self.auth_layout.addWidget(self.auth_second_label)
        self.auth_layout.addWidget(self.auth_third_label)
        self.auth_client_id_text = QLabel('Client ID')
        self.auth_client_id_text.setStyleSheet(
            "margin-left: 35px; margin-right: 35px;")
        self.auth_layout.addWidget(self.auth_client_id_text)
        self.client_id_input = QLineEdit()
        self.client_id_input.setStyleSheet(
            "margin-left: 35px; margin-right: 35px;")
        self.client_id_input.textChanged.connect(self.check_credentials_filled)
        self.auth_layout.addWidget(self.client_id_input)
        self.auth_client_secret_text = QLabel('Client Secret')
        self.auth_client_secret_text.setStyleSheet(
            "margin-left: 35px; margin-right: 35px;")
        self.auth_layout.addWidget(self.auth_client_secret_text)
        self.client_secret_input = QLineEdit()
        self.client_secret_input.setStyleSheet(
            "margin-left: 35px;  margin-right: 35px;")
        self.client_secret_input.textChanged.connect(
            self.check_credentials_filled)
        self.auth_layout.addWidget(self.client_secret_input)
        self.auth_code_layout = QHBoxLayout()
        self.auth_code_text = QLabel('Redirect URL')
        self.auth_code_text.setStyleSheet("margin-left: 35px;")
        self.auth_code_layout.addWidget(self.auth_code_text)
        self.auth_code_input = QLineEdit()
        self.auth_code_input.setEnabled(False)
        # Set the maximum width to 200 pixels
        self.auth_code_input.setMaximumWidth(340)
        self.auth_code_layout.addWidget(self.auth_code_input)
        self.get_button = QPushButton('Get')
        self.get_button.setStyleSheet(
            "margin-right: 35px; padding-top: 4px; padding-bottom: 4px;")
        self.get_button.clicked.connect(self.handle_get_clicked)
        self.get_button.setEnabled(False)
        self.verify_button = QPushButton('Verify')
        self.verify_button.setStyleSheet(
            "margin-right: 35px; padding-top: 4px; padding-bottom: 4px;")
        self.verify_button.clicked.connect(self.handle_verify_clicked)
        self.verify_button.setVisible(False)
        self.auth_code_layout.addWidget(self.get_button)
        self.auth_code_layout.addWidget(self.verify_button)
        self.auth_layout.addLayout(self.auth_code_layout)
        self.auth_text = QLabel(
            "URL will open in 5 seconds, Accept the terms, Copy the code in the redirected URL.\nThen paste the code into the input field")
        self.auth_text.setStyleSheet("margin-left: 35px;")
        self.auth_text.setVisible(False)
        self.auth_layout.addWidget(self.auth_text)
        self.auth_checkbox = QCheckBox("Enable lyrics?")
        self.auth_checkbox.setStyleSheet("margin-left: 35px;")
        self.auth_checkbox.setVisible(False)
        self.auth_checkbox.setChecked(True)
        self.auth_layout.addWidget(self.auth_checkbox)
        self.auth_layout.addStretch(1)
        self.auth_buttons_layout = QHBoxLayout()
        self.auth_buttons_layout.addStretch(1)
        self.next_button_auth = QPushButton('Next')
        self.next_button_auth.setMaximumWidth(80)
        self.next_button_auth.setEnabled(False)
        self.next_button_auth.clicked.connect(self.handle_auth_next)
        self.cancel_button_auth = QPushButton('Cancel')
        self.cancel_button_auth.setMaximumWidth(80)
        self.cancel_button_auth.clicked.connect(self.handle_cancel)
        self.auth_buttons_layout.addWidget(self.next_button_auth)
        self.auth_buttons_layout.addWidget(self.cancel_button_auth)
        self.auth_layout.addLayout(self.auth_buttons_layout)

        # Genius Layout
        self.genius_widget = QWidget()
        self.genius_layout = QVBoxLayout(self.genius_widget)
        self.genius_first_label = QLabel('Authenticate your Genius app')
        self.genius_first_label.setStyleSheet(
            "margin-left: 10px; font: bold;")
        self.genius_second_label = QLabel(
            "Authenticate your Genius account to use Spotr Lyrics.")
        self.genius_second_label.setStyleSheet(
            "margin-left: 35px; margin-right: 50px; margin-bottom: 30px;")
        self.genius_third_label = QLabel(
            "Get your Client Access Token from <a href='https://genius.com/api-clients/new'>https://genius.com/api-clients/new</a> and paste it in the field below.")
        self.genius_third_label.setOpenExternalLinks(True)
        self.genius_third_label.setWordWrap(True)
        self.genius_third_label.setStyleSheet(
            "margin-left: 35px; margin-bottom: 10px;")
        self.genius_layout.addWidget(self.genius_first_label)
        self.genius_layout.addWidget(self.genius_second_label)
        self.genius_layout.addWidget(self.genius_third_label)
        self.genius_layout_text = QLabel('Client Access Token')
        self.genius_layout_text.setStyleSheet("margin-left: 35px;")
        self.genius_layout.addWidget(self.genius_layout_text)
        self.genius_access_token_input = QLineEdit()
        self.genius_access_token_input.setStyleSheet(
            "margin-left: 35px; margin-right: 35px;")
        self.genius_layout.addWidget(self.genius_access_token_input)
        self.genius_layout.addStretch(1)
        self.genius_buttons_layout = QHBoxLayout()
        self.genius_buttons_layout.addStretch(1)
        self.back_button_genius = QPushButton('Back')
        self.back_button_genius.setMaximumWidth(80)
        self.back_button_genius.clicked.connect(self.go_to_auth)
        self.next_button_genius = QPushButton('Next')
        self.next_button_genius.setMaximumWidth(80)
        self.next_button_genius.clicked.connect(
            self.handle_genius_next_clicked)
        self.cancel_button_genius = QPushButton('Cancel')
        self.cancel_button_genius.setMaximumWidth(80)
        self.cancel_button_genius.clicked.connect(self.handle_cancel)
        self.genius_buttons_layout.addWidget(self.back_button_genius)
        self.genius_buttons_layout.addWidget(self.next_button_genius)
        self.genius_buttons_layout.addWidget(self.cancel_button_genius)
        self.genius_layout.addLayout(self.genius_buttons_layout)

        # Finish Layout
        self.finish_widget = QWidget()
        self.finish_layout = QVBoxLayout(self.finish_widget)
        self.finish_first_label = QLabel('Setup is now finished')
        self.finish_first_label.setStyleSheet(
            "margin-left: 10px; font: bold;")
        self.finish_second_label = QLabel(
            "Make sure to add this to the system environment PATH:")
        self.finish_second_label.setStyleSheet(
            "margin-left: 35px; margin-right: 50px; margin-bottom: 30px;")
        self.finish_layout.addWidget(self.finish_first_label)
        self.finish_layout.addWidget(self.finish_second_label)
        self.path_layout = QHBoxLayout()
        self.dir_label = QLabel(os.path.join(directory_path, 'Spotr'))
        self.dir_label.setStyleSheet(
            "margin-left: 35px; margin-right: 50px;")
        self.dir_button = QPushButton("Copy to Clipboard")
        self.dir_button.clicked.connect(self.copy_to_clipboard)
        self.dir_button.setStyleSheet(
            "margin-left: 35px; margin-right: 35px; padding-top: 4px; padding-bottom: 4px;")
        self.path_layout.addWidget(self.dir_label)
        self.path_layout.addWidget(self.dir_button)
        self.finish_layout.addLayout(self.path_layout)
        self.finish_checkbox = QCheckBox("Test Spotr?")
        self.finish_checkbox.setStyleSheet(
            "margin-left: 35px; margin-right: 50px;")
        self.finish_checkbox.setChecked(True)
        self.finish_layout.addWidget(self.finish_checkbox)
        self.finish_layout.addStretch(1)
        self.finish_button = QPushButton("Finish")
        # Assuming you want to handle finish
        self.finish_button.clicked.connect(self.handle_finish)
        self.finish_layout.addWidget(self.finish_button)

        # Add the widgets to the stacked widget
        self.stacked_widget.addWidget(self.start_widget)
        self.stacked_widget.addWidget(self.license_widget)
        self.stacked_widget.addWidget(self.directory_widget)
        self.stacked_widget.addWidget(self.ready_widget)
        self.stacked_widget.addWidget(self.install_widget)
        self.stacked_widget.addWidget(self.auth_widget)
        self.stacked_widget.addWidget(self.genius_widget)
        self.stacked_widget.addWidget(self.finish_widget)
        # Set the layout of the main window
        self.setLayout(self.stacked_widget.layout())

        self.setFixedSize(self.size())



    def set_logo(self, label, image_path):
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            print("Failed to load image:", image_path)
            return
        label.setPixmap(pixmap)
        label.setScaledContents(True)  # Make the image scale to fit the label

    def update_next_button_state(self):
        # Enable the 'Next' button only if the 'I accept the agreement' radio button is checked
        self.next_button_license.setEnabled(self.agree_radio.isChecked())

    def go_to_start(self):
        self.stacked_widget.setCurrentWidget(self.start_widget)

    def go_to_license(self):
        self.stacked_widget.setCurrentWidget(self.license_widget)

    def go_to_directory(self):
        self.stacked_widget.setCurrentWidget(self.directory_widget)

    def go_to_ready(self):
        # Update the display with the latest directory path
        self.update_installation_path_display()
        self.stacked_widget.setCurrentWidget(self.ready_widget)

    def go_to_install(self):
        # Get the directory from the input field
        directory = self.directory_line_edit.text()
        # Pass the directory to the InstallThread
        self.install_thread = InstallThread(directory)
        self.install_thread.update_progress.connect(self.set_progress)
        self.install_thread.update_output.connect(self.append_output)
        self.install_thread.installation_finished.connect(
            self.show_auth_layout)
        self.install_thread.start()
        self.stacked_widget.setCurrentWidget(self.install_widget)

    def go_to_auth(self):
        self.stacked_widget.setCurrentWidget(self.auth_widget)

    def handle_auth_next(self):
        if self.auth_checkbox.isChecked():
            self.go_to_genius()
        else:
            self.go_to_finish

    def copy_to_clipboard(self):
        clipboard = QApplication.clipboard()
        text_to_copy = self.dir_label.text()
        clipboard.setText(text_to_copy)
        self.dir_button.setText('Copied!')

    def go_to_genius(self):
        self.stacked_widget.setCurrentWidget(self.genius_widget)

    def go_to_finish(self):
        self.stacked_widget.setCurrentWidget(self.finish_widget)

    def handle_finish(self):
        if self.finish_checkbox.checkState() == Qt.Checked:
            os.system("start cmd")
            QApplication.instance().quit()

        else:
            QApplication.instance().quit()

    def check_credentials_filled(self):
        if self.client_id_input.text() and self.client_secret_input.text():
            self.auth_code_input.setEnabled(True)
            self.get_button.setEnabled(True)
        else:
            self.auth_code_input.setEnabled(False)
            self.get_button.setEnabled(False)

    def handle_get_clicked(self):
        self.get_button.setVisible(False)
        self.auth_text.setVisible(True)
        # Get the client ID and secret from the QLineEdits
        client_id = self.client_id_input.text()
        client_secret = self.client_secret_input.text()
        # Update the API instance with the new client ID and secret
        self.api.spotify_client_id = client_id
        self.api.spotify_client_secret = client_secret
        # Call the open_spotify_auth method of the API instance
        QTimer.singleShot(5000, self.api.open_spotify_auth)
        self.verify_button.setVisible(True)

    def handle_verify_clicked(self):
        # Get the auth code from the QLineEdit
        auth_code = self.auth_code_input.text()
        # Call the process_spotify_auth method of the API instance with the auth code
        self.api.process_spotify_auth(auth_code)
        self.auth_checkbox.setVisible(True)
        self.next_button_auth.setEnabled(True)

    def handle_genius_next_clicked(self):
        genius_access_token = self.genius_access_token_input.text()
        self.api.authorise_genius(genius_access_token)
        self.go_to_finish()

    def handle_cancel(self):
        reply = QMessageBox.question(self, 'Exit Setup',
                                     "Are you sure you want to exit the setup?",
                                     QMessageBox.Yes | QMessageBox.No,
                                     QMessageBox.No)
        if reply == QMessageBox.Yes:
            QApplication.instance().quit()

    def browse(self):
        directory = QFileDialog.getExistingDirectory(
            self, 'Select Installation Directory', self.directory_line_edit.text(),
            QFileDialog.ShowDirsOnly
        )
        if directory:
            self.directory_line_edit.setText(directory)
            # Update the display in the ready layout
            self.update_installation_path_display()


    def set_progress(self, value):
        self.progress_bar.setValue(value)

    def append_output(self, message):
        # Use append to add text to QTextEdit
        self.output_label.setText(message)

    def show_auth_layout(self):
        self.go_to_auth()  # Switch to the authentication layout

    def update_installation_path_display(self):
        # Get the chosen directory path from the directory_line_edit
        chosen_directory = self.directory_line_edit.text()
        installation_path = os.path.join(chosen_directory, 'Spotr')
        installation_path = os.path.normpath(installation_path)
        formatted_text = f"""
        <p>Destination location:</p>
        <pre>    {installation_path}</pre>
        """
        self.ready_text.setHtml(formatted_text)


if __name__ == '__main__':
    app = QApplication([])
    wizard = Wizard()
    wizard.show()
    app.exec_()
