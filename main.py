#!/usr/bin/env python3
"""
MLBB Telegram Bot â€” production build for Railway.
Primary profile source: https://mlbbbbv2.onrender.com/lookup
Bulk check with live stats (valid, invalid, banned, highest level, highest skins).
"""

import os
import io
import json
import time
import random
import string
import socket
import struct
import asyncio
import logging
import threading
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from urllib.parse import urlparse

import requests
import zstandard as zstd
from Crypto.Cipher import AES
import aiosqlite

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logger = logging.getLogger("mlbb-bot")
logger.setLevel(logging.INFO)

# ============================================================
# CONFIG
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or 0)

PRICE_CREATION = int(os.environ.get("PRICE_CREATION", "10"))
PRICE_BAN = int(os.environ.get("PRICE_BAN", "10"))
FREE_DAILY_CREATION = int(os.environ.get("FREE_DAILY_CREATION", "2"))
FREE_DAILY_BAN = int(os.environ.get("FREE_DAILY_BAN", "2"))

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    DATA_DIR = Path(".")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = str(DATA_DIR / "mlbb_bot.db")
PROXIES_FILE = DATA_DIR / "proxies.txt"
REPORTS_DIR = DATA_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

USER_COOLDOWN_SEC = float(os.environ.get("USER_COOLDOWN_SEC", "3"))
LOGIN_CACHE_TTL = int(os.environ.get("LOGIN_CACHE_TTL", "90"))

LOGIN_HOST = "login.ml.youngjoygame.com"
LOGIN_PORT = 30021
CLIENT_VERSION = os.environ.get("CLIENT_VERSION", "2.1.99.1205.1")
CHANNEL = os.environ.get("CHANNEL", "and_usa")
LANGUAGE = os.environ.get("LANGUAGE", "en")

AES_KEY = bytes.fromhex("f5a193d50ade553e9835595f5cd75ddd")
AES_IV = b"\x00" * 16

# Primary lookup API
LOOKUP_API = os.environ.get("LOOKUP_API", "https://mlbbbbv2.onrender.com/lookup")
LOOKUP_TIMEOUT = int(os.environ.get("LOOKUP_TIMEOUT", "30"))
FALLBACK_LOOKUPS = [
    ("https://mlbbapi.onrender.com/lookup", "role_id"),
    ("https://mlbb-api.vercel.app/lookup", "role_id"),
]

CN31_SERVERS = [
    "https://solver-server-production.up.railway.app",
    "http://solver-server-production.up.railway.app",
    "https://solver-solver-production.up.railway.app",
    "http://solver-solver-production.up.railway.app",
    "https://solar-solver-production.up.railway.app",
    "http://solar-solver-production.up.railway.app",
    "http://217.216.35.81:8080",
    "http://217.216.35.129:8082",
    "http://62.146.237.138:8080",
]
TOKEN_PATHS = ["/get-token", "/token", "/cookies", "/cn31", "/api/token", "/v1/token"]

# Bulk waiting state â€” admin user IDs that have called /bulk and are waiting to upload
BULK_WAITING: set = set()
BULK_WAIT_TIMEOUT_SEC = 300  # must upload within 5 min of /bulk
_bulk_wait_ts: Dict[int, float] = {}


