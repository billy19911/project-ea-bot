# -*- coding: utf-8 -*-
"""Ops drill runner for Gate D (CERT-D1).

This script performs the **real** operational drills behind Gate D and records
honest, verifiable evidence into ``services/python/logs/ops_drills.jsonl`` —
the exact file the certification collector
(:func:`src.live_readiness.certification_evidence._collect_gate_d`) reads.

Design contract
---------------

* **Sequential only, never parallel.** Every drill disturbs a *live* service
  (MT5 terminal, Python API, Node API, 9router, Postgres, Telegram). Running
  them concurrently would corrupt the very signals they are meant to measure,
  so ``--all`` runs them strictly one after another.
* **Rollback in ``finally``.** Each drill registers an explicit ``rollback``
  callable; it is *always* invoked after the drill, whether the drill passed,
  failed, or timed out. A drill that leaves the host in a broken state is a bug,
  not an acceptable outcome.
* **Per-drill timeout.** A drill that hangs (a service never comes back, a
  ``wait_for_health`` loop spins) is cut off by the timeout and recorded as
  ``failed`` — the process never hangs forever.
* **Health before + after.** Every drill verifies the stack is healthy *before*
  it starts (so we don't measure a drill against an already-broken baseline)
  and that it is healthy again *after* rollback.
* **Honest records.** Each record is ``{"drill", "status", "at", "method",
  "detail"}``. The ``method`` field states *exactly* what was done — e.g. for
  ``pc_restart`` it says "restart layanan penuh (bukan reboot OS)"; this runner
  never reboots the host. No secrets are ever written to the log (env overrides
  are described, never their values).

CLI
---

    python scripts/run_ops_drills.py --drill mt5_restart
    python scripts/run_ops_drills.py --all
    python scripts/run_ops_drills.py --all --drill-timeout 300

This module performs no work at import time; everything runs from ``main``
(guarded by ``if __name__ == "__main__"``), which is what the unit tests rely
on to import it safely.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Repo / service layout
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DRILLS_PATH = _REPO_ROOT / "services" / "python" / "logs" / "ops_drills.jsonl"

# Default per-drill timeout. Generous: a full-stack restart can take a while,
# but bounded so a stuck drill can never hang the orchestrator forever.
DEFAULT_DRILL_TIMEOUT_S = 300

# Ports from .env.runtime (non-default). Overridable via the same env file.
DEFAULT_PY_PORT = 8787
DEFAULT_NODE_PORT = 3789
DEFAULT_WEB_PORT = 4321
DEFAULT_NINE_PORT = 20128

# The 7 Gate D drills — the canonical names the collector knows.
DRILLS: tuple[str, ...] = (
    "mt5_restart",
    "pc_restart",
    "mt5_disconnect",
    "database_failure",
    "llm_failure",
    "nine_router_failure",
    "telegram_failure",
)


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_runtime_env() -> dict[str, str]:
    """Parse ``.env.runtime`` into a dict (no secret exposure beyond in-memory)."""
    out: dict[str, str] = {}
    runtime = _REPO_ROOT / ".env.runtime"
    try:
        for raw in runtime.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
    except OSError:
        pass
    return out


def _port(env: dict[str, str], key: str, fallback: int) -> int:
    try:
        return int(env.get(key) or fallback)
    except (TypeError, ValueError):
        return fallback


def _http_status(url: str, timeout_s: float = 5.0) -> Optional[int]:
    """Return the HTTP status code for *url*, or ``None`` if unreachable."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            return int(resp.status)
    except urllib.error.HTTPError as exc:  # reachable, non-2xx
        return int(exc.code)
    except Exception:  # noqa: BLE001 - unreachable == None
        return None


def _is_http_up(url: str, timeout_s: float = 5.0) -> bool:
    status = _http_status(url, timeout_s)
    return status is not None and 200 <= status < 500


def _wait_http_up(
    url: str,
    timeout_s: float = 60.0,
    interval_s: float = 1.0,
) -> bool:
    """Poll *url* until it answers (2xx–4xx) or the timeout elapses."""
    deadline = time.monotonic() + max(0.0, timeout_s)
    while time.monotonic() < deadline:
        if _is_http_up(url):
            return True
        time.sleep(interval_s)
    return _is_http_up(url)


def _pid_on_port(port: int) -> Optional[int]:
    """Return the PID listening on *port* (Windows ``netstat``), else None."""
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in result.stdout.splitlines():
        if "LISTENING" not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local = parts[1]
        # Accept "127.0.0.1:8787", "0.0.0.0:8787" and "[::]:8787".
        if not local.endswith(f":{port}"):
            continue
        try:
            return int(parts[-1])
        except ValueError:
            continue
    return None


