# web/routes_queue_logs.py
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
)

from shared import config

queue_logs_bp = Blueprint("queue_logs", __name__)

SAFE_LOG_NAME = re.compile(r"^[A-Za-z0-9._-]+\.log$")
MAX_TAIL_LINES = 20000


def _log_dir() -> Path:
    """
    Resolve the queue-manager log directory.

    queue_manager.logging_utils currently uses a relative LOG_DIR = "logs",
    so the normal location is ./logs from the process working directory.
    We also fall back to BASE_DIR/logs.

    If you deploy queue manager and web app separately, set:
        QUEUE_MANAGER_LOG_DIR=/path/to/logs
    """
    candidates = []

    env_dir = os.environ.get("QUEUE_MANAGER_LOG_DIR")
    if env_dir:
        candidates.append(Path(env_dir))

    candidates.extend(
        [
            Path("logs"),
            Path.cwd() / "logs",
            Path(getattr(config, "BASE_DIR", ".")) / "logs",
        ]
    )

    for candidate in candidates:
        try:
            path = Path(candidate).expanduser().resolve()
            if path.is_dir():
                return path
        except Exception:
            continue

    # Return a sensible default even if the directory does not exist yet.
    return (Path.cwd() / "logs").resolve()


def _safe_log_path(name: str) -> Path:
    """
    Prevent path traversal and only allow simple *.log filenames.
    """
    name = os.path.basename(name or "")

    if not SAFE_LOG_NAME.match(name):
        abort(400, description="Invalid log file name")

    log_dir = _log_dir()
    path = (log_dir / name).resolve()

    try:
        path.relative_to(log_dir)
    except ValueError:
        abort(400, description="Invalid log file path")

    if not path.is_file():
        abort(404, description="Log file not found")

    return path


def _tail_lines(path: Path, n: int) -> bytes:
    """
    Return the last n lines of a file without reading the whole file into
    memory when possible.

    This is intentionally simple and robust rather than maximally clever.
    """
    if n <= 0:
        return path.read_bytes()

    file_size = path.stat().st_size
    if file_size == 0:
        return b""

    block_size = 65536
    data = b""
    newline_count = 0
    pos = file_size

    with open(path, "rb") as f:
        while pos > 0 and newline_count <= n:
            read_size = min(block_size, pos)
            pos -= read_size
            f.seek(pos)
            chunk = f.read(read_size)
            data = chunk + data
            newline_count = data.count(b"\n")

    lines = data.splitlines()

    if len(lines) > n:
        lines = lines[-n:]

    return b"\n".join(lines)


@queue_logs_bp.route("/queue_logs")
def queue_logs_viewer():
    """
    Render the log viewer page.
    """
    domain_config = getattr(config, "_domain_config", {}) or {}
    return render_template(
        "queue_logs.html",
        domain_config=domain_config,
        queue_manager_url=config.QUEUE_MANAGER_URL,
    )


@queue_logs_bp.route("/queue_logs/list")
def queue_logs_list():
    """
    JSON list of log files.
    """
    log_dir = _log_dir()
    files = []

    if log_dir.is_dir():
        for path in log_dir.glob("*.log"):
            try:
                st = path.stat()
            except OSError:
                continue

            files.append(
                {
                    "name": path.name,
                    "size": st.st_size,
                    "modified": datetime.fromtimestamp(
                        st.st_mtime, timezone.utc
                    ).isoformat(),
                }
            )

    files.sort(key=lambda item: item["modified"], reverse=True)

    return jsonify(
        {
            "log_dir": str(log_dir),
            "queue_manager_url": config.QUEUE_MANAGER_URL,
            "files": files,
        }
    )


@queue_logs_bp.route("/queue_logs/raw")
def queue_logs_raw():
    """
    Return raw log text.

    Query params:
        name=dispatcher.log
        tail=5000          optional, last N lines
        download=1         optional, download full file
    """
    path = _safe_log_path(request.args.get("name", ""))

    if request.args.get("download"):
        return send_file(
            str(path),
            mimetype="text/plain; charset=utf-8",
            as_attachment=True,
        )

    tail = request.args.get("tail", type=int)

    if tail is not None:
        tail = max(0, min(tail, MAX_TAIL_LINES))

        if tail == 0:
            return send_file(
                str(path),
                mimetype="text/plain; charset=utf-8",
            )

        return Response(
            _tail_lines(path, tail),
            mimetype="text/plain; charset=utf-8",
        )

    return send_file(
        str(path),
        mimetype="text/plain; charset=utf-8",
    )