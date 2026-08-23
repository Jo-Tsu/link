"""GitHub connector tools."""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from ...secrets import SecretStore
from ..tool_utils import attach, request, schema


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_base() -> str:
    import os

    return os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")


def _github_git_base() -> str:
    import os

    return os.environ.get("GITHUB_GIT_URL", "https://github.com").rstrip("/")


def _github_auth(
    secrets: SecretStore, install: str = "", *, force: bool = False
) -> tuple[Optional[dict[str, str]], Optional[dict[str, str]]]:
    """(headers, err). PAT wins; managed relay mints installation token."""
    profile = secrets.get("github:default") or {}
    if profile.get("token"):
        return _github_headers(profile["token"]), None
    if profile.get("mode") == "relay":
        from ...cloud import github_installation_token
        from ...config import load_config
        from .. import github_installs

        installation_id, _prof = github_installs.resolve(secrets, install)
        if not installation_id and install:
            installation_id, _prof = github_installs.resolve(secrets, "")
        if not installation_id:
            return None, {"error": "github is not connected; no App installation"}
        token = github_installation_token(
            secrets, load_config(), installation_id, force=force
        )
        if not token:
            return None, {
                "error": "github installation token unavailable "
                "(sign in to Smallink Cloud and retry)"
            }
        return _github_headers(token), None
    return None, {"error": "github is not connected; missing token"}


def _github_git_auth_args(secrets: SecretStore, owner: str) -> list[str]:
    """Per-invocation git auth via HTTP header (no token at rest)."""
    import base64

    headers, err = _github_auth(secrets, owner)
    if err:
        return ["-c", "credential.helper="]
    token = headers["Authorization"].split(" ", 1)[1]
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return [
        "-c",
        f"http.extraHeader=AUTHORIZATION: basic {basic}",
        "-c",
        "credential.helper=",
    ]


def _run_git(
    args: list[str], *, cwd: Any = None, timeout: int = 600
) -> tuple[str, str]:
    """(stdout, error). Never raises."""
    import subprocess

    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError:
        return "", "git is not installed"
    except subprocess.TimeoutExpired:
        return "", "git timed out"
    if proc.returncode != 0:
        return "", (proc.stderr or proc.stdout).strip()[-500:]
    return proc.stdout.strip(), ""


def _github_call(
    secrets: SecretStore,
    method: str,
    path: str,
    *,
    install: str = "",
    request_fn: Callable[..., dict[str, Any]] = request,
    **kw: Any,
) -> dict[str, Any]:
    """GitHub API call with auto-retry on 401 for managed tokens."""
    headers, err = _github_auth(secrets, install)
    if err:
        return err
    out = request_fn(method, _github_base() + path, headers=headers, **kw)
    managed = not (secrets.get("github:default") or {}).get("token")
    if managed and out.get("error") == "HTTP 401":
        headers, err = _github_auth(secrets, install, force=True)
        if err:
            return out
        out = request_fn(method, _github_base() + path, headers=headers, **kw)
    return out


def make_github_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build GitHub connector tools."""
    tools: list[Callable[..., Any]] = []

    def github_search(
        query: str, search_type: str = "issues", max_results: int = 10
    ) -> dict[str, Any]:
        kind = "repositories" if search_type == "repositories" else "issues"
        out = _github_call(
            secrets,
            "GET",
            f"/search/{kind}",
            request_fn=request_fn,
            params={"q": query, "per_page": max(1, min(int(max_results or 10), 20))},
        )
        if "error" in out:
            return out
        items = out["data"].get("items", [])
        return {"results": items}

    github_search.__name__ = "github_search"
    tools.append(
        attach(
            github_search,
            schema(
                "github_search",
                "Search GitHub issues, pull requests, or repositories.",
                {
                    "query": {"type": "string"},
                    "search_type": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                ["query"],
            ),
            caps=["github", "read"],
        )
    )

    def github_get_issue(owner: str, repo: str, issue_number: int) -> dict[str, Any]:
        return _github_call(
            secrets,
            "GET",
            f"/repos/{owner}/{repo}/issues/{issue_number}",
            install=owner,
            request_fn=request_fn,
        )

    github_get_issue.__name__ = "github_get_issue"
    tools.append(
        attach(
            github_get_issue,
            schema(
                "github_get_issue",
                "Read a GitHub issue or pull request by number.",
                {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "issue_number": {"type": "integer"},
                },
                ["owner", "repo", "issue_number"],
            ),
            caps=["github", "read"],
        )
    )

    def github_create_issue(
        owner: str, repo: str, title: str, body: str = ""
    ) -> dict[str, Any]:
        return _github_call(
            secrets,
            "POST",
            f"/repos/{owner}/{repo}/issues",
            install=owner,
            request_fn=request_fn,
            json={"title": title, "body": body},
        )

    github_create_issue.__name__ = "github_create_issue"
    tools.append(
        attach(
            github_create_issue,
            schema(
                "github_create_issue",
                "Create a GitHub issue. Requires user approval.",
                {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
                ["owner", "repo", "title"],
            ),
            approval=True,
            caps=["github", "write"],
        )
    )

    def github_reply(owner: str, repo: str, number: int, body: str) -> dict[str, Any]:
        return _github_call(
            secrets,
            "POST",
            f"/repos/{owner}/{repo}/issues/{number}/comments",
            install=owner,
            request_fn=request_fn,
            json={"body": body},
        )

    github_reply.__name__ = "github_reply"
    tools.append(
        attach(
            github_reply,
            schema(
                "github_reply",
                "Comment on a GitHub issue or pull request. Requires user approval.",
                {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "number": {"type": "integer"},
                    "body": {"type": "string"},
                },
                ["owner", "repo", "number", "body"],
            ),
            approval=True,
            caps=["github", "write"],
        )
    )

    def github_review(
        owner: str, repo: str, pull_number: int, event: str = "COMMENT", body: str = ""
    ) -> dict[str, Any]:
        event = (event or "COMMENT").upper()
        if event not in ("APPROVE", "REQUEST_CHANGES", "COMMENT"):
            return {"error": "event must be APPROVE, REQUEST_CHANGES or COMMENT"}
        return _github_call(
            secrets,
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
            install=owner,
            request_fn=request_fn,
            json={"event": event, **({"body": body} if body else {})},
        )

    github_review.__name__ = "github_review"
    tools.append(
        attach(
            github_review,
            schema(
                "github_review",
                "Submit a pull-request review (approve / request changes / "
                "comment). Requires user approval.",
                {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "pull_number": {"type": "integer"},
                    "event": {"type": "string"},
                    "body": {"type": "string"},
                },
                ["owner", "repo", "pull_number"],
            ),
            approval=True,
            caps=["github", "write"],
        )
    )

    def github_list_commits(
        owner: str,
        repo: str,
        since: str = "",
        until: str = "",
        author: str = "",
        max_results: int = 30,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"per_page": max(1, min(int(max_results or 30), 100))}
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        if author:
            params["author"] = author
        out = _github_call(
            secrets,
            "GET",
            f"/repos/{owner}/{repo}/commits",
            install=owner,
            request_fn=request_fn,
            params=params,
        )
        if "error" in out:
            return out
        commits = [
            {
                "sha": (c.get("sha") or "")[:12],
                "author": ((c.get("commit") or {}).get("author") or {}).get("name")
                or (c.get("author") or {}).get("login", ""),
                "date": ((c.get("commit") or {}).get("author") or {}).get("date", ""),
                "message": ((c.get("commit") or {}).get("message") or "")[:500],
            }
            for c in (out["data"] if isinstance(out["data"], list) else [])
        ]
        return {"commits": commits, "count": len(commits)}

    github_list_commits.__name__ = "github_list_commits"
    tools.append(
        attach(
            github_list_commits,
            schema(
                "github_list_commits",
                "List a repository's commits (newest first), optionally filtered "
                "by ISO-8601 since/until dates or author.",
                {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "since": {
                        "type": "string",
                        "description": "ISO-8601, e.g. 2026-07-06T00:00:00Z",
                    },
                    "until": {"type": "string"},
                    "author": {"type": "string", "description": "GitHub login"},
                    "max_results": {"type": "integer"},
                },
                ["owner", "repo"],
            ),
            approval=False,
            caps=["github", "read"],
        )
    )

    def _writable_target(
        raw: str, *, default_name: str = ""
    ) -> tuple[Any, dict[str, Any] | None]:
        from pathlib import Path as _Path

        writable = [r.path for r in (roots or []) if r.writable]
        if not writable:
            return None, {"error": "no writable session directory to clone into"}
        path = (
            _Path(str(raw)).expanduser().resolve()
            if raw
            else (writable[0] / default_name).resolve()
        )
        if not any(path.is_relative_to(root) for root in writable):
            return None, {
                "error": f"{path} is outside the session's writable directories"
            }
        return path, None

    def github_clone(owner: str, repo: str, directory: str = "") -> dict[str, Any]:
        target, err = _writable_target(directory, default_name=repo)
        if err:
            return err
        if target.exists() and any(target.iterdir()):
            return {
                "error": f"{target} already exists and is not empty (use github_pull?)"
            }
        url = f"{_github_git_base()}/{owner}/{repo}.git"
        _out, git_err = _run_git(
            [*_github_git_auth_args(secrets, owner), "clone", url, str(target)]
        )
        if git_err:
            return {"error": f"clone failed: {git_err}"}
        config = (target / ".git" / "config").read_text()
        if "AUTHORIZATION" in config or "x-access-token" in config:
            import shutil

            shutil.rmtree(target)
            return {"error": "clone aborted: credentials would have persisted"}
        head, _ = _run_git(["rev-parse", "--short", "HEAD"], cwd=target)
        return {"ok": True, "path": str(target), "head": head}

    github_clone.__name__ = "github_clone"
    tools.append(
        attach(
            github_clone,
            schema(
                "github_clone",
                "Clone a GitHub repository into a session folder. Requires user approval.",
                {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "directory": {
                        "type": "string",
                        "description": "target path inside a granted folder (default: <primary>/<repo>)",
                    },
                },
                ["owner", "repo"],
            ),
            approval=True,
            caps=["github", "read"],
        )
    )

    def github_pull(directory: str) -> dict[str, Any]:
        target, err = _writable_target(directory)
        if err:
            return err
        if not (target / ".git").exists():
            return {"error": f"{target} is not a git repository"}
        remote, git_err = _run_git(["remote", "get-url", "origin"], cwd=target)
        if git_err:
            return {"error": f"no origin remote: {git_err}"}
        m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", remote)
        owner = m.group(1) if m else ""
        _out, git_err = _run_git(
            [
                *_github_git_auth_args(secrets, owner),
                "-C",
                str(target),
                "pull",
                "--ff-only",
            ]
        )
        if git_err:
            return {"error": f"pull failed: {git_err}"}
        head, _ = _run_git(["rev-parse", "--short", "HEAD"], cwd=target)
        return {"ok": True, "path": str(target), "head": head}

    github_pull.__name__ = "github_pull"
    tools.append(
        attach(
            github_pull,
            schema(
                "github_pull",
                "Fast-forward an existing clone to latest upstream. Requires user approval.",
                {"directory": {"type": "string"}},
                ["directory"],
            ),
            approval=True,
            caps=["github", "read"],
        )
    )

    return tools
