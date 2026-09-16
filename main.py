"""
MLBB Device ID Checker — Telegram Bot
Rich player card + separate ban check + BF kicker + live stats.
"""
from __future__ import annotations
import asyncio, html, io, logging, os, secrets, sqlite3, string, threading, time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton, BotCommand, BotCommandScopeDefault, BufferedInputFile)

from checker_core import (
    check_device_id, check_ban_only,
    fetch_session_profile, kick_device,
    generate_device_ids, read_ids_from_text, save_line, save_ban_line,
)

BOT_TOKEN      = os.environ.get("BOT_TOKEN", "8702549007:AAHe3d-RSBaYs4wX4D4x4rkLpevipByEPqs").strip()
ADMIN_IDS      = [int(x) for x in os.environ.get("ADMIN_IDS", "8621676055").split(",") if x.strip().isdigit()]
DB_PATH        = os.environ.get("DB_PATH", "bot.db")
BULK_THREADS   = int(os.environ.get("BULK_THREADS", "30"))
KICK_DELAY     = float(os.environ.get("KICK_DELAY", "3.0"))
KICK_ROUNDS    = int(os.environ.get("KICK_ROUNDS", "0"))
UPDATE_INTERVAL = float(os.environ.get("UPDATE_INTERVAL", "2.0"))
BRAND          = os.environ.get("BRAND", "@SHINRT771")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("mlbb-bot")
if not BOT_TOKEN: raise SystemExit("Set BOT_TOKEN env var")

LINE_HEAVY = "━" * 28
LINE_DOT   = "┈" * 28

# ============== KICK REGISTRY ==============
kick_jobs: Dict[int, Dict[str, Any]] = {}
kick_lock = threading.Lock()

def _fmt_secs(s) -> str:
    s = int(max(0, s))
    if s < 60: return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60: return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m {s}s"

def kick_status_text(uid: int) -> str:
    with kick_lock: job = kick_jobs.get(uid)
    if not job:
        return "📭 <b>No active kick job.</b>\n<i>Use /kick &lt;device_id&gt; to start.</i>"
    s = job["stats"]
    elapsed = time.time() - job["started"]
    rounds_txt = "∞" if job["rounds"] == 0 else str(job["rounds"])
    pct = (s["attempts"] / job["rounds"] * 100) if job["rounds"] > 0 else 0.0
    bar_w = 20; filled = int(bar_w * pct / 100) if pct else 0
    bar = "▓" * filled + "░" * (bar_w - filled)
    status = "🟢 RUNNING"
    if job.get("done"): status = "✅ FINISHED"
    elif s.get("status") == "fetching": status = "🔍 FETCHING PROFILE"
    elif s.get("status") == "error": status = "❌ ERROR"
    elif job.get("stop_event") and job["stop_event"].is_set() and not job.get("done"): status = "🛑 STOPPING"
    err = s.get("error"); err_line = f"\n┣ ⚠️ Error  : <i>{html.escape(err[:60])}</i>" if err else ""
    return (
        f"⚡ <b>BRUTEFORCE KICKER</b> — {status}\n{LINE_HEAVY}\n"
        f"┣ 🆔 Device   : <code>…{html.escape(job['device_id'][-12:])}</code>\n"
        f"┣ 👤 Target   : <b>{html.escape(str(s.get('nickname','?'))[:20])}</b>\n"
        f"┣ 🎮 Acc ID   : <code>{html.escape(str(s.get('account_id','?')))}</code>\n"
        f"┣ 🌐 GameSrv  : <code>{html.escape(str(s.get('gs_info','?')))}</code>\n"
        f"┣ 🔄 Attempts : <b>{s['attempts']}</b> / {rounds_txt}\n"
        f"┣ ✅ Hits     : <b>{s['hits']}</b>\n┣ ❌ Fails    : <b>{s['fails']}</b>\n"
        f"┣ ⚡ Avg Lat  : <b>{s.get('avg_latency',0):.0f}ms</b>{err_line}\n"
        f"┣ ⏱ Elapsed  : <b>{_fmt_secs(elapsed)}</b>\n"
        f"┣ ⏳ Delay    : <b>{KICK_DELAY:.1f}s</b> / attempt\n"
        f"┗ 📊 Progress : <code>{bar}</code> <b>{pct:.1f}%</b>\n"
        f"\n<i>Use /kickstatus · /kickstop</i>")

def kick_buttons(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Refresh", callback_data=f"kick:refresh:{uid}"),
         InlineKeyboardButton(text="🛑 Stop", callback_data=f"kick:stop:{uid}")]])

# ============== HELPERS ==============
def _esc(s): return html.escape(str(s if s not in (None, "") else "N/A"))

def classify_error(err: str) -> str:
    e = (err or "").lower()
    if "no account data returned" in e: return "unregistered"
    if "guest" in e or "unregistered" in e: return "unregistered"
    return "invalid"