# ============================================================
# DATABASE
# ============================================================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                free_creation INTEGER DEFAULT 2,
                free_ban INTEGER DEFAULT 2,
                last_date TEXT DEFAULT ''
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS codes (
                code TEXT PRIMARY KEY,
                amount INTEGER,
                used INTEGER DEFAULT 0,
                used_by INTEGER DEFAULT NULL
            )
        """)
        await db.commit()
    logger.info(f"Database ready at {DB_PATH}")


async def get_user(user_id: int) -> Dict:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        async with db.execute(
            "SELECT balance, free_creation, free_ban, last_date FROM users WHERE user_id=?",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
            if row:
                return {
                    "balance": row[0],
                    "free_creation": row[1],
                    "free_ban": row[2],
                    "last_date": row[3],
                }
            today = date.today().isoformat()
            await db.execute(
                "INSERT INTO users (user_id, balance, free_creation, free_ban, last_date) "
                "VALUES (?, 0, ?, ?, ?)",
                (user_id, FREE_DAILY_CREATION, FREE_DAILY_BAN, today),
            )
            await db.commit()
            return {
                "balance": 0,
                "free_creation": FREE_DAILY_CREATION,
                "free_ban": FREE_DAILY_BAN,
                "last_date": today,
            }


async def update_user(user_id: int, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [user_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute(f"UPDATE users SET {cols} WHERE user_id=?", vals)
        await db.commit()


async def reset_daily_if_needed(user_id: int) -> bool:
    u = await get_user(user_id)
    today = date.today().isoformat()
    if u["last_date"] != today:
        await update_user(
            user_id,
            free_creation=FREE_DAILY_CREATION,
            free_ban=FREE_DAILY_BAN,
            last_date=today,
        )
        return True
    return False


async def generate_code(amount: int) -> str:
    code = "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute(
            "INSERT INTO codes (code, amount, used) VALUES (?, ?, 0)",
            (code, amount),
        )
        await db.commit()
    return code


async def redeem_code(user_id: int, code: str) -> Tuple[bool, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        async with db.execute(
            "SELECT amount, used FROM codes WHERE code=?", (code,)
        ) as cur:
            row = await cur.fetchone()
            if not row or row[1] == 1:
                return False, 0
            amount = row[0]
        await db.execute(
            "UPDATE codes SET used=1, used_by=? WHERE code=?", (user_id, code)
        )
        async with db.execute(
            "SELECT balance FROM users WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                new_balance = row[0] + amount
                await db.execute(
                    "UPDATE users SET balance=? WHERE user_id=?",
                    (new_balance, user_id),
                )
            else:
                today = date.today().isoformat()
                await db.execute(
                    "INSERT INTO users (user_id, balance, free_creation, free_ban, last_date) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, amount, FREE_DAILY_CREATION, FREE_DAILY_BAN, today),
                )
                new_balance = amount
        await db.commit()
    return True, amount


# ============================================================
# RATE LIMITER
# ============================================================
_last_cmd: Dict[int, float] = {}
_last_cmd_lock = threading.Lock()


def rate_limited(user_id: int) -> bool:
    now = time.time()
    with _last_cmd_lock:
        last = _last_cmd.get(user_id, 0)
        if now - last < USER_COOLDOWN_SEC:
            return True
        _last_cmd[user_id] = now
    return False


# ============================================================
# PROXY ROTATOR
# ============================================================
PROXY_LIST: List[str] = []
PROXY_LOCK = threading.Lock()


def load_proxies():
    global PROXY_LIST
    if not PROXIES_FILE.exists():
        PROXY_LIST = []
        logger.warning(f"{PROXIES_FILE} not found â€” running without proxies.")
        return
    try:
        raw = [
            l.strip()
            for l in PROXIES_FILE.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")
        ]
        valid = []
        for p in raw:
            if not p.startswith(("http://", "https://", "socks4://", "socks5://")):
                p = "http://" + p
            try:
                if urlparse(p).netloc:
                    valid.append(p)
            except Exception:
                pass
        PROXY_LIST = valid
        logger.info(f"Loaded {len(PROXY_LIST)} proxies.")
    except Exception as e:
        PROXY_LIST = []
        logger.warning(f"Proxy load failed: {e}")


def get_proxy() -> Optional[Dict[str, str]]:
    if not PROXY_LIST:
        return None
    with PROXY_LOCK:
        url = random.choice(PROXY_LIST)
    return {"http": url, "https": url}


# ============================================================
# SDP PROTOCOL
# ============================================================
class SdpType:
    INT_POS = 0
    INT_NEG = 1
    FLOAT = 2
    DOUBLE = 3
    STRING = 4
    LIST = 5
    DICT = 6
    STRUCT_BEGIN = 7
    STRUCT_END = 8


class SdpStruct(dict):
    def __init__(self, data=None):
        super().__init__()
        self.data = b""
        self.offset = 0
        if isinstance(data, bytes):
            self.data = data
            self._unpack()
        elif data is not None:
            self.update(data)
            self._pack()

    def _pack(self):
        self.data = bytes([SdpType.STRUCT_BEGIN << 4])
        for k, v in sorted(self.items()):
            self._pack_item(k, v)
        self.data += bytes([SdpType.STRUCT_END << 4])

    def _unpack(self):
        if not self.data:
            return
        if self.data[0] >> 4 == SdpType.STRUCT_BEGIN:
            self.offset = 1
        while self.offset < len(self.data):
            k, v = self._unpack_item()
            if isinstance(v, int) and v == SdpType.STRUCT_END:
                break
            self[k] = v

    def _write_varint(self, n: int) -> bytes:
        out = bytearray()
        while n >= 0x80:
            out.append((n & 0x7F) | 0x80)
            n >>= 7
        out.append(n & 0x7F)
        return bytes(out)

    def _read_varint(self) -> int:
        n = 1
        val = self.data[self.offset] & 0x7F
        while self.data[self.offset + n - 1] >= 0x80:
            val |= (self.data[self.offset + n] & 0x7F) << (7 * n)
            n += 1
        self.offset += n
        return val

    def _pack_header(self, tag: int, dtype: int):
        if tag < 15:
            self.data += bytes([(dtype << 4) | tag])
        else:
            self.data += bytes([(dtype << 4) | 15]) + self._write_varint(tag)

    def _pack_item(self, tag: int, val):
        if isinstance(val, bool):
            self._pack_header(tag, SdpType.INT_POS)
            self.data += self._write_varint(1 if val else 0)
        elif isinstance(val, int):
            if val < 0:
                self._pack_header(tag, SdpType.INT_NEG)
                self.data += self._write_varint(-val)
            else:
                self._pack_header(tag, SdpType.INT_POS)
                self.data += self._write_varint(val)
        elif isinstance(val, float):
            self._pack_header(tag, SdpType.DOUBLE)
            self.data += self._write_varint(8) + struct.pack("<d", val)
        elif isinstance(val, (str, bytes)):
            self._pack_header(tag, SdpType.STRING)
            enc = val.encode("utf-8") if isinstance(val, str) else val
            self.data += self._write_varint(len(enc)) + enc
        elif isinstance(val, list):
            self._pack_header(tag, SdpType.LIST)
            self.data += self._write_varint(len(val))
            for item in val:
                self._pack_item(0, item)
        elif isinstance(val, dict):
            if isinstance(val, SdpStruct):
                self._pack_header(tag, SdpType.STRUCT_BEGIN)
                for k, v in sorted(val.items()):
                    self._pack_item(k, v)
                self.data += bytes([SdpType.STRUCT_END << 4])
            else:
                self._pack_header(tag, SdpType.DICT)
                self.data += self._write_varint(len(val))
                for k, v in sorted(val.items()):
                    self._pack_item(0, k)
                    self._pack_item(0, v)
        else:
            raise TypeError(f"Unsupported SDP type: {type(val)}")

    def _unpack_item(self) -> Tuple[int, any]:
        if self.offset >= len(self.data):
            return 0, None
        hdr = self.data[self.offset]
        tag = hdr & 0xF
        dtype = hdr >> 4
        self.offset += 1
        if tag == 15:
            tag = self._read_varint()
        if dtype == SdpType.INT_POS:
            return tag, self._read_varint()
        if dtype == SdpType.INT_NEG:
            return tag, -self._read_varint()
        if dtype == SdpType.FLOAT:
            return tag, struct.unpack("<f", self._read_varint().to_bytes(4, "little"))[0]
        if dtype == SdpType.DOUBLE:
            return tag, struct.unpack("<d", self._read_varint().to_bytes(8, "little"))[0]
        if dtype == SdpType.STRING:
            l = self._read_varint()
            raw = self.data[self.offset:self.offset + l]
            self.offset += l
            try:
                return tag, raw.decode("utf-8")
            except UnicodeDecodeError:
                return tag, raw
        if dtype == SdpType.LIST:
            l = self._read_varint()
            return tag, [self._unpack_item()[1] for _ in range(l)]
        if dtype == SdpType.DICT:
            l = self._read_varint()
            res = {}
            for _ in range(l):
                _, k = self._unpack_item()
                _, v = self._unpack_item()
                res[k] = v
            return tag, res
        if dtype == SdpType.STRUCT_BEGIN:
            res = {}
            while True:
                k, v = self._unpack_item()
                if isinstance(v, int) and v == SdpType.STRUCT_END:
                    break
                res[k] = v
            return tag, SdpStruct(res)
        if dtype == SdpType.STRUCT_END:
            return tag, SdpType.STRUCT_END
        raise ValueError(f"Unknown SDP data type: {dtype}")


# ============================================================
# TCP LOGIN
# ============================================================
class GameLogin:
    def __init__(self, device_id: str):
        self.device_id = device_id.strip()
        raw = self.device_id
        if raw.startswith(("and_", "ios_")):
            raw = raw[4:]
        self.imei = raw[:32] if len(raw) >= 32 else raw
        self.android = raw[32:48] if len(raw) >= 48 else ""
        self.adid = raw[48:] if len(raw) > 48 else ""
        self.sock: Optional[socket.socket] = None
        self.sequence = 1
        self.queue = b""

    def _connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(8)
        self.sock.connect((LOGIN_HOST, LOGIN_PORT))

    def _close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.sequence = 1

    def _send(self, pid: int, sdp: SdpStruct):
        pkt = SdpStruct({0: pid, 1: self.sequence, 5: sdp.data}).data
        comp = zstd.compress(pkt)
        flags = (len(comp) + 4) | (16 << 24)
        self.sock.send(flags.to_bytes(4, "big") + comp)
        self.sequence += 1

    def _recv(self) -> Tuple[Optional[int], Optional[SdpStruct]]:
        try:
            while len(self.queue) < 4:
                chunk = self.sock.recv(4096)
                if not chunk:
                    return None, None
                self.queue += chunk
            flags = int.from_bytes(self.queue[:4], "big")
            size = flags & 0xFFFFFF
            ctype = flags >> 24
            while len(self.queue) < size:
                chunk = self.sock.recv(4096)
                if not chunk:
                    return None, None
                self.queue += chunk
            data = self.queue[4:size]
            self.queue = self.queue[size:]
            if ctype == 16:
                data = zstd.decompress(data)
            elif ctype == 2:
                cipher = AES.new(AES_KEY, AES.MODE_CBC, iv=AES_IV)
                data = cipher.decrypt(data).rstrip(b"\x00")
            res = SdpStruct(data)
            pid = res.get(0)
            if pid is None:
                return None, None
            body = res.get(6) or res.get(5)
            return (pid, SdpStruct(body)) if isinstance(body, bytes) else (pid, None)
        except socket.timeout:
            return -1, None
        except Exception as e:
            logger.debug(f"recv error: {e}")
            return None, None

    def resolve(self) -> Dict:
        try:
            self._connect()
            self._send(1, SdpStruct({
                0: self.device_id,
                1: f"gps_adid={self.adid}&android_id={self.android}&device_unique_id={self.imei}",
                2: CLIENT_VERSION,
                3: CHANNEL,
                4: LANGUAGE,
            }))
            pid, res = self._recv()
            if pid != 2 or not res:
                return {"success": False, "error": f"Login rejected (packet {pid})"}
            zone_field = res.get(2)
            zone_id = zone_field[0] if isinstance(zone_field, list) and zone_field else 0
            return {
                "success": True,
                "account_id": res.get(0),
                "zone_id": zone_id,
                "ban_flag": res.get(3) or res.get(10) or res.get(20),
                "creation_ts": res.get(19, 0),
                "raw": {str(k): (v if isinstance(v, (int, float, str, bool, type(None))) else repr(v))
                        for k, v in dict(res).items()},
            }
        except socket.timeout:
            return {"success": False, "error": "TCP timeout"}
        except ConnectionRefusedError:
            return {"success": False, "error": "Login server refused connection"}
        except Exception as e:
            return {"success": False, "error": f"TCP error: {str(e)[:100]}"}
        finally:
            self._close()


# ============================================================
# LOOKUP API
# ============================================================
def _extract_player(data: any) -> Optional[Dict]:
    if not data:
        return None
    if isinstance(data, list):
        for item in data:
            p = _extract_player(item)
            if p:
                return p
        return None
    if not isinstance(data, dict):
        return None
    for key in ("nickname", "name", "username", "ign"):
        if data.get(key):
            return data
    for key in ("data", "result", "player", "player_data", "account", "profile"):
        nested = data.get(key)
        if nested:
            p = _extract_player(nested)
            if p:
                return p
    return None


def fetch_profile_from_lookup_api(account_id: int, zone_id: int) -> Dict:
    param_sets = [
        {"role_id": str(account_id), "zone_id": str(zone_id)},
        {"uid": str(account_id), "zone_id": str(zone_id)},
        {"account_id": str(account_id), "zone_id": str(zone_id)},
        {"role_id": str(account_id), "zone": str(zone_id)},
        {"user_id": str(account_id), "zone_id": str(zone_id)},
    ]
    last_error = "unknown"
    for params in param_sets:
        try:
            r = requests.post(
                LOOKUP_API,
                json=params,
                timeout=LOOKUP_TIMEOUT,
                proxies=get_proxy(),
            )
            if r.status_code != 200:
                last_error = f"HTTP {r.status_code}"
                continue
            try:
                data = r.json()
            except ValueError:
                last_error = f"non-JSON: {r.text[:80]!r}"
                continue
            p = _extract_player(data)
            if p:
                return {"success": True, "data": p, "source": f"{LOOKUP_API} ({list(params)[0]})"}
            last_error = f"no player fields: {str(data)[:120]}"
        except requests.Timeout:
            last_error = "timeout"
            continue
        except Exception as e:
            last_error = f"{type(e).__name__}: {str(e)[:80]}"
            continue
    return {"success": False, "error": f"lookup API failed: {last_error}"}


# ============================================================
# CN31 TOKEN / BAN
# ============================================================
def fetch_cn31_token() -> Optional[str]:
    for server in CN31_SERVERS:
        for path in TOKEN_PATHS:
            try:
                r = requests.get(server + path, timeout=5)
                if r.status_code != 200:
                    continue
                try:
                    data = r.json()
                    for key in ("token", "access_token", "cookie", "cn31"):
                        if data.get(key):
                            return str(data[key])
                except ValueError:
                    txt = r.text.strip()
                    if txt.startswith("CN31_") or len(txt) > 20:
                        return txt
            except Exception:
                continue
    return None


def _cn31_session(token: str) -> requests.Session:
    s = requests.Session()
    px = get_proxy()
    if px:
        s.proxies.update(px)
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Cookie": f"session_key={token}; token={token}",
        "Referer": "https://account.cn31.mobilelegends.com/",
        "Origin": "https://account.cn31.mobilelegends.com",
    })
    return s


def check_ban_real(account_id: int, zone_id: int, token: Optional[str]) -> Dict:
    if not token:
        return {"banned": False, "reason": "No CN31 token — TCP flag will be used", "source": "tcp-pending"}
    s = _cn31_session(token)
    endpoints = [
        f"https://account.cn31.mobilelegends.com/v1/ban/info?uid={account_id}&zone={zone_id}",
        f"https://account.cn31.mlbb.com/v1/status?uid={account_id}&zone={zone_id}",
        f"https://account.cn31.mobilelegends.com/v1/player/ban?uid={account_id}&zone={zone_id}",
    ]
    for url in endpoints:
        try:
            r = s.get(url, timeout=8)
            if r.status_code in (401, 403):
                return {"banned": False, "reason": "Auth rejected (token stale)", "source": url}
            if r.status_code != 200:
                continue
            data = r.json()
            if data.get("ban_status", 0) > 0:
                return {"banned": True, "reason": data.get("ban_reason", "Permanent Ban"), "source": url}
            if data.get("is_banned") is True:
                return {"banned": True, "reason": data.get("reason", "Unknown"), "source": url}
            if data.get("code") in (1002, 1003, 1004):
                return {"banned": True, "reason": f"Code {data['code']}", "source": url}
            if data.get("ban_time", 0) > 0:
                return {"banned": True, "reason": f"Banned until {data['ban_time']}", "source": url}
            if "ban" in data or "status" in data:
                return {"banned": False, "reason": "Not banned", "source": url}
        except Exception:
            continue
    return {"banned": False, "reason": "No ban signal from CN31", "source": "none"}


def fetch_account_info(account_id: int, zone_id: int, token: Optional[str]) -> Dict:
    primary = fetch_profile_from_lookup_api(account_id, zone_id)
    if primary.get("success"):
        return primary

    if token:
        s = _cn31_session(token)
        for url in [
            f"https://account.cn31.mobilelegends.com/v1/profile?uid={account_id}&zone={zone_id}",
            f"https://account.cn31.mobilelegends.com/v1/player/info?uid={account_id}&zone={zone_id}",
            f"https://account.cn31.mlbb.com/v1/profile?uid={account_id}&zone={zone_id}",
        ]:
            try:
                r = s.get(url, timeout=8)
                if r.status_code != 200:
                    continue
                p = _extract_player(r.json())
                if p:
                    return {"success": True, "data": p, "source": "cn31"}
            except Exception:
                continue

    for api, key in FALLBACK_LOOKUPS:
        try:
            r = requests.post(
                api,
                json={key: str(account_id), "zone_id": str(zone_id)},
                timeout=12,
                proxies=get_proxy(),
            )
            if r.status_code != 200:
                continue
            p = _extract_player(r.json())
            if p:
                return {"success": True, "data": p, "source": api}
        except Exception:
            continue

    return {"success": False, "error": primary.get("error", "all profile sources failed")}


# ============================================================
# LOGIN CACHE
# ============================================================
_login_cache: Dict[str, Tuple[float, Dict]] = {}
_login_cache_lock = threading.Lock()


def _cache_get(device_id: str) -> Optional[Dict]:
    with _login_cache_lock:
        entry = _login_cache.get(device_id)
        if not entry:
            return None
        ts, val = entry
        if time.time() - ts > LOGIN_CACHE_TTL:
            _login_cache.pop(device_id, None)
            return None
        return val


def _cache_put(device_id: str, val: Dict):
    with _login_cache_lock:
        _login_cache[device_id] = (time.time(), val)
        if len(_login_cache) > 500:
            oldest = sorted(_login_cache.items(), key=lambda kv: kv[1][0])[:100]
            for k, _ in oldest:
                _login_cache.pop(k, None)


# ============================================================
# FULL CHECK PIPELINE
# ============================================================
def full_check(device_id: str) -> Dict:
    cached = _cache_get(device_id)
    if cached is not None:
        cached = dict(cached)
        cached["cached"] = True
        return cached

    login = GameLogin(device_id).resolve()
    if not login.get("success"):
        return {
            "success": False,
            "stage": "login",
            "error": login.get("error", "Login failed"),
        }

    account_id = login["account_id"]
    zone_id = login["zone_id"]

    token: Optional[str] = None
    profile: Dict = {"success": False, "error": "skipped"}
    ban: Dict = {"banned": False, "reason": "not checked", "source": "none"}

    try:
        token = fetch_cn31_token()
    except Exception as e:
        logger.warning(f"token fetch raised: {e}")

    try:
        profile = fetch_account_info(account_id, zone_id, token)
    except Exception as e:
        profile = {"success": False, "error": f"profile exception: {e}"}

    try:
        ban = check_ban_real(account_id, zone_id, token)
    except Exception as e:
        ban = {"banned": False, "reason": f"ban exception: {e}", "source": "none"}

    if login.get("ban_flag") and not ban["banned"]:
        ban = {"banned": True, "reason": f"TCP ban_flag={login['ban_flag']}", "source": "tcp"}

    result = {
        "success": True,
        "device_id": device_id,
        "account_id": account_id,
        "zone_id": zone_id,
        "profile": profile.get("data") if profile.get("success") else None,
        "profile_source": profile.get("source"),
        "profile_error": profile.get("error"),
        "banned": ban["banned"],
        "ban_reason": ban["reason"],
        "ban_source": ban.get("source"),
        "creation_ts": login.get("creation_ts", 0),
        "cached": False,
    }
    _cache_put(device_id, result)
    return result


# ============================================================
# FORMATTERS
# ============================================================
def fmt_bool(v) -> str:
    return "✅ Yes" if v else "❌ No"


def fmt_creation(ts) -> str:
    if not ts:
        return "N/A"
    try:
        sec = ts / 1000 if ts > 1e10 else ts
        return datetime.fromtimestamp(sec, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return "N/A"


def _pick(d: Dict, *keys, default="N/A"):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", 0, "0"):
            return v
    return default


def _pick_int(d: Dict, *keys, default=0) -> int:
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        try:
            return int(float(v))
        except (ValueError, TypeError):
            continue
    return default


def render_single(result: Dict) -> str:
    if not result.get("success"):
        return (
            f"❌ *Check Failed*\n\n"
            f"Stage: `{result.get('stage', '?')}`\n"
            f"Reason: `{result.get('error', 'Unknown')}`"
        )

    p = result.get("profile") or {}
    tag = " _(cached)_" if result.get("cached") else ""

    lines = [
        f"📱 *Device Check Result*{tag}",
        "",
        "🟢 *Login*: success",
        f"🆔 Device ID : `{result['device_id']}`",
        f"👤 Account ID: `{result['account_id']}`",
        f"🗺 Zone ID   : `{result['zone_id']}`",
        f"📅 Created   : `{fmt_creation(result.get('creation_ts'))}`",
        "",
        f"🚫 *Banned*  : {fmt_bool(result['banned'])}",
        f"   Reason    : `{result.get('ban_reason', 'N/A')}`",
        f"   Source    : `{result.get('ban_source', 'N/A')}`",
    ]

    if p:
        lines += [
            "",
            "📊 *Account Info*",
            f"• Nickname : `{_pick(p, 'nickname', 'name', 'username', 'ign')}`",
            f"• Level    : `{_pick(p, 'level', 'account_level', 'lvl')}`",
            f"• Rank     : `{_pick(p, 'current_rank', 'rank', 'rank_name', 'tier')}`",
            f"• Heroes   : `{_pick(p, 'hero_count', 'heroes', 'total_heroes')}`",
            f"• Skins    : `{_pick(p, 'skin_count', 'skins', 'total_skins')}`",
            f"• Winrate  : `{_pick(p, 'win_rate', 'winrate', 'wr')}`",
            f"• Matches  : `{_pick(p, 'matches', 'total_matches', 'games')}`",
            f"• MVP      : `{_pick(p, 'mvp', 'mvp_count', 'total_mvp')}`",
            f"• Source   : `{result.get('profile_source', 'N/A')}`",
        ]
    else:
        lines += [
            "",
            "📊 *Account Info*: _unavailable_",
            f"   Reason: `{result.get('profile_error') or 'no profile API reachable'}`",
            "",
            "_Identity and ban status above are from the real MLBB login server._",
        ]
    return "\n".join(lines)


# ============================================================
# KEYBOARD
# ============================================================
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Creation Date", callback_data="menu_creation")],
        [InlineKeyboardButton("🚫 Ban Status", callback_data="menu_ban")],
        [InlineKeyboardButton("🔍 Lookup / Full Check", callback_data="menu_lookup")],
        [InlineKeyboardButton("📦 Bulk Check (admin)", callback_data="menu_bulk")],
        [InlineKeyboardButton("💰 Balance", callback_data="menu_balance")],
        [InlineKeyboardButton("🎫 Redeem Code", callback_data="menu_redeem")],
    ])


# ============================================================
# HANDLERS
# ============================================================
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if rate_limited(uid):
        return
    await reset_daily_if_needed(uid)
    u = await get_user(uid)
    await update.message.reply_text(
        f"🤖 *MLBB Checker Bot*\n\n"
        f"💰 Balance: `{u['balance']}` PHP\n"
        f"🆓 Free creation checks: `{u['free_creation']}`\n"
        f"🆓 Free ban checks: `{u['free_ban']}`\n\n"
        f"Choose an option:",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )


async def cb_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "menu_creation":
        txt = ("📅 *Creation Date Check*\n\n"
               "Send:\n`/check_creation <device_id>`\n\n"
               f"Cost: {PRICE_CREATION} PHP (2 free daily)")
    elif data == "menu_ban":
        txt = ("🚫 *Ban Status Check*\n\n"
               "Send:\n`/check_ban <device_id>`\n\n"
               f"Cost: {PRICE_BAN} PHP (2 free daily)")
    elif data == "menu_lookup":
        txt = ("🔍 *Full Lookup*\n\n"
               "Logs in the device ID via the real MLBB TCP server, then fetches\n"
               "profile data and checks ban status.\n\n"
               "Send:\n`/lookup <device_id>`\n\n"
               "Free.")
    elif data == "menu_bulk":
        txt = ("📦 *Bulk Check (admin only)*\n\n"
               "Send `/bulk` first, then upload your `.txt` file\n"
               "with one device ID per line.")
    elif data == "menu_balance":
        u = await get_user(q.from_user.id)
        txt = (f"💰 Balance: `{u['balance']}` PHP\n"
               f"🆓 Free creation: `{u['free_creation']}`\n"
               f"🆓 Free ban: `{u['free_ban']}`")
    elif data == "menu_redeem":
        txt = "🎫 Send: `/redeem <code>`"
    else:
        txt = "Unknown option."
    try:
        await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=main_menu_kb())
    except Exception as e:
        if "not modified" not in str(e):
            logger.error(f"callback edit error: {e}")


async def cmd_check_creation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if rate_limited(uid):
        return
    if not ctx.args:
        await update.message.reply_text("❌ Usage: `/check_creation <device_id>`", parse_mode="Markdown")
        return
    device_id = ctx.args[0].strip()
    await reset_daily_if_needed(uid)
    u = await get_user(uid)
    if u["free_creation"] > 0:
        await update_user(uid, free_creation=u["free_creation"] - 1)
        cost = f"✅ Free check used ({u['free_creation'] - 1} left)"
    else:
        if u["balance"] < PRICE_CREATION:
            await update.message.reply_text(f"❌ Need {PRICE_CREATION} PHP. Balance: {u['balance']}")
            return
        await update_user(uid, balance=u["balance"] - PRICE_CREATION)
        cost = f"💸 Charged {PRICE_CREATION} PHP (balance: {u['balance'] - PRICE_CREATION})"

    msg = await update.message.reply_text("⏳ Logging in device…")
    result = await asyncio.to_thread(full_check, device_id)

    if not result["success"]:
        await msg.edit_text(f"❌ Login failed: `{result['error']}`\n\n{cost}", parse_mode="Markdown")
        return
    await msg.edit_text(
        f"📅 *Creation Date:* `{fmt_creation(result['creation_ts'])}`\n"
        f"🆔 Account: `{result['account_id']}` | Zone: `{result['zone_id']}`\n\n{cost}",
        parse_mode="Markdown",
    )


async def cmd_check_ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if rate_limited(uid):
        return
    if not ctx.args:
        await update.message.reply_text("❌ Usage: `/check_ban <device_id>`", parse_mode="Markdown")
        return
    device_id = ctx.args[0].strip()
    await reset_daily_if_needed(uid)
    u = await get_user(uid)
    if u["free_ban"] > 0:
        await update_user(uid, free_ban=u["free_ban"] - 1)
        cost = f"✅ Free check used ({u['free_ban'] - 1} left)"
    else:
        if u["balance"] < PRICE_BAN:
            await update.message.reply_text(f"❌ Need {PRICE_BAN} PHP. Balance: {u['balance']}")
            return
        await update_user(uid, balance=u["balance"] - PRICE_BAN)
        cost = f"💸 Charged {PRICE_BAN} PHP (balance: {u['balance'] - PRICE_BAN})"

    msg = await update.message.reply_text("⏳ Logging in device & checking ban…")
    result = await asyncio.to_thread(full_check, device_id)

    if not result["success"]:
        await msg.edit_text(f"❌ Login failed: `{result['error']}`\n\n{cost}", parse_mode="Markdown")
        return
    status = "🚫 *BANNED*" if result["banned"] else "✅ *NOT BANNED*"
    await msg.edit_text(
        f"{status}\n"
        f"Reason: `{result.get('ban_reason', 'N/A')}`\n"
        f"Source: `{result.get('ban_source', 'N/A')}`\n"
        f"🆔 Account: `{result['account_id']}` | Zone: `{result['zone_id']}`\n\n{cost}",
        parse_mode="Markdown",
    )


async def cmd_lookup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if rate_limited(uid):
        return
    if not ctx.args:
        await update.message.reply_text("❌ Usage: `/lookup <device_id>`", parse_mode="Markdown")
        return
    device_id = ctx.args[0].strip()
    msg = await update.message.reply_text("⏳ Logging in & fetching account info…")
    result = await asyncio.to_thread(full_check, device_id)
    try:
        await msg.edit_text(render_single(result), parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(render_single(result))


async def cmd_diag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return
    if not ctx.args:
        await update.message.reply_text("❌ Usage: `/diag <device_id>`", parse_mode="Markdown")
        return
    device_id = ctx.args[0].strip()
    msg = await update.message.reply_text("⏳ Running diagnostics…")

    def _run():
        g = GameLogin(device_id)
        login_res = g.resolve()
        token = fetch_cn31_token()
        out = {
            "device_id": device_id,
            "login": login_res,
            "token_ok": bool(token),
            "token_preview": (token[:24] + "…") if token else None,
            "lookup_api": LOOKUP_API,
            "lookup_probe": None,
        }
        if login_res.get("success"):
            probe = fetch_profile_from_lookup_api(login_res["account_id"], login_res["zone_id"])
            out["lookup_probe"] = {
                "success": probe.get("success"),
                "source": probe.get("source"),
                "error": probe.get("error"),
                "data_keys": list(probe["data"].keys()) if probe.get("data") else None,
                "data_preview": {k: str(v)[:40] for k, v in list(probe.get("data", {}).items())[:10]} if probe.get("data") else None,
            }
        return out

    raw = await asyncio.to_thread(_run)
    try:
        pretty = json.dumps(raw, indent=2, default=str)
    except Exception as e:
        pretty = f"<json error: {e}>"

    for i in range(0, len(pretty), 3500):
        chunk = pretty[i:i + 3500]
        try:
            await update.message.reply_text(f"```json\n{chunk}\n```", parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(chunk)


# ============================================================
# BULK CHECK — live stats
# ============================================================
def render_bulk_live(stats: Dict) -> str:
    done = stats["done"]
    total = stats["total"]
    bar_len = 12
    filled = int(bar_len * done / total) if total else 0
    bar = "█" * filled + "░" * (bar_len - filled)

    def _short(dev):
        if not dev:
            return ""
        return f" `{dev[:14]}…`" if len(dev) > 14 else f" `{dev}`"

    lines = [
        f"📦 *Bulk Check — Live*",
        f"`[{bar}]` {done}/{total}",
        "",
        f"✅ Valid   : `{stats['valid']}`",
        f"❌ Invalid : `{stats['invalid']}`",
        f"🚫 Banned  : `{stats['banned']}`",
        "",
        f"🏆 *Highest Level* : `{stats['highest_level']}`{_short(stats['highest_level_dev'])}",
        f"🎨 *Highest Skins* : `{stats['highest_skin']}`{_short(stats['highest_skin_dev'])}",
        "",
        f"⏱ Elapsed: `{int(time.time() - stats['started'])}s`",
    ]
    return "\n".join(lines)


async def run_bulk(update: Update, ctx: ContextTypes.DEFAULT_TYPE, doc):
    f = await doc.get_file()
    buf = io.BytesIO()
    await f.download_to_memory(buf)
    buf.seek(0)
    try:
        text = buf.read().decode("utf-8", errors="ignore")
    except Exception as e:
        await update.message.reply_text(f"❌ Could not read file: {e}")
        return

    ids = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]
    seen = set()
    unique = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            unique.append(i)

    if not unique:
        await update.message.reply_text("❌ No device IDs found in file.")
        return

    stats = {
        "total": len(unique),
        "done": 0,
        "valid": 0,
        "invalid": 0,
        "banned": 0,
        "highest_level": 0,
        "highest_level_dev": None,
        "highest_skin": 0,
        "highest_skin_dev": None,
        "started": time.time(),
    }

    status = await update.message.reply_text(
        render_bulk_live(stats), parse_mode="Markdown"
    )

    results: List[Dict] = []
    sem = asyncio.Semaphore(3)
    last_edit = {"t": 0.0}
    EDIT_INTERVAL = 1.5  # seconds between Telegram edits

    async def worker(dev: str):
        async with sem:
            try:
                return await asyncio.to_thread(full_check, dev)
            except Exception as e:
                return {"success": False, "stage": "worker", "error": str(e), "device_id": dev}

    async def update_status(force: bool = False):
        now = time.time()
        if not force and now - last_edit["t"] < EDIT_INTERVAL:
            return
        last_edit["t"] = now
        try:
            await status.edit_text(render_bulk_live(stats), parse_mode="Markdown")
        except Exception:
            pass

    tasks = [worker(d) for d in unique]
    for coro in asyncio.as_completed(tasks):
        res = await coro
        results.append(res)
        stats["done"] += 1

        if res.get("success"):
            stats["valid"] += 1
            if res.get("banned"):
                stats["banned"] += 1
            p = res.get("profile") or {}
            lvl = _pick_int(p, "level", "account_level", "lvl")
            sk = _pick_int(p, "skin_count", "skins", "total_skins")
            if lvl > stats["highest_level"]:
                stats["highest_level"] = lvl
                stats["highest_level_dev"] = res.get("device_id")
            if sk > stats["highest_skin"]:
                stats["highest_skin"] = sk
                stats["highest_skin_dev"] = res.get("device_id")
        else:
            stats["invalid"] += 1

        await update_status()

    await update_status(force=True)

    # Final summary
    banned = [r for r in results if r.get("success") and r.get("banned")]
    clean = [r for r in results if r.get("success") and not r.get("banned")]
    failed = [r for r in results if not r.get("success")]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "clean": len(clean),
        "banned": len(banned),
        "failed": len(failed),
        "highest_level": stats["highest_level"],
        "highest_level_device": stats["highest_level_dev"],
        "highest_skin": stats["highest_skin"],
        "highest_skin_device": stats["highest_skin_dev"],
        "results": results,
    }
    report_path = REPORTS_DIR / f"bulk_report_{int(time.time())}.json"
    try:
        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not persist report: {e}")

    out = io.BytesIO(json.dumps(report, indent=2, default=str).encode("utf-8"))
    out.name = report_path.name

    summary = (
        f"📦 *Bulk Check Complete*\n\n"
        f"Total   : `{len(results)}`\n"
        f"✅ Valid : `{len(clean)}`\n"
        f"🚫 Banned: `{len(banned)}`\n"
        f"❌ Invalid: `{len(failed)}`\n\n"
        f"🏆 *Highest Level* : `{stats['highest_level']}`"
        + (f" — `{stats['highest_level_dev']}`" if stats["highest_level_dev"] else "")
        + "\n"
        f"🎨 *Highest Skins* : `{stats['highest_skin']}`"
        + (f" — `{stats['highest_skin_dev']}`" if stats["highest_skin_dev"] else "")
    )
    if banned:
        summary += "\n\n*Banned device IDs:*\n"
        for r in banned[:20]:
            summary += f"• `{r['device_id']}` — {r.get('ban_reason', 'N/A')}\n"
        if len(banned) > 20:
            summary += f"…and {len(banned) - 20} more (see report)\n"

    try:
        await status.edit_text(summary, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(summary, parse_mode="Markdown")
    await update.message.reply_document(document=out, filename=out.name)


async def cmd_bulk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return

    # Case A: a document is already attached / replied to
    doc = None
    if update.message.reply_to_message and update.message.reply_to_message.document:
        doc = update.message.reply_to_message.document
    elif update.message.document:
        doc = update.message.document

    if doc:
        await run_bulk(update, ctx, doc)
        return

    # Case B: enter "waiting for file" state
    uid = update.effective_user.id
    BULK_WAITING.add(uid)
    _bulk_wait_ts[uid] = time.time()
    await update.message.reply_text(
        "📦 *Bulk Check ready.*\n\n"
        "Now send your `.txt` file — one device ID per line.\n"
        "_You have 5 minutes._",
        parse_mode="Markdown",
    )


async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Catches the .txt file sent after /bulk."""
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        return
    if uid not in BULK_WAITING:
        return
    # Expire stale wait
    if time.time() - _bulk_wait_ts.get(uid, 0) > BULK_WAIT_TIMEOUT_SEC:
        BULK_WAITING.discard(uid)
        return
    BULK_WAITING.discard(uid)
    _bulk_wait_ts.pop(uid, None)
    await run_bulk(update, ctx, update.message.document)


