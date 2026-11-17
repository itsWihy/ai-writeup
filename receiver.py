# receiver.py — backup file receiver, packer, and browser
from flask import Flask, request, send_from_directory, send_file, abort
from datetime import datetime, timezone
from pathlib import Path
import io
import os
import zipfile

app = Flask(__name__)

SAVE_DIR = Path("received")
SAVE_DIR.mkdir(exist_ok=True)
count = 0

ALLOWED_PACK_PREFIXES = ("/home/", "/backups/", "/tmp/")
MAX_PACK_SIZE_MB = 500


@app.post("/pack")
def pack():
    """Zip a directory on this server and return it."""
    data = request.get_json(silent=True) or {}
    path = data.get("path", "").strip()

    if not path:
        return {"ok": False, "error": "missing 'path'"}, 400

    resolved = Path(path).resolve()
    if ".." in Path(path).parts:
        return {"ok": False, "error": "path traversal"}, 400

    if not any(str(resolved).startswith(p) for p in ALLOWED_PACK_PREFIXES):
        return {"ok": False, "error": f"path outside allowed prefixes"}, 403

    if not resolved.is_dir():
        return {"ok": False, "error": "not a directory"}, 404

    buf = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in sorted(resolved.rglob("*")):
            if not fp.is_file() or fp.is_symlink():
                continue
            rel = fp.relative_to(resolved).as_posix()
            zf.write(fp, rel)
            added += 1

    if added == 0:
        return {"ok": False, "error": "directory empty"}, 404

    size_mb = buf.tell() / (1024 * 1024)
    if size_mb > MAX_PACK_SIZE_MB:
        return {"ok": False, "error": f"zip too large ({size_mb:.1f} MB)"}, 413

    buf.seek(0)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = f"pack_{resolved.name}_{ts}.zip"

    print(f"Packed {added} files from {resolved} ({size_mb:.1f} MB) -> {name}")
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=name)


@app.post("/upload")
def upload():
    global count

    f = request.files.get("file")
    if not f or not f.filename:
        return {"ok": False, "error": "no file"}, 400

    name = Path(f.filename).name
    if not name or name.startswith(".") or ".." in name:
        return {"ok": False, "error": "bad filename"}, 400

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest_name = f"{ts}_{name}"
    dest = SAVE_DIR / dest_name
    f.save(dest)

    count += 1
    size = dest.stat().st_size
    print(f"#{count} [{ts}] {size} bytes — {dest_name} from {request.remote_addr}")

    return {"ok": True, "count": count, "filename": dest_name, "bytes": size}, 200


@app.post("/hook")
def hook():
    global count
    count += 1

    body = request.get_data()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
    (SAVE_DIR / f"{ts}.bin").write_bytes(body)

    return {"ok": True, "count": count, "bytes": len(body)}, 200


@app.get("/download/<path:filename>")
def download(filename):
    safe = Path(filename).name
    if not (SAVE_DIR / safe).is_file():
        abort(404)
    return send_from_directory(SAVE_DIR, safe, as_attachment=True)


@app.get("/health")
def health():
    return {"ok": True, "received": count}, 200


@app.get("/")
def index():
    files = []
    for p in sorted(SAVE_DIR.iterdir(), reverse=True):
        if p.is_file():
            stat = p.stat()
            size = stat.st_size
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MB"
            files.append((p.name, size_str))

    rows = ""
    for name, size in files:
        rows += f'<tr><td><a href="/download/{name}">{name}</a></td><td>{size}</td></tr>\n'

    if not rows:
        rows = '<tr><td colspan="2" style="text-align:center;color:#888">No backups yet</td></tr>'

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Backups</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 700px; margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.4rem; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #ddd; }}
  th {{ font-size: 0.85rem; color: #666; text-transform: uppercase; }}
  a {{ color: #2563eb; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .count {{ color: #888; font-size: 0.9rem; }}
</style>
</head>
<body>
<h1>Backup Archive <span class="count">({len(files)} file{"s" if len(files) != 1 else ""})</span></h1>
<table>
<tr><th>Filename</th><th>Size</th></tr>
{rows}
</table>
</body>
</html>"""


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8787)
