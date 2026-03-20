from __future__ import annotations

import ipaddress
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from app.config import Settings

_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "metadata.google.internal",
        "metadata.goog",
    }
)


def clone_destination(repo_id: str, settings: Settings) -> Path:
    """Absolute path where this repo id is cloned (`data/clones/{repo_id}`)."""
    base = (settings.data_dir.expanduser().resolve() / "clones").resolve()
    base.mkdir(parents=True, exist_ok=True)
    if not re.match(r"^[a-zA-Z0-9._-]+$", repo_id):
        raise ValueError("Invalid repo id for clone path.")
    dest = (base / repo_id).resolve()
    if dest.parent != base:
        raise ValueError("Invalid clone destination.")
    return dest


def validate_git_url_for_clone(url: str, settings: Settings) -> str:
    raw = url.strip()
    if not raw:
        raise ValueError("git_url is empty.")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http(s) git URLs are allowed.")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("Git URL has no host.")
    if host in _BLOCKED_HOSTNAMES:
        raise ValueError(f"Host '{host}' is not allowed.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved):
        raise ValueError("Private or loopback IP hosts are not allowed in git_url.")
    allowed = settings.git_url_allowed_hosts
    if allowed and not _host_matches_allowlist(host, allowed):
        raise ValueError(
            f"Host '{host}' is not in GITNEXUS_GIT_URL_ALLOWED_HOSTS.",
        )
    return raw


def _host_matches_allowlist(host: str, patterns: list[str]) -> bool:
    h = host.lower()
    for p in patterns:
        p = p.strip().lower()
        if not p:
            continue
        if p.startswith("*."):
            suf = p[1:]
            if h.endswith(suf) or h == p[2:]:
                return True
        elif h == p:
            return True
    return False


def _run_git(args: list[str], *, timeout: int, cwd: Path | None = None) -> None:
    try:
        subprocess.run(
            args,
            check=True,
            timeout=timeout,
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd else None,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"git timed out after {timeout}s") from e
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or str(e)).strip()
        raise RuntimeError(err or "git command failed") from e


def git_clone(
    url: str,
    dest: Path,
    *,
    branch: str | None,
    settings: Settings,
) -> None:
    timeout = settings.git_clone_timeout_seconds
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.git_binary,
        "clone",
        "--depth",
        str(settings.git_clone_depth),
        "--single-branch",
    ]
    if branch:
        cmd.extend(["--branch", branch])
    cmd.extend([url, str(dest)])
    _run_git(cmd, timeout=timeout)


def git_pull_ff(root: Path, settings: Settings) -> None:
    if not (root / ".git").is_dir():
        raise RuntimeError("Not a git worktree; cannot pull.")
    timeout = settings.git_clone_timeout_seconds
    _run_git(
        [settings.git_binary, "-C", str(root), "pull", "--ff-only"],
        timeout=timeout,
    )


def prepare_git_worktree(
    url: str,
    dest: Path,
    *,
    branch: str | None,
    settings: Settings,
    force_fresh_clone: bool,
) -> None:
    """
    Ensure `dest` contains a clone of `url`.
    If an existing git worktree is present and not force_fresh, run `git pull --ff-only`.
    """
    if dest.exists() and (dest / ".git").is_dir() and not force_fresh_clone:
        git_pull_ff(dest, settings)
        return
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    git_clone(url, dest, branch=branch, settings=settings)
