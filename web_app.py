"""
MLBB Device ID Checker — Web App v2 (PostgreSQL / psycopg 3)
Auth + credits + captcha + job persistence + admin panel.
"""
from __future__ import annotations
import os, time, threading, uuid, secrets, json, re, random
from datetime import datetime
from functools import wraps
from io import BytesIO
from typing import Any, Dict, List, Optional

import psycopg
from psycopg.rows import dict_row

from flask import (Flask, render_template, request, jsonify, send_file, session)
from werkzeug.security import generate_password_hash, check_password_hash

from checker_core import (
    check_device_id, check_ban_only, kick_device,
    generate_device_ids, read_ids_from_text, save_line, save_ban_line,
)

# ═════════════════════════════════════════════════════════════
# APP INIT
# ═════════════════════════════════════════════════════════════
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["JSON_SORT_KEYS"] = False

# Railway Postgres URL
DATABASE_URL = os.environ.get("DATABASE_URL", "")

def _norm_pg_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url

if DATABASE_URL:
    DATABASE_URL = _norm_pg_url(DATABASE_URL)

# Session secret
def _load_or_create_secret() -> str:
    env = os.environ.get("SECRET_KEY")
    if env and len(env) >= 32:
        return env
    return secrets.token_hex(32)

app.secret_key = _load_or_create_secret()

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_NAME="mlbb_session",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14,
)

ADMIN_PASSWORD   = "Adrian@103"
FREE_CREDITS     = 50
MAX_IDS_PER_JOB  = 5000
KICK_CREDIT_COST = 5

# ═════════════════════════════════════════════════════════════
# DB (PostgreSQL / psycopg 3)
# ═════════════════════════════════════════════════════════════
def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)

def init_db():
    if not DATABASE_URL:
        print("[WARN] DATABASE_URL missing — skipping init_db()")
        return
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id              SERIAL PRIMARY KEY,
        username        TEXT UNIQUE NOT NULL,
        password_hash   TEXT NOT NULL,
        credits         INTEGER DEFAULT 50,
        is_admin        INTEGER DEFAULT 0,
        is_banned       INTEGER DEFAULT 0,
        created_at      INTEGER,
        last_login      INTEGER
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id              TEXT PRIMARY KEY,
        user_id         INTEGER,
        kind            TEXT,
        total           INTEGER,
        checked         INTEGER DEFAULT 0,
        registered      INTEGER DEFAULT 0,
        unregistered    INTEGER DEFAULT 0,
        invalid         INTEGER DEFAULT 0,
        valid           INTEGER DEFAULT 0,
        banned          INTEGER DEFAULT 0,
        clean           INTEGER DEFAULT 0,
        stopped         INTEGER DEFAULT 0,
        done            INTEGER DEFAULT 0,
        started         INTEGER,
        finished        INTEGER,
        latest          TEXT DEFAULT '[]',
        results         TEXT DEFAULT '[]'
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS credit_log (
        id              SERIAL PRIMARY KEY,
        user_id         INTEGER,
        amount          INTEGER,
        reason          TEXT,
        created_at      INTEGER
    );
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

# ═════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════
def user_row_to_dict(row):
    if not row: return None
    return {
        "id": row["id"], "username": row["username"], "credits": row["credits"],
        "is_admin": bool(row["is_admin"]), "is_banned": bool(row["is_banned"]),
        "created_at": row["created_at"], "last_login": row["last_login"],
    }