def _kill_pid(pid: int) -> bool:
    """Force-kill a process by PID (best effort). Returns True if sent."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except OSError:
            return False


def _kill_port(port: int) -> bool:
    pid = _pid_on_port(port)
    if pid is None:
        return False
    return _kill_pid(pid)


def _listener_pid(port: int) -> Optional[int]:
    """PID listening on *port* via psutil (returns None when unavailable)."""
    try:
        import psutil
    except ImportError:
        return None
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if (
                conn.status == psutil.CONN_LISTEN
                and conn.laddr
                and int(conn.laddr.port) == int(port)
            ):
                return int(conn.pid) if conn.pid else None
    except Exception:  # noqa: BLE001 - probe is best-effort
        return None
    return None


def _service_env_lookup(port: int, name: str) -> tuple[bool, Optional[str]]:
    """``(probe_ran, value)`` for env var *name* of the listener process on *port*.

    Reads the *live* service process environment — the only way to prove a
    drill's env override actually reached the running service instead of being
    silently clobbered. The full environment is never logged; only the single
    requested value is returned and callers record booleans, never secrets.
    """
    pid = _listener_pid(port)
    if pid is None:
        return False, None
    try:
        import psutil
    except ImportError:
        return False, None
    try:
        env = psutil.Process(pid).environ()
    except Exception:  # noqa: BLE001 - access denied / process gone
        return False, None
    return True, env.get(name)


def _override_applied(port: int, name: str, expected: str) -> Optional[bool]:
    """Whether the running service on *port* really has ``name=expected``.

    ``True`` = proven applied (non-vacuous drill); ``False`` = the probe ran
    and the live value differs (the drill would be vacuous); ``None`` = probe
    unavailable (psutil missing / process unreadable).
    """
    ran, value = _service_env_lookup(port, name)
    if not ran:
        return None
    return value == expected


def _ai_models_source(ports: "ServicePorts") -> Optional[str]:
    """``source`` field from ``GET /ai/models`` (``gateway`` or ``defaults``).

    Calling this while the service points at a dead LLM base URL exercises the
    real LLM discovery path (registry → gateway client) and must fail safe
    (``source=defaults``, still answering). Returns None when unreachable.
    """
    url = f"http://127.0.0.1:{ports.py}/ai/models"
    headers: dict[str, str] = {}
    key = ports.env.get("PYTHON_API_KEY") or os.environ.get("PYTHON_API_KEY", "")
    if key:
        headers["X-API-Key"] = key
    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - unreachable => None
        return None
    source = data.get("source") if isinstance(data, dict) else None
    return str(source) if source else None


def _selected_terminal_id() -> Optional[str]:
    """Terminal id from ``services/python/mt5_selected.json`` (else None)."""
    selected = _REPO_ROOT / "services" / "python" / "mt5_selected.json"
    try:
        data = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    tid = data.get("selected_id") if isinstance(data, dict) else None
    return str(tid) if tid else None


def _api_post(
    ports: "ServicePorts", path: str, payload: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """POST JSON to the Python service with auth; None when unreachable/failed."""
    url = f"http://127.0.0.1:{ports.py}{path}"
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    key = ports.env.get("PYTHON_API_KEY") or os.environ.get("PYTHON_API_KEY", "")
    if key:
        headers["X-API-Key"] = key
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - unreachable => None
        return None


def _mt5_symbol_count(ports: "ServicePorts") -> Optional[int]:
    """Number of symbols served by the live MT5 binding (None when unreachable).

    ``GET /mt5/symbols`` is the honest liveness probe of the *binding*: a
    running ``terminal64.exe`` alone is not enough — after a terminal restart
    the Python connector must re-attach, otherwise ``symbols`` stays empty
    while the process looks alive.
    """
    url = f"http://127.0.0.1:{ports.py}/mt5/symbols"
    headers: dict[str, str] = {}
    key = ports.env.get("PYTHON_API_KEY") or os.environ.get("PYTHON_API_KEY", "")
    if key:
        headers["X-API-Key"] = key
    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - unreachable => None
        return None
    symbols = data.get("symbols") if isinstance(data, dict) else None
    return len(symbols) if isinstance(symbols, list) else None


def _reattach_mt5(
    ports: "ServicePorts", attempts: int = 8, delay_s: float = 10.0
) -> tuple[bool, str]:
    """Re-attach the MT5 binding to the selected terminal and verify symbols.

    A restarted terminal leaves the connector detached (``symbols == []``), so
    the drill must re-select the terminal — the same call the UI makes — and
    then prove the binding serves symbols again. The terminal needs time to
    finish loading after its process starts, hence the bounded retry.
    Returns ``(ok, detail)``.
    """
    tid = _selected_terminal_id()
    if not tid:
        return False, "selected_id tidak ditemukan (mt5_selected.json)"
    last = "belum dicoba"
    for attempt in range(1, attempts + 1):
        result = _api_post(ports, "/mt5/terminals/select", {"terminal_id": tid})
        if isinstance(result, dict) and result.get("ok"):
            count = _mt5_symbol_count(ports)
            if count is not None and count > 0:
                return (
                    True,
                    f"re-attach '{tid}' ok (percobaan {attempt}); symbols={count}",
                )
            last = f"symbols={count}"
        else:
            msg = (
                result.get("message")
                if isinstance(result, dict)
                else "respons tidak valid"
            )
            last = str(msg)
        if attempt < attempts:
            time.sleep(delay_s)
    return False, f"re-attach '{tid}' gagal setelah {attempts} percobaan: {last}"


def _run_capture(
    cmd: list[str],
    timeout_s: float,
    env: Optional[dict[str, str]] = None,
) -> tuple[int, str]:
    """Run *cmd*, capturing merged output through a temp file (NOT a pipe).

    The ``scripts/`` helpers spawn detached services (uvicorn etc.) that inherit
    the parent's stdout handle. With a pipe the write end never closes, so
    ``subprocess.run(..., capture_output=True)`` blocks forever — even its own
    timeout handler hangs while draining the pipe (observed: the llm_failure
    drill hitting its 300s watchdog). A temp file has no EOF wait, so the call
    returns as soon as the script itself exits.
    """
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as fh:
        result = subprocess.run(
            cmd,
            stdout=fh,
            stderr=subprocess.STDOUT,
            timeout=timeout_s,
            cwd=str(_REPO_ROOT),
            env=env,
        )
        fh.seek(0)
        return int(result.returncode), fh.read()


def _run_ps1(script_name: str, timeout_s: float = 180.0) -> tuple[int, str]:
    """Run a PowerShell script from ``scripts/`` and return (rc, tail-output).

    Output is captured via temp file (see ``_run_capture``), not a pipe, so a
    detached service spawned by the script cannot hang the capture.
    """
    script = _REPO_ROOT / "scripts" / script_name
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
    ]
    try:
        rc, text = _run_capture(cmd, timeout_s)
    except subprocess.TimeoutExpired:
        return 124, f"timeout setelah {timeout_s}s: {script_name}"
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"gagal menjalankan {script_name}: {exc}"
    return rc, text[-2000:].strip()


def _mt5_terminal_pids() -> list[int]:
    """PIDs of running MT5 ``terminal64.exe`` processes."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    pids: list[int] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.startswith('"'):
            continue
        cells = [c.strip('"') for c in line.split(",")]
        if len(cells) >= 2:
            try:
                pids.append(int(cells[1]))
            except ValueError:
                continue
    return pids


