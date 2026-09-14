from pathlib import Path
import time

from fastapi.testclient import TestClient

from app.main import app

examples = Path(r"C:\Users\120ch\Cursor Projects\EQ Gear Management\Examples")
inv = next(examples.glob("*-Inventory.txt"))
client = TestClient(app)
r = client.get("/api/health")
print("health", r.status_code, r.json())
r = client.get("/api/version")
print("version", r.status_code, r.json().get("version"))
files = [("files", (inv.name, inv.read_bytes(), "text/plain"))]
r = client.post("/api/upload", files=files)
print("upload", r.status_code)
data = r.json()
print("session", data.get("sessionId"), "choices", len(data.get("choices", [])))
assert r.status_code == 200 and data["choices"]
session = data["sessionId"]
paths = data["choices"][0]["paths"]
r = client.post(
    "/api/generate",
    headers={"X-EQGM-Session": session},
    json={
        "paths": paths,
        "includeSpells": False,
        "includeAchievements": False,
        "includeSlot2": False,
        "includeType5": False,
        "includeType18": False,
        "includeRaidBis": False,
    },
)
print("generate", r.status_code, r.json())
job_id = r.json()["jobId"]
for _ in range(60):
    s = client.get(f"/api/jobs/{job_id}").json()
    print("status", s["status"], s.get("progress"))
    if s["status"] in ("done", "error"):
        print("result", s.get("result"))
        break
    time.sleep(1)
else:
    raise SystemExit("timeout")
if s["status"] == "done":
    dl = client.get(f"/api/jobs/{job_id}/download/html")
    print("download", dl.status_code, len(dl.content))
    assert dl.status_code == 200 and len(dl.content) > 100
print("SMOKE OK")
