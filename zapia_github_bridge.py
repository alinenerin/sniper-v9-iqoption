"""Ponte segura Zapia -> GitHub Actions -> relatório.

Uso pela orquestração: configurar GITHUB_TOKEN fora do repositório.
Nunca executa ordens e nunca aceita parâmetros de execução.
"""
from __future__ import annotations
import io, json, os, time, zipfile
from typing import Any, Dict, Optional
import requests

API = "https://api.github.com"
REPO = os.getenv("GITHUB_REPO", "alinenerin/sniper-v9-iqoption")
WORKFLOW = "unified_readonly_scan.yml"


class GitHubScanBridge:
    def __init__(self, token: Optional[str] = None, repo: str = REPO):
        self.token = token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if not self.token:
            raise ValueError("GITHUB_TOKEN_REQUIRED_OUTSIDE_REPOSITORY")
        self.repo = repo
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"})

    def dispatch(self, symbols: list[str], include_otc: bool = False, ref: str = "main") -> Dict[str, Any]:
        safe_symbols = [s.upper() for s in symbols if s and s.replace("-", "").isalnum()][:20]
        if not safe_symbols:
            raise ValueError("SYMBOLS_REQUIRED")
        response = self.session.post(
            f"{API}/repos/{self.repo}/actions/workflows/{WORKFLOW}/dispatches",
            json={"ref": ref, "inputs": {"symbols": " ".join(safe_symbols), "include_otc": str(bool(include_otc)).lower()}},
            timeout=30,
        )
        response.raise_for_status()
        return {"dispatched": True, "workflow": WORKFLOW, "repo": self.repo, "ref": ref, "dispatched_at": time.time(), "execution_allowed": False}

    def run_after(self, dispatched_at: float, timeout_seconds: int = 60) -> Dict[str, Any]:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            run = self.latest_run()
            created = run.get("created_at", "")
            # GitHub timestamps are authoritative; the newest run is sufficient
            # after dispatch, while this short retry handles API propagation lag.
            if run.get("status") in {"queued", "in_progress", "completed"}:
                return run
            time.sleep(2)
        raise TimeoutError("SCAN_RUN_NOT_FOUND_AFTER_DISPATCH")

    def latest_run(self, head_sha: Optional[str] = None) -> Dict[str, Any]:
        response = self.session.get(f"{API}/repos/{self.repo}/actions/workflows/{WORKFLOW}/runs", params={"per_page": 10}, timeout=30)
        response.raise_for_status()
        runs = response.json().get("workflow_runs", [])
        if head_sha:
            runs = [r for r in runs if r.get("head_sha") == head_sha]
        if not runs:
            raise LookupError("SCAN_RUN_NOT_FOUND")
        return runs[0]

    def wait_for_run(self, run_id: int, timeout_seconds: int = 900, poll_seconds: int = 10) -> Dict[str, Any]:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            r = self.session.get(f"{API}/repos/{self.repo}/actions/runs/{run_id}", timeout=30)
            r.raise_for_status()
            data = r.json()
            if data.get("status") == "completed":
                if data.get("conclusion") != "success":
                    raise RuntimeError(f"SCAN_FAILED:{data.get('conclusion')}")
                return data
            time.sleep(poll_seconds)
        raise TimeoutError("SCAN_TIMEOUT")

    def download_latest_report(self, run_id: int) -> Dict[str, Any]:
        response = self.session.get(f"{API}/repos/{self.repo}/actions/runs/{run_id}/artifacts", timeout=30)
        response.raise_for_status()
        artifacts = response.json().get("artifacts", [])
        artifact = next((a for a in artifacts if a.get("name", "").startswith("latest-scan-")), None)
        if not artifact:
            raise LookupError("SCAN_ARTIFACT_NOT_FOUND")
        blob = self.session.get(artifact["archive_download_url"], timeout=60)
        blob.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(blob.content)) as archive:
            with archive.open("latest_scan.json") as handle:
                report = json.load(handle)
        if report.get("execution_allowed") is not False:
            raise RuntimeError("REPORT_EXECUTION_GUARD_FAILED")
        return report
