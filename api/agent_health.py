"""Hermes agent/gateway heartbeat payload helpers (#716).

The WebUI process is not always paired with a long-running Hermes gateway. Some
setups use WebUI only, while self-hosted messaging deployments run a separate
Hermes gateway daemon that records runtime metadata in the Hermes Agent home.
This module turns those existing safe runtime signals into a small UI-facing
heartbeat without shelling out or adding psutil as a hard dependency.
"""

from __future__ import annotations

import importlib
import json
import os
from datetime import datetime, timezone
from typing import Any


def _checked_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gateway_status_module():
    """Load gateway.status lazily so tests and WebUI-only installs stay isolated."""
    return importlib.import_module("gateway.status")


def _active_profile_runtime_status() -> dict[str, Any] | None:
    """Read gateway runtime status from the active WebUI profile, if available."""
    try:
        from api.profiles import get_active_hermes_home

        status_path = get_active_hermes_home() / "gateway_state.json"
        if not status_path.exists():
            return None
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _runtime_pid(runtime_status: dict[str, Any] | None) -> int | None:
    if not isinstance(runtime_status, dict):
        return None
    try:
        pid = int(runtime_status.get("pid") or 0)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _pid_is_running(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _choose_runtime_status(
    runtime_status: dict[str, Any] | None,
    active_runtime_status: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Prefer live active-profile gateway status over stale process-default status."""
    active_pid = _runtime_pid(active_runtime_status)
    if _pid_is_running(active_pid):
        return active_runtime_status
    return runtime_status


def _runtime_detail_subset(runtime_status: dict[str, Any] | None) -> dict[str, Any]:
    """Return only non-sensitive runtime fields for the browser.

    gateway.status records argv/PID metadata so the CLI can validate process
    identity. The WebUI alert only needs health semantics, never raw command
    lines, paths, environment, or tokens.
    """
    if not isinstance(runtime_status, dict):
        return {}

    details: dict[str, Any] = {}
    gateway_state = runtime_status.get("gateway_state")
    if isinstance(gateway_state, str) and gateway_state:
        details["gateway_state"] = gateway_state

    updated_at = runtime_status.get("updated_at")
    if isinstance(updated_at, str) and updated_at:
        details["updated_at"] = updated_at

    try:
        details["active_agents"] = max(0, int(runtime_status.get("active_agents") or 0))
    except (TypeError, ValueError):
        pass

    platforms = runtime_status.get("platforms")
    if isinstance(platforms, dict):
        details["platform_count"] = len(platforms)
        states: dict[str, int] = {}
        for payload in platforms.values():
            if not isinstance(payload, dict):
                continue
            state = payload.get("state")
            if isinstance(state, str) and state:
                states[state] = states.get(state, 0) + 1
        if states:
            details["platform_states"] = states

    return details


def build_agent_health_payload() -> dict[str, Any]:
    """Return `{alive, checked_at, details}` for the Hermes gateway/agent.

    `alive` is intentionally tri-state:
      * True: a gateway runtime signal says the process is alive.
      * False: gateway metadata exists, but no live gateway process owns it.
      * None: no gateway metadata/status is available, so this WebUI setup is
        probably not configured with a separate gateway process.
    """
    checked_at = _checked_at()
    try:
        gateway_status = _gateway_status_module()
    except Exception as exc:
        return {
            "alive": None,
            "checked_at": checked_at,
            "details": {
                "state": "unknown",
                "reason": "gateway_status_unavailable",
                "error": type(exc).__name__,
            },
        }

    runtime_status = None
    try:
        runtime_status = gateway_status.read_runtime_status()
    except Exception:
        runtime_status = None

    runtime_status = _choose_runtime_status(
        runtime_status,
        _active_profile_runtime_status(),
    )

    running_pid = _runtime_pid(runtime_status)
    if not _pid_is_running(running_pid):
        try:
            running_pid = gateway_status.get_running_pid(cleanup_stale=False)
        except TypeError:
            # Older agent versions may not expose cleanup_stale. Keep compatibility.
            running_pid = gateway_status.get_running_pid()
        except Exception:
            running_pid = None

    safe_details = _runtime_detail_subset(runtime_status)
    if running_pid is not None:
        return {
            "alive": True,
            "checked_at": checked_at,
            "details": {
                "state": "alive",
                **safe_details,
            },
        }

    if isinstance(runtime_status, dict):
        return {
            "alive": False,
            "checked_at": checked_at,
            "details": {
                "state": "down",
                "reason": "gateway_not_running",
                **safe_details,
            },
        }

    return {
        "alive": None,
        "checked_at": checked_at,
        "details": {
            "state": "unknown",
            "reason": "gateway_not_configured",
        },
    }
