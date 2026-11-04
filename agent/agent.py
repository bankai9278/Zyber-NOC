"""Home agent for a hosted copy of Zyber NOC.

The hosted website cannot reach devices on the home network. This script
runs on the home PC, asks the website which saved devices to check,
checks them with the same ping and TCP code as the local app
(app/monitoring.py), and posts the results back in one batch.

It runs once and exits. Windows Task Scheduler starts it every 5 minutes
(see the README). Run it with the project's virtual-environment Python:

    .\\.venv\\Scripts\\python.exe agent\\agent.py

It reads the website address and the agent key from agent/config.json,
which git ignores. Copy agent/config.example.json to start.

The agent does not trust the website. Every address is validated again
here with the inventory's own rules, only the allowed TCP ports are
tried, at most 200 devices are checked per run, and redirects are not
followed, so the key is only ever sent to the configured address.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

AGENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = AGENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Config  # noqa: E402
from app.database import ALLOWED_TCP_PORTS, ValidationError, normalize_ip_address  # noqa: E402
from app.monitoring import check_connectivity, check_tcp_port  # noqa: E402

CONFIG_PATH = AGENT_DIR / "config.json"
LOG_PATH = AGENT_DIR / "agent.log"
LOG_MAX_BYTES = 512 * 1024
KEY_HEADER = "X-Zyber-Agent-Key"
MIN_KEY_LENGTH = 32
MAX_DEVICES = 200
MAX_CONCURRENCY = 4
REQUEST_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 1024 * 1024
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


class AgentError(Exception):
    """The run cannot continue. The message is safe to print and log."""


def load_config(path=CONFIG_PATH):
    """Read and check agent/config.json."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AgentError(f"No config file at {path}. Copy config.example.json to config.json and fill it in.") from None
    except (OSError, ValueError):
        raise AgentError(f"The config file at {path} could not be read as JSON.") from None
    if not isinstance(data, dict):
        raise AgentError("The config file must be a JSON object.")
    return {
        "site_url": _checked_site_url(data.get("site_url")),
        "agent_key": _checked_key(data.get("agent_key")),
        "concurrency": _checked_concurrency(data.get("concurrency", 2)),
    }


def _checked_site_url(value):
    if not isinstance(value, str) or not value.strip():
        raise AgentError("site_url is missing from the config file.")
    parts = urlsplit(value.strip())
    # The key must never travel unencrypted, except to this PC while testing.
    plain_local = parts.scheme == "http" and parts.hostname in LOCAL_HOSTS
    if parts.scheme != "https" and not plain_local:
        raise AgentError("site_url must start with https:// (http:// is allowed only for 127.0.0.1).")
    if not parts.hostname or parts.query or parts.fragment or parts.username or parts.password:
        raise AgentError("site_url must be a plain address such as https://example.pythonanywhere.com")
    return value.strip().rstrip("/")


def _checked_key(value):
    if not isinstance(value, str) or len(value.strip()) < MIN_KEY_LENGTH:
        raise AgentError(f"agent_key must be at least {MIN_KEY_LENGTH} characters, the same value as ZYBER_AGENT_KEY on the website.")
    return value.strip()


