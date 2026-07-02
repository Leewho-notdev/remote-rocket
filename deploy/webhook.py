#!/usr/bin/env python3
"""
GitHub webhook listener — auto-deploys on push to main.
Runs as a systemd service on the VPS.
"""

import hashlib
import hmac
import json
import logging
import os
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

SECRET = os.environ.get("WEBHOOK_SECRET", "").encode()
REPO_DIR = os.environ.get("REPO_DIR", "/root/remote-rocket")
BRANCH = "refs/heads/main"
PORT = int(os.environ.get("WEBHOOK_PORT", "9000"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def verify_signature(body: bytes, sig_header: str) -> bool:
    if not SECRET:
        return True  # no secret configured — skip verification
    expected = "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header or "")


def deploy():
    log.info("Starting deploy")
    result = subprocess.run(
        ["bash", "-c", "git pull && docker compose restart app"],
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        log.info("Deploy succeeded:\n%s", result.stdout)
    else:
        log.error("Deploy failed:\n%s\n%s", result.stdout, result.stderr)
    return result.returncode == 0


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        sig = self.headers.get("X-Hub-Signature-256", "")
        if not verify_signature(body, sig):
            log.warning("Bad signature — ignoring request")
            self.send_response(403)
            self.end_headers()
            return

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        ref = payload.get("ref", "")
        if ref != BRANCH:
            log.info("Push to %s — not main, skipping", ref)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"skipped")
            return

        ok = deploy()
        self.send_response(200 if ok else 500)
        self.end_headers()
        self.wfile.write(b"ok" if ok else b"deploy failed")

    def log_message(self, *args):
        pass  # suppress default HTTP log noise


if __name__ == "__main__":
    log.info("Webhook listener on port %d, watching %s", PORT, BRANCH)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