def current_user():
    uid = session.get("user_id")
    if not uid: return None
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (uid,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row or row["is_banned"]:
        session.clear()
        return None
    return user_row_to_dict(row)

def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not current_user():
            return jsonify({"ok": False, "error": "not_logged_in"}), 401
        return f(*a, **k)
    return w

def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        u = current_user()
        if not u: return jsonify({"ok": False, "error": "not_logged_in"}), 401
        if not u.get("is_admin"): return jsonify({"ok": False, "error": "admin_only"}), 403
        return f(*a, **k)
    return w

# ─── Captcha ─────────────────────────────────────────────
def make_captcha() -> str:
    a, b = random.randint(2, 9), random.randint(2, 9)
    op = random.choice(["+", "-", "*"])
    if op == "+":
        ans = a + b
    elif op == "-":
        a, b = max(a, b), min(a, b); ans = a - b
    else:
        ans = a * b
    session["captcha_answer"] = str(ans)
    session["captcha_time"] = time.time()
    return f"{a} {op} {b}"

def verify_captcha(u: str) -> bool:
    stored = session.get("captcha_answer")
    ts = session.get("captcha_time", 0)
    if not stored or time.time() - ts > 600: return False
    session.pop("captcha_answer", None)
    return str(u).strip() == str(stored)

# ─── Rate limit ──────────────────────────────────────────
RATE_LOCK = threading.Lock()
RATE_BUCKETS: Dict[str, List[float]] = {}

def rate_check(ip: str, bucket: str, max_hits: int, window: float) -> bool:
    key = f"{bucket}:{ip}"
    now = time.time()
    with RATE_LOCK:
        hits = [t for t in RATE_BUCKETS.get(key, []) if now - t < window]
        if len(hits) >= max_hits:
            RATE_BUCKETS[key] = hits
            return False
        hits.append(now)
        RATE_BUCKETS[key] = hits
    return True

def client_ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd: return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"

# ═════════════════════════════════════════════════════════════
# JOBS
# ═════════════════════════════════════════════════════════════
JOBS_LOCK = threading.Lock()
JOBS_CACHE: Dict[str, Dict[str, Any]] = {}

def _row_to_job(row):
    return {
        "id": row["id"], "user_id": row["user_id"], "kind": row["kind"],
        "total": row["total"], "checked": row["checked"],
        "registered": row["registered"], "unregistered": row["unregistered"],
        "invalid": row["invalid"], "valid": row["valid"],
        "banned": row["banned"], "clean": row["clean"],
        "stopped": bool(row["stopped"]), "done": bool(row["done"]),
        "started": row["started"], "finished": row["finished"],
        "latest": json.loads(row["latest"] or "[]"),
        "results": json.loads(row["results"] or "[]"),
    }

def _save_job(job):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO jobs (id,user_id,kind,total,checked,registered,unregistered,
                              invalid,valid,banned,clean,stopped,done,started,
                              finished,latest,results)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                checked=EXCLUDED.checked,
                registered=EXCLUDED.registered,
                unregistered=EXCLUDED.unregistered,
                invalid=EXCLUDED.invalid,
                valid=EXCLUDED.valid,
                banned=EXCLUDED.banned,
                clean=EXCLUDED.clean,
                stopped=EXCLUDED.stopped,
                done=EXCLUDED.done,
                finished=EXCLUDED.finished,
                latest=EXCLUDED.latest,
                results=EXCLUDED.results
        """, (
            job["id"], job["user_id"], job["kind"], job["total"], job["checked"],
            job["registered"], job["unregistered"], job["invalid"], job["valid"],
            job["banned"], job["clean"], int(job["stopped"]), int(job["done"]),
            job["started"], job["finished"],
            json.dumps(job["latest"][-30:]),
            json.dumps(job["results"][-500:]),
        ))
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        print("[save_job error]", e)

def new_job(user_id, kind, total) -> Dict[str, Any]:
    jid = uuid.uuid4().hex[:12]
    job = {
        "id": jid, "user_id": user_id, "kind": kind, "total": total,
        "checked": 0, "registered": 0, "unregistered": 0, "invalid": 0,
        "valid": 0, "banned": 0, "clean": 0, "stopped": False, "done": False,
        "started": int(time.time()), "finished": 0,
        "latest": [], "results": [],
    }
    with JOBS_LOCK:
        JOBS_CACHE[jid] = job
    _save_job(job)
    return job

def job_snapshot(jid):
    with JOBS_LOCK:
        job = JOBS_CACHE.get(jid)
    if not job:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM jobs WHERE id = %s", (jid,))
        row = cur.fetchone()
        cur.close(); conn.close()
        if not row: return None
        job = _row_to_job(row)
        with JOBS_LOCK:
            JOBS_CACHE[jid] = job
    snap = dict(job)
    snap["elapsed"] = (job["finished"] or time.time()) - job["started"]
    snap["pct"] = (job["checked"] / job["total"] * 100.0) if job["total"] else 0.0
    return snap

# ═════════════════════════════════════════════════════════════
# BULK WORKERS
# ═════════════════════════════════════════════════════════════
def _run_bulk_check(jid, device_ids, threads):
    import concurrent.futures as cf

    def one(did):
        with JOBS_LOCK:
            j = JOBS_CACHE.get(jid)
            if not j or j["stopped"]: return
        try:
            res = check_device_id(did)
        except Exception as e:
            res = {"status": "error", "device_id": did, "error": str(e)}

        upd = {"state": None, "info": {}, "line": None}
        if res.get("status") == "success":
            p = res["player_data"]; upd["state"] = "registered"
            try: lvl = int(p.get("level", 0))
            except Exception: lvl = 0
            if lvl < 9:
                upd["info"] = {"state": "filtered", "level": lvl}
            else:
                upd["info"] = {"state": "valid", "nickname": p.get("nickname"),
                               "level": lvl, "rank": p.get("current_rank"),
                               "skins": p.get("skin_count")}
                upd["line"] = save_line(did, p)
        else:
            err = str(res.get("error", "unknown")); low = err.lower()
            if "no account data" in low or "guest" in low or "unregistered" in low:
                upd["state"] = "unregistered"
            else:
                upd["state"] = "invalid"
            upd["info"] = {"state": upd["state"], "error": err}

        with JOBS_LOCK:
            j = JOBS_CACHE.get(jid)
            if not j: return
            j["checked"] += 1
            st = upd["state"]
            if st == "registered":
                j["registered"] += 1
                if upd["info"].get("state") == "valid":
                    j["valid"] += 1
                    if upd["line"]:
                        j["results"] = (j["results"] + [upd["line"]])[-500:]
                j["latest"] = (j["latest"] + [{"device_id": did, **upd["info"]}])[-30:]
            elif st == "unregistered":
                j["unregistered"] += 1
                j["latest"] = (j["latest"] + [{"device_id": did, **upd["info"]}])[-30:]
            else:
                j["invalid"] += 1
                j["latest"] = (j["latest"] + [{"device_id": did, **upd["info"]}])[-30:]

    try:
        with cf.ThreadPoolExecutor(max_workers=threads) as ex:
            list(ex.map(one, device_ids))
    finally:
        with JOBS_LOCK:
            j = JOBS_CACHE.get(jid)
            if j:
                j["done"] = True
                j["finished"] = int(time.time())
                _save_job(j)

def _run_bulk_ban(jid, device_ids, threads):
    import concurrent.futures as cf

    def one(did):
        with JOBS_LOCK:
            j = JOBS_CACHE.get(jid)
            if not j or j["stopped"]: return
        try:
            res = check_ban_only(did)
        except Exception as e:
            res = {"status": "error", "device_id": did, "error": str(e),
                   "ban": {"banned": False, "state": "unknown", "label": str(e)}}

        upd = {"state": None, "info": {}, "line": None}
        if res.get("status") == "success":
            ban = res["ban"]; state = ban.get("state", "clear")
            upd["state"] = state
            upd["line"] = save_ban_line(did, ban)
            if state == "banned":
                upd["info"] = {"state": "banned", "reason": ban.get("reason"),
                               "remaining": ban.get("remaining")}
            elif state == "unknown":
                upd["info"] = {"state": "unknown", "error": ban.get("label", "unknown")}
            elif state == "unregistered":
                upd["info"] = {"state": "unregistered"}
            else:
                upd["info"] = {"state": "clean"}
        else:
            upd["state"] = "invalid"
            upd["info"] = {"state": "invalid", "error": res.get("error")}
            upd["line"] = f"{did} | FAILED | {res.get('error','?')}"

        with JOBS_LOCK:
            j = JOBS_CACHE.get(jid)
            if not j: return
            j["checked"] += 1
            st = upd["state"]
            if st == "banned":
                j["banned"] += 1; j["valid"] += 1
                if upd["line"]:
                    j["results"] = (j["results"] + [upd["line"]])[-500:]
            elif st == "clean":
                j["clean"] += 1; j["valid"] += 1
                if upd["line"]:
                    j["results"] = (j["results"] + [upd["line"]])[-500:]
            elif st in ("unknown", "unregistered"):
                j["unregistered"] += 1
                if upd["line"]:
                    j["results"] = (j["results"] + [upd["line"]])[-500:]
            else:
                j["invalid"] += 1
                if upd["line"]:
                    j["results"] = (j["results"] + [upd["line"]])[-500:]
            j["latest"] = (j["latest"] + [{"device_id": did, **upd["info"]}])[-30:]

    try:
        with cf.ThreadPoolExecutor(max_workers=threads) as ex:
            list(ex.map(one, device_ids))
    finally:
        with JOBS_LOCK:
            j = JOBS_CACHE.get(jid)
            if j:
                j["done"] = True
                j["finished"] = int(time.time())
                _save_job(j)

def _persist_loop():
    while True:
        time.sleep(3)
        with JOBS_LOCK:
            jids = [j["id"] for j in JOBS_CACHE.values() if not j["done"]]
        for jid in jids:
            with JOBS_LOCK:
                job = JOBS_CACHE.get(jid)
                if job and not job["done"]:
                    _save_job(job)

threading.Thread(target=_persist_loop, daemon=True).start()

# ═════════════════════════════════════════════════════════════
# CREDITS
# ═════════════════════════════════════════════════════════════
CREDIT_LOCK = threading.Lock()

def spend_credits(user_id, amount, reason) -> bool:
    with CREDIT_LOCK:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT credits FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if not row or row["credits"] < amount:
            cur.close(); conn.close()
            return False
        cur.execute("UPDATE users SET credits = credits - %s WHERE id = %s",
                    (amount, user_id))
        cur.execute("""INSERT INTO credit_log (user_id, amount, reason, created_at)
                       VALUES (%s,%s,%s,%s)""",
                    (user_id, -amount, reason, int(time.time())))
        conn.commit()
        cur.close(); conn.close()
    return True

def add_credits(user_id, amount, reason):
    with CREDIT_LOCK:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE users SET credits = credits + %s WHERE id = %s",
                    (amount, user_id))
        cur.execute("""INSERT INTO credit_log (user_id, amount, reason, created_at)
                       VALUES (%s,%s,%s,%s)""",
                    (user_id, amount, reason, int(time.time())))
        conn.commit()
        cur.close(); conn.close()

# ═════════════════════════════════════════════════════════════
# AUTH ROUTES
# ═════════════════════════════════════════════════════════════
@app.route("/api/captcha")
def api_captcha():
    if not rate_check(client_ip(), "captcha", 30, 60):
        return jsonify({"ok": False, "error": "rate_limited"}), 429
    return jsonify({"ok": True, "question": make_captcha()})

@app.route("/api/auth/signup", methods=["POST"])
def api_signup():
    if not rate_check(client_ip(), "signup", 5, 3600):
        return jsonify({"ok": False, "error": "Too many signups — try later"}), 429
    d = request.get_json(force=True) or {}
    username = (d.get("username") or "").strip()
    password = (d.get("password") or "").strip()
    captcha  = (d.get("captcha") or "").strip()

    if not re.match(r"^[A-Za-z0-9_]{3,20}$", username):
        return jsonify({"ok": False, "error": "Username must be 3–20 alnum/_"}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "error": "Password min 6 characters"}), 400
    if not verify_captcha(captcha):
        return jsonify({"ok": False, "error": "Wrong captcha answer"}), 400

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""INSERT INTO users (username, password_hash, credits, created_at)
                       VALUES (%s,%s,%s,%s) RETURNING id""",
                    (username, generate_password_hash(password),
                     FREE_CREDITS, int(time.time())))
        uid = cur.fetchone()["id"]
        cur.execute("""INSERT INTO credit_log (user_id, amount, reason, created_at)
                       VALUES (%s,%s,%s,%s)""",
                    (uid, FREE_CREDITS, "welcome_bonus", int(time.time())))
        conn.commit()
    except psycopg.IntegrityError:
        conn.rollback()
        cur.close(); conn.close()
        return jsonify({"ok": False, "error": "Username already taken"}), 400
    cur.close(); conn.close()

    session.permanent = True
    session["user_id"] = uid
    return jsonify({"ok": True, "user": {"id": uid, "username": username,
                                          "credits": FREE_CREDITS, "is_admin": False}})

