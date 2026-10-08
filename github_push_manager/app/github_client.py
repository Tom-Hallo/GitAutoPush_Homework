"""
github_client.py
Handles the GitHub Personal Access Token lifecycle and repository creation.

The token is NEVER stored in SQLite or any plaintext file. It lives only
in the OS credential store via the `keyring` library (Windows Credential
Manager / macOS Keychain / Linux Secret Service).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import keyring
from github import Github, GithubException, BadCredentialsException

SERVICE_NAME = "github_push_manager"
USERNAME_KEY = "github_token"  # keyring "account" name, arbitrary but fixed


class GitHubClientError(Exception):
    """Raised for any GitHub-related failure with a user-friendly message."""

    def __init__(self, message: str, technical_detail: str = ""):
        super().__init__(message)
        self.message = message
        self.technical_detail = technical_detail


@dataclass
class RepoCreateResult:
    name: str
    url: str            # clone URL, used for `git remote`
    html_url: str       # web page URL, used for the "open in browser" button
    already_existed: bool


def save_token(token: str) -> None:
    if not token or not token.strip():
        raise GitHubClientError("Token không được để trống.")
    keyring.set_password(SERVICE_NAME, USERNAME_KEY, token.strip())


def load_token() -> Optional[str]:
    try:
        return keyring.get_password(SERVICE_NAME, USERNAME_KEY)
    except Exception:
        return None


def delete_token() -> None:
    try:
        keyring.delete_password(SERVICE_NAME, USERNAME_KEY)
    except keyring.errors.PasswordDeleteError:
        pass  # already absent, nothing to do


def verify_token(token: Optional[str] = None) -> str:
    """Return the authenticated username, or raise GitHubClientError."""
    token = token or load_token()
    if not token:
        raise GitHubClientError("Chưa có GitHub API Key. Vui lòng nhập và lưu token.")
    try:
        gh = Github(token)
        user = gh.get_user()
        login = user.login  # triggers the API call
        return login
    except BadCredentialsException:
        raise GitHubClientError("GitHub API Key không hợp lệ hoặc đã hết hạn.")
    except GithubException as e:
        raise GitHubClientError(
            "Không thể kết nối tới GitHub.", technical_detail=str(e)
        )
    except Exception as e:
        raise GitHubClientError(
            "Lỗi không xác định khi kiểm tra token.", technical_detail=str(e)
        )


def get_client() -> Github:
    token = load_token()
    if not token:
        raise GitHubClientError("Chưa có GitHub API Key.")
    return Github(token)


def create_repository(name: str, private: bool = False) -> RepoCreateResult:
    """Create a repo on GitHub. If it already exists, return it instead
    of raising, so the caller can decide (skip / use existing)."""
    gh = get_client()
    try:
        user = gh.get_user()
        repo = user.create_repo(name, private=private, auto_init=False)
        return RepoCreateResult(
            name=repo.name, url=repo.clone_url, html_url=repo.html_url, already_existed=False
        )
    except GithubException as e:
        if e.status == 422:
            # Name already exists under this account
            try:
                existing = gh.get_user().get_repo(name)
                return RepoCreateResult(
                    name=existing.name, url=existing.clone_url,
                    html_url=existing.html_url, already_existed=True,
                )
            except GithubException as e2:
                raise GitHubClientError(
                    f"Repository '{name}' đã tồn tại nhưng không thể truy xuất.",
                    technical_detail=str(e2),
                )
        if e.status == 401:
            raise GitHubClientError("GitHub API Key không hợp lệ hoặc đã hết hạn.")
        if e.status == 403:
            raise GitHubClientError(
                "Không đủ quyền để tạo repository (kiểm tra scope của token: cần 'repo').",
                technical_detail=str(e),
            )
        raise GitHubClientError(
            f"Không thể tạo repository '{name}'.", technical_detail=str(e)
        )