# ============== CARD ==============
def render_card(did: str, p: Dict) -> str:
    def g(k, d="N/A"): return p.get(k) if p.get(k) not in (None, "") else d

    sb = p.get("skin_breakdown") or {}
    cur = g("current_rank", "Unranked")
    high = g("high_rank")
    coll = g("collector_tier", "None")
    cpt = p.get("collector_point", 0)
    cpt_s = f"{int(cpt):,}" if isinstance(cpt, (int, float)) and cpt > 0 else "0"
    hh = p.get("hero_history") or []
    hh_s = ", ".join(hh[:5]) if hh else "N/A"
    found = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return (
        f"◇  <b>DEVICE ID CHECK RESULT</b>  ◇\n{LINE_HEAVY}\n"
        f"┣ 🆔 Device : <code>{html.escape(did)}</code>\n"
        f"┣ 🎮 Acc    : <code>{_esc(g('player_id','?'))}</code>\n"
        f"┣ 🌐 Zone   : <code>{_esc(g('server','?'))}</code>\n"
        f"┣ 🏷 Nick   : <b>{_esc(g('nickname'))}</b>\n"
        f"┣ 📈 Level  : <code>{_esc(g('level'))}</code>\n"
        f"┣ 🦸 Heroes : <code>{_esc(g('hero_count',0))}</code>\n"
        f"┗ 🎨 Skins  : <code>{_esc(g('skin_count',0))}</code>\n\n"
        f"◇  <b>RANKS</b>  ◇\n{LINE_HEAVY}\n"
        f"┣ 🏆 Current: <code>{_esc(cur)}</code>\n"
        f"┣ ⭐ High   : <code>{_esc(high)}</code>\n"
        f"┣ 💠 Collector: <code>{_esc(coll)}</code>\n"
        f"┗ 💎 Points : <code>{_esc(cpt_s)}</code>\n\n"
        f"◇  <b>SKIN BREAKDOWN</b>  ◇\n{LINE_HEAVY}\n"
        f"┣ 💎 Supreme  : <code>{sb.get('Supreme Skins',0)}</code>\n"
        f"┣ 🟣 Grand    : <code>{sb.get('Grand Skins',0)}</code>\n"
        f"┣ 🟡 Exquisite: <code>{sb.get('Exquisite Skins',0)}</code>\n"
        f"┣ 🔵 Deluxe   : <code>{sb.get('Deluxe Skins',0)}</code>\n"
        f"┣ 🟢 Exceptional: <code>{sb.get('Exceptional Skins',0)}</code>\n"
        f"┗ ⚪ Common   : <code>{sb.get('Common Skins',0)}</code>\n\n"
        f"◇  <b>ACCOUNT</b>  ◇\n{LINE_HEAVY}\n"
        f"┣ 📍 Loc    : <code>{_esc(g('location','NOT FOUND'))}</code>\n"
        f"┣ ⏰ Login  : <code>{_esc(g('last_login'))}</code>\n"
        f"┣ 📅 Created: <code>{_esc(g('creation_date'))}</code>\n"
        f"┣ ⌛ Age    : <code>{_esc(g('account_age'))}</code>\n"
        f"┣ 👥 Squad  : <code>{_esc(g('squad','—'))}</code>\n"
        f"┣ 🎯 WR     : <code>{_esc(g('win_rate'))}</code>\n"
        f"┣ ⚔ Battles: <code>{_esc(g('total_battles',0))}</code>\n"
        f"┣ 💛 Affinity: <code>{_esc(g('affinity','None'))}</code>\n"
        f"┣ ⭐ Starlight: <code>{_esc(g('starlight_user','No'))}</code>\n"
        f"┣ 🛡 Credits : <code>{_esc(g('credits_score','N/A'))}</code>\n"
        f"┣ 🚨 Flags   : <code>{_esc(g('restriction_flags','None'))}</code>\n"
        f"┗ 🦸 Recent  : <code>{_esc(hh_s)}</code>\n\n"
        f"{LINE_DOT}\n🕒 Found : <code>{found}</code>\n👑 {html.escape(BRAND)}")