@app.route("/api/auth/login", methods=["POST"])
def api_login():
    if not rate_check(client_ip(), "login", 10, 300):
        return jsonify({"ok": False, "error": "Too many attempts — wait 5 min"}), 429
    d = request.get_json(force=True) or {}
    username = (d.get("username") or "").strip()
    password = (d.get("password") or "")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = %s", (username,))
    row = cur.fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        cur.close(); conn.close()
        return jsonify({"ok": False, "error": "Invalid username or password"}), 401
    if row["is_banned"]:
        cur.close(); conn.close()
        return jsonify({"ok": False, "error": "Account is banned"}), 403
    cur.execute("UPDATE users SET last_login = %s WHERE id = %s",
                (int(time.time()), row["id"]))
    conn.commit()
    cur.close(); conn.close()

    session.permanent = True
    session["user_id"] = row["id"]
    return jsonify({"ok": True, "user": user_row_to_dict(row)})

@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/auth/me")
def api_me():
    u = current_user()
    return jsonify({"ok": True, "user": u})

# ═════════════════════════════════════════════════════════════
# CHECK ROUTES
# ═════════════════════════════════════════════════════════════
@app.route("/api/check/single", methods=["POST"])
@login_required
def api_check_single():
    u = current_user()
    d = request.get_json(force=True) or {}
    did = (d.get("device_id") or "").strip()
    if not did: return jsonify({"ok": False, "error": "Missing device_id"}), 400
    if not spend_credits(u["id"], 1, f"check:{did[-8:]}"):
        return jsonify({"ok": False, "error": "Not enough credits"}), 402
    return jsonify({"ok": True, "result": check_device_id(did)})

