"""
git_ops.py
Wraps local Git operations needed to push a folder to a GitHub repository.

We use `subprocess` directly (rather than GitPython) for the actual
add/commit/push sequence because it gives us precise stderr text to
classify errors against, and it does not require Git to be importable
as a Python binding -- only present on PATH, which we check explicitly.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitOpsError(Exception):
    """User-friendly Git error with an optional technical detail and a
    short suggestion the UI can show."""

    def __init__(self, message: str, suggestion: str = "", technical_detail: str = ""):
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion
        self.technical_detail = technical_detail


@dataclass
class PushResult:
    repo_name: str
    success: bool
    message: str
    technical_detail: str = ""
    no_changes: bool = False  # True when "nothing to commit" but push still ran


def git_available() -> bool:
    return shutil.which("git") is not None


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _classify_stderr(stderr: str) -> tuple[str, str]:
    """Map raw git stderr to (user_message, suggestion)."""
    s = stderr.lower()
    if "could not resolve host" in s or "network is unreachable" in s or "unable to access" in s:
        return ("Không có kết nối internet.", "Kiểm tra lại kết nối mạng rồi thử lại.")
    if "authentication failed" in s or "invalid username or password" in s or "could not read username" in s:
        return ("Xác thực GitHub thất bại.", "Kiểm tra lại GitHub API Key (token).")
    if "permission denied" in s or "403" in s:
        return ("Không có quyền truy cập repository.", "Kiểm tra quyền của token hoặc quyền truy cập repo.")
    if "repository not found" in s or "404" in s:
        return ("Remote repository không tồn tại.", "Kiểm tra tên repository hoặc remote URL.")
    if "failed to push some refs" in s or "non-fast-forward" in s:
        return ("Push bị conflict với remote.", "Pull thay đổi mới nhất từ remote rồi thử lại.")
    if "src refspec" in s and "does not match any" in s:
        return ("Không có gì để commit hoặc branch không tồn tại.", "Kiểm tra lại nội dung thay đổi trong folder.")
    if "not a git repository" in s:
        return ("Folder chưa phải là Git repository.", "App sẽ tự khởi tạo git init.")
    if "remote origin already exists" in s:
        return ("Remote 'origin' đã tồn tại.", "App sẽ cập nhật lại remote URL.")
    if "detected dubious ownership" in s:
        return ("Git từ chối thao tác vì lý do quyền sở hữu thư mục.", "Kiểm tra quyền sở hữu folder hoặc cấu hình safe.directory trong Git.")
    return ("Lỗi Git không xác định.", "Xem chi tiết lỗi để biết thêm thông tin.")


def ensure_repo_ready(folder: Path, remote_url: str, branch: str = "main") -> None:
    """Ensure `folder` is a git repo with `origin` pointing at remote_url."""
    if not git_available():
        raise GitOpsError(
            "Git chưa được cài đặt hoặc không nằm trong PATH.",
            suggestion="Cài đặt Git từ git-scm.com rồi khởi động lại app.",
        )

    git_dir = folder / ".git"
    if not git_dir.exists():
        result = _run(["git", "init", "-b", branch], folder)
        if result.returncode != 0:
            msg, sug = _classify_stderr(result.stderr)
            raise GitOpsError(msg, sug, result.stderr)

    # Check / set remote "origin"
    result = _run(["git", "remote", "get-url", "origin"], folder)
    if result.returncode != 0:
        # No remote yet
        result = _run(["git", "remote", "add", "origin", remote_url], folder)
        if result.returncode != 0:
            msg, sug = _classify_stderr(result.stderr)
            raise GitOpsError(msg, sug, result.stderr)
    else:
        current_url = result.stdout.strip()
        if current_url != remote_url:
            result = _run(["git", "remote", "set-url", "origin", remote_url], folder)
            if result.returncode != 0:
                msg, sug = _classify_stderr(result.stderr)
                raise GitOpsError(msg, sug, result.stderr)


def push_folder(folder_path: str, remote_url: str, commit_message: str,
                 branch: str = "main", repo_name: str = "") -> PushResult:
    """Full add/commit/push sequence for one repository folder."""
    folder = Path(folder_path)

    if not commit_message or not commit_message.strip():
        return PushResult(repo_name, False, "Commit message không được để trống.")

    if not folder.exists() or not folder.is_dir():
        return PushResult(
            repo_name, False,
            f"Folder không tồn tại: {folder_path}",
        )

    try:
        ensure_repo_ready(folder, remote_url, branch)

        add_result = _run(["git", "add", "."], folder)
        if add_result.returncode != 0:
            msg, _ = _classify_stderr(add_result.stderr)
            return PushResult(repo_name, False, msg, add_result.stderr)

        commit_result = _run(["git", "commit", "-m", commit_message], folder)
        no_changes = False
        if commit_result.returncode != 0:
            out = (commit_result.stdout + commit_result.stderr).lower()
            if "nothing to commit" in out:
                # Not fatal -- there may be nothing new, still try to push
                # in case local commits exist that weren't pushed yet.
                no_changes = True
            else:
                msg, _ = _classify_stderr(commit_result.stderr)
                return PushResult(repo_name, False, msg, commit_result.stderr)

        push_result = _run(["git", "push", "-u", "origin", branch], folder)
        if push_result.returncode != 0:
            push_out = (push_result.stdout + push_result.stderr).lower()
            if no_changes and "everything up-to-date" in push_out:
                # Nothing new to commit AND nothing new to push -- this is
                # the normal "re-push with no local changes" case, not an
                # error.
                return PushResult(
                    repo_name, True,
                    "Không có thay đổi mới. Repository đã được cập nhật.",
                    no_changes=True,
                )
            msg, _ = _classify_stderr(push_result.stderr)
            return PushResult(repo_name, False, msg, push_result.stderr)

        if no_changes:
            return PushResult(
                repo_name, True,
                "Không có thay đổi mới. Repository đã được cập nhật.",
                no_changes=True,
            )
        return PushResult(repo_name, True, "Push thành công.")

    except GitOpsError as e:
        return PushResult(repo_name, False, e.message, e.technical_detail)
    except subprocess.TimeoutExpired:
        return PushResult(repo_name, False, "Git operation quá thời gian chờ (timeout).")
    except Exception as e:
        return PushResult(repo_name, False, "Lỗi không xác định khi push.", str(e))


def validate_folder(folder_path: str) -> tuple[bool, str]:
    """Returns (is_valid, error_message)."""
    if not folder_path:
        return False, "Chưa chọn folder."
    p = Path(folder_path)
    if not p.exists():
        return False, f"Folder không tồn tại:\n{folder_path}"
    if not p.is_dir():
        return False, f"Đường dẫn không phải là thư mục:\n{folder_path}"
    return True, ""