def _checked_concurrency(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_CONCURRENCY:
        raise AgentError(f"concurrency must be a whole number from 1 to {MAX_CONCURRENCY}.")
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects, so the key header is never sent to another address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_transport(config):
    """Return a function that sends one JSON request to the website."""
    opener = urllib.request.build_opener(_NoRedirect())

    def send(method, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            config["site_url"] + path,
            data=data,
            method=method,
            headers={
                KEY_HEADER: config["agent_key"],
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "zyber-noc-agent/1",
            },
        )
        try:
            with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                status = response.status
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = exc.read(MAX_RESPONSE_BYTES + 1)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            reason = getattr(exc, "reason", None) or type(exc).__name__
            raise AgentError(f"Could not reach {config['site_url']}: {reason}") from None
        return status, _json_body(status, body)

    return send


def _json_body(status, body):
    if len(body) > MAX_RESPONSE_BYTES:
        raise AgentError("The website's answer was too large.")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise AgentError(f"The website answered {status} without JSON. Check site_url.") from None


def plan_checks(device_list):
    """Turn the website's device list into checks the local rules allow.

    Returns (jobs, skipped). A device whose address fails validation gets
    an error result instead of a check, so the dashboard shows the problem.
    """
    devices = device_list.get("devices") if isinstance(device_list, dict) else None
    if not isinstance(devices, list):
        raise AgentError("The website's device list was not in the expected shape.")
    jobs = []
    skipped = 0
    for item in devices[:MAX_DEVICES]:
        device_id = item.get("id") if isinstance(item, dict) else None
        if isinstance(device_id, bool) or not isinstance(device_id, int) or device_id < 1:
            skipped += 1
            continue
        try:
            address = normalize_ip_address(item.get("ip_address"))
        except ValidationError as exc:
            jobs.append({"device_id": device_id, "check_type": "ping", "refused": f"The agent refused this address: {exc}"})
            continue
        checks = item.get("checks")
        if not isinstance(checks, list) or not checks:
            checks = [{"check_type": "ping"}]
        for check in checks:
            jobs.append(_planned_check(device_id, address, check))
    return jobs, skipped + max(0, len(devices) - MAX_DEVICES)


def _planned_check(device_id, address, check):
    check_type = check.get("check_type") if isinstance(check, dict) else None
    if check_type == "tcp":
        port = check.get("port")
        if isinstance(port, bool) or port not in ALLOWED_TCP_PORTS:
            return {"device_id": device_id, "check_type": "ping", "refused": "The agent refused a TCP port outside 22, 53, 80, 443, and 3389."}
        return {"device_id": device_id, "check_type": "tcp", "port": port, "ip_address": address}
    if check_type != "ping":
        return {"device_id": device_id, "check_type": "ping", "refused": "The agent refused an unknown check type."}
    return {"device_id": device_id, "check_type": "ping", "ip_address": address}


def run_checks(jobs, *, concurrency=2, ping=check_connectivity, tcp=check_tcp_port):
    """Run every planned check and return result rows in the same order."""

    def one(job):
        if "refused" in job:
            return _error_row(job, job["refused"])
        try:
            if job["check_type"] == "tcp":
                result = tcp(job["ip_address"], job["port"], timeout_seconds=Config.TCP_TIMEOUT_SECONDS)
            else:
                result = ping(job["ip_address"], attempts=Config.PING_ATTEMPTS, timeout_ms=Config.PING_TIMEOUT_MS)
        except Exception:
            return _error_row(job, "The connectivity check could not be completed.")
        row = {"device_id": job["device_id"], "check_type": job["check_type"], **result}
        if job["check_type"] == "tcp":
            row["port"] = job["port"]
        return row

    with ThreadPoolExecutor(max_workers=min(MAX_CONCURRENCY, max(1, concurrency))) as pool:
        return list(pool.map(one, jobs))


def _error_row(job, message):
    row = {
        "device_id": job["device_id"],
        "check_type": job["check_type"],
        "status": "error",
        "error_details": message[:500],
    }
    if job["check_type"] == "tcp":
        row["port"] = job["port"]
    return row


def run_once(config, *, transport=None, ping=check_connectivity, tcp=check_tcp_port):
    """Fetch the device list, check every device, and post the results.

    Returns a short summary dictionary. Raises AgentError when the website
    cannot be reached or refuses the request.
    """
    send = transport or http_transport(config)
    status, device_list = send("GET", "/api/agent/devices")
    _require_ok(status, device_list, "fetch the device list")
    jobs, skipped = plan_checks(device_list)
    rows = run_checks(jobs, concurrency=config["concurrency"], ping=ping, tcp=tcp)
    summary = {"checked": len(rows), "skipped": skipped, "saved": 0, "rejected": 0}
    if not rows:
        return summary
    status, answer = send("POST", "/api/agent/results", {"results": rows})
    _require_ok(status, answer, "send the results")
    summary["saved"] = answer.get("saved", 0) if isinstance(answer, dict) else 0
    rejected = answer.get("rejected") if isinstance(answer, dict) else None
    summary["rejected"] = len(rejected) if isinstance(rejected, list) else 0
    return summary


def _require_ok(status, answer, action):
    if status == 200:
        return
    if status == 401:
        raise AgentError(f"Could not {action}: the website did not accept the agent key.")
    if status == 404:
        raise AgentError(f"Could not {action}: the agent API is off. Set ZYBER_AGENT_KEY on the website.")
    detail = answer.get("error") if isinstance(answer, dict) else None
    raise AgentError(f"Could not {action}: the website answered {status}" + (f" ({detail})" if detail else "") + ".")


def log(message, path=None):
    """Print a line and append it to agent/agent.log, keeping the file small."""
    path = LOG_PATH if path is None else path
    line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {message}"
    print(line)
    try:
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            path.replace(path.with_suffix(".log.old"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check the saved devices and send the results to the hosted Zyber NOC.")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Path to the config file (default: agent/config.json).")
    parser.add_argument("--check-connection", action="store_true", help="Only fetch the device list and say how many devices it has.")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.check_connection:
            send = http_transport(config)
            status, device_list = send("GET", "/api/agent/devices")
            _require_ok(status, device_list, "fetch the device list")
            jobs, _skipped = plan_checks(device_list)
            log(f"Connected to {config['site_url']}. {len(jobs)} checks to run.")
            return 0
        summary = run_once(config)
    except AgentError as exc:
        log(f"FAILED {exc}")
        return 1
    log(
        f"Checked {summary['checked']}, saved {summary['saved']}, "
        f"rejected {summary['rejected']}, skipped {summary['skipped']}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
