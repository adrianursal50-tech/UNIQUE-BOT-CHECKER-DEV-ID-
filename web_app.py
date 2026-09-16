"""
MLBB Device ID Checker — Web App (Railway-ready)
"""
from __future__ import annotations
import os, json, time, threading, uuid
from datetime import datetime
from typing import Any, Dict, List
from flask import Flask, render_template, request, jsonify, send_file
from io import BytesIO

from checker_core import (
    check_device_id, check_ban_only, kick_device,
    generate_device_ids, read_ids_from_text, save_line, save_ban_line,
)

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["JSON_SORT_KEYS"] = False

# -------------------------------------------------------------------
# In-memory job registry (bulk operations)
# -------------------------------------------------------------------
JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()

def _new_job(kind: str, total: int) -> Dict[str, Any]:
    jid = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[jid] = {
            "id": jid, "kind": kind, "total": total, "checked": 0,
            "registered": 0, "unregistered": 0, "invalid": 0,
            "valid": 0, "banned": 0, "clean": 0,
            "stopped": False, "done": False,
            "started": time.time(), "finished": 0.0,
            "results": [], "latest": [],
        }
    return JOBS[jid]

def _job_snapshot(jid: str) -> Dict[str, Any]:
    with JOBS_LOCK:
        j = JOBS.get(jid)
        if not j:
            return {"error": "unknown job"}
        snap = dict(j)
        snap["elapsed"] = (j["finished"] or time.time()) - j["started"]
        snap["pct"] = (j["checked"] / j["total"] * 100.0) if j["total"] else 0.0
        snap["results"] = j["results"][-50:]
        snap["latest"] = j["latest"][-10:]
        return snap

# -------------------------------------------------------------------
# Background workers
# -------------------------------------------------------------------
def _run_bulk_check(jid: str, device_ids: List[str], threads: int):
    import concurrent.futures as cf
    job = JOBS[jid]

    def one(did: str):
        if job["stopped"]:
            return None
        try:
            res = check_device_id(did)
        except Exception as e:
            res = {"status": "error", "device_id": did, "error": str(e)}

        with JOBS_LOCK:
            job["checked"] += 1
            if res.get("status") == "success":
                p = res["player_data"]
                job["registered"] += 1
                try:
                    lvl = int(p.get("level", 0))
                except Exception:
                    lvl = 0
                if lvl < 9:
                    job["latest"].append({"device_id": did, "state": "filtered", "level": lvl})
                else:
                    job["valid"] += 1
                    job["results"].append(save_line(did, p))
                    job["latest"].append({
                        "device_id": did, "state": "valid",
                        "nickname": p.get("nickname"),
                        "level": lvl,
                        "rank": p.get("current_rank"),
                        "skins": p.get("skin_count"),
                    })
            else:
                err = str(res.get("error", "unknown"))
                low = err.lower()
                if "no account data" in low or "guest" in low or "unregistered" in low:
                    job["unregistered"] += 1
                    job["latest"].append({"device_id": did, "state": "unregistered", "error": err})
                else:
                    job["invalid"] += 1
                    job["latest"].append({"device_id": did, "state": "invalid", "error": err})
        return res

    try:
        with cf.ThreadPoolExecutor(max_workers=threads) as ex:
            list(ex.map(one, device_ids))
    finally:
        with JOBS_LOCK:
            job["done"] = True
            job["finished"] = time.time()


def _run_bulk_ban(jid: str, device_ids: List[str], threads: int):
    import concurrent.futures as cf
    job = JOBS[jid]

    def one(did: str):
        if job["stopped"]:
            return None
        try:
            res = check_ban_only(did)
        except Exception as e:
            res = {"status": "error", "device_id": did, "error": str(e),
                   "ban": {"banned": False, "state": "unknown", "label": str(e)}}

        with JOBS_LOCK:
            job["checked"] += 1
            if res.get("status") == "success":
                ban = res["ban"]
                state = ban.get("state", "clear")
                if state == "banned":
                    job["banned"] += 1
                    job["valid"] += 1
                    job["results"].append(save_ban_line(did, ban))
                    job["latest"].append({"device_id": did, "state": "banned",
                                          "reason": ban.get("reason"),
                                          "remaining": ban.get("remaining")})
                elif state == "unknown":
                    job["unregistered"] += 1
                    job["results"].append(save_ban_line(did, ban))
                    job["latest"].append({"device_id": did, "state": "unknown",
                                          "error": ban.get("label", "unknown")})
                elif state == "unregistered":
                    job["unregistered"] += 1
                    job["results"].append(save_ban_line(did, ban))
                    job["latest"].append({"device_id": did, "state": "unregistered"})
                else:
                    job["clean"] += 1
                    job["valid"] += 1
                    job["results"].append(save_ban_line(did, ban))
                    job["latest"].append({"device_id": did, "state": "clean"})
            else:
                job["invalid"] += 1
                job["results"].append(f"{did} | FAILED | {res.get('error','?')}")
                job["latest"].append({"device_id": did, "state": "invalid",
                                      "error": res.get("error")})
        return res

    try:
        with cf.ThreadPoolExecutor(max_workers=threads) as ex:
            list(ex.map(one, device_ids))
    finally:
        with JOBS_LOCK:
            job["done"] = True
            job["finished"] = time.time()

# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/check/single", methods=["POST"])
def api_check_single():
    data = request.get_json(force=True) or {}
    did = (data.get("device_id") or "").strip()
    if not did:
        return jsonify({"ok": False, "error": "Missing device_id"}), 400
    res = check_device_id(did)
    return jsonify({"ok": True, "result": res})

@app.route("/api/ban/single", methods=["POST"])
def api_ban_single():
    data = request.get_json(force=True) or {}
    did = (data.get("device_id") or "").strip()
    if not did:
        return jsonify({"ok": False, "error": "Missing device_id"}), 400
    res = check_ban_only(did)
    return jsonify({"ok": True, "result": res})

@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json(force=True) or {}
    try:
        count = int(data.get("count") or 10)
    except Exception:
        return jsonify({"ok": False, "error": "Invalid count"}), 400
    count = max(1, min(count, 10000))
    ids = generate_device_ids(count)
    return jsonify({"ok": True, "count": len(ids), "ids": ids})

@app.route("/api/bulk/start", methods=["POST"])
def api_bulk_start():
    data = request.get_json(force=True) or {}
    kind = data.get("kind") or "check"
    text = data.get("ids") or ""
    threads = int(data.get("threads") or 30)
    threads = max(1, min(threads, 60))

    ids = read_ids_from_text(text)
    if not ids:
        return jsonify({"ok": False, "error": "No device IDs found"}), 400
    if len(ids) > 5000:
        return jsonify({"ok": False, "error": "Max 5000 IDs per job"}), 400

    job = _new_job(kind, len(ids))
    if kind == "ban":
        t = threading.Thread(target=_run_bulk_ban, args=(job["id"], ids, threads), daemon=True)
    else:
        t = threading.Thread(target=_run_bulk_check, args=(job["id"], ids, threads), daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job["id"], "total": len(ids)})

@app.route("/api/bulk/status/<jid>")
def api_bulk_status(jid):
    return jsonify({"ok": True, "job": _job_snapshot(jid)})

@app.route("/api/bulk/stop/<jid>", methods=["POST"])
def api_bulk_stop(jid):
    with JOBS_LOCK:
        j = JOBS.get(jid)
        if not j:
            return jsonify({"ok": False, "error": "unknown job"}), 404
        j["stopped"] = True
    return jsonify({"ok": True})

@app.route("/api/bulk/download/<jid>")
def api_bulk_download(jid):
    with JOBS_LOCK:
        j = JOBS.get(jid)
        if not j:
            return jsonify({"ok": False, "error": "unknown job"}), 404
        lines = list(j["results"])
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    bio = BytesIO(payload)
    bio.seek(0)
    return send_file(bio, as_attachment=True, download_name=f"results_{jid}.txt",
                     mimetype="text/plain")

@app.route("/api/kick/start", methods=["POST"])
def api_kick_start():
    data = request.get_json(force=True) or {}
    did = (data.get("device_id") or "").strip()
    if not did:
        return jsonify({"ok": False, "error": "Missing device_id"}), 400
    stop_event = threading.Event()
    stats: Dict[str, Any] = {"attempts": 0, "hits": 0, "fails": 0,
                             "status": "fetching", "nickname": "?", "gs_info": "?",
                             "account_id": "?", "error": ""}

    def on_prog(s):
        stats.update(s)

    def runner():
        try:
            kick_device(did, rounds=0, delay=3.0, stop_event=stop_event, on_progress=on_prog)
        except Exception as e:
            stats["status"] = "error"
            stats["error"] = str(e)

    threading.Thread(target=runner, daemon=True).start()
    return jsonify({"ok": True, "stats": stats, "stop": stop_event.is_set()})

@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat() + "Z"})

# -------------------------------------------------------------------
# Local run (Railway uses gunicorn via Procfile)
# -------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)