"""One foreground process supervisor for Python API (with worker) and Next.js."""
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

from .config import ROOT
from .console import configure_logging

# -m executes this file as __main__; keep it in the configured backend namespace.
logger = logging.getLogger("backend.launcher")


def main():
    if any(arg not in {"--prod", "--help"} for arg in sys.argv[1:]) or "--help" in sys.argv:
        print("Usage: ./start.sh [--prod]\nDefaults: frontend 3001, backend 8001. Ctrl+C stops both.\nConsole logs: APP_LOG_LEVEL=INFO (default), or DEBUG for polling and diagnostics.")
        return 0 if "--help" in sys.argv else 2
    level = configure_logging()
    logger.info("Console logging enabled: %s. Child services stream directly to this terminal.", level)
    frontend_port = int(os.getenv("FRONTEND_PORT", os.getenv("PORT", "3001")))
    backend_port = int(os.getenv("BACKEND_PORT", "8001"))
    if frontend_port == backend_port or any(not 1024 <= p <= 65535 for p in (frontend_port, backend_port)):
        raise ValueError("Choose distinct FRONTEND_PORT and BACKEND_PORT values between 1024 and 65535.")
    for port in (frontend_port, backend_port):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise ValueError(f"Port {port} is in use. Stop the existing app or set FRONTEND_PORT / BACKEND_PORT. No existing process was stopped.") from None
    production = "--prod" in sys.argv
    logger.info("Starting %s mode; frontend port=%s backend port=%s", "production" if production else "development", frontend_port, backend_port)
    environment = {**os.environ, "FRONTEND_PORT": str(frontend_port), "BACKEND_PORT": str(backend_port),
                   "BACKEND_URL": f"http://127.0.0.1:{backend_port}", "PYTHONUNBUFFERED": "1"}
    children = []
    stopping = False

    def request_stop(signum, frame):
        nonlocal stopping
        stopping = True

    def spawn(command):
        child = subprocess.Popen(command, cwd=ROOT, env=environment, start_new_session=True)
        children.append(child)
        return child

    def signal_groups(sig):
        for child in children:
            # The group can outlive its parent; always attempt group cleanup.
            try:
                os.killpg(child.pid, sig)
            except ProcessLookupError:
                pass

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        if production:
            logger.info("Building Next.js for production…")
            build = spawn(["node", "node_modules/next/dist/bin/next", "build"])
            while build.poll() is None and not stopping:
                time.sleep(0.2)
            if stopping:
                return 0
            if build.returncode:
                return build.returncode
            children.remove(build)
        logger.info("Starting Python API and staffing supervisor; waiting for health check…")
        # App middleware logs safe route templates; Uvicorn access logs expose raw URLs/query strings.
        api = spawn([sys.executable, "-u", "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(backend_port), "--workers", "1", "--log-level", "info", "--no-access-log"])
        deadline = time.monotonic() + 60
        ready = False
        while not stopping and time.monotonic() < deadline:
            if api.poll() is not None:
                raise RuntimeError("Python backend exited during startup. See the error above.")
            try:
                with urlopen(f"http://127.0.0.1:{backend_port}/api/health", timeout=1) as response:
                    ready = json.load(response).get("status") == "ok"
                if ready:
                    break
            except (URLError, TimeoutError, OSError):
                time.sleep(0.2)
        if stopping:
            return 0
        if not ready:
            raise RuntimeError("Python backend did not become ready within 60 seconds.")
        logger.info("Python API is ready. Starting Next.js…")
        spawn(["node", "node_modules/next/dist/bin/next", "start" if production else "dev", "--hostname", "127.0.0.1", "--port", str(frontend_port)])
        print(f"\nUI: http://localhost:{frontend_port}\nPython API/docs: http://127.0.0.1:{backend_port}/docs\nSupervisor runs inside Python. Ctrl+C stops both services.\n", flush=True)
        while not stopping:
            for child in children:
                if child.poll() is not None:
                    logger.error("Service pid=%s exited with code=%s; stopping the other service.", child.pid, child.returncode)
                    return child.returncode or 1
            time.sleep(0.3)
        return 0
    finally:
        logger.info("Stopping frontend, backend and internal supervisor…")
        signal_groups(signal.SIGTERM)
        deadline = time.monotonic() + 30
        while any(p.poll() is None for p in children) and time.monotonic() < deadline:
            time.sleep(0.2)
        signal_groups(signal.SIGKILL)
        for child in children:
            child.wait()
        logger.info("All launched services stopped.")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError) as error:
        print(f"Startup failed: {error}", file=sys.stderr)
        sys.exit(1)
