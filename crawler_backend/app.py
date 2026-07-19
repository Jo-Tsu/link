from __future__ import annotations

import ipaddress
import json
import os
import socket
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from scrapling.fetchers import DynamicFetcher, Fetcher, StealthyFetcher


HOST = "0.0.0.0"
PORT = 8000
MAX_HTML = 2_000_000
MAX_TEXT = 500_000
JOBS_FILE = Path(os.environ.get("CRAWLER_JOBS_FILE", "/data/jobs.json"))


def load_jobs() -> dict[str, dict]:
    try:
        records = json.loads(JOBS_FILE.read_text("utf-8"))
        jobs = {str(item["id"]): item for item in records if isinstance(item, dict) and item.get("id")}
        for job in jobs.values():
            if job.get("status") in {"queued", "running"}:
                job.update(status="failed", error="采集服务重启，任务未完成", result=None, finished_at=time.time())
        return jobs
    except FileNotFoundError:
        return {}
    except Exception:
        traceback.print_exc()
        return {}


JOBS: dict[str, dict] = load_jobs()
JOBS_LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="crawl")


def persist_jobs_locked() -> None:
    JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = JOBS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(list(JOBS.values()), ensure_ascii=False), "utf-8")
    temporary.replace(JOBS_FILE)


def public_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("仅支持有效的 HTTP/HTTPS 网址")
    if parsed.username or parsed.password:
        raise ValueError("网址不能包含用户名或密码")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ValueError("目标域名无法解析") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("为保护内网安全，不能采集本机或内网地址")
    return value


def response_text(response) -> str:
    try:
        return response.get_all_text(separator="\n", strip=True)
    except TypeError:
        return response.get_all_text()


def extract_fields(response, fields: list[dict]) -> dict:
    extracted = {}
    for field in fields:
        name = str(field.get("name", "")).strip()
        selector = str(field.get("selector", "")).strip()
        if not name or not selector:
            continue
        nodes = response.xpath(selector) if field.get("selector_type") == "xpath" else response.css(selector)
        if field.get("multiple"):
            values = nodes.getall()
            extracted[name] = [str(value).strip() for value in values if str(value).strip()]
        else:
            value = nodes.get()
            extracted[name] = str(value).strip() if value is not None else None
    return extracted


def run_job(job_id: str, payload: dict) -> None:
    with JOBS_LOCK:
        JOBS[job_id]["status"] = "running"
        persist_jobs_locked()
    try:
        url = public_url(str(payload.get("url", "")))
        mode = payload.get("mode", "static")
        timeout_seconds = max(1, min(60, int(payload.get("timeout_ms", 30000))) / 1000)
        selector_config = {
            "adaptive": bool(payload.get("adaptive", False)),
            "huge_tree": bool(payload.get("huge_tree", False)),
        }
        if mode == "static":
            response = Fetcher.get(url, timeout=timeout_seconds, selector_config=selector_config)
        else:
            options = {
                "timeout": timeout_seconds * 1000,
                "wait": max(0, min(10000, int(payload.get("wait_ms", 0)))),
                "wait_selector": payload.get("wait_selector") or None,
                "network_idle": bool(payload.get("network_idle", True)),
                "disable_resources": bool(payload.get("disable_resources", False)),
                "block_ads": bool(payload.get("block_ads", True)),
                "selector_config": selector_config,
                "headless": True,
            }
            response = (
                StealthyFetcher.fetch(url, **options)
                if mode == "stealth"
                else DynamicFetcher.fetch(url, **options)
            )

        html = response.html_content
        if isinstance(html, bytes):
            html = html.decode(response.encoding or "utf-8", errors="replace")
        text = response_text(response)
        title = response.css("title::text").get() or url
        truncated = len(html) > MAX_HTML or len(text) > MAX_TEXT
        result = {
            "title": str(title).strip(),
            "status_code": int(response.status),
            "text": text[:MAX_TEXT],
            "html": html[:MAX_HTML],
            "fields": extract_fields(response, payload.get("fields") or []),
            "truncated": truncated,
        }
        with JOBS_LOCK:
            JOBS[job_id].update(status="succeeded", result=result, error=None, finished_at=time.time())
            persist_jobs_locked()
    except Exception as exc:
        traceback.print_exc()
        with JOBS_LOCK:
            JOBS[job_id].update(status="failed", error=str(exc), result=None, finished_at=time.time())
            persist_jobs_locked()


class Handler(BaseHTTPRequestHandler):
    server_version = "LinkCrawler/1.0"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        super().end_headers()

    def json_response(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self.json_response(200, {"ok": True, "service": "link-crawler", "engine": "Scrapling"})
            return
        if self.path == "/api/crawls":
            with JOBS_LOCK:
                jobs = sorted(JOBS.values(), key=lambda item: item["created_at"], reverse=True)
            self.json_response(200, {"jobs": jobs})
            return
        prefix = "/api/crawls/"
        if self.path.startswith(prefix):
            job_id = self.path[len(prefix) :].split("?", 1)[0]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
            if job:
                self.json_response(200, job)
            else:
                self.json_response(404, {"detail": "任务不存在"})
            return
        self.json_response(404, {"detail": "Not found"})

    def do_POST(self) -> None:
        if self.path != "/api/crawls":
            self.json_response(404, {"detail": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            url = public_url(str(payload.get("url", "")))
            mode = payload.get("mode", "static")
            if mode not in {"static", "dynamic", "stealth"}:
                raise ValueError("未知的抓取模式")
            job_id = str(uuid.uuid4())
            job = {
                "id": job_id,
                "url": url,
                "mode": mode,
                "status": "queued",
                "created_at": time.time(),
                "error": None,
                "result": None,
            }
            with JOBS_LOCK:
                JOBS[job_id] = job
                persist_jobs_locked()
            EXECUTOR.submit(run_job, job_id, payload)
            self.json_response(202, {"id": job_id, "status": "queued"})
        except (ValueError, json.JSONDecodeError) as exc:
            self.json_response(400, {"detail": str(exc)})
        except Exception as exc:
            traceback.print_exc()
            self.json_response(500, {"detail": str(exc)})

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {self.address_string()} {fmt % args}", flush=True)


if __name__ == "__main__":
    print(f"Link crawler API listening on {HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
