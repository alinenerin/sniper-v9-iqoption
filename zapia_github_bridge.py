"""Secure Zapia -> GitHub Actions bridge for guarded read-only scans."""
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

    def dispatch(self, symbols: list[str], include_otc: bool = False, otc_only: bool = False, ref: str = "main") -> Dict[str, Any]:
        safe_symbols = [s.upper() for s in symbols if s and s.replace("-", "").isalnum()][:20]
        if not safe_symbols:
            raise ValueError("SYMBOLS_REQUIRED")
        if otc_only:
            include_otc = True
            safe_symbols = [s if s.endswith("-OTC") else s + "-OTC" for s in safe_symbols]
        dispatched_at = time.time()
        response = self.session.post(
            f"{API}/repos/{self.repo}/actions/workflows/{WORKFLOW}/dispatches",
            json={"ref": ref, "inputs": {"symbols": " ".join(safe_symbols), "include_otc": str(bool(include_otc)).lower(), "otc_only": str(bool(otc_only)).lower()}},
            timeout=30,
        )
        response.raise_for_status()
        return {"dispatched": True, "workflow": WORKFLOW, "repo": self.repo, "ref": ref, "dispatched_at": dispatched_at, "symbols": safe_symbols, "include_otc": include_otc, "otc_only": otc_only, "execution_allowed": False}

    def run_after(self, dispatched_at: float, timeout_seconds: int = 120) -> Dict[str, Any]:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            response = self.session.get(f"{API}/repos/{self.repo}/actions/workflows/{WORKFLOW}/runs", params={"per_page": 20}, timeout=30)
            response.raise_for_status()
            for run in response.json().get("workflow_runs", []):
                created = run.get("created_at")
                if not created:
                    continue
                created_epoch = time.mktime(time.strptime(created, "%Y-%m-%dT%H:%M:%SZ"))
                if created_epoch >= dispatched_at - 5:
                    return run
            time.sleep(3)
        raise TimeoutError("SCAN_RUN_NOT_FOUND_AFTER_DISPATCH")

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

    def download_latest_report(self, run_id: int, expected: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        response = self.session.get(f"{API}/repos/{self.repo}/actions/runs/{run_id}/artifacts", timeout=30)
        response.raise_for_status()
        artifacts = response.json().get("artifacts", [])
        artifact = next((a for a in artifacts if a.get("name") == f"latest-scan-{run_id}"), None)
        if not artifact:
            raise LookupError("SCAN_ARTIFACT_NOT_FOUND_FOR_RUN")
        blob = self.session.get(artifact["archive_download_url"], timeout=60)
        blob.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(blob.content)) as archive:
            with archive.open("latest_scan.json") as handle:
                report = json.load(handle)
        if report.get("execution_allowed") is not False or report.get("mode") != "read_only":
            raise RuntimeError("REPORT_EXECUTION_OR_MODE_GUARD_FAILED")
        if str(report.get("workflow_run_id")) != str(run_id):
            raise RuntimeError("REPORT_RUN_ID_MISMATCH")
        if expected:
            inputs = report.get("inputs") or {}
            if bool(inputs.get("include_otc")) != bool(expected.get("include_otc")):
                raise RuntimeError("REPORT_INCLUDE_OTC_MISMATCH")
            if bool(inputs.get("otc_only")) != bool(expected.get("otc_only")):
                raise RuntimeError("REPORT_OTC_ONLY_MISMATCH")
            expected_symbols = set(expected.get("symbols") or [])
            report_symbols = set(inputs.get("symbols") or [])
            if expected_symbols != report_symbols:
                raise RuntimeError("REPORT_SYMBOLS_MISMATCH")
        return report
