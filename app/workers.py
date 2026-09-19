"""
workers.py
Background QThread workers so GitHub/Git operations never freeze the GUI.

Threading notes
----------------
All Git/GitHub network calls happen inside `run()`, i.e. on the worker
thread. Workers never touch UI widgets directly -- they only emit
Qt Signals, which `main_window.py` connects to slots that run on the
GUI thread (the default "AutoConnection" already does this correctly
for cross-thread signals).

`CreateRepositoriesWorker.repo_conflict` is the one exception that
needs the caller to *answer back*: when a name already exists on
GitHub, the worker thread must pause and let the user pick
"use existing" vs "skip" before moving on. That decision has to be
made with a real dialog on the GUI thread. The pattern used here is
the standard Qt way to do that safely:

    worker.repo_conflict.connect(slot, Qt.BlockingQueuedConnection)

With a BlockingQueuedConnection, `emit()` on the worker thread blocks
until the slot has finished running on the GUI thread. The slot
receives a plain mutable Python list (`answer_holder`) and appends the
user's boolean choice to it; because the emit() call does not return
until the slot returns, the worker thread can safely read
`answer_holder[0]` right after `emit()` completes.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from . import git_ops, github_client
from .db import Repository


class VerifyTokenWorker(QThread):
    finished_ok = Signal(str)      # username
    finished_err = Signal(str, str)  # message, technical_detail

    def run(self):
        try:
            login = github_client.verify_token()
            self.finished_ok.emit(login)
        except github_client.GitHubClientError as e:
            self.finished_err.emit(e.message, e.technical_detail)
        except Exception as e:
            self.finished_err.emit("Lỗi không xác định.", str(e))


class CreateRepositoriesWorker(QThread):
    # name, html_url, clone_url, was_already_on_github
    repo_created = Signal(str, str, str, bool)
    repo_skipped = Signal(str)              # name -- user chose to skip an existing repo
    repo_failed = Signal(str, str, str)     # name, message, technical_detail
    # name, html_url, clone_url, answer_holder(list) -- filled in by the
    # GUI-thread slot before this signal's emit() call returns.
    repo_conflict = Signal(str, str, str, object)
    finished_all = Signal()

    def __init__(self, names: list[str], private: bool = False):
        super().__init__()
        self.names = names
        self.private = private
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        for name in self.names:
            if self._cancelled:
                break
            try:
                result = github_client.create_repository(name, private=self.private)
            except github_client.GitHubClientError as e:
                self.repo_failed.emit(name, e.message, e.technical_detail)
                continue
            except Exception as e:
                self.repo_failed.emit(name, "Lỗi không xác định.", str(e))
                continue

            if result.already_existed:
                answer_holder: list[bool] = []
                self.repo_conflict.emit(name, result.html_url, result.url, answer_holder)
                use_existing = bool(answer_holder[0]) if answer_holder else False
                if use_existing:
                    self.repo_created.emit(name, result.html_url, result.url, True)
                else:
                    self.repo_skipped.emit(name)
            else:
                self.repo_created.emit(name, result.html_url, result.url, False)
        self.finished_all.emit()


class PushOneWorker(QThread):
    result_ready = Signal(object)  # git_ops.PushResult

    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo

    def run(self):
        result = git_ops.push_folder(
            folder_path=self.repo.folder_path,
            remote_url=self.repo.clone_url or self.repo.repo_url,
            commit_message=self.repo.commit_message,
            branch=self.repo.branch,
            repo_name=self.repo.repo_name,
        )
        self.result_ready.emit(result)


class PushAllWorker(QThread):
    """Pushes a list of repositories sequentially in a background thread,
    emitting progress after every single repo so the UI can update its
    table row-by-row without freezing.

    Cancellation is cooperative: the currently running `git` command is
    allowed to finish (we never kill a git subprocess mid-operation,
    since that could corrupt the local repo state); the batch simply
    does not start the next repository once `cancel()` has been called.
    """

    repo_started = Signal(str)               # repo_name
    repo_finished = Signal(object)            # git_ops.PushResult
    all_finished = Signal(bool)               # was_cancelled

    def __init__(self, repos: list[Repository]):
        super().__init__()
        self.repos = repos
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        for repo in self.repos:
            if self._cancelled:
                break
            self.repo_started.emit(repo.repo_name)

            if not repo.folder_path:
                from .git_ops import PushResult
                result = PushResult(repo.repo_name, False, "Chưa gắn folder cho repository này.")
            else:
                result = git_ops.push_folder(
                    folder_path=repo.folder_path,
                    remote_url=repo.clone_url or repo.repo_url,
                    commit_message=repo.commit_message,
                    branch=repo.branch,
                    repo_name=repo.repo_name,
                )
            self.repo_finished.emit(result)
            # A single repo failing must never stop the batch.
        self.all_finished.emit(self._cancelled)
