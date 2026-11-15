# receiver.py
from flask import Flask, request
from datetime import datetime, timezone
from pathlib import Path

app = Flask(__name__)

SAVE_DIR = Path("received")
SAVE_DIR.mkdir(exist_ok=True)
count = 0

@app.post("/hook")
def hook():
    global count
    count += 1

    body = request.get_data()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
    (SAVE_DIR / f"{ts}.bin").write_bytes(body)

    # show what came in
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = repr(body)  # binary payload, show raw

    print(f"\n--- #{count}  [{ts}]  {len(body)} bytes from {request.remote_addr} ---")
    print(text)
    print("-" * 50)

    return {"ok": True, "count": count, "bytes": len(body)}, 200

@app.get("/health")
def health():
    return {"ok": True, "received": count}, 200

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8787)
