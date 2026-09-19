"""
ui/dialogs.py
Confirmation dialogs used by main_window.py. Pulled into their own
module because there are several of them and each needs custom button
text (the default Yes/No of QMessageBox.question() does not say what
"Yes" actually means, which matters for a dangerous action like
Push All).
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox


def confirm_push_all(parent, count: int) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle("Xác nhận Push All")
    box.setText(
        f"Bạn sắp push {count} repositories.\n\n"
        "Các repository sẽ được xử lý lần lượt.\n"
        "Repository lỗi sẽ không làm dừng các repository tiếp theo.\n\n"
        "Bạn có muốn tiếp tục?"
    )
    btn_cancel = box.addButton("Hủy", QMessageBox.RejectRole)
    btn_ok = box.addButton("Push tất cả", QMessageBox.AcceptRole)
    box.setDefaultButton(btn_cancel)
    box.exec()
    return box.clickedButton() is btn_ok


def confirm_folder_count_mismatch(parent, n_folders: int, n_repos: int) -> bool:
    if n_folders < n_repos:
        text = (
            f"Bạn chỉ kéo {n_folders} folder cho {n_repos} repository.\n\n"
            f"{n_folders} repository đầu tiên sẽ được gắn folder.\n\n"
            "Tiếp tục?"
        )
    else:
        text = (
            f"Bạn kéo {n_folders} folder nhưng chỉ có {n_repos} repository.\n\n"
            f"Chỉ {n_repos} folder đầu tiên sẽ được gắn.\n\n"
            "Tiếp tục?"
        )
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Số lượng folder không khớp")
    box.setText(text)
    btn_cancel = box.addButton("Hủy", QMessageBox.RejectRole)
    btn_ok = box.addButton("Tiếp tục", QMessageBox.AcceptRole)
    box.setDefaultButton(btn_cancel)
    box.exec()
    return box.clickedButton() is btn_ok


def ask_use_existing_repo(parent, name: str, html_url: str) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle("Repository đã tồn tại")
    url_line = f"\n\n{html_url}" if html_url else ""
    box.setText(f"Repository '{name}' đã tồn tại trên GitHub.{url_line}")
    btn_skip = box.addButton("Bỏ qua", QMessageBox.RejectRole)
    btn_use = box.addButton("Dùng Repository này", QMessageBox.AcceptRole)
    box.setDefaultButton(btn_skip)
    box.exec()
    return box.clickedButton() is btn_use


def confirm_close_while_pushing(parent) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Đang push")
    box.setText(
        "Push All đang chạy. Đóng ứng dụng bây giờ có thể làm gián đoạn "
        "quá trình push.\n\nBạn có chắc muốn đóng?"
    )
    btn_cancel = box.addButton("Ở lại", QMessageBox.RejectRole)
    btn_ok = box.addButton("Đóng ứng dụng", QMessageBox.AcceptRole)
    box.setDefaultButton(btn_cancel)
    box.exec()
    return box.clickedButton() is btn_ok
