"""Test the real async video integration (Veo) end-to-end via the movie server.

Reuses a project that already has a keyframed shot (run test_local.py first), starts an
image-to-video job from the keyframe, and polls it BY NAME (stateless) until done.

Run:  cd movie && GOOGLE_CLOUD_PROJECT=<proj> uv run python test_video.py
"""

from __future__ import annotations

import time

import movie_server as m
import movie_store as store

U = "creator1"

projs = store.list_projects(U)
assert projs, "no projects — run test_local.py first to create one with keyframes"

# pick the most recent project that has a keyframed shot
pid = None
sid = None
for p in reversed(projs):
    b = store.get_project(U, p["project_id"])
    kf = next((s for s in b["shots"] if s.get("keyframe_uri")), None)
    if kf:
        pid, sid = p["project_id"], kf["shot_id"]
        break
assert pid, "no keyframed shot found — run test_local.py first"

b = store.get_project(U, pid)
shot = next(s for s in b["shots"] if s["shot_id"] == sid)
print(f"== starting async video: project {pid}, shot {sid} ==")
print("   from keyframe:", shot["keyframe_uri"])

start = m.mv_start_shot_video(U, pid, sid, model="veo-3.1-fast-generate-001", duration_seconds=6)
job = start["job_name"]
print("   job handle (upstream, stateless):", job)
print("   backend:", start["backend"], "status:", start["status"])

print("== polling by name (server holds no state) ==")
final = None
for i in range(30):  # up to ~6 min
    time.sleep(12)
    st = m.mv_get_shot_video(U, pid, sid)
    print(f"   poll {i}: {st['status']}")
    if st["status"] in ("done", "error"):
        final = st
        break

assert final and final["status"] == "done", f"video did not finish: {final}"
print("\nVIDEO DONE ✅")
print("   video_uri:", final.get("video_uri"))
print("   size_bytes:", final.get("size_bytes"))

# confirm the bible recorded it (durable state, not server memory)
b2 = store.get_project(U, pid)
s2 = next(s for s in b2["shots"] if s["shot_id"] == sid)
print("   bible status:", s2["status"], "| bible video_uri:", s2.get("video_uri"))
assert s2["status"] == "video_done" and s2.get("video_uri"), "bible not updated"
print("\nASYNC VEO INTEGRATION TEST PASSED ✅")