# ============================================================
# OTHER HANDLERS
# ============================================================
async def cmd_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await reset_daily_if_needed(uid)
    u = await get_user(uid)
    await update.message.reply_text(
        f"💰 Balance: `{u['balance']}` PHP\n"
        f"🆓 Free creation: `{u['free_creation']}`\n"
        f"🆓 Free ban: `{u['free_ban']}`",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )


async def cmd_redeem(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("❌ Usage: `/redeem <code>`", parse_mode="Markdown")
        return
    code = ctx.args[0].strip().upper()
    ok, amount = await redeem_code(update.effective_user.id, code)
    if ok:
        await update.message.reply_text(f"✅ Redeemed {amount} PHP!")
    else:
        await update.message.reply_text("❌ Invalid or already used code.")


async def cmd_gencode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return
    if not ctx.args:
        await update.message.reply_text("❌ Usage: `/gencode <amount>`", parse_mode="Markdown")
        return
    try:
        amount = int(ctx.args[0])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Amount must be positive integer.")
        return
    code = await generate_code(amount)
    await update.message.reply_text(f"✅ Code: `{code}` ({amount} PHP)", parse_mode="Markdown")


async def cmd_unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Unknown command. Use /start.")


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Handler exception: {ctx.error}", exc_info=ctx.error)


# ============================================================
# STARTUP / MAIN
# ============================================================
async def post_init(application: Application) -> None:
    await init_db()
    logger.info("Bot initialized — DB ready.")
    print("🤖 Bot running. Ctrl+C to stop.")
    print(f"🌐 Proxies loaded: {len(PROXY_LIST)}")
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"📂 Data dir: {DATA_DIR}")
    print(f"🗄  DB: {DB_PATH}")
    print(f"🔍 Lookup API: {LOOKUP_API}")


def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN env var is missing.")
        return
    if ADMIN_ID == 0:
        print("⚠️ ADMIN_ID env var is missing or zero — admin commands will be unusable.")

    load_proxies()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("check_creation", cmd_check_creation))
    app.add_handler(CommandHandler("check_ban", cmd_check_ban))
    app.add_handler(CommandHandler("lookup", cmd_lookup))
    app.add_handler(CommandHandler("diag", cmd_diag))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("redeem", cmd_redeem))
    app.add_handler(CommandHandler("gencode", cmd_gencode))
    app.add_handler(CommandHandler("bulk", cmd_bulk))

    # Document handler — picks up the .txt file after /bulk
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    app.add_handler(CallbackQueryHandler(cb_menu))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))
    app.add_error_handler(on_error)

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
        poll_interval=1.0,
        timeout=30,
    )


if __name__ == "__main__":
    main()