# ============== STORAGE ==============
class Storage:
    def __init__(self, path):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT,
            first_name TEXT, joined_at INTEGER, is_admin INTEGER DEFAULT 0, is_banned INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS keys (key TEXT PRIMARY KEY, duration_hours INTEGER,
            max_checks INTEGER, checks_used INTEGER DEFAULT 0, created_at INTEGER,
            created_by INTEGER, activated_by INTEGER, activated_at INTEGER,
            is_active INTEGER DEFAULT 1, is_revoked INTEGER DEFAULT 0, note TEXT);
        CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            total INTEGER, valid INTEGER, invalid INTEGER, filtered INTEGER,
            started_at INTEGER, ended_at INTEGER);
        """)
        self._conn.commit()
    def upsert_user(self, uid, username, first_name):
        with self._conn:
            self._conn.execute("INSERT INTO users(user_id,username,first_name,joined_at,is_admin) "
                "VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,"
                "first_name=excluded.first_name",
                (uid, username or "", first_name or "", int(time.time()), 1 if uid in ADMIN_IDS else 0))
    def is_admin(self, uid):
        if uid in ADMIN_IDS: return True
        r = self._conn.execute("SELECT is_admin FROM users WHERE user_id=?", (uid,)).fetchone()
        return bool(r and r["is_admin"])
    def set_admin(self, uid, val):
        with self._conn:
            self._conn.execute("UPDATE users SET is_admin=? WHERE user_id=?", (1 if val else 0, uid))
    def is_banned(self, uid):
        r = self._conn.execute("SELECT is_banned FROM users WHERE user_id=?", (uid,)).fetchone()
        return bool(r and r["is_banned"])
    @staticmethod
    def _new_key():
        a = string.ascii_uppercase + string.digits
        return "MLBB-" + "-".join("".join(secrets.choice(a) for _ in range(4)) for _ in range(4))
    def generate_keys(self, count, dur, maxc, admin, note=""):
        out = []; now = int(time.time())
        with self._conn:
            for _ in range(count):
                for _ in range(5):
                    k = self._new_key()
                    try:
                        self._conn.execute("INSERT INTO keys(key,duration_hours,max_checks,created_at,"
                            "created_by,note) VALUES(?,?,?,?,?,?)", (k, dur, maxc, now, admin, note))
                        out.append(k); break
                    except sqlite3.IntegrityError: continue
        return out
    def get_key(self, key):
        return self._conn.execute("SELECT * FROM keys WHERE key=?", (key,)).fetchone()
    def revoke_key(self, key):
        with self._conn:
            return self._conn.execute("UPDATE keys SET is_revoked=1,is_active=0 WHERE key=?",
                                       (key,)).rowcount > 0
    def activate_key(self, uid, key):
        k = self.get_key(key)
        if not k: return False, "Key not found"
        if k["is_revoked"]: return False, "Key revoked"
        if not k["is_active"]: return False, "Key already used"
        if k["activated_by"] and k["activated_by"] != uid: return False, "Used by another user"
        with self._conn:
            self._conn.execute("UPDATE keys SET activated_by=?,activated_at=?,is_active=0 WHERE key=?",
                               (uid, int(time.time()), key))
        return True, "OK"
    def user_active_key(self, uid):
        return self._conn.execute("SELECT * FROM keys WHERE activated_by=? AND is_revoked=0 "
            "AND checks_used < max_checks AND (activated_at + duration_hours*3600) > ? "
            "ORDER BY activated_at DESC LIMIT 1", (uid, int(time.time()))).fetchone()
    def user_any_key(self, uid):
        return self._conn.execute("SELECT * FROM keys WHERE activated_by=? ORDER BY activated_at DESC LIMIT 1",
                                   (uid,)).fetchone()
    def consume_checks(self, key, n=1):
        with self._conn:
            return self._conn.execute("UPDATE keys SET checks_used = checks_used + ? "
                "WHERE key=? AND checks_used + ? <= max_checks", (n, key, n)).rowcount > 0
    def list_keys(self, limit=20):
        return self._conn.execute("SELECT * FROM keys ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    def list_users(self, limit=50):
        return self._conn.execute("SELECT * FROM users ORDER BY joined_at DESC LIMIT ?", (limit,)).fetchall()
    def count_users(self):
        return self._conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    def stats(self):
        c = self._conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        k = self._conn.execute("SELECT COUNT(*) c FROM keys").fetchone()["c"]
        ku = self._conn.execute("SELECT COUNT(*) c FROM keys WHERE activated_by IS NULL AND is_revoked=0").fetchone()["c"]
        j = self._conn.execute("SELECT COALESCE(SUM(total),0) t, COALESCE(SUM(valid),0) v FROM jobs").fetchone()
        return {"users": c, "keys_total": k, "keys_unused": ku, "checks_total": j["t"], "checks_valid": j["v"]}
    def record_job(self, uid, total, valid, invalid, filtered, st, en):
        with self._conn:
            self._conn.execute("INSERT INTO jobs(user_id,total,valid,invalid,filtered,started_at,ended_at) "
                "VALUES(?,?,?,?,?,?,?)", (uid, total, valid, invalid, filtered, st, en))
storage = Storage(DB_PATH)

# ============== JOB ==============
@dataclass
class Job:
    user_id: int; chat_id: int; message_id: int; total: int
    mode: str = "player"
    checked: int = 0; registered: int = 0; unregistered: int = 0
    valid: int = 0; invalid: int = 0; filtered: int = 0; banned: int = 0
    stopped: bool = False; start: float = field(default_factory=time.time)
    last_update: float = 0.0
    latest: List[str] = field(default_factory=list)
    results: List[str] = field(default_factory=list)
    input_name: str = "input"
    @property
    def elapsed(self): return max(time.time() - self.start, 0.001)
    @property
    def pct(self): return (self.checked / self.total * 100.0) if self.total else 0.0
    @property
    def speed(self): return self.checked / self.elapsed
jobs: Dict[int, Job] = {}

def progress_bar(pct, width=24):
    f = int(width * pct / 100.0); return "█" * f + "░" * (width - f)

def fmt_line(ok, did, info):
    tag = "✅" if ok else "❌"
    sid = did[-8:] if len(did) >= 8 else did
    return f"{tag} <code>…{html.escape(sid)}</code> │ {html.escape(info[:60])}"

def render_job(job: Job) -> str:
    pct = job.pct; bar = progress_bar(pct, 24)
    eta_line = ""
    if job.speed > 0 and job.checked < job.total:
        eta_line = f"\n⏳ <b>ETA:</b> <b>{_fmt_secs((job.total-job.checked)/job.speed)}</b>  ·  ⚡ <b>{job.speed:.1f}/s</b>"
    latest = ""
    if job.latest: latest = "\n\n<b>Latest:</b>\n" + "\n".join(job.latest[-3:])
    title = "Bulk checking" if job.mode == "player" else "Bulk ban scan"
    return (
        f"✅  <b>{title}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<code>{bar}</code> <b>{pct:5.1f}%</b>\n\n"
        f"📄  Total:        <b>{job.total:,}</b>\n"
        f"✅  Registered:   <b>{job.registered:,}</b>\n"
        f"⚠️  Unregistered: <b>{job.unregistered:,}</b>\n"
        f"❌  Invalid:      <b>{job.invalid:,}</b>\n"
        f"📦  Valid:        <b>{job.valid:,}</b>\n\n"
        f"⏱  Time:  <b>{_fmt_secs(job.elapsed)}</b>{eta_line}{latest}\n\n"
        f"<i>/stop to cancel · /status for snapshot</i>")

async def edit_job(bot, job: Job):
    try:
        await bot.edit_message_text(chat_id=job.chat_id, message_id=job.message_id,
            text=render_job(job), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception: pass

# ============== BULK ==============
async def run_bulk_player(bot, chat_id, message_id, user_id, device_ids, input_name="input.txt"):
    job = Job(user_id=user_id, chat_id=chat_id, message_id=message_id,
              total=len(device_ids), input_name=input_name, mode="player")
    jobs[user_id] = job; await edit_job(bot, job)
    sem = asyncio.Semaphore(BULK_THREADS)

    async def one(did):
        if job.stopped: return
        async with sem:
            if job.stopped: return
            try: res = await asyncio.to_thread(check_device_id, did)
            except Exception as e: res = {"status":"error","device_id":did,"error":str(e)}
            job.checked += 1
            if res.get("status") == "success":
                p = res["player_data"]; job.registered += 1
                try: lvl = int(p.get("level", 0))
                except Exception: lvl = 0
                if lvl < 9:
                    job.filtered += 1
                    job.latest.append(fmt_line(True, did, f"Lv{lvl} filtered"))
                else:
                    job.valid += 1
                    job.results.append(save_line(did, p))
                    info = (f"{p.get('nickname','?')[:14]} Lv:{lvl} "
                            f"🎨{p.get('skin_count','?')} {p.get('collector_tier','?')}")
                    job.latest.append(fmt_line(True, did, info))
            else:
                err = str(res.get("error","unknown")); cat = classify_error(err)
                if cat == "unregistered": job.unregistered += 1
                else: job.invalid += 1
                job.latest.append(fmt_line(False, did, err[:60]))
            now = time.time()
            if now - job.last_update >= UPDATE_INTERVAL:
                job.last_update = now
                await edit_job(bot, job)

    tasks = [asyncio.create_task(one(d)) for d in device_ids]
    try: await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await edit_job(bot, job)
        if job.results:
            data = ("\n".join(job.results) + "\n").encode("utf-8")
            try:
                await bot.send_document(chat_id=chat_id,
                    document=BufferedInputFile(data, filename=f"players_{user_id}_{int(time.time())}.txt"),
                    caption=(f"✅ <b>Done</b>\nRegistered: <b>{job.registered}</b> │ "
                             f"Valid: <b>{job.valid}</b> │ Unregistered: <b>{job.unregistered}</b> │ "
                             f"Invalid: <b>{job.invalid}</b>\n⏱ {_fmt_secs(job.elapsed)}"),
                    parse_mode=ParseMode.HTML)
            except Exception as e: log.warning("send_document failed: %s", e)
        storage.record_job(user_id, job.total, job.valid, job.invalid, job.filtered,
                           int(job.start), int(time.time()))
        k = storage.user_active_key(user_id)
        if k: storage.consume_checks(k["key"], n=job.total)
        await asyncio.sleep(30); jobs.pop(user_id, None)

async def run_bulk_ban(bot, chat_id, message_id, user_id, device_ids, input_name="input.txt"):
    job = Job(user_id=user_id, chat_id=chat_id, message_id=message_id,
              total=len(device_ids), input_name=input_name, mode="ban")
    jobs[user_id] = job; await edit_job(bot, job)
    sem = asyncio.Semaphore(BULK_THREADS)

    async def one(did):
        if job.stopped: return
        async with sem:
            if job.stopped: return
            try: res = await asyncio.to_thread(check_ban_only, did)
            except Exception as e: res = {"status":"error","device_id":did,"error":str(e)}
            job.checked += 1
            if res.get("status") == "success":
                ban = res["ban"]; job.registered += 1
                if ban.get("banned"):
                    job.banned += 1; job.valid += 1
                    job.results.append(save_ban_line(did, ban))
                    job.latest.append(fmt_line(False, did, ban.get("label","Banned")[:60]))
                else:
                    job.valid += 1
                    job.results.append(save_ban_line(did, ban))
                    job.latest.append(fmt_line(True, did, "Not Banned"))
            else:
                err = str(res.get("error","unknown")); cat = classify_error(err)
                if cat == "unregistered": job.unregistered += 1
                else: job.invalid += 1
                job.results.append(f"{did} | FAILED | {err}")
                job.latest.append(fmt_line(False, did, err[:60]))
            now = time.time()
            if now - job.last_update >= UPDATE_INTERVAL:
                job.last_update = now; await edit_job(bot, job)

    tasks = [asyncio.create_task(one(d)) for d in device_ids]
    try: await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await edit_job(bot, job)
        if job.results:
            data = ("\n".join(job.results) + "\n").encode("utf-8")
            try:
                await bot.send_document(chat_id=chat_id,
                    document=BufferedInputFile(data, filename=f"bans_{user_id}_{int(time.time())}.txt"),
                    caption=f"✅ Ban scan done · 🚫 {job.banned} │ ✅ {job.valid-job.banned} │ ⚠️ {job.unregistered} │ ❌ {job.invalid}",
                    parse_mode=ParseMode.HTML)
            except Exception as e: log.warning("send_document failed: %s", e)
        storage.record_job(user_id, job.total, job.valid, job.invalid, 0,
                           int(job.start), int(time.time()))
        k = storage.user_active_key(user_id)
        if k: storage.consume_checks(k["key"], n=job.total)
        await asyncio.sleep(30); jobs.pop(user_id, None)

def has_access(uid):
    if uid in ADMIN_IDS or storage.is_admin(uid): return True, ""
    if storage.is_banned(uid): return False, "🚫 You are banned."
    k = storage.user_active_key(uid)
    if not k: return False, "🚫 No active key. Use <code>/redeem &lt;key&gt;</code>."
    if k["checks_used"] >= k["max_checks"]: return False, "🚫 Key exhausted."
    return True, ""

# ============== BOT ==============
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router(); dp.include_router(router)

class KeyGen(StatesGroup):
    count = State(); duration = State(); max_checks = State(); note = State()
class RevokeFSM(StatesGroup): key = State()
class BroadcastFSM(StatesGroup): msg = State()
class AdminFSM(StatesGroup): uid = State()

def kb_main(is_admin):
    rows = [
        [InlineKeyboardButton(text="🔍 Single Check", callback_data="ui:single"),
         InlineKeyboardButton(text="📦 Bulk Check", callback_data="ui:bulk")],
        [InlineKeyboardButton(text="🚫 Ban (single)", callback_data="ui:ban"),
         InlineKeyboardButton(text="📦 Ban Bulk", callback_data="ui:banbulk")],
        [InlineKeyboardButton(text="📊 Status", callback_data="ui:status"),
         InlineKeyboardButton(text="🛑 Stop", callback_data="ui:stop")],
        [InlineKeyboardButton(text="🔑 Redeem Key", callback_data="ui:redeem"),
         InlineKeyboardButton(text="👤 My Key", callback_data="ui:mykey")],
        [InlineKeyboardButton(text="ℹ️ Help", callback_data="ui:help")],
    ]
    if is_admin:
        rows.insert(2, [InlineKeyboardButton(text="⚡ Kick (single)", callback_data="ui:kick"),
                        InlineKeyboardButton(text="📡 Kick Status", callback_data="ui:kickstatus")])
        rows.append([InlineKeyboardButton(text="🛠 Admin Panel", callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_admin():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Generate Keys", callback_data="admin:gen"),
         InlineKeyboardButton(text="📋 List Keys", callback_data="admin:list")],
        [InlineKeyboardButton(text="🗑 Revoke Key", callback_data="admin:revoke")],
        [InlineKeyboardButton(text="👥 Users", callback_data="admin:users"),
         InlineKeyboardButton(text="📈 Stats", callback_data="admin:stats")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="admin:bc"),
         InlineKeyboardButton(text="👑 Set Admin", callback_data="admin:setadmin")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="admin:back")],
    ])

# ---------------- Commands ----------------
@router.message(CommandStart())
async def cmd_start(msg: Message, command: CommandObject):
    u = msg.from_user
    storage.upsert_user(u.id, u.username or "", u.first_name or "")
    is_admin = storage.is_admin(u.id)
    txt = (f"👋 <b>Welcome, {html.escape(u.first_name or 'user')}!</b>\n\n"
           "🤖 <b>MLBB Device ID Checker Bot</b>\n\n<b>Commands</b>\n"
           "• <code>/check &lt;id&gt;</code> — full player card\n"
           "• <code>/bulk</code> — bulk player info from .txt\n"
           "• <code>/ban &lt;id&gt;</code> — ban status only\n"
           "• <code>/banbulk</code> — bulk ban scan\n")
    if is_admin:
        txt += ("👑 <b>Admin</b>\n"
                "• <code>/kick &lt;id&gt;</code> — bruteforce kick\n"
                "• <code>/kickstatus</code> · <code>/kickstop</code>\n")
    txt += ("• <code>/status</code> · <code>/stop</code>\n"
            "• <code>/redeem &lt;key&gt;</code> · <code>/mykey</code>")
    await msg.answer(txt, reply_markup=kb_main(is_admin))

@router.message(Command("help"))
async def cmd_help(msg: Message):
    txt = ("📖 <b>Help</b>\n\n"
           "🔍 <code>/check and_xxxx…</code> — full card\n"
           f"📦 <code>/bulk</code> → send .txt ({BULK_THREADS} threads)\n"
           "🚫 <code>/ban and_xxxx…</code> — ban status\n"
           "📦 <code>/banbulk</code> → send .txt\n")
    if storage.is_admin(msg.from_user.id):
        txt += (f"👑 <code>/kick and_xxxx…</code> — bruteforce ({KICK_DELAY}s delay)\n"
                "👑 <code>/kickstatus</code> · <code>/kickstop</code>\n")
    txt += "📊 <code>/status</code> · 🛑 <code>/stop</code>"
    await msg.answer(txt)

@router.message(Command("mykey"))
async def cmd_mykey(msg: Message):
    k = storage.user_any_key(msg.from_user.id)
    if not k: return await msg.answer("🚫 No key. Use <code>/redeem &lt;key&gt;</code>.")
    now = int(time.time()); exp = (k["activated_at"] or 0) + k["duration_hours"] * 3600
    left = max(exp - now, 0)
    st = "🟢 active" if storage.user_active_key(msg.from_user.id) else "🔴 expired/exhausted"
    await msg.answer(f"🔑 <b>Your key</b>\n<code>{k['key']}</code>\nStatus: <b>{st}</b>\n"
                     f"Used: <b>{k['checks_used']}/{k['max_checks']}</b>\n"
                     f"Duration: <b>{k['duration_hours']}h</b>\nLeft: <b>{left//3600}h {(left%3600)//60}m</b>")

@router.message(Command("redeem"))
async def cmd_redeem(msg: Message, command: CommandObject):
    storage.upsert_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.first_name or "")
    key = (command.args or "").strip().upper()
    if not key: return await msg.answer("Usage: <code>/redeem MLBB-XXXX-XXXX-XXXX-XXXX</code>")
    ok, reason = storage.activate_key(msg.from_user.id, key)
    if not ok: return await msg.answer(f"❌ {reason}")
    await msg.answer("✅ Key activated!")

@router.message(Command("check"))
async def cmd_check(msg: Message, command: CommandObject):
    storage.upsert_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.first_name or "")
    ok, reason = has_access(msg.from_user.id)
    if not ok: return await msg.answer(reason)
    did = (command.args or "").strip()
    if not did: return await msg.answer("Usage: <code>/check &lt;device_id&gt;</code>")
    ph = await msg.answer("🔍 <i>Fetching full info (this takes ~10s)…</i>")
    res = await asyncio.to_thread(check_device_id, did)
    if res.get("status") != "success":
        return await ph.edit_text(f"❌ <b>Check failed</b>\n"
            f"<code>…{html.escape(did[-12:])}</code>\n\n"
            f"💡 <i>{html.escape(res.get('error','unknown'))}</i>")
    p = res["player_data"]
    k = storage.user_active_key(msg.from_user.id)
    if k: storage.consume_checks(k["key"], 1)
    card = render_card(did, p)
    try: await ph.edit_text(card)
    except Exception: await msg.answer(card)

@router.message(Command("ban"))
async def cmd_ban(msg: Message, command: CommandObject):
    storage.upsert_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.first_name or "")
    ok, reason = has_access(msg.from_user.id)
    if not ok: return await msg.answer(reason)
    did = (command.args or "").strip()
    if not did: return await msg.answer("Usage: <code>/ban &lt;device_id&gt;</code>")
    ph = await msg.answer("🚫 <i>Checking ban status…</i>")
    res = await asyncio.to_thread(check_ban_only, did)
    if res.get("status") != "success":
        return await ph.edit_text(f"❌ <b>Ban check failed</b>\n"
            f"<code>…{html.escape(did[-12:])}</code>\n\n"
            f"💡 <i>{html.escape(res.get('error','unknown'))}</i>")
    ban = res["ban"]
    k = storage.user_active_key(msg.from_user.id)
    if k: storage.consume_checks(k["key"], 1)
    if ban.get("banned"):
        await ph.edit_text(
            f"🚫 <b>BANNED</b>\n{LINE_HEAVY}\n"
            f"┣ 🆔 Device  : <code>…{html.escape(did[-12:])}</code>\n"
            f"┣ 📝 Reason  : <b>{html.escape(str(ban.get('reason','?')))}</b>\n"
            f"┗ ⏱ Remaining: <b>{html.escape(str(ban.get('remaining','?')))}</b>")
    else:
        await ph.edit_text(f"✅ <b>NOT BANNED</b>\n{LINE_HEAVY}\n"
            f"┗ 🆔 Device: <code>…{html.escape(did[-12:])}</code>")

# ---------- BF kicker ----------
@router.message(Command("kick"))
async def cmd_kick(msg: Message, command: CommandObject):
    if not storage.is_admin(msg.from_user.id): return await msg.answer("👑 Admin only.")
    uid = msg.from_user.id
    did = (command.args or "").strip()
    if not did: return await msg.answer("Usage: <code>/kick &lt;device_id&gt;</code>")
    with kick_lock: existing = kick_jobs.get(uid)
    if existing and not existing.get("done"):
        return await msg.answer("⚠️ Kick already running. Use /kickstatus or /kickstop.")
    stop_ev = threading.Event()
    with kick_lock:
        kick_jobs[uid] = {"device_id": did, "rounds": KICK_ROUNDS,
            "stats": {"attempts":0,"hits":0,"fails":0,"elapsed":0.0,"status":"fetching",
                      "avg_latency":0.0,"nickname":"?","gs_info":"?","account_id":"?"},
            "stop_event": stop_ev, "started": time.time(),
            "chat_id": msg.chat.id, "message_id": 0, "done": False}
    ph = await msg.answer(kick_status_text(uid), reply_markup=kick_buttons(uid))
    with kick_lock: kick_jobs[uid]["message_id"] = ph.message_id

    def _on_prog(s):
        with kick_lock:
            j = kick_jobs.get(uid)
            if j: j["stats"] = s
    def _runner():
        try:
            kick_device(did, rounds=KICK_ROUNDS, delay=KICK_DELAY,
                        stop_event=stop_ev, on_progress=_on_prog)
        except Exception as e: log.exception("kick runner error: %s", e)
        finally:
            with kick_lock:
                j = kick_jobs.get(uid)
                if j: j["done"] = True
    threading.Thread(target=_runner, daemon=True).start()

    async def _refresher():
        while True:
            await asyncio.sleep(2)
            with kick_lock:
                j = kick_jobs.get(uid)
                if not j: return
                done = j.get("done"); mid = j.get("message_id", ph.message_id)
            try:
                await bot.edit_message_text(chat_id=ph.chat.id, message_id=mid,
                    text=kick_status_text(uid), reply_markup=kick_buttons(uid))
            except Exception: pass
            if done:
                await asyncio.sleep(60)
                with kick_lock: kick_jobs.pop(uid, None)
                return
    asyncio.create_task(_refresher())

@router.message(Command("kickstatus"))
async def cmd_kickstatus(msg: Message):
    if not storage.is_admin(msg.from_user.id): return await msg.answer("👑 Admin only.")
    await msg.answer(kick_status_text(msg.from_user.id), reply_markup=kick_buttons(msg.from_user.id))

@router.message(Command("kickstop"))
async def cmd_kickstop(msg: Message):
    if not storage.is_admin(msg.from_user.id): return await msg.answer("👑 Admin only.")
    with kick_lock: job = kick_jobs.get(msg.from_user.id)
    if not job or job.get("done"): return await msg.answer("📭 No active kick job.")
    job["stop_event"].set()
    await msg.answer("🛑 Stop signal sent.")

@router.message(Command("bulk"))
async def cmd_bulk(msg: Message):
    storage.upsert_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.first_name or "")
    ok, reason = has_access(msg.from_user.id)
    if not ok: return await msg.answer(reason)
    await msg.answer(f"📦 <b>Bulk player check</b>\nSend .txt (one ID per line).\n⚡ {BULK_THREADS} threads.")

@router.message(Command("banbulk"))
async def cmd_banbulk(msg: Message):
    storage.upsert_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.first_name or "")
    ok, reason = has_access(msg.from_user.id)
    if not ok: return await msg.answer(reason)
    await msg.answer(f"🚫 <b>Bulk ban scan</b>\nSend .txt (one ID per line).\n⚡ {BULK_THREADS} threads.")

@router.message(F.document)
async def on_document(msg: Message):
    storage.upsert_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.first_name or "")
    if msg.from_user.id in jobs and not jobs[msg.from_user.id].stopped:
        return await msg.answer("⚠️ Job already running. Use /stop first.")
    doc = msg.document
    if not doc.file_name.lower().endswith(".txt"):
        return await msg.answer("❌ Only .txt files supported.")
    f = await bot.get_file(doc.file_id); buf = io.BytesIO()
    await bot.download_file(f.file_path, buf)
    ids = read_ids_from_text(buf.getvalue().decode("utf-8", errors="ignore"))
    if not ids: return await msg.answer("❌ No IDs found.")
    if len(ids) > 10000: return await msg.answer(f"❌ Too many IDs ({len(ids)}). Max 10000.")
    mode = "player"
    if msg.caption and "ban" in msg.caption.lower(): mode = "ban"
    ok, reason = has_access(msg.from_user.id)
    if not ok: return await msg.answer(reason)
    ph = await msg.answer(f"🚀 Starting <b>{mode}</b> job of <b>{len(ids)}</b> IDs…")
    if mode == "ban":
        asyncio.create_task(run_bulk_ban(bot, msg.chat.id, ph.message_id, msg.from_user.id, ids, doc.file_name))
    else:
        asyncio.create_task(run_bulk_player(bot, msg.chat.id, ph.message_id, msg.from_user.id, ids, doc.file_name))

@router.message(Command("status"))
async def cmd_status(msg: Message):
    job = jobs.get(msg.from_user.id)
    if not job: return await msg.answer("📭 No job running.")
    await msg.answer(render_job(job))

@router.message(Command("stop"))
async def cmd_stop(msg: Message):
    job = jobs.get(msg.from_user.id)
    if not job: return await msg.answer("📭 No job running.")
    job.stopped = True
    await msg.answer("🛑 Stop requested…")

# ---------------- Admin ----------------
@router.message(Command("admin"))
async def cmd_admin(msg: Message):
    if not storage.is_admin(msg.from_user.id): return await msg.answer("🚫 Admin only.")
    s = storage.stats()
    with kick_lock: active_kicks = sum(1 for j in kick_jobs.values() if not j.get("done"))
    await msg.answer(f"🛠 <b>Admin Panel</b>\n\n👥 Users: <b>{s['users']}</b>\n"
        f"🔑 Keys: <b>{s['keys_total']}</b> (unused: <b>{s['keys_unused']}</b>)\n"
        f"📊 Checks: <b>{s['checks_total']}</b>\n"
        f"🧵 Threads: <b>{BULK_THREADS}</b> · Kick delay: <b>{KICK_DELAY}s</b>\n"
        f"⚡ Active kicks: <b>{active_kicks}</b>", reply_markup=kb_admin())

@router.callback_query(F.data == "admin:home")
async def cb_admin_home(cq):
    if not storage.is_admin(cq.from_user.id): return await cq.answer("Admin only", show_alert=True)
    await cq.message.edit_text("🛠 <b>Admin Panel</b>", reply_markup=kb_admin()); await cq.answer()

@router.callback_query(F.data == "admin:back")
async def cb_admin_back(cq):
    if not storage.is_admin(cq.from_user.id): return await cq.answer("Admin only", show_alert=True)
    await cq.message.edit_text("🏠 <b>Main menu</b>", reply_markup=kb_main(True)); await cq.answer()

@router.callback_query(F.data == "admin:gen")
async def cb_admin_gen(cq, state: FSMContext):
    if not storage.is_admin(cq.from_user.id): return await cq.answer("Admin only", show_alert=True)
    await state.set_state(KeyGen.count); await cq.message.answer("🔢 How many keys? (1–500)"); await cq.answer()

@router.message(KeyGen.count)
async def kg_count(msg: Message, state: FSMContext):
    try: n = int(msg.text.strip()); assert 1 <= n <= 500
    except Exception: return await msg.answer("❌ 1–500.")
    await state.update_data(count=n); await state.set_state(KeyGen.duration)
    await msg.answer("⏱ Duration in hours:")

@router.message(KeyGen.duration)
async def kg_dur(msg: Message, state: FSMContext):
    try: h = int(msg.text.strip()); assert 1 <= h <= 24 * 365
    except Exception: return await msg.answer("❌ 1–8760.")
    await state.update_data(duration=h); await state.set_state(KeyGen.max_checks)
    await msg.answer("🔢 Max checks per key:")

@router.message(KeyGen.max_checks)
async def kg_max(msg: Message, state: FSMContext):
    try: m = int(msg.text.strip()); assert 1 <= m <= 1_000_000
    except Exception: return await msg.answer("❌ 1–1000000.")
    await state.update_data(max_checks=m); await state.set_state(KeyGen.note)
    await msg.answer("📝 Note (or '-'):")

@router.message(KeyGen.note)
async def kg_note(msg: Message, state: FSMContext):
    data = await state.get_data()
    note = "" if msg.text.strip() == "-" else msg.text.strip()[:80]
    keys = storage.generate_keys(data["count"], data["duration"], data["max_checks"],
                                  msg.from_user.id, note)
    await state.clear()
    body = "\n".join(f"<code>{k}</code>" for k in keys)
    out = f"✅ Generated <b>{len(keys)}</b> keys\n\n{body}"
    if len(out) > 3500:
        buf = io.BytesIO(("\n".join(keys) + "\n").encode())
        await msg.answer_document(BufferedInputFile(buf.getvalue(), filename="keys.txt"),
                                  caption=f"✅ {len(keys)} keys")
    else: await msg.answer(out)

@router.callback_query(F.data == "admin:list")
async def cb_admin_list(cq):
    if not storage.is_admin(cq.from_user.id): return await cq.answer("Admin only", show_alert=True)
    rows = storage.list_keys(limit=20)
    if not rows: return await cq.answer("No keys", show_alert=True)
    lines = ["📋 <b>Recent keys</b>\n"]
    for r in rows:
        st = "🟢" if r["activated_by"] is None and not r["is_revoked"] else ("🔴" if r["is_revoked"] else "🔵")
        lines.append(f"{st} <code>{r['key']}</code> | {r['checks_used']}/{r['max_checks']} | {r['duration_hours']}h"
                     + (f" | by <code>{r['activated_by']}</code>" if r["activated_by"] else ""))
    await cq.message.answer("\n".join(lines)); await cq.answer()

@router.callback_query(F.data == "admin:revoke")
async def cb_revoke(cq, state: FSMContext):
    if not storage.is_admin(cq.from_user.id): return await cq.answer("Admin only", show_alert=True)
    await state.set_state(RevokeFSM.key); await cq.message.answer("🗑 Send the key:"); await cq.answer()

@router.message(RevokeFSM.key)
async def rv_key(msg: Message, state: FSMContext):
    ok = storage.revoke_key(msg.text.strip().upper()); await state.clear()
    await msg.answer("✅ Revoked." if ok else "❌ Not found.")

@router.callback_query(F.data == "admin:users")
async def cb_users(cq):
    if not storage.is_admin(cq.from_user.id): return await cq.answer("Admin only", show_alert=True)
    rows = storage.list_users(limit=30)
    lines = [f"👥 <b>Users</b> ({len(rows)}/{storage.count_users()})\n"]
    for r in rows:
        flags = []
        if r["is_admin"]: flags.append("👑")
        if r["is_banned"]: flags.append("🚫")
        un = f"@{r['username']}" if r["username"] else "—"
        lines.append(f"<code>{r['user_id']}</code> {html.escape(r['first_name'] or '')} {un} {' '.join(flags)}")
    await cq.message.answer("\n".join(lines)); await cq.answer()

@router.callback_query(F.data == "admin:stats")
async def cb_stats(cq):
    if not storage.is_admin(cq.from_user.id): return await cq.answer("Admin only", show_alert=True)
    s = storage.stats()
    with kick_lock: active_kicks = sum(1 for j in kick_jobs.values() if not j.get("done"))
    await cq.message.answer(f"📈 <b>Stats</b>\n👥 {s['users']}\n🔑 {s['keys_total']} (unused {s['keys_unused']})\n"
                            f"🧪 {s['checks_total']}\n🧵 Jobs: {len(jobs)} · 👑 Kicks: {active_kicks}")
    await cq.answer()

@router.callback_query(F.data == "admin:bc")
async def cb_bc(cq, state: FSMContext):
    if not storage.is_admin(cq.from_user.id): return await cq.answer("Admin only", show_alert=True)
    await state.set_state(BroadcastFSM.msg); await cq.message.answer("📢 Send text:"); await cq.answer()

@router.message(BroadcastFSM.msg)
async def bc_send(msg: Message, state: FSMContext):
    await state.clear()
    users = storage.list_users(limit=100000); ok = fail = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], f"📢 <b>Broadcast</b>\n\n{msg.html_text}")
            ok += 1; await asyncio.sleep(0.05)
        except Exception: fail += 1
    await msg.answer(f"✅ {ok} | ❌ {fail}")

@router.callback_query(F.data == "admin:setadmin")
async def cb_setadmin(cq, state: FSMContext):
    if not storage.is_admin(cq.from_user.id): return await cq.answer("Admin only", show_alert=True)
    await state.set_state(AdminFSM.uid); await cq.message.answer("👑 Send user_id:"); await cq.answer()

@router.message(AdminFSM.uid)
async def ad_uid(msg: Message, state: FSMContext):
    await state.clear()
    try: uid = int(msg.text.strip())
    except Exception: return await msg.answer("❌ Invalid ID.")
    new = not storage.is_admin(uid); storage.set_admin(uid, new)
    await msg.answer(f"👑 <code>{uid}</code> admin = <b>{new}</b>")

# ---------------- UI callbacks ----------------
@router.callback_query(F.data == "ui:help")
async def cb_ui_help(cq): await cq.message.answer("Send /help."); await cq.answer()

@router.callback_query(F.data == "ui:status")
async def cb_ui_status(cq):
    job = jobs.get(cq.from_user.id)
    if not job: return await cq.answer("No job", show_alert=True)
    await cq.message.answer(render_job(job)); await cq.answer()

@router.callback_query(F.data == "ui:stop")
async def cb_ui_stop(cq):
    job = jobs.get(cq.from_user.id)
    if not job: return await cq.answer("No job", show_alert=True)
    job.stopped = True; await cq.answer("🛑 Stopping…", show_alert=True)

@router.callback_query(F.data == "ui:redeem")
async def cb_ui_redeem(cq):
    await cq.message.answer("Use <code>/redeem MLBB-XXXX-XXXX-XXXX-XXXX</code>"); await cq.answer()

@router.callback_query(F.data == "ui:mykey")
async def cb_ui_mykey(cq):
    k = storage.user_any_key(cq.from_user.id)
    if not k: return await cq.answer("No key", show_alert=True)
    now = int(time.time()); exp = (k["activated_at"] or 0) + k["duration_hours"] * 3600
    left = max(exp - now, 0)
    await cq.message.answer(f"🔑 <code>{k['key']}</code>\nUsed: <b>{k['checks_used']}/{k['max_checks']}</b>\n"
                            f"Left: <b>{left//3600}h {(left%3600)//60}m</b>")
    await cq.answer()

@router.callback_query(F.data == "ui:single")
async def cb_ui_single(cq): await cq.message.answer("Use <code>/check &lt;device_id&gt;</code>"); await cq.answer()

@router.callback_query(F.data == "ui:bulk")
async def cb_ui_bulk(cq): await cq.message.answer("Use <code>/bulk</code> then send a .txt file."); await cq.answer()

@router.callback_query(F.data == "ui:ban")
async def cb_ui_ban(cq): await cq.message.answer("Use <code>/ban &lt;device_id&gt;</code>"); await cq.answer()

@router.callback_query(F.data == "ui:banbulk")
async def cb_ui_banbulk(cq): await cq.message.answer("Use <code>/banbulk</code> then send a .txt file."); await cq.answer()

@router.callback_query(F.data == "ui:kick")
async def cb_ui_kick(cq):
    if not storage.is_admin(cq.from_user.id): return await cq.answer("Admin only", show_alert=True)
    await cq.message.answer(f"Use <code>/kick &lt;device_id&gt;</code> · delay {KICK_DELAY}s"); await cq.answer()

@router.callback_query(F.data == "ui:kickstatus")
async def cb_ui_kickstatus(cq):
    if not storage.is_admin(cq.from_user.id): return await cq.answer("Admin only", show_alert=True)
    await cq.message.answer(kick_status_text(cq.from_user.id),
                            reply_markup=kick_buttons(cq.from_user.id)); await cq.answer()

@router.callback_query(F.data.startswith("kick:refresh:"))
async def cb_kick_refresh(cq):
    if not storage.is_admin(cq.from_user.id): return await cq.answer("Admin only", show_alert=True)
    try: target = int(cq.data.split(":")[2])
    except Exception: target = cq.from_user.id
    try: await cq.message.edit_text(kick_status_text(target), reply_markup=kick_buttons(target))
    except Exception: pass
    await cq.answer("🔄 Refreshed")

@router.callback_query(F.data.startswith("kick:stop:"))
async def cb_kick_stop(cq):
    if not storage.is_admin(cq.from_user.id): return await cq.answer("Admin only", show_alert=True)
    try: target = int(cq.data.split(":")[2])
    except Exception: target = cq.from_user.id
    with kick_lock: job = kick_jobs.get(target)
    if not job or job.get("done"): return await cq.answer("No active kick", show_alert=True)
    job["stop_event"].set(); await cq.answer("🛑 Stopping…", show_alert=True)

# ---------------- Main ----------------
async def set_commands():
    cmds = [BotCommand(command="start",  description="Start"),
            BotCommand(command="help",   description="Help"),
            BotCommand(command="check",  description="Full player check"),
            BotCommand(command="bulk",   description="Bulk player check (.txt)"),
            BotCommand(command="ban",    description="Single ban check"),
            BotCommand(command="banbulk",description="Bulk ban scan (.txt)"),
            BotCommand(command="status", description="Job status"),
            BotCommand(command="stop",   description="Stop job"),
            BotCommand(command="redeem", description="Activate key"),
            BotCommand(command="mykey",  description="My key"),
            BotCommand(command="admin",  description="Admin panel"),
            BotCommand(command="kick",      description="Bruteforce kick (admin)"),
            BotCommand(command="kickstatus",description="Kick status (admin)"),
            BotCommand(command="kickstop",  description="Stop kick (admin)")]
    await bot.set_my_commands(cmds, scope=BotCommandScopeDefault())

async def main():
    await set_commands()
    log.info("Bot started. Threads=%d · Kick delay=%.1fs · Rounds=%s",
             BULK_THREADS, KICK_DELAY, "∞" if KICK_ROUNDS == 0 else KICK_ROUNDS)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): log.info("bye")
