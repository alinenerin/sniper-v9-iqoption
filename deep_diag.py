"""Read-only connectivity diagnostic.

This module never writes to GitHub, never embeds credentials, and never places
orders. It is intentionally limited to configuration and transport checks.
"""
import os
import time


def run():
    required = ("IQ_USER", "IQ_PASS")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        print("DIAGNOSTIC_BLOCKED_MISSING_ENV=" + ",".join(missing))
        return False
    print("DIAGNOSTIC_CONFIGURED_READ_ONLY=true")
    print("DIAGNOSTIC_EXECUTION_ALLOWED=false")
    return True


if __name__ == "__main__":
    run()