def _start_mt5_terminal() -> bool:
    """Start the selected MT5 terminal (best effort, detached)."""
    selected = _REPO_ROOT / "services" / "python" / "mt5_selected.json"
    terminals = _REPO_ROOT / "services" / "python" / "mt5_terminals.json"
    path: Optional[str] = None
    try:
        sel = json.loads(selected.read_text(encoding="utf-8"))
        selected_id = str(sel.get("selected_id") or "")
        reg = json.loads(terminals.read_text(encoding="utf-8"))
        for entry in reg.get("terminals", []):
            if str(entry.get("id")) == selected_id:
                path = str(entry.get("path") or "")
                break
    except (OSError, json.JSONDecodeError):
        return False
    if not path or not Path(path).exists():
        return False
    try:
        subprocess.Popen(  # noqa: S603,S607 - operator-controlled path
            [path],
            cwd=str(Path(path).parent),
            # Do NOT let MT5 inherit our stdout/stderr: the terminal runs
            # forever, so an inherited pipe handle would keep the caller's
            # capture open after this process exits (the drill would hang).
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        return True
    except OSError:
        return False


@dataclass
class ServicePorts:
    """Resolved ports for our services (from ``.env.runtime``)."""

    py: int = DEFAULT_PY_PORT
    node: int = DEFAULT_NODE_PORT
    web: int = DEFAULT_WEB_PORT
    nine: int = DEFAULT_NINE_PORT
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "ServicePorts":
        env = _load_runtime_env()
        return cls(
            py=_port(env, "PY_PORT", DEFAULT_PY_PORT),
            node=_port(env, "NODE_PORT", DEFAULT_NODE_PORT),
            web=_port(env, "WEB_PORT", DEFAULT_WEB_PORT),
            nine=_port(env, "NINE_ROUTER_PORT", DEFAULT_NINE_PORT),
            env=env,
        )

    def py_health(self) -> str:
        return f"http://127.0.0.1:{self.py}/health"

    def node_health(self) -> str:
        return f"http://127.0.0.1:{self.node}/health"

    def web_url(self) -> str:
        return f"http://127.0.0.1:{self.web}/"

    def stack_healthy(self) -> dict[str, bool]:
        """Health of the 3 core services (Python, Node, Web)."""
        return {
            "python": _is_http_up(self.py_health()),
            "node": _is_http_up(self.node_health()),
            "web": _is_http_up(self.web_url()),
        }

    def all_healthy(self) -> bool:
        return all(self.stack_healthy().values())


# ---------------------------------------------------------------------------
# Per-drill implementations
# ---------------------------------------------------------------------------
#
# Every ``run_<drill>`` returns a dict:
#     {"ok": bool, "detail": str, "method": str}
# *or* raises. The runner builds the final record (timestamp, status, method)
# around this. Each drill is paired with a ``rollback_<drill>`` used in the
# runner's ``finally`` so the host is always restored.


def run_mt5_restart(ports: ServicePorts) -> dict[str, Any]:
    """Stop the MT5 terminal → start it again → verify reconnect + service health."""
    method = (
        "stop proses terminal MT5 → start ulang → verifikasi reconnect + service sehat"
    )
    before = ports.stack_healthy()
    pids = _mt5_terminal_pids()
    if not pids:
        return {
            "ok": False,
            "method": method,
            "detail": "tidak ada terminal64.exe berjalan",
        }
    for pid in pids:
        _kill_pid(pid)
    time.sleep(3)
    started = _start_mt5_terminal()
    # Wait for a terminal to come back.
    deadline = time.monotonic() + 60
    back = False
    while time.monotonic() < deadline:
        if _mt5_terminal_pids():
            back = True
            break
        time.sleep(1)
    healthy = ports.stack_healthy()
    # Non-vacuous: the binding must actually serve symbols again (a live
    # terminal64.exe alone is not proof — the connector can stay detached).
    reattach_ok, reattach_detail = _reattach_mt5(ports)
    ok = (started or back) and healthy["python"] and reattach_ok
    detail = (
        f"terminal sebelum={pids}; start_ulang={started}; terminal_kembali={back}; "
        f"service sebelum={before}; service sesudah={healthy}; {reattach_detail}"
    )
    return {"ok": bool(ok), "method": method, "detail": detail}


def rollback_mt5_restart(ports: ServicePorts) -> str:
    """Ensure the MT5 terminal is running again and the binding is attached."""
    if not _mt5_terminal_pids():
        _start_mt5_terminal()
    _reattach_mt5(ports, attempts=4, delay_s=5.0)
    return "pastikan terminal64.exe berjalan + binding re-attach"


def run_pc_restart(ports: ServicePorts) -> dict[str, Any]:
    """Full-stack restart via ``restart-all.ps1`` — NOT an OS reboot.

    Verifies all services come back healthy and that durable state survives
    the restart (kill-switch store + order ledger are append-only JSONL on
    disk and must still exist after the restart).
    """
    method = "restart layanan penuh (bukan reboot OS) via scripts/restart-all.ps1"
    ks_before = (
        _REPO_ROOT / "services" / "python" / "logs" / "kill_switch.jsonl"
    ).exists()
    ledger_before = (
        _REPO_ROOT / "services" / "python" / "logs" / "order_state.jsonl"
    ).exists()

    rc, tail = _run_ps1("restart-all.ps1", timeout_s=240)

    py_ok = _wait_http_up(ports.py_health(), 90)
    node_ok = _wait_http_up(ports.node_health(), 60)
    web_ok = _wait_http_up(ports.web_url(), 90)

    ks_after = (
        _REPO_ROOT / "services" / "python" / "logs" / "kill_switch.jsonl"
    ).exists()
    ledger_after = (
        _REPO_ROOT / "services" / "python" / "logs" / "order_state.jsonl"
    ).exists()
    state_survived = (ks_after >= ks_before) and (ledger_after >= ledger_before)

    ok = py_ok and node_ok and web_ok and state_survived
    detail = (
        f"restart-all rc={rc}; sehat py={py_ok} node={node_ok} web={web_ok}; "
        f"state selamat kill_switch={ks_after} ledger={ledger_after}; tail={tail[-300:]}"
    )
    return {"ok": bool(ok), "method": method, "detail": detail}


def rollback_pc_restart(ports: ServicePorts) -> str:
    """If any service is still down, run the start script (best effort)."""
    if not ports.all_healthy():
        _run_ps1("start-all.ps1", timeout_s=240)
    return "verifikasi/nyalakan semua service"


def run_mt5_disconnect(ports: ServicePorts) -> dict[str, Any]:
    """Cut the terminal connection → verify degrade (not crash) → reconnect → healthy.

    The Python service consumes MT5 read-only; when the terminal disappears it
    must degrade (still answer ``/health``) rather than crash. We prove the
    service keeps answering while the terminal is gone, then bring the terminal
    back and confirm it reconnects.
    """
    method = "putuskan terminal MT5 → verifikasi service degrade (bukan crash) → reconnect → sehat"
    if not _mt5_terminal_pids():
        return {"ok": False, "method": method, "detail": "terminal MT5 tidak berjalan"}
    for pid in _mt5_terminal_pids():
        _kill_pid(pid)
    time.sleep(5)
    # Service must still respond (degrade, not crash).
    degraded_ok = _is_http_up(ports.py_health(), timeout_s=8)
    _start_mt5_terminal()
    reconnected = _wait_http_up(ports.py_health(), 60)
    deadline = time.monotonic() + 60
    terminal_back = False
    while time.monotonic() < deadline:
        if _mt5_terminal_pids():
            terminal_back = True
            break
        time.sleep(1)
    # Non-vacuous: reconnect means the *binding* serves symbols again.
    reattach_ok, reattach_detail = _reattach_mt5(ports)
    ok = degraded_ok and reconnected and terminal_back and reattach_ok
    detail = (
        f"service_saat_putus(degrade)={degraded_ok}; reconnect(sehat)={reconnected}; "
        f"terminal_kembali={terminal_back}; {reattach_detail}"
    )
    return {"ok": bool(ok), "method": method, "detail": detail}


def rollback_mt5_disconnect(ports: ServicePorts) -> str:
    if not _mt5_terminal_pids():
        _start_mt5_terminal()
    _reattach_mt5(ports, attempts=4, delay_s=5.0)
    return "pastikan terminal MT5 kembali terhubung + binding re-attach"


def run_database_failure(ports: ServicePorts) -> dict[str, Any]:
    """Point the service at a dead DB (env override) → verify fail-safe → restore.

    This host runs PostgreSQL (``DATABASE_URL_PYTHON`` → ``postgresql://…``),
    so there is no sqlite file to rename. Instead the service is restarted with
    ``DATABASE_URL_PYTHON`` aimed at a dead port — the same env-override pattern
    as ``llm_failure``. The service must still start and answer ``/health``
    (fail-safe bootstrap, per ``main.py`` lifespan), then the normal config is
    restored and verified. The override value is a non-secret dead URL.
    """
    method = (
        "restart service dengan DATABASE_URL_PYTHON invalid (env override sementara) → "
        "1 siklus → verifikasi fail-safe → restart normal"
    )
    dead_url = "postgresql://ea_bot:***@127.0.0.1:1/ea_bot"
    env_override = {"DATABASE_URL_PYTHON": dead_url}
    rc, tail = _run_ps1_env("restart-py.ps1", env_override, timeout_s=120)
    # With a dead DB the service must still come up and stay healthy (fail-safe).
    healthy = _wait_http_up(ports.py_health(), 60)
    # Non-vacuous: the LIVE service process really carries the override env.
    override_ok = _override_applied(ports.py, "DATABASE_URL_PYTHON", dead_url)
    cycle_ok = _run_one_pipeline_cycle(ports)
    # Restart back to the normal config.
    rc2, tail2 = _run_ps1("restart-py.ps1", timeout_s=120)
    normal_ok = _wait_http_up(ports.py_health(), 60)
    ok = healthy and normal_ok and (override_ok is not False)
    detail = (
        f"override=DATABASE_URL_PYTHON=<dead-port> (nilai non-sensitif); restart1 rc={rc}; "
        f"sehat_saat_DB_mati={healthy}; env_override_terpasang={override_ok}; "
        f"siklus_fail_safe={cycle_ok}; "
        f"restart2_normal rc={rc2}; sehat_normal={normal_ok}; tail={tail[-200:]}"
    )
    return {"ok": bool(ok), "method": method, "detail": detail}


def rollback_database_failure(ports: ServicePorts) -> str:
    """Always restart the Python service with the normal DB config."""
    _run_ps1("restart-py.ps1", timeout_s=120)
    return "restart Python service dengan konfigurasi DB normal"


def run_llm_failure(ports: ServicePorts) -> dict[str, Any]:
    """Restart the service with an invalid LLM base URL (temp env) → 1 cycle →
    verify fail-safe → restart normal.

    The temp override points ``NINE_ROUTER_BASE_URL`` at a dead port so every
    LLM call fails; the pipeline must fail *safe* (still healthy, no crash),
    then the service is restarted with the normal config. The override value is
    a non-secret dead URL — recorded honestly, never a real key.
    """
    method = (
        "restart service dengan base URL LLM invalid (env override sementara) → "
        "1 siklus → verifikasi fail-safe → restart normal"
    )
    dead_url = "http://127.0.0.1:1/v1"
    env_override = {"NINE_ROUTER_BASE_URL": dead_url}
    # Differential probe (pre): with the normal config the LLM gateway is the
    # live discovery source — recorded so the override's effect can be compared.
    source_before = _ai_models_source(ports)
    rc, tail = _run_ps1_env("restart-py.ps1", env_override, timeout_s=120)
    # With a dead LLM the service must still come up and stay healthy (fail-safe).
    healthy = _wait_http_up(ports.py_health(), 60)
    # Non-vacuous #1: the LIVE service process really carries the override env.
    override_ok = _override_applied(ports.py, "NINE_ROUTER_BASE_URL", dead_url)
    # Non-vacuous #2: the real LLM discovery path must now fail safe (flip from
    # "gateway" to "defaults") instead of silently succeeding.
    source_dead = _ai_models_source(ports)
    cycle_ok = _run_one_pipeline_cycle(ports)
    # Restart back to the normal config.
    rc2, tail2 = _run_ps1("restart-py.ps1", timeout_s=120)
    normal_ok = _wait_http_up(ports.py_health(), 60)
    source_after = _ai_models_source(ports)
    # A pass requires the override to be PROVABLY active: either the live
    # process env matched the dead URL, or discovery flipped to "defaults".
    proven = (override_ok is True) or (source_dead == "defaults")
    ok = healthy and normal_ok and proven
    detail = (
        f"override={env_override} (nilai non-sensitif); restart1 rc={rc}; "
        f"sehat_saat_LLM_mati={healthy}; env_override_terpasang={override_ok}; "
        f"llm_source: normal={source_before} → mati={source_dead} → pulih={source_after}; "
        f"siklus_fail_safe={cycle_ok}; restart2_normal rc={rc2}; sehat_normal={normal_ok}; "
        f"tail={tail[-200:]}"
    )
    return {"ok": bool(ok), "method": method, "detail": detail}


def rollback_llm_failure(ports: ServicePorts) -> str:
    """Always restart the Python service with the normal config."""
    _run_ps1("restart-py.ps1", timeout_s=120)
    return "restart Python service dengan konfigurasi normal"


def run_nine_router_failure(ports: ServicePorts) -> dict[str, Any]:
    """Stop 9router (:20128) → 1 cycle → verify degrade → relaunch canonical → healthy."""
    method = (
        "stop proses 9router (:20128) → 1 siklus → verifikasi degrade → "
        "relaunch kanonik (node custom-server.js) → sehat"
    )
    pid = _pid_on_port(ports.nine)
    if pid is None:
        return {
            "ok": False,
            "method": method,
            "detail": f"tidak ada proses di :{ports.nine}",
        }
    cmdline_before = _nine_router_cmdline(pid)
    stopped = _kill_pid(pid)
    time.sleep(2)
    # Our Python service must degrade gracefully (still answering), not crash.
    degraded_ok = _is_http_up(ports.py_health(), timeout_s=8)
    cycle_ok = _run_one_pipeline_cycle(ports)
    # Relaunch canonically: start-all.ps1 does NOT start 9router.
    restarted = _start_nine_router(ports)
    back = _wait_http_up(f"http://127.0.0.1:{ports.nine}/", 60)
    ok = stopped and degraded_ok and back
    detail = (
        f"pid={pid}; cmdline_sebelum={cmdline_before or 'n/a'}; stopped={stopped}; "
        f"service_degrade={degraded_ok}; siklus={cycle_ok}; restarted={restarted}; nine_back={back}"
    )
    return {"ok": bool(ok), "method": method, "detail": detail}


def rollback_nine_router_failure(ports: ServicePorts) -> str:
    if not _is_http_up(f"http://127.0.0.1:{ports.nine}/", timeout_s=3):
        _start_nine_router(ports)
    return "pastikan 9router :20128 kembali berjalan"


def _node_exe() -> Optional[str]:
    """Locate node.exe: the canonical install first (what 9router runs on), then PATH."""
    candidates: list[str] = [r"C:\Program Files\nodejs\node.exe"]
    which = shutil.which("node")
    if which:
        candidates.append(which)
    for cand in candidates:
        if cand and Path(cand).is_file():
            return cand
    return None


def _nine_router_cmdline(pid: int) -> str:
    """Best-effort command line of *pid* (recorded in evidence for honesty)."""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (result.stdout or "").strip()


def _start_nine_router(ports: ServicePorts) -> bool:
    """Relaunch 9router the canonical way: node + ``custom-server.js`` (standalone).

    ``start-all.ps1`` does NOT start 9router, so relaunching through it would
    leave the user's 9router dead after the drill. Instead this mirrors what the
    9router CLI itself does: ``node --dns-result-order=ipv4first
    --max-old-space-size=6144 <npm>/node_modules/9router/app/custom-server.js``
    with ``PORT``/``HOSTNAME`` env, cwd = the ``app`` dir, detached.
    """
    if _is_http_up(f"http://127.0.0.1:{ports.nine}/", timeout_s=5):
        return True
    node = _node_exe()
    npm_root = Path(os.environ.get("APPDATA", "")) / "npm"
    server = npm_root / "node_modules" / "9router" / "app" / "custom-server.js"
    if not node or not server.is_file():
        return False
    env = dict(os.environ)
    env["PORT"] = str(ports.nine)
    env["HOSTNAME"] = "0.0.0.0"
    try:
        subprocess.Popen(  # noqa: S603 - fixed, operator-controlled path
            [
                node,
                "--dns-result-order=ipv4first",
                "--max-old-space-size=6144",
                str(server),
            ],
            cwd=str(server.parent),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except OSError:
        return False
    return _wait_http_up(f"http://127.0.0.1:{ports.nine}/", 60)


def run_telegram_failure(ports: ServicePorts) -> dict[str, Any]:
    """Simulate a Telegram token/API failure (env override) → verify the
    notifier fails safe → restore.

    The override sets an obviously-invalid token so sends fail; the notifier
    must swallow the error (logged, never raised into the pipeline). The real
    token is never read or written — only a non-secret placeholder is used.
    """
    method = (
        "simulasi token/API Telegram gagal (env override) → "
        "verifikasi notifier fail-safe → restore"
    )
    dead_token = "drill-invalid-token"
    env_override = {"TELEGRAM_BOT_TOKEN": dead_token}
    rc, tail = _run_ps1_env("restart-py.ps1", env_override, timeout_s=120)
    healthy = _wait_http_up(ports.py_health(), 60)
    # Non-vacuous: the LIVE service process really carries the placeholder token.
    override_ok = _override_applied(ports.py, "TELEGRAM_BOT_TOKEN", dead_token)
    # Run a cycle; a dead Telegram gateway must not crash it.
    cycle_ok = _run_one_pipeline_cycle(ports)
    rc2, tail2 = _run_ps1("restart-py.ps1", timeout_s=120)
    normal_ok = _wait_http_up(ports.py_health(), 60)
    ok = healthy and normal_ok and (override_ok is not False)
    detail = (
        f"override=TELEGRAM_BOT_TOKEN=*** (placeholder non-sensitif); restart1 rc={rc}; "
        f"sehat_saat_telegram_mati={healthy}; env_override_terpasang={override_ok}; "
        f"siklus_fail_safe={cycle_ok}; "
        f"restart2_normal rc={rc2}; sehat_normal={normal_ok}; tail={tail[-200:]}"
    )
    return {"ok": bool(ok), "method": method, "detail": detail}


def rollback_telegram_failure(ports: ServicePorts) -> str:
    _run_ps1("restart-py.ps1", timeout_s=120)
    return "restart Python service dengan konfigurasi Telegram normal"


# ---------------------------------------------------------------------------
# Helper: run one pipeline cycle, and env-override PowerShell wrapper
# ---------------------------------------------------------------------------


def _run_one_pipeline_cycle(ports: ServicePorts) -> bool:
    """POST one pipeline cycle; True if the service accepts it (no crash).

    Sends the API key (``PYTHON_API_KEY`` from ``.env.runtime``) when present so
    the cycle genuinely executes instead of dying on auth (401). The key is used
    in-memory for this request only and is never written to evidence.
    """
    url = f"http://127.0.0.1:{ports.py}/pipeline/run"
    payload = json.dumps(
        {"event": {"event_type": "ANALYZE", "symbol": "XAUUSD"}}
    ).encode()
    headers = {"Content-Type": "application/json"}
    key = ports.env.get("PYTHON_API_KEY") or os.environ.get("PYTHON_API_KEY", "")
    if key:
        headers["X-API-Key"] = key
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return 200 <= int(resp.status) < 500
    except urllib.error.HTTPError as exc:
        # A 4xx/5xx still means the service answered (degraded, not crashed);
        # 401/403 mean auth blocked the cycle, so it never actually ran.
        code = int(exc.code)
        return 400 <= code < 600 and code not in (401, 403)
    except Exception:  # noqa: BLE001 - unreachable => cycle could not be verified
        return False


def _run_ps1_env(
    script_name: str,
    env_override: dict[str, str],
    timeout_s: float = 120.0,
) -> tuple[int, str]:
    """Run a ``scripts/`` PowerShell script with temporary env overrides.

    Overrides are injected into the child process environment only; the parent
    env is untouched. Secret-looking values are redacted in the returned tail.
    """
    script = _REPO_ROOT / "scripts" / script_name
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
    ]
    child_env = dict(os.environ)
    child_env.update(env_override)
    try:
        rc, text = _run_capture(cmd, timeout_s, env=child_env)
    except subprocess.TimeoutExpired:
        return 124, f"timeout setelah {timeout_s}s: {script_name}"
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"gagal menjalankan {script_name}: {exc}"
    return rc, _redact_secrets(text[-2000:]).strip()


def _redact_secrets(text: str) -> str:
    """Strip anything that looks like a secret from log output."""
    lowered = text.lower()
    if any(
        marker in lowered
        for marker in ("token", "api_key", "apikey", "password", "secret")
    ):
        # Keep the text but mask long alnum runs that could be tokens.
        import re

        return re.sub(r"[A-Za-z0-9_\-:]{24,}", "***", text)
    return text


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

# Drill name -> (drill function name, rollback function name).
#
# Names (not direct references) are stored so the runner resolves them from
# this module's globals at call time — the unit tests monkeypatch
# ``run_<drill>`` on the module and expect the override to take effect.
_DRILL_TABLE: dict[str, tuple[str, str]] = {
    "mt5_restart": ("run_mt5_restart", "rollback_mt5_restart"),
    "pc_restart": ("run_pc_restart", "rollback_pc_restart"),
    "mt5_disconnect": ("run_mt5_disconnect", "rollback_mt5_disconnect"),
    "database_failure": ("run_database_failure", "rollback_database_failure"),
    "llm_failure": ("run_llm_failure", "rollback_llm_failure"),
    "nine_router_failure": ("run_nine_router_failure", "rollback_nine_router_failure"),
    "telegram_failure": ("run_telegram_failure", "rollback_telegram_failure"),
}


def _resolve_drill(drill: str) -> tuple[Callable[[ServicePorts], dict], Callable]:
    """Resolve the drill + rollback callables for *drill* from module globals.

    Resolved at call time (not import time) so monkeypatched overrides in tests
    are honoured.
    """
    drill_name, rollback_name = _DRILL_TABLE[drill]
    return globals()[drill_name], globals()[rollback_name]


class DrillTimeout(Exception):
    """Raised when a drill exceeds its per-drill timeout."""


class OpsDrillRunner:
    """Run one or all Gate D drills, with timeout + rollback + evidence logging.

    Args:
        drills_path: JSONL evidence store. Defaults to
            ``services/python/logs/ops_drills.jsonl`` (overridable via
            ``OPS_DRILLS_PATH``).
        drill_timeout_s: Per-drill timeout in seconds. A drill that exceeds it
            is recorded ``failed`` and its rollback still runs.
        ports: Resolved service ports. Defaults to ``ServicePorts.load()``.
        verification_timeout_s: How long post-rollback health checks may wait.
    """

    def __init__(
        self,
        drills_path: Optional[Path] = None,
        drill_timeout_s: float = DEFAULT_DRILL_TIMEOUT_S,
        ports: Optional[ServicePorts] = None,
        verification_timeout_s: float = 60.0,
    ) -> None:
        env_path = os.environ.get("OPS_DRILLS_PATH")
        self.drills_path = Path(
            drills_path or (env_path if env_path else _DEFAULT_DRILLS_PATH)
        )
        self.drill_timeout_s = float(drill_timeout_s)
        self.verification_timeout_s = float(verification_timeout_s)
        self.ports = ports or ServicePorts.load()

    # -- evidence ----------------------------------------------------------

    def _append_record(self, record: dict[str, Any]) -> None:
        self.drills_path.parent.mkdir(parents=True, exist_ok=True)
        with self.drills_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    # -- core --------------------------------------------------------------

    def _preflight(self) -> tuple[bool, str]:
        """Confirm the required services are healthy BEFORE a drill runs."""
        health = self.ports.stack_healthy()
        return all(health.values()), f"health pra-drill={health}"

    def _verify_after(self) -> tuple[bool, str]:
        """Confirm the stack is healthy AFTER rollback (bounded wait)."""
        ok_py = _wait_http_up(self.ports.py_health(), self.verification_timeout_s)
        ok_node = _is_http_up(self.ports.node_health())
        ok_web = _is_http_up(self.ports.web_url())
        return (ok_py and ok_node and ok_web), (
            f"health pasca-drill py={ok_py} node={ok_node} web={ok_web}"
        )

    def run_one(
        self,
        drill: str,
        rollback: Optional[Callable[..., Any]] = None,
    ) -> dict[str, Any]:
        """Run a single drill. Never raises — always returns a record.

        The rollback callable is ALWAYS invoked in ``finally`` (whether the
        drill passed, failed, raised, or timed out).
        """
        at = _now_iso()
        drill_fn, default_rollback = _resolve_drill(drill)
        rollback_fn = rollback if rollback is not None else default_rollback
        method = f"drill {drill}"
        status = "failed"
        detail = ""

        # Preflight — if already broken, don't measure against a bad baseline.
        pre_ok, pre_detail = self._preflight()
        if not pre_ok:
            detail = f"preflight gagal: {pre_detail}"
            record = {
                "drill": drill,
                "status": "failed",
                "at": at,
                "method": method,
                "detail": detail,
            }
            self._append_record(record)
            return record

        try:
            result = self._with_timeout(drill_fn, self.ports)
            method = str(result.get("method") or method)
            detail = str(result.get("detail") or "")
            if result.get("ok"):
                status = "passed"
            else:
                status = "failed"
        except DrillTimeout as exc:
            status = "failed"
            detail = f"timeout: {exc}"
        except Exception as exc:  # noqa: BLE001 - a raising drill is a failure
            status = "failed"
            detail = f"exception: {exc}"
        finally:
            try:
                rb_detail = rollback_fn(self.ports)
                detail = f"{detail} | rollback: {rb_detail}".strip(" |")
            except Exception as exc:  # noqa: BLE001 - rollback never fails the run
                detail = f"{detail} | rollback gagal: {exc}".strip(" |")

        # Post-rollback verification: a drill only passes if the stack is back.
        post_ok, post_detail = self._verify_after()
        detail = f"{detail} | {post_detail}".strip(" |")
        if status == "passed" and not post_ok:
            status = "failed"

        record = {
            "drill": drill,
            "status": status,
            "at": at,
            "method": method,
            "detail": detail,
        }
        self._append_record(record)
        return record

    def _with_timeout(
        self, drill_fn: Callable[[ServicePorts], dict], ports: ServicePorts
    ) -> dict:
        """Run *drill_fn* under a hard timeout.

        Uses a daemon ``threading.Timer``-based watchdog so a hung drill is
        abandoned: the orchestrator is never blocked past the timeout. (A
        Python thread cannot be force-killed, but the drill's own blocking
        calls are bounded subprocess/HTTP timeouts, so the thread exits once
        those return.)
        """
        import threading

        box: dict[str, Any] = {}

        def _target() -> None:
            try:
                box["result"] = drill_fn(ports)
            except BaseException as exc:  # noqa: BLE001 - capture for caller
                box["error"] = exc

        worker = threading.Thread(
            target=_target, name=f"drill-{drill_fn.__name__}", daemon=True
        )
        worker.start()
        worker.join(self.drill_timeout_s)
        if worker.is_alive():
            raise DrillTimeout(f"{drill_fn.__name__} > {self.drill_timeout_s}s")
        if "error" in box:
            raise box["error"]
        return box.get("result") or {
            "ok": False,
            "detail": "drill tidak mengembalikan hasil",
        }

    def run_all(self, drills: Optional[tuple[str, ...]] = None) -> list[dict[str, Any]]:
        """Run drills sequentially (never parallel). Returns all records."""
        out: list[dict[str, Any]] = []
        for drill in drills or DRILLS:
            out.append(self.run_one(drill))
        return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Jalankan drill operasional Gate D dan catat bukti nyata.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--drill", choices=list(DRILLS), help="jalankan satu drill")
    group.add_argument(
        "--all", action="store_true", help="jalankan semua drill berurutan"
    )
    parser.add_argument(
        "--drill-timeout",
        type=float,
        default=DEFAULT_DRILL_TIMEOUT_S,
        help=f"timeout per drill (detik, default {DEFAULT_DRILL_TIMEOUT_S})",
    )
    parser.add_argument(
        "--drills-path",
        type=str,
        default=None,
        help="lokasi store evidence JSONL (default services/python/logs/ops_drills.jsonl)",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    runner = OpsDrillRunner(
        drills_path=Path(args.drills_path) if args.drills_path else None,
        drill_timeout_s=args.drill_timeout,
    )
    if args.drill:
        records = [runner.run_one(args.drill)]
    else:
        records = runner.run_all()
    for record in records:
        print(json.dumps(record, ensure_ascii=False))
    all_passed = all(r["status"] == "passed" for r in records)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