@app.route("/api/ban/single", methods=["POST"])
@login_required
def api_ban_single():
    u = current_user()
    d = request.get_json(force=True) or {}
    did = (d.get("device_id") or "").strip()
    if not did: return jsonify({"ok": False, "error": "Missing device_id"}), 400
    if not spend_credits(u["id"], 1, f"ban:{did[-8:]}"):
        return jsonify({"ok": False, "error": "Not enough credits"}), 402
    return jsonify({"ok": True, "result": check_ban_only(did)})

@app.route("/api/generate", methods=["POST"])
@login_required
def api_generate():
    d = request.get_json(force=True) or {}
    try:
        count = int(d.get("count") or 10)
    except Exception:
        return jsonify({"ok": False, "error": "Invalid count"}), 400
    count = max(1, min(count, 10000))
    return jsonify({"ok": True, "count": count, "ids": generate_device_ids(count)})

@app.route("/api/bulk/start", methods=["POST"])
@login_required
def api_bulk_start():
    u = current_user()
    d = request.get_json(force=True) or {}
    kind = d.get("kind") or "check"
    text = d.get("ids") or ""
    threads = max(1, min(int(d.get("threads") or 30), 60))

    ids = read_ids_from_text(text)
    if not ids:
        return jsonify({"ok": False, "error": "No device IDs found"}), 400
    if len(ids) > MAX_IDS_PER_JOB:
        return jsonify({"ok": False, "error": f"Max {MAX_IDS_PER_JOB} IDs"}), 400

    if not spend_credits(u["id"], len(ids), f"bulk_{kind}"):
        return jsonify({"ok": False, "error": f"Not enough credits (need {len(ids)})"}), 402

    job = new_job(u["id"], kind, len(ids))
    target = _run_bulk_ban if kind == "ban" else _run_bulk_check
    threading.Thread(target=target, args=(job["id"], ids, threads), daemon=True).start()
    return jsonify({"ok": True, "job_id": job["id"], "total": len(ids)})

