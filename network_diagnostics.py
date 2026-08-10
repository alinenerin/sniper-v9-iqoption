"""Bounded, credential-free connectivity probes for Railway -> IQ Option.

This module never logs credentials or sends a real login. The SDK login timing is
recorded separately by current_iq.py, after these transport probes complete.
"""
from __future__ import annotations

import json
import logging
import socket
import ssl
import time
import urllib.error
import urllib.request

LOG = logging.getLogger("iq_network_diagnostics")
HOSTS = ("auth.iqoption.com", "ws.iqoption.com", "iqoption.com")


def _probe_host(host: str) -> dict:
    result = {"host": host}
    started = time.monotonic()
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ips = sorted({item[4][0] for item in infos})
        result["dns"] = {"ok": True, "elapsed_ms": round((time.monotonic() - started) * 1000, 1), "ips": ips[:8]}
    except Exception as exc:
        result["dns"] = {"ok": False, "elapsed_ms": round((time.monotonic() - started) * 1000, 1), "error": type(exc).__name__}
        return result

    ip = result["dns"]["ips"][0]
    started = time.monotonic()
    try:
        with socket.create_connection((ip, 443), timeout=8) as sock:
            result["tcp"] = {"ok": True, "elapsed_ms": round((time.monotonic() - started) * 1000, 1), "ip": ip}
    except Exception as exc:
        result["tcp"] = {"ok": False, "elapsed_ms": round((time.monotonic() - started) * 1000, 1), "ip": ip, "error": type(exc).__name__}
        return result

    started = time.monotonic()
    try:
        context = ssl.create_default_context()
        with socket.create_connection((ip, 443), timeout=8) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                result["tls"] = {"ok": True, "elapsed_ms": round((time.monotonic() - started) * 1000, 1), "version": tls.version()}
    except Exception as exc:
        result["tls"] = {"ok": False, "elapsed_ms": round((time.monotonic() - started) * 1000, 1), "error": type(exc).__name__}
        return result

    started = time.monotonic()
    try:
        req = urllib.request.Request(f"https://{host}/", headers={"User-Agent": "BinaryQuantX-network-diagnostic/1"})
        with urllib.request.urlopen(req, timeout=8) as response:
            result["https"] = {"ok": True, "elapsed_ms": round((time.monotonic() - started) * 1000, 1), "status": response.status}
    except urllib.error.HTTPError as exc:
        # An HTTP response, including 4xx/5xx, proves DNS/TCP/TLS/HTTP completed.
        result["https"] = {"ok": True, "elapsed_ms": round((time.monotonic() - started) * 1000, 1), "status": exc.code}
    except Exception as exc:
        result["https"] = {"ok": False, "elapsed_ms": round((time.monotonic() - started) * 1000, 1), "error": type(exc).__name__}
    return result


def _probe_websocket(host: str) -> dict:
    started = time.monotonic()
    result = {"host": host, "url": f"wss://{host}/echo/websocket"}
    try:
        import websocket
        ws = websocket.create_connection(result["url"], timeout=8, http_proxy_host=None, http_proxy_port=None)
        ws.close()
        result.update(ok=True, elapsed_ms=round((time.monotonic() - started) * 1000, 1))
    except Exception as exc:
        result.update(ok=False, elapsed_ms=round((time.monotonic() - started) * 1000, 1), error=type(exc).__name__)
    return result


def run_once() -> None:
    started = time.monotonic()
    report = {"phase": "transport", "started_at": time.time(), "hosts": [_probe_host(h) for h in HOSTS], "websocket": [_probe_websocket(h) for h in ("ws.iqoption.com", "iqoption.com")]}
    report["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
    # Single-line JSON makes Railway log collection and later comparison reliable.
    LOG.info("IQ_NETWORK_DIAGNOSTIC %s", json.dumps(report, separators=(",", ":"), sort_keys=True))
