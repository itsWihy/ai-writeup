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
from pathlib import Path
from urllib.parse import urlparse

import requests

CONNECT_TIMEOUT = 10
UPLOAD_TIMEOUT = 120


def _validate_server_url(server: str) -> bool:
    if not server:
        return False
    parsed = urlparse(server)
    if parsed.scheme != "https":
        return False
    if not parsed.hostname:
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
                return True

        except requests.ConnectionError:
            pass
        except requests.Timeout:
            pass
        except Exception:
            pass

    return False


def check_connectivity(server: str, port: int = 0) -> bool:
    if not _validate_server_url(server):
        return False

    base = _build_base_url(server, port)
    health_url = base + "/health"
    try:
        resp = requests.get(health_url, timeout=CONNECT_TIMEOUT)
        if resp.ok:
            return True
        return False
    except Exception:
        return False