@app.route("/api/bulk/status/<jid>")
@login_required
def api_bulk_status(jid):
    u = current_user()
    snap = job_snapshot(jid)
    if not snap: return jsonify({"ok": False, "error": "unknown job"}), 404
    if snap["user_id"] != u["id"] and not u.get("is_admin"):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    return jsonify({"ok": True, "job": snap})

@app.route("/api/bulk/stop/<jid>", methods=["POST"])
@login_required
def api_bulk_stop(jid):
    u = current_user()
    with JOBS_LOCK:
        j = JOBS_CACHE.get(jid)
        if not j: return jsonify({"ok": False, "error": "unknown job"}), 404
        if j["user_id"] != u["id"] and not u.get("is_admin"):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        j["stopped"] = True
    _save_job(j)
    return jsonify({"ok": True})

@app.route("/api/bulk/download/<jid>")
@login_required
def api_bulk_download(jid):
    u = current_user()
    snap = job_snapshot(jid)
    if not snap: return jsonify({"ok": False, "error": "unknown job"}), 404
    if snap["user_id"] != u["id"] and not u.get("is_admin"):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    payload = ("\n".join(snap.get("results") or []) + "\n").encode("utf-8")
    bio = BytesIO(payload); bio.seek(0)
    return send_file(bio, as_attachment=True,
                     download_name=f"results_{jid}.txt",
                     mimetype="text/plain")

