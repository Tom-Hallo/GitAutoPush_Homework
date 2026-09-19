"""
ui/main_window.py
Main window for GitPushManager.

Layout (top to bottom):
    1. Project bar          - New / Open / Delete project
    2. GitHub API Key area  - save / check / delete token
    3. Create Repository area - bulk-create repos on GitHub
    4. Repository table     - one row per repo: folder, commit msg,
                               branch, status, GitHub link, push action
                               (also accepts dragged-in folders)
    5. Push All bar          - Push All + Cancel
    6. Activity Log
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QSpinBox, QTableWidgetItem,
    QPlainTextEdit, QFileDialog, QMessageBox, QInputDialog, QHeaderView,
    QAbstractItemView, QSizePolicy,
)

from .. import db, github_client, git_ops, naming
from ..workers import (
    VerifyTokenWorker, CreateRepositoriesWorker, PushOneWorker, PushAllWorker,
)
from . import dialogs
from .widgets import ElidedLabel, StatusBadge, MultiCursorTextEdit, DroppableRepoTable

COL_INDEX = 0
COL_REPO = 1
COL_FOLDER = 2
COL_COMMIT = 3
COL_BRANCH = 4
COL_STATUS = 5
COL_GITHUB = 6
COL_ACTION = 7
COLUMN_HEADERS = [
    "#", "Repository", "Folder", "Commit Message", "Branch", "Status", "GitHub", "Action",
]


def _fmt_datetime(iso_str: str | None) -> str:
    if not iso_str:
        return ""
    try:
        return datetime.fromisoformat(iso_str).strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return iso_str


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GitPushManager")
        self.resize(1180, 760)
        self.setMinimumSize(880, 560)

        db.init_db()

        self.current_project: db.Project | None = None
        self.repo_rows: dict[int, db.Repository] = {}   # row index -> Repository
        self.last_error_detail: dict[int, str] = {}      # repo.id -> technical detail
        self._active_push_repo_ids: set[int] = set()      # repos currently being pushed

        self._create_repos_worker = None
        self._push_all_worker = None
        self._verify_worker = None

        self._build_ui()
        self._load_or_create_default_project()
        self._refresh_token_status(silent=True)

    # ------------------------------------------------------------ UI build

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(12)

        root.addLayout(self._build_project_bar())
        root.addWidget(self._build_api_key_box())
        root.addWidget(self._build_create_repo_box())
        root.addWidget(self._build_table())
        root.addLayout(self._build_push_all_bar())
        root.addWidget(self._build_log_box())

    def _build_project_bar(self):
        row = QHBoxLayout()
        self.project_label = QLabel("Project: (chưa có)")
        self.project_label.setStyleSheet("font-weight: 600;")
        btn_new = QPushButton("New Project")
        btn_open = QComboBox()
        btn_open.setMinimumWidth(220)
        self.project_combo = btn_open
        btn_delete = QPushButton("Delete Project")

        btn_new.clicked.connect(self._on_new_project)
        btn_open.currentIndexChanged.connect(self._on_project_selected)
        btn_delete.clicked.connect(self._on_delete_project)

        row.addWidget(self.project_label)
        row.addStretch()
        row.addWidget(QLabel("Chọn project:"))
        row.addWidget(btn_open)
        row.addWidget(btn_new)
        row.addWidget(btn_delete)
        return row

    def _build_api_key_box(self):
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("GitHub Personal Access Token")
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(title)

        row = QHBoxLayout()
        self.token_input = QLineEdit()
        self.token_input.setEchoMode(QLineEdit.Password)
        self.token_input.setPlaceholderText("Nhập GitHub Personal Access Token...")
        self.token_input.returnPressed.connect(self._on_save_token)

        btn_save = QPushButton("Lưu Token")
        btn_check = QPushButton("Kiểm tra")
        btn_delete = QPushButton("Xóa")

        btn_save.clicked.connect(self._on_save_token)
        btn_check.clicked.connect(self._on_check_token)
        btn_delete.clicked.connect(self._on_delete_token)

        row.addWidget(self.token_input)
        row.addWidget(btn_save)
        row.addWidget(btn_check)
        row.addWidget(btn_delete)
        layout.addLayout(row)

        self.token_status_label = QLabel("Trạng thái: chưa kiểm tra")
        layout.addWidget(self.token_status_label)
        return box

    def _build_create_repo_box(self):
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Tạo Repository")
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.addWidget(QLabel("Tên bài:"))
        self.prefix_input = QLineEdit()
        self.prefix_input.setPlaceholderText("Bai")
        self.prefix_input.returnPressed.connect(self._on_create_repositories)
        row.addWidget(self.prefix_input)

        row.addWidget(QLabel("Số lượng:"))
        self.quantity_input = QSpinBox()
        self.quantity_input.setRange(1, 1000)
        self.quantity_input.setValue(3)
        self.quantity_input.lineEdit().returnPressed.connect(self._on_create_repositories)
        row.addWidget(self.quantity_input)

        row.addWidget(QLabel("Format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(naming.FORMATS)
        row.addWidget(self.format_combo)

        self.btn_create_repos = QPushButton("TẠO REPOSITORY")
        self.btn_create_repos.clicked.connect(self._on_create_repositories)
        row.addWidget(self.btn_create_repos)

        layout.addLayout(row)
        return box

    def _build_table(self):
        self.table = DroppableRepoTable(0, len(COLUMN_HEADERS))
        self.table.setHorizontalHeaderLabels(COLUMN_HEADERS)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_INDEX, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_REPO, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_FOLDER, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_COMMIT, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_BRANCH, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_GITHUB, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_ACTION, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(COL_REPO, 160)
        self.table.setWordWrap(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setToolTip(
            "Có thể kéo-thả nhiều folder từ Windows Explorer vào đây để gắn "
            "folder cho các repository theo thứ tự."
        )
        self.table.foldersDropped.connect(self._on_folders_dropped)
        return self.table

    def _build_push_all_bar(self):
        row = QHBoxLayout()
        self.btn_push_all = QPushButton("🚀 PUSH TẤT CẢ")
        self.btn_push_all.clicked.connect(self._on_push_all)
        self.btn_cancel_push_all = QPushButton("Cancel")
        self.btn_cancel_push_all.clicked.connect(self._on_cancel_push_all)
        self.btn_cancel_push_all.setVisible(False)
        row.addStretch()
        row.addWidget(self.btn_cancel_push_all)
        row.addWidget(self.btn_push_all)
        return row

    def _build_log_box(self):
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Activity Log")
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(title)
        self.log_widget = QPlainTextEdit()
        self.log_widget.setReadOnly(True)
        self.log_widget.setMaximumBlockCount(2000)
        self.log_widget.setFixedHeight(160)
        layout.addWidget(self.log_widget)
        return box

    # -------------------------------------------------------------- Logging

    def log(self, message: str, level: str = "INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        icon = {"INFO": "•", "SUCCESS": "✓", "WARNING": "⚠", "ERROR": "✗"}.get(level, "•")
        self.log_widget.appendPlainText(f"{ts} {icon} {message}")

    # ------------------------------------------------------------ Projects

    def _load_or_create_default_project(self):
        projects = db.list_projects()
        if not projects:
            projects = [db.create_project("Default Project")]
        self._reload_project_combo(projects)
        self.project_combo.setCurrentIndex(0)
        self._set_current_project(projects[0])

    def _reload_project_combo(self, projects: list[db.Project]):
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        for p in projects:
            self.project_combo.addItem(p.name, userData=p.id)
        self.project_combo.blockSignals(False)

    def _set_current_project(self, project: db.Project):
        self.current_project = project
        self.project_label.setText(f"Project: {project.name}")
        self._load_repositories_into_table()

    def _on_new_project(self):
        name, ok = QInputDialog.getText(self, "New Project", "Tên project:")
        if not ok or not name.strip():
            return
        try:
            project = db.create_project(name.strip())
        except Exception:
            QMessageBox.warning(self, "Lỗi", "Tên project đã tồn tại.")
            return
        self._reload_project_combo(db.list_projects())
        idx = self.project_combo.findData(project.id)
        self.project_combo.setCurrentIndex(idx)
        self.log(f"Đã tạo project '{project.name}'", "SUCCESS")

    def _on_project_selected(self, index: int):
        if index < 0:
            return
        project_id = self.project_combo.itemData(index)
        project = db.get_project(project_id)
        if project:
            self._set_current_project(project)

    def _on_delete_project(self):
        # Dangerous action: requires an explicit click on this button and
        # an explicit confirmation click below -- Enter never reaches here.
        if not self.current_project:
            return
        if self._is_push_all_running():
            QMessageBox.warning(self, "Lỗi", "Không thể xóa project khi đang Push All.")
            return
        confirm = QMessageBox.question(
            self, "Xác nhận",
            f"Xóa project '{self.current_project.name}' và toàn bộ repository trong đó?",
        )
        if confirm != QMessageBox.Yes:
            return
        db.delete_project(self.current_project.id)
        self.log(f"Đã xóa project '{self.current_project.name}'", "WARNING")
        remaining = db.list_projects()
        if not remaining:
            remaining = [db.create_project("Default Project")]
        self._reload_project_combo(remaining)
        self.project_combo.setCurrentIndex(0)
        self._set_current_project(remaining[0])

    # -------------------------------------------------------- Token / API key

    def _refresh_token_status(self, silent: bool = False):
        has_token = github_client.load_token() is not None
        if not has_token:
            self.token_status_label.setText("✗ Chưa cấu hình GitHub Personal Access Token")
            self.token_status_label.setStyleSheet("color:#b26a00;")
        elif not silent:
            self._on_check_token()
        else:
            self.token_status_label.setText("• Đã lưu Token (chưa kiểm tra)")
            self.token_status_label.setStyleSheet("color:#555;")

    def _on_save_token(self):
        token = self.token_input.text().strip()
        if not token:
            QMessageBox.warning(self, "Lỗi", "Vui lòng nhập GitHub Personal Access Token.")
            return
        try:
            github_client.save_token(token)
        except github_client.GitHubClientError as e:
            QMessageBox.warning(self, "Lỗi", e.message)
            return
        self.token_input.clear()
        self.log("Đã lưu GitHub Personal Access Token", "SUCCESS")
        self._on_check_token()

    def _on_check_token(self):
        self.token_status_label.setText("Đang kiểm tra...")
        self._verify_worker = VerifyTokenWorker()
        self._verify_worker.finished_ok.connect(self._on_token_valid)
        self._verify_worker.finished_err.connect(self._on_token_invalid)
        self._verify_worker.start()

    def _on_token_valid(self, username: str):
        self.token_status_label.setText(f"✓ GitHub connected — User: {username}")
        self.token_status_label.setStyleSheet("color:#1a7f37;")
        self.log(f"GitHub connected (user: {username})", "SUCCESS")

    def _on_token_invalid(self, message: str, detail: str):
        self.token_status_label.setText(f"✗ {message}")
        self.token_status_label.setStyleSheet("color:#c62828;")
        self.log(message, "ERROR")

    def _on_delete_token(self):
        # Dangerous action: requires explicit click + explicit confirmation.
        confirm = QMessageBox.question(
            self, "Xác nhận", "Bạn có chắc muốn xóa GitHub Personal Access Token đã lưu?"
        )
        if confirm != QMessageBox.Yes:
            return
        github_client.delete_token()
        self.token_status_label.setText("✗ Chưa cấu hình GitHub Personal Access Token")
        self.token_status_label.setStyleSheet("color:#b26a00;")
        self.log("Đã xóa GitHub Personal Access Token", "WARNING")

    # ------------------------------------------------------- Create repos

    def _on_create_repositories(self):
        if not self.current_project:
            return
        if github_client.load_token() is None:
            QMessageBox.warning(self, "Lỗi", "Vui lòng lưu GitHub Personal Access Token trước.")
            return
        if self._create_repos_worker is not None and self._create_repos_worker.isRunning():
            return  # guard against double-click while a batch is already running

        prefix = self.prefix_input.text()
        qty = self.quantity_input.value()
        fmt = self.format_combo.currentText()
        try:
            names = naming.generate_names(prefix, qty, fmt)
        except ValueError as e:
            QMessageBox.warning(self, "Lỗi", str(e))
            return

        # Never create a duplicate DB record for a repo name already
        # tracked in this project -- this check is local/instant, no
        # need to hit the GitHub API for it.
        new_names = []
        for name in names:
            if db.repository_name_exists(self.current_project.id, name):
                self.log(f"Repository '{name}' đã tồn tại trong project — bỏ qua.", "WARNING")
            else:
                new_names.append(name)

        if not new_names:
            QMessageBox.information(
                self, "Thông báo", "Tất cả repository đã tồn tại trong project này."
            )
            return

        self.btn_create_repos.setEnabled(False)
        self.log(f"Đang tạo {len(new_names)} repository...", "INFO")

        worker = CreateRepositoriesWorker(new_names)
        worker.repo_created.connect(self._on_repo_created)
        worker.repo_skipped.connect(self._on_repo_create_skipped)
        worker.repo_failed.connect(self._on_repo_create_failed)
        worker.repo_conflict.connect(self._on_repo_conflict, Qt.BlockingQueuedConnection)
        worker.finished_all.connect(self._on_create_repos_finished)
        self._create_repos_worker = worker
        worker.start()

    def _on_create_repos_finished(self):
        self.btn_create_repos.setEnabled(True)
        self.log("Hoàn tất tạo repository.", "SUCCESS")

    def _on_repo_conflict(self, name: str, html_url: str, clone_url: str, answer_holder: list):
        # Runs on the GUI thread via a BlockingQueuedConnection: the
        # worker thread is paused until this returns.
        use_existing = dialogs.ask_use_existing_repo(self, name, html_url)
        answer_holder.append(use_existing)

    def _on_repo_created(self, name: str, html_url: str, clone_url: str, already_existed: bool):
        repo = db.Repository(
            id=None,
            project_id=self.current_project.id,
            repo_name=name,
            html_url=html_url,
            clone_url=clone_url,
            commit_message=f"Update {name}",
            status=db.STATUS_NOT_UP,
        )
        repo = db.add_repository(repo)
        self._append_repo_row(repo)
        if already_existed:
            self.log(f"Repository '{name}' đã tồn tại — đã dùng repository này", "WARNING")
        else:
            self.log(f"Created repository {name}", "SUCCESS")

    def _on_repo_create_skipped(self, name: str):
        self.log(f"Bỏ qua repository '{name}' đã tồn tại trên GitHub (theo lựa chọn của bạn).", "WARNING")

    def _on_repo_create_failed(self, name: str, message: str, detail: str):
        self.log(f"Tạo repository '{name}' thất bại: {message}", "ERROR")

    # ------------------------------------------------------------- Table

    def _load_repositories_into_table(self):
        self.table.setRowCount(0)
        self.repo_rows.clear()
        if not self.current_project:
            return
        for repo in db.list_repositories(self.current_project.id):
            self._append_repo_row(repo)

    def _append_repo_row(self, repo: db.Repository):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.repo_rows[row] = repo

        self.table.setItem(row, COL_INDEX, QTableWidgetItem(str(row + 1)))

        repo_label = ElidedLabel(repo.repo_name)
        self.table.setCellWidget(row, COL_REPO, repo_label)

        # Folder cell: warning icon (if missing) + elided path label + button
        folder_widget = QWidget()
        folder_layout = QHBoxLayout(folder_widget)
        folder_layout.setContentsMargins(4, 2, 4, 2)
        warn_label = QLabel("⚠")
        warn_label.setStyleSheet("color:#b26a00; font-weight:700;")
        warn_label.setToolTip("Chưa gắn folder cho repository này.")
        warn_label.setVisible(not repo.folder_path)
        folder_label = ElidedLabel(repo.folder_path or "(chưa gắn folder)")
        folder_btn = QPushButton("Đổi Folder" if repo.folder_path else "Chọn Folder")
        folder_btn.clicked.connect(lambda _, r=row: self._on_choose_folder(r))
        folder_layout.addWidget(warn_label)
        folder_layout.addWidget(folder_label, stretch=1)
        folder_layout.addWidget(folder_btn)
        self.table.setCellWidget(row, COL_FOLDER, folder_widget)
        repo._folder_label = folder_label
        repo._folder_warn = warn_label
        repo._folder_btn = folder_btn

        # Commit message: Ctrl+D-capable editor
        commit_edit = MultiCursorTextEdit(repo.commit_message)
        commit_edit.editingFinished.connect(lambda r=row: self._on_commit_message_changed(r))
        self.table.setCellWidget(row, COL_COMMIT, commit_edit)
        repo._commit_edit = commit_edit

        branch_label = QLabel(repo.branch or "main")
        branch_label.setAlignment(Qt.AlignCenter)
        self.table.setCellWidget(row, COL_BRANCH, branch_label)
        repo._branch_label = branch_label

        status_badge = StatusBadge(repo.status)
        self.table.setCellWidget(row, COL_STATUS, status_badge)
        repo._status_badge = status_badge

        github_btn = QPushButton("↗")
        github_btn.setFixedWidth(36)
        github_url = repo.html_url or repo.clone_url or repo.repo_url
        github_btn.setEnabled(bool(github_url))
        github_btn.setToolTip(github_url or "Chưa có URL GitHub")
        github_btn.clicked.connect(lambda _, r=row: self._on_open_github(r))
        self.table.setCellWidget(row, COL_GITHUB, github_btn)
        repo._github_btn = github_btn

        # Action cell: Push button + "Chi tiết lỗi" (hidden unless failed)
        action_widget = QWidget()
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 2, 4, 2)
        push_btn = QPushButton("Push")
        push_btn.clicked.connect(lambda _, r=row: self._on_push_one(r))
        if repo.last_push_at:
            push_btn.setToolTip(f"Last push: {_fmt_datetime(repo.last_push_at)}")
        detail_btn = QPushButton("Chi tiết lỗi")
        detail_btn.setVisible(repo.status == db.STATUS_FAILED)
        detail_btn.clicked.connect(lambda _, r=row: self._on_show_error_detail(r))
        action_layout.addWidget(push_btn)
        action_layout.addWidget(detail_btn)
        self.table.setCellWidget(row, COL_ACTION, action_widget)
        repo._push_btn = push_btn
        repo._detail_btn = detail_btn

        self.table.resizeRowToContents(row)

    def _on_commit_message_changed(self, row: int):
        repo = self.repo_rows.get(row)
        if not repo:
            return
        text = repo._commit_edit.text()
        if text == repo.commit_message:
            return
        repo.commit_message = text
        db.update_repository(repo)

    def _on_open_github(self, row: int):
        repo = self.repo_rows.get(row)
        if not repo:
            return
        url = repo.html_url or repo.clone_url or repo.repo_url
        if not url:
            return
        QDesktopServices.openUrl(QUrl(url))

    def _on_choose_folder(self, row: int):
        repo = self.repo_rows.get(row)
        if not repo:
            return
        folder = QFileDialog.getExistingDirectory(self, f"Chọn folder cho {repo.repo_name}")
        if not folder:
            return
        valid, error = git_ops.validate_folder(folder)
        if not valid:
            QMessageBox.warning(self, "Folder không hợp lệ", error)
            self.log(f"Folder không hợp lệ cho {repo.repo_name}: {error}", "ERROR")
            return
        self._assign_folder(row, folder)
        self.log(f"Folder đã được gắn cho {repo.repo_name}: {folder}", "SUCCESS")

    def _assign_folder(self, row: int, folder: str):
        repo = self.repo_rows.get(row)
        if not repo:
            return
        repo.folder_path = folder
        db.update_repository(repo)
        repo._folder_label.set_full_text(folder)
        repo._folder_warn.setVisible(False)
        repo._folder_btn.setText("Đổi Folder")
        self._set_row_status(row, db.STATUS_NOT_UP)

    # ------------------------------------------------- Drag & drop folders

    def _on_folders_dropped(self, folders: list[str]):
        rows = sorted(self.repo_rows.keys())
        n_repos = len(rows)
        n_folders = len(folders)
        if n_repos == 0:
            QMessageBox.information(self, "Thông báo", "Chưa có repository nào để gắn folder.")
            return

        if n_folders != n_repos:
            proceed = dialogs.confirm_folder_count_mismatch(self, n_folders, n_repos)
            if not proceed:
                self.log("Drag & drop folder bị hủy (số lượng không khớp).", "INFO")
                return

        count = min(n_folders, n_repos)
        applied = 0
        for i in range(count):
            row = rows[i]
            folder = folders[i]
            valid, error = git_ops.validate_folder(folder)
            repo = self.repo_rows[row]
            if not valid:
                self.log(f"Bỏ qua folder không hợp lệ cho {repo.repo_name}: {error}", "ERROR")
                continue
            self._assign_folder(row, folder)
            self.log(f"✓ {repo.repo_name} ← {folder}", "SUCCESS")
            applied += 1

        if applied:
            self.log(f"Đã gắn folder cho {applied} repository qua drag & drop.", "SUCCESS")

    def _set_row_status(self, row: int, status: str):
        repo = self.repo_rows.get(row)
        if not repo:
            return
        repo.status = status
        db.update_repository(repo)
        repo._status_badge.set_status(status)
        repo._detail_btn.setVisible(status == db.STATUS_FAILED)

    # -------------------------------------------------------------- Push

    def _is_push_all_running(self) -> bool:
        return self._push_all_worker is not None and self._push_all_worker.isRunning()

    def _set_all_push_buttons_enabled(self, enabled: bool):
        for repo in self.repo_rows.values():
            # Never re-enable a row that is individually mid-push (should
            # not normally happen while Push All runs, but stay safe).
            if enabled and repo.id in self._active_push_repo_ids:
                continue
            repo._push_btn.setEnabled(enabled)

    def _on_push_one(self, row: int):
        repo = self.repo_rows.get(row)
        if not repo:
            return
        if self._is_push_all_running():
            QMessageBox.information(self, "Thông báo", "Đang chạy Push All, vui lòng đợi.")
            return
        if repo.id in self._active_push_repo_ids:
            return  # already pushing this repo -- ignore the extra click
        if not repo.folder_path:
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn folder trước khi push.")
            return
        if not repo.commit_message.strip():
            QMessageBox.warning(self, "Lỗi", "Commit message không được để trống.")
            return

        self._active_push_repo_ids.add(repo.id)
        repo._push_btn.setEnabled(False)
        self._set_row_status(row, db.STATUS_PUSHING)
        self.log(f"Pushing {repo.repo_name}", "INFO")

        worker = PushOneWorker(repo)
        worker.result_ready.connect(lambda result, r=row: self._on_push_one_done(r, result))
        repo._push_worker = worker  # keep a reference alive
        worker.start()

    def _on_push_one_done(self, row: int, result: git_ops.PushResult):
        repo = self.repo_rows.get(row)
        if not repo:
            return
        self._active_push_repo_ids.discard(repo.id)
        repo._push_btn.setEnabled(True)
        if result.success:
            self._set_row_status(row, db.STATUS_SUCCESS)
            repo.last_push_at = datetime.now().isoformat(timespec="seconds")
            db.update_repository(repo)
            repo._push_btn.setToolTip(f"Last push: {_fmt_datetime(repo.last_push_at)}")
            if result.no_changes:
                self.log(f"{repo.repo_name}: {result.message}", "SUCCESS")
            else:
                self.log(f"{repo.repo_name} pushed successfully", "SUCCESS")
        else:
            self._set_row_status(row, db.STATUS_FAILED)
            self.last_error_detail[repo.id] = result.technical_detail
            self.log(f"{repo.repo_name} push failed: {result.message}", "ERROR")

    def _on_show_error_detail(self, row: int):
        repo = self.repo_rows.get(row)
        if not repo:
            return
        detail = self.last_error_detail.get(repo.id, "(không có chi tiết)")
        QMessageBox.information(self, f"Chi tiết lỗi — {repo.repo_name}", detail or "(không có chi tiết)")

    def _on_push_all(self):
        # Dangerous / batch action: always requires explicit confirmation,
        # and is guarded against being started twice.
        if self._is_push_all_running():
            return
        repos = [r for r in self.repo_rows.values()]
        if not repos:
            QMessageBox.information(self, "Thông báo", "Chưa có repository nào để push.")
            return

        if not dialogs.confirm_push_all(self, len(repos)):
            self.log("Push All cancelled by user.", "INFO")
            return

        self.btn_push_all.setEnabled(False)
        self.btn_cancel_push_all.setVisible(True)
        self.btn_cancel_push_all.setEnabled(True)
        self._set_all_push_buttons_enabled(False)
        self.log(f"Bắt đầu push tất cả ({len(repos)} repository)", "INFO")

        self._push_all_worker = PushAllWorker(repos)
        self._push_all_worker.repo_started.connect(self._on_batch_repo_started)
        self._push_all_worker.repo_finished.connect(self._on_batch_repo_finished)
        self._push_all_worker.all_finished.connect(self._on_batch_all_finished)
        self._push_all_worker.start()

    def _on_cancel_push_all(self):
        if self._push_all_worker is not None:
            self._push_all_worker.cancel()
            self.btn_cancel_push_all.setEnabled(False)
            self.log("Đang hủy Push All (sẽ dừng sau khi repository hiện tại hoàn tất)...", "WARNING")

    def _row_for_repo_name(self, name: str) -> int | None:
        for row, repo in self.repo_rows.items():
            if repo.repo_name == name:
                return row
        return None

    def _on_batch_repo_started(self, repo_name: str):
        row = self._row_for_repo_name(repo_name)
        if row is not None:
            self._set_row_status(row, db.STATUS_PUSHING)
            self.log(f"Pushing {repo_name}", "INFO")

    def _on_batch_repo_finished(self, result: git_ops.PushResult):
        row = self._row_for_repo_name(result.repo_name)
        if row is None:
            return
        repo = self.repo_rows[row]
        if result.success:
            self._set_row_status(row, db.STATUS_SUCCESS)
            repo.last_push_at = datetime.now().isoformat(timespec="seconds")
            db.update_repository(repo)
            repo._push_btn.setToolTip(f"Last push: {_fmt_datetime(repo.last_push_at)}")
            if result.no_changes:
                self.log(f"{result.repo_name}: {result.message}", "SUCCESS")
            else:
                self.log(f"{result.repo_name} pushed successfully", "SUCCESS")
        else:
            self._set_row_status(row, db.STATUS_FAILED)
            self.last_error_detail[repo.id] = result.technical_detail
            self.log(f"{result.repo_name} push failed: {result.message}", "ERROR")

    def _on_batch_all_finished(self, was_cancelled: bool):
        self.btn_push_all.setEnabled(True)
        self.btn_cancel_push_all.setVisible(False)
        self._set_all_push_buttons_enabled(True)
        if was_cancelled:
            self.log("Push All đã bị hủy.", "WARNING")
        else:
            self.log("Hoàn tất Push Tất Cả", "SUCCESS")

    # -------------------------------------------------------------- Close

    def closeEvent(self, event):
        if self._is_push_all_running():
            if not dialogs.confirm_close_while_pushing(self):
                event.ignore()
                return
            self._push_all_worker.cancel()
        event.accept()
