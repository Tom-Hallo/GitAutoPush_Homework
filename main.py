"""
GitHub Push Manager
--------------------
Desktop app giúp sinh viên quản lý nhiều bài tập GitHub và push code
mà không cần dùng Terminal thủ công.

Chạy:
    pip install -r requirements.txt
    python main.py
"""

import sys

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("GitPushManager")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