@app.route("/api/jobs/mine")
@login_required
def api_jobs_mine():
    u = current_user()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, kind, total, checked, valid, banned, clean, done, started, finished
        FROM jobs WHERE user_id = %s ORDER BY started DESC LIMIT 20
    """, (u["id"],))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify({"ok": True, "jobs": [dict(r) for r in rows]})

@app.route("/api/kick/start", methods=["POST"])
@login_required
def api_kick_start():
    u = current_user()
    d = request.get_json(force=True) or {}
    did = (d.get("device_id") or "").strip()
    if not did: return jsonify({"ok": False, "error": "Missing device_id"}), 400
    if not spend_credits(u["id"], KICK_CREDIT_COST, f"kick:{did[-8:]}"):
        return jsonify({"ok": False, "error": f"Not enough credits (need {KICK_CREDIT_COST})"}), 402

    stop_ev = threading.Event()
    stats = {"attempts": 0, "hits": 0, "fails": 0, "status": "fetching",
             "nickname": "?", "gs_info": "?", "account_id": "?", "error": ""}

    def runner():
        try:
            kick_device(did, rounds=20, delay=3.0, stop_event=stop_ev,
                        on_progress=lambda s: stats.update(s))
        except Exception as e:
            stats["status"] = "error"
            stats["error"] = str(e)

    threading.Thread(target=runner, daemon=True).start()
    return jsonify({"ok": True, "stats": stats})

@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat() + "Z"})

# ═════════════════════════════════════════════════════════════
# ADMIN
# ═════════════════════════════════════════════════════════════
@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    if not rate_check(client_ip(), "adminlogin", 5, 900):
        return jsonify({"ok": False, "error": "Too many attempts"}), 429
    u = current_user()
    if not u: return jsonify({"ok": False, "error": "not_logged_in"}), 401
    pw = (request.get_json(force=True) or {}).get("password") or ""
    if pw != ADMIN_PASSWORD:
        return jsonify({"ok": False, "error": "Wrong password"}), 401
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_admin = 1 WHERE id = %s", (u["id"],))
    conn.commit()
    cur.close(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/admin/stats")
@admin_required
def api_admin_stats():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM users")
    users = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM jobs")
    jobs_total = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM jobs WHERE done = 0")
    jobs_running = cur.fetchone()["c"]
    cur.execute("SELECT COALESCE(SUM(ABS(amount)),0) AS s FROM credit_log WHERE amount < 0")
    credits_used = cur.fetchone()["s"]
    cur.execute("SELECT COALESCE(SUM(amount),0) AS s FROM credit_log WHERE amount > 0")
    credits_added = cur.fetchone()["s"]
    cur.close(); conn.close()
    return jsonify({"ok": True, "stats": {
        "users": users, "jobs_total": jobs_total, "jobs_running": jobs_running,
        "credits_used": credits_used, "credits_added": credits_added,
    }})

@app.route("/api/admin/users")
@admin_required
def api_admin_users():
    q = (request.args.get("q") or "").strip()
    conn = get_db()
    cur = conn.cursor()
    if q:
        cur.execute("""
            SELECT id, username, credits, is_admin, is_banned, created_at, last_login
            FROM users WHERE username ILIKE %s ORDER BY id DESC LIMIT 200
        """, (f"%{q}%",))
    else:
        cur.execute("""
            SELECT id, username, credits, is_admin, is_banned, created_at, last_login
            FROM users ORDER BY id DESC LIMIT 200
        """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify({"ok": True, "users": [dict(r) for r in rows]})

@app.route("/api/admin/user/<int:uid>", methods=["POST"])
@admin_required
def api_admin_user_update(uid):
    d = request.get_json(force=True) or {}
    action = d.get("action")

    if action == "add_credits":
        amt = int(d.get("amount") or 0)
        add_credits(uid, amt, "admin_add")
        return jsonify({"ok": True})

    conn = get_db()
    cur = conn.cursor()
    if action == "ban":
        cur.execute("UPDATE users SET is_banned = 1 WHERE id = %s", (uid,))
    elif action == "unban":
        cur.execute("UPDATE users SET is_banned = 0 WHERE id = %s", (uid,))
    elif action == "make_admin":
        cur.execute("UPDATE users SET is_admin = 1 WHERE id = %s", (uid,))
    elif action == "remove_admin":
        cur.execute("UPDATE users SET is_admin = 0 WHERE id = %s", (uid,))
    elif action == "reset_password":
        newpw = str(d.get("password") or "")
        if len(newpw) < 6:
            cur.close(); conn.close()
            return jsonify({"ok": False, "error": "Password too short"}), 400
        cur.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                    (generate_password_hash(newpw), uid))
    else:
        cur.close(); conn.close()
        return jsonify({"ok": False, "error": "unknown action"}), 400
    conn.commit()
    cur.close(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/admin/jobs")
@admin_required
def api_admin_jobs():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT j.id, j.user_id, u.username, j.kind, j.total, j.checked,
               j.valid, j.banned, j.clean, j.done, j.started, j.finished
        FROM jobs j LEFT JOIN users u ON u.id = j.user_id
        ORDER BY j.started DESC LIMIT 100
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify({"ok": True, "jobs": [dict(r) for r in rows]})

# ═════════════════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)