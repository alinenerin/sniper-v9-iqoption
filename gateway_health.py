"""Shared liveness/readiness contract for the read-only gateway."""


def connection_is_ready(connection):
    """Return whether the upstream connection is fully established."""
    return str((connection or {}).get("status", "")).strip().lower() == "connected"


def liveness_payload(connection):
    """Describe process liveness independently of upstream availability."""
    connection = connection or {}
    return {
        "status": connection.get("status", "unknown"),
        "liveness": "ok",
        "ready": connection_is_ready(connection),
        "connection": connection,
    }


def readiness_payload(connection):
    """Describe whether the service can currently serve upstream-backed work."""
    connection = connection or {}
    ready = connection_is_ready(connection)
    return {
        "status": "connected" if ready else connection.get("status", "disconnected"),
        "ready": ready,
        "connection": connection,
    }
