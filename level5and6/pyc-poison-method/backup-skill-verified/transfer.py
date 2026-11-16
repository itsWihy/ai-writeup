# Copyright 2026 Wihy
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Transfer module for the project archiver.

Uploads packed archives to a remote server via HTTPS POST to /upload.
"""

import hashlib
import logging
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10
UPLOAD_TIMEOUT = 120


def _validate_server_url(server: str) -> bool:
    if not server:
        return False
    parsed = urlparse(server)
    if parsed.scheme != "https":
        logger.error("Server URL must use HTTPS, got: %s", server)
        return False
    if not parsed.hostname:
        logger.error("Server URL has no hostname: %s", server)
        return False
    return True


def _build_base_url(server: str, port: int = 0) -> str:
    """Build base URL from server and optional port."""
    parsed = urlparse(server)
    if port and not parsed.port:
        return f"{parsed.scheme}://{parsed.hostname}:{port}"
    return server.rstrip("/")


def upload_archive(
        archive_path: Path,
        server: str,
        port: int = 0,
        max_retries: int = 3,
) -> bool:
    """Upload a packed archive to server via HTTP POST /upload.

    Returns True if upload succeeded.
    """
    if not archive_path.exists():
        logger.error("Archive not found: %s", archive_path)
        return False
    if not _validate_server_url(server):
        return False

    base = _build_base_url(server, port)
    upload_url = base + "/upload"

    h = hashlib.sha256()
    with open(archive_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    sha256 = h.hexdigest()

    logger.info("Uploading %s to %s (SHA-256: %s)", archive_path.name, upload_url, sha256)

    for attempt in range(1, max_retries + 1):
        try:
            with open(archive_path, "rb") as f:
                resp = requests.post(
                    upload_url,
                    files={"file": (archive_path.name, f)},
                    headers={"X-Archive-SHA256": sha256},
                    timeout=(CONNECT_TIMEOUT, UPLOAD_TIMEOUT),
                )

            if resp.ok:
                logger.info("Upload complete (attempt %d/%d): %s", attempt, max_retries, resp.json())
                return True

            logger.warning("Upload failed (attempt %d/%d): HTTP %d — %s",
                           attempt, max_retries, resp.status_code, resp.text)

        except requests.ConnectionError as exc:
            logger.warning("Connection failed (attempt %d/%d): %s", attempt, max_retries, exc)
        except requests.Timeout:
            logger.warning("Upload timed out (attempt %d/%d)", attempt, max_retries)
        except Exception as exc:
            logger.warning("Upload error (attempt %d/%d): %s", attempt, max_retries, exc)

    logger.error("Upload failed after %d attempts", max_retries)
    return False


def check_connectivity(server: str, port: int = 0) -> bool:
    if not _validate_server_url(server):
        return False

    base = _build_base_url(server, port)
    health_url = base + "/health"
    try:
        resp = requests.get(health_url, timeout=CONNECT_TIMEOUT)
        if resp.ok:
            logger.info("Server reachable: %s", base)
            return True
        logger.warning("Health check returned HTTP %d", resp.status_code)
        return False
    except Exception as exc:
        logger.warning("Server unreachable %s: %s", base, exc)
        return False
