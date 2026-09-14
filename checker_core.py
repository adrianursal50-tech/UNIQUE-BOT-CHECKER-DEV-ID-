"""
MLBB Device ID Checker — Core Module
Pure logic, no CLI, no rich. Importable.
Includes ACCURATE ban check (reason + remaining time) from shin.py.
"""
from __future__ import annotations
import datetime, hashlib, logging, os, random, socket, struct, uuid, zlib
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

try:
    import zstandard as zstd
except ImportError:
    raise SystemExit("pip install zstandard")

try:
    from Crypto.Cipher import AES
except ImportError:
    raise SystemExit("pip install pycryptodome")

# ---------------- Config ----------------
LOGIN_HOST       = os.environ.get("MLBB_LOGIN_HOST", "login.ml.youngjoygame.com")
LOGIN_PORT       = int(os.environ.get("MLBB_LOGIN_PORT", "30021"))
CLIENT_VERSION   = os.environ.get("MLBB_CLIENT_VERSION", "2.1.88.1205.1")
CHANNEL          = os.environ.get("MLBB_CHANNEL", "and_usa")
LANGUAGE         = os.environ.get("MLBB_LANG", "en")
SOCKET_TIMEOUT   = float(os.environ.get("MLBB_SOCK_TIMEOUT", "3.0"))
CONNECT_TIMEOUT  = float(os.environ.get("MLBB_CONNECT_TIMEOUT", "5.0"))
TCP_NODELAY      = os.environ.get("MLBB_TCP_NODELAY", "1").lower() in ("1", "true", "yes")
RECV_CHUNK       = 8192

# ---------------- Hero map ----------------
HERO_ID_MAP: Dict[int, str] = {
    1:"Miya",2:"Balmond",3:"Saber",4:"Alice",5:"Nana",6:"Tigreal",7:"Alucard",8:"Karina",
    9:"Akai",10:"Franco",11:"Bane",12:"Bruno",13:"Clint",14:"Rafaela",15:"Eudora",16:"Zilong",
    17:"Fanny",18:"Layla",19:"Minotaur",20:"Lolita",21:"Hayabusa",22:"Freya",23:"Gord",24:"Natalia",
    25:"Kagura",26:"Chou",27:"Sun",28:"Alpha",29:"Ruby",30:"Yi Sun-shin",31:"Moskov",32:"Johnson",
    33:"Cyclops",34:"Estes",35:"Hilda",36:"Aurora",37:"Lapu-Lapu",38:"Vexana",39:"Roger",40:"Karrie",
    41:"Gatotkaca",42:"Harley",43:"Irithel",44:"Grock",45:"Argus",46:"Odette",47:"Lancelot",48:"Diggie",
    49:"Hylos",50:"Zhask",51:"Helcurt",52:"Pharsa",53:"Lesley",54:"Jawhead",55:"Angela",56:"Gusion",
    57:"Valir",58:"Martis",59:"Uranus",60:"Hanabi",61:"Chang'e",62:"Kaja",63:"Selena",64:"Aldous",
    65:"Claude",66:"Vale",67:"Leomord",68:"Lunox",69:"Hanzo",70:"Belerick",71:"Kimmy",72:"Thamuz",
    73:"Harith",74:"Minsitthar",75:"Kadita",76:"Faramis",77:"Badang",78:"Khufra",79:"Granger",
    80:"Guinevere",81:"Esmeralda",82:"Terizla",83:"X.Borg",84:"Ling",85:"Dyrroth",86:"Lylia",87:"Baxia",
    88:"Masha",89:"Wanwan",90:"Silvanna",91:"Cecilion",92:"Carmilla",93:"Atlas",94:"Popol and Kupa",
    95:"Yu Zhong",96:"Luo Yi",97:"Benedetta",98:"Khaleed",99:"Barats",100:"Brody",101:"Yve",
    102:"Mathilda",103:"Paquito",104:"Gloo",105:"Beatrix",106:"Phoveus",107:"Natan",108:"Aulus",
    109:"Aamon",110:"Valentina",111:"Edith",112:"Floryn",113:"Yin",114:"Melissa",115:"Xavier",
    116:"Julian",117:"Fredrinn",118:"Joy",119:"Novaria",120:"Arlott",121:"Ixia",122:"Nolan",
    123:"Cici",124:"Chip",125:"Zhuxin",126:"Suyou",127:"Lukas",128:"Kalea",129:"Zetian",130:"Obsidia"
}

def hero_name(hid: int) -> str:
    return HERO_ID_MAP.get(hid, f"Unknown({hid})")

# ---------------- Rank ----------------
RANK_DEFS = [
    (0,4,"Warrior III"),(5,9,"Warrior II"),(10,14,"Warrior I"),
    (15,19,"Elite IV"),(20,24,"Elite III"),(25,29,"Elite II"),(30,34,"Elite I"),
    (35,39,"Master IV"),(40,44,"Master III"),(45,49,"Master II"),(50,54,"Master I"),
    (55,59,"Grandmaster IV"),(60,64,"Grandmaster III"),(65,69,"Grandmaster II"),(70,74,"Grandmaster I"),
    (75,81,"Epic IV"),(82,88,"Epic III"),(89,95,"Epic II"),(96,107,"Epic I"),
    (108,114,"Legend IV"),(115,121,"Legend III"),(122,128,"Legend II"),(129,135,"Legend I"),
    (136,160,lambda p: f"Mythic {p-135}"),
    (161,195,lambda p: f"Mythical Honor {p-135}"),
    (196,235,lambda p: f"Mythical Glory {p-157}"),
    (236,999,lambda p: f"Mythical Immortal {p-157}"),
]

def map_rank(p: int) -> str:
    for mn, mx, r in RANK_DEFS:
        if mn <= p <= mx:
            return r(p) if callable(r) else r
    return "Unknown"

COLLECTOR_TIERS = [(0,"None"),(1,"Collector I"),(100,"Collector II"),(300,"Collector III"),
                   (600,"Collector IV"),(1000,"Collector V"),(2000,"Collector VI"),(5000,"Collector VII")]

def map_collector(pts: int) -> str:
    t = "None"
    for th, lb in COLLECTOR_TIERS:
        if pts >= th: t = lb
    return t

_AFFINITY = {0:"None",1:"Bronze",2:"Silver",3:"Gold",4:"Platinum",5:"Diamond"}
_BAN_CODES = {1:"Banned(perm)",2:"Banned(temp)",3:"Banned",4:"Suspended",5:"Restricted"}

def fmt_ts(ts: int) -> str:
    if not ts: return "Never"
    try:
        return datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(ts)

# ---------------- AES ----------------
AES_KEY = bytes.fromhex("f5a193d50ade553e9835595f5cd75ddd")
AES_IV  = b"\x00" * 16

def aes_decrypt(data: bytes) -> bytes:
    c = AES.new(AES_KEY, AES.MODE_CBC, iv=AES_IV)
    return c.decrypt(data[:-1] if len(data) % 16 != 0 else data)

# ---------------- SDP ----------------
class SdpDataType(Enum):
    INTEGER_POSITIVE = 0; INTEGER_NEGATIVE = 1; FLOAT = 2; DOUBLE = 3
    STRING = 4; LIST = 5; DICT = 6; STRUCT_BEGIN = 7; STRUCT_END = 8

class SdpException(Exception): pass

class SdpStruct(dict):
    def __init__(self, data: Any=None):
        super().__init__()
        self.data = b""; self.offset = 0
        if isinstance(data, bytes):
            self.data = data; self._unpack_bin()
        elif data is not None:
            super().update(data); self._pack_bin()

    def _pack_bin(self):
        self.data = bytes([SdpDataType.STRUCT_BEGIN.value << 4])
        for t, v in sorted(self.items()):
            self._pk(t, v)
        self.data += bytes([SdpDataType.STRUCT_END.value << 4])

    def _wn(self, v: int) -> bytes:
        r = bytearray()
        while v >= 128:
            r.append(v & 127 | 128); v >>= 7
        r.append(v & 127); return bytes(r)

    def _ph(self, tag: int, dt: SdpDataType):
        if tag < 15: self.data += bytes([dt.value << 4 | tag])
        else:
            self.data += bytes([dt.value << 4 | 15]); self.data += self._wn(tag)

    def _pk(self, tag: int, value: Any):
        if isinstance(value, bool):
            self._ph(tag, SdpDataType.INTEGER_POSITIVE); self.data += self._wn(1 if value else 0)
        elif isinstance(value, int):
            if value < 0:
                self._ph(tag, SdpDataType.INTEGER_NEGATIVE); self.data += self._wn(-value)
            else:
                self._ph(tag, SdpDataType.INTEGER_POSITIVE); self.data += self._wn(value)
        elif isinstance(value, float):
            self._ph(tag, SdpDataType.DOUBLE); p = struct.pack("<d", value)
            self.data += self._wn(len(p)); self.data += p
        elif isinstance(value, (str, bytes)):
            self._ph(tag, SdpDataType.STRING)
            e = value.encode() if isinstance(value, str) else value
            self.data += self._wn(len(e)); self.data += e
        elif isinstance(value, list):
            self._ph(tag, SdpDataType.LIST); self.data += self._wn(len(value))
            for i in value: self._pk(0, i)
        elif isinstance(value, dict):
            if isinstance(value, SdpStruct):
                self._ph(tag, SdpDataType.STRUCT_BEGIN)
                for k, v in sorted(value.items()): self._pk(k, v)
                self.data += bytes([SdpDataType.STRUCT_END.value << 4])
            else:
                self._ph(tag, SdpDataType.DICT); self.data += self._wn(len(value))
                for k, v in sorted(value.items()):
                    self._pk(0, k); self._pk(0, v)
        else:
            raise SdpException(f"bad type {type(value)}")

    def _unpack_bin(self):
        if not self.data: return
        if self.data[0] >> 4 == SdpDataType.STRUCT_BEGIN.value: self.offset = 1
        while self.offset < len(self.data):
            t, v = self._up()
            if isinstance(v, SdpDataType) and v == SdpDataType.STRUCT_END: break
            self[t] = v

    def _rn(self) -> int:
        n = 1; val = self.data[self.offset] & 127
        while self.data[self.offset + n - 1] >= 128:
            val |= (self.data[self.offset + n] & 127) << 7 * n; n += 1
        self.offset += n; return val

    def _up(self) -> Tuple[int, Any]:
        if self.offset >= len(self.data): return (0, None)
        h = self.data[self.offset]; tag = h & 15; dt = SdpDataType(h >> 4); self.offset += 1
        if tag == 15: tag = self._rn()
        if dt == SdpDataType.INTEGER_POSITIVE: return (tag, self._rn())
        if dt == SdpDataType.INTEGER_NEGATIVE: return (tag, -self._rn())
        if dt == SdpDataType.FLOAT:  return (tag, struct.unpack("<f", self._rn().to_bytes(4,"little"))[0])
        if dt == SdpDataType.DOUBLE: return (tag, struct.unpack("<d", self._rn().to_bytes(8,"little"))[0])
        if dt == SdpDataType.STRING:
            ln = self._rn()
            try: v = self.data[self.offset:self.offset+ln].decode()
            except Exception: v = self.data[self.offset:self.offset+ln]
            self.offset += ln; return (tag, v)
        if dt == SdpDataType.LIST:
            ln = self._rn(); items = []
            for _ in range(ln):
                _, i = self._up(); items.append(i)
            return (tag, items)
        if dt == SdpDataType.DICT:
            ln = self._rn(); d = {}
            for _ in range(ln):
                _, k = self._up(); _, v = self._up(); d[k] = v
            return (tag, d)
        if dt == SdpDataType.STRUCT_BEGIN:
            sub = {}
            while True:
                st, sv = self._up()
                if isinstance(sv, SdpDataType) and sv == SdpDataType.STRUCT_END: break
                sub[st] = sv
            return (tag, SdpStruct(sub))
        if dt == SdpDataType.STRUCT_END: return (tag, SdpDataType.STRUCT_END)
        raise SdpException("unpack error")

    def copy(self): return SdpStruct(super().copy())
    def update(self, o): super().update(o); self._pack_bin()

def _frame(pid: int, seq: int, payload: bytes) -> bytes:
    pkt = SdpStruct({0: pid, 1: seq, 5: payload}).data
    buf = zstd.compress(pkt)
    return (len(buf) + 4 | 16 << 24).to_bytes(4, "big") + buf

def _decode(ct: int, data: bytes) -> bytes:
    if ct == 1:  return zlib.decompress(data)
    if ct == 16: return zstd.decompress(data)
    if ct == 2:  return aes_decrypt(data).rstrip(b"\x00")
    if ct == 3:  return zlib.decompress(aes_decrypt(data).rstrip(b"\x00"))
    if ct == 18: return zstd.decompress(aes_decrypt(data).rstrip(b"\x00"))
    return data

# ---------------- Connection ----------------
class BaseConnection:
    def __init__(self, host, port):
        self.host = host; self.port = port; self.sequence = 1
        self.socket: Optional[socket.socket] = None; self.queue_data = b""

    def connect(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if TCP_NODELAY: s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.settimeout(CONNECT_TIMEOUT); s.connect((self.host, self.port))
        s.settimeout(SOCKET_TIMEOUT); self.socket = s

    def cleanup(self):
        if self.socket:
            try: self.socket.close()
            except Exception: pass
            self.socket = None; self.sequence = 1; self.queue_data = b""

    def send_data(self, pid, sdp: SdpStruct):
        self.socket.send(_frame(pid, self.sequence, sdp.data)); self.sequence += 1

    def recv_data(self):
        try:
            while len(self.queue_data) < 4:
                d = self.socket.recv(RECV_CHUNK)
                if not d: return (None, None)
                self.queue_data += d
            flags = int.from_bytes(self.queue_data[:4], "big")
            size = flags & 16777215; ct = flags >> 24
            while len(self.queue_data) < size:
                d = self.socket.recv(RECV_CHUNK)
                if not d: return (None, None)
                self.queue_data += d
            data = self.queue_data[4:size]; self.queue_data = self.queue_data[size:]
            data = _decode(ct, data); r = SdpStruct(data); pid = r[0]
            if pid is None: return (None, None)
            res = r.get(6) or r.get(5)
            if not res or not isinstance(res, bytes): return (pid, None)
            return (pid, SdpStruct(res))
        except socket.timeout: return (-1, None)
        except Exception:      return (None, None)


class GameConnection(BaseConnection):
    def __init__(self, device_id: str, device_model: Optional[str]=None):
        super().__init__(LOGIN_HOST, LOGIN_PORT)
        self.device_id = device_id
        self.device_model = device_model or "Xiaomi:Redmi Note 12"
        self.imei_md5, self.android_id, self.advertising_id = self._parse(device_id)
        self.account_id = 0; self.session_key = ""; self.zone_id = 0
        self.game_server_host = ""; self.game_server_port = 0
        self.ban_status = "Unknown"; self.ban_end_ts = 0
        self.is_guest = False

    @staticmethod
    def _parse(did: str):
        parts = did.split("_")
        if len(parts) >= 2:
            info = parts[1]
            if len(parts) >= 3 and len(info) < 32: info += "_" + parts[2]
            if len(info) >= 32:
                imei = info[:32]
                android = info[32:48] if len(info) >= 48 else ""
                adv = info[48:] if len(info) > 48 else ""
            else:
                imei = info; android = ""; adv = ""
        else:
            imei = did; android = ""; adv = ""
        return (imei, android, adv)

    def login_to_login_server(self) -> bool:
        self.send_data(1, SdpStruct({
            0: self.device_id,
            1: f"gps_adid={self.advertising_id}&android_id={self.android_id}&device_unique_id={self.imei_md5}",
            2: CLIENT_VERSION, 3: CHANNEL, 4: LANGUAGE,
        }))
        pid, res = self.recv_data()
        if pid == 2 and res:
            acc = res.get(0)
            # Guest rejection
            if acc is None or str(acc).startswith(("221", "222")):
                self.is_guest = True
                self.ban_status = "UNREGISTERED"
                return False
            self.account_id = acc
            self.session_key = res[1]
            self.zone_id = res[2][0]
            err = res.get(10, 0)
            if err in (3,4,5,6,100,101,102):
                self.ban_status = "BANNED"; self.ban_end_ts = res.get(20, 0)
            return True
        return False

    def get_game_server(self) -> bool:
        self.send_data(5, SdpStruct({0: self.account_id, 1: self.session_key,
                                     2: CLIENT_VERSION, 5: self.zone_id, 6: CHANNEL}))
        pid, res = self.recv_data()
        if pid == 6 and res:
            try:
                host, port = res[1].split(":")
                self.game_server_host = host; self.game_server_port = int(port)
                return True
            except Exception:
                return False
        return False

    def connect_to_game_server(self) -> bool:
        self.cleanup(); self.host = self.game_server_host
        self.port = self.game_server_port; self.connect()
        self.send_data(10001, SdpStruct({0: self.account_id, 1: self.session_key,
                                         2: self.zone_id, 4: CLIENT_VERSION,
                                         13: CHANNEL, 15: self.device_id}))
        for _ in range(20):
            pid, _ = self.recv_data()
            if pid is None or pid == -1: return False
            if pid == 10002: return True
            if pid == 20001: continue   # early ban info — keep reading
            return False
        return False

    def _drain_queue(self):
        """Flush stale packets before ban-check response."""
        if not self.socket: return
        try: self.socket.settimeout(0.2)
        except Exception: return
        try:
            for _ in range(20):
                try:
                    pid, _res = self.recv_data()
                except Exception:
                    break
                if pid in (-1, None): break
        finally:
            try: self.socket.settimeout(SOCKET_TIMEOUT)
            except Exception: pass

    # ============================================================
    # ACCURATE BAN CHECK  (ported from shin.py)
    # ============================================================
    def check_ban_status(self) -> Dict[str, Any]:
        """
        PID 10101 {0:0, 2:2} → response PID 20001 (ban info) / 20002 (clean).
        Returns: {banned, reason, remaining, label}
        """
        if self.is_guest or (self.account_id and str(self.account_id).startswith(("221", "222"))):
            return {"banned": False, "reason": "", "remaining": "", "label": "UNREGISTERED"}

        self._drain_queue()
        self.send_data(10101, SdpStruct({0: 0, 2: 2}))
        for _ in range(6):
            pid, res = self.recv_data()
            if pid == 20002:
                return {"banned": False, "reason": "", "remaining": "", "label": "Not Banned"}
            if pid == 20001 and res and isinstance(res, dict) and 0 in res and isinstance(res[0], dict):
                b = res[0]
                reason = b.get("ban_reason", "")
                d = b.get("endtime_day", "0"); h = b.get("endtime_hour", "0")
                m = b.get("endtime_min", "0"); s = b.get("endtime_sec", "0")
                try:
                    total = int(d)*86400 + int(h)*3600 + int(m)*60 + int(s)
                except Exception:
                    total = 0
                if reason and str(reason).strip() and total > 0:
                    label = f"Banned (Reason: {reason} | {d}d {h}h {m}m {s}s)"
                    return {"banned": True, "reason": str(reason),
                            "remaining": f"{d}d {h}h {m}m {s}s", "label": label}
                return {"banned": False, "reason": "", "remaining": "", "label": "Not Banned"}
            if pid in (-1, None):
                break
        return {"banned": False, "reason": "", "remaining": "", "label": "Not Banned"}

    def lookup_player(self, search_value, search_type="id", server_filter=None):
        ldata = SdpStruct({1: int(search_value)}) if search_type == "id" \
                else SdpStruct({0: str(search_value).strip()})
        self.send_data(11153, ldata); cnt = 0
        while True:
            pid, res = self.recv_data()
            if pid is None or pid == -1: return None
            if pid == 11154:
                if search_type == "nickname" and server_filter is not None:
                    if res and res.get(0):
                        for p in res[0]:
                            if isinstance(p, dict) and p.get(1) == server_filter:
                                return SdpStruct({0: [p]})
                    return None
                return res
            if pid == 20001:
                cnt += 1
                if cnt >= 5: return None

# ---------------- Extract ----------------
def extract_player_data(result) -> Optional[Dict[str, Any]]:
    if not result or not result.get(0) or len(result[0]) == 0: return None
    try:
        pd = result[0][0]
        nickname = pd.get(2, "Unknown"); player_id = pd.get(0, "Unknown")
        server = pd.get(1, "Unknown"); level = pd.get(3, "Unknown")
        try: skin_count = int(pd.get(83, 0))
        except Exception: skin_count = 0
        last_login = fmt_ts(pd.get(5, 0)); llc = pd.get(87, "Unknown")
        hero_count = pd.get(4, 0); win = pd.get(18, 0); loss = pd.get(155, 0)
        total = win + loss
        wr = f"{win / total * 100:.2f}%" if total > 0 else "N/A"
        loc = "NOT FOUND"; ld = pd.get(71)
        if ld and isinstance(ld, list) and len(ld) >= 2:
            loc = ", ".join(str(x) for x in ld)
        sn = str(pd.get(30, "")).replace("`", "").strip(); si = str(pd.get(31, ""))
        squad = f"{si} {sn}".strip() if sn else "—"
        sqid = pd.get(34, pd.get(28, 0)); squad_id = f"Squad ID: {sqid}" if sqid else "N/A"
        hr = map_rank(pd.get(95)) if pd.get(95) is not None else "Unknown"
        cr = map_rank(pd.get(8))  if pd.get(8)  is not None else "Unknown"
        t136 = pd.get(136, {})
        cpt = t136.get(9, 0) if isinstance(t136, dict) else 0
        ctier = map_collector(cpt)
        aff_lv = (pd.get(135, {}) or {}).get(1, 0)
        affinity = _AFFINITY.get(aff_lv, f"Lv{aff_lv}") if aff_lv else "None"
        cac = pd.get(97, "Unknown")
        t91 = pd.get(91, [])
        lmh = hero_name(t91[0]) if isinstance(t91, list) and t91 else None
        prev: List[str] = []
        if isinstance(t91, list) and len(t91) > 1:
            seen = set()
            for hid in t91[1:]:
                if hid not in seen:
                    seen.add(hid); prev.append(hero_name(hid))
                if len(prev) >= 5: break
        lm = {"hero_name": lmh, "prev": prev} if lmh else None
        return {
            "nickname": nickname, "player_id": player_id, "server": server, "level": level,
            "ban_status": "Not Banned", "ban_end": "N/A",
            "ban_reason": "", "ban_remaining": "", "is_banned": False,
            "skin_count": skin_count,
            "last_login": last_login, "last_login_country": llc, "create_country": cac,
            "hero_count": hero_count, "location": loc, "high_rank": hr, "current_rank": cr,
            "collector_tier": ctier, "squad": squad, "squad_id": squad_id, "affinity": affinity,
            "total_battles": total, "win_rate": wr, "last_match": lm,
        }
    except Exception as e:
        logging.debug("parse error: %s", e)
        return None

# ---------------- Check ----------------
def check_device_id(device_id: str) -> Dict[str, Any]:
    device_id = (device_id or "").strip()
    if not device_id or len(device_id) < 10:
        return {"status": "error", "device_id": device_id, "error": "ID too short"}

    conn: Optional[GameConnection] = None
    try:
        conn = GameConnection(device_id); conn.connect()
        if not conn.login_to_login_server():
            conn.cleanup()
            if conn.is_guest:
                return {"status": "error", "device_id": device_id, "error": "Guest / unregistered"}
            return {"status": "error", "device_id": device_id, "error": "Login failed"}

        aid = conn.account_id
        if not aid:
            conn.cleanup()
            return {"status": "error", "device_id": device_id, "error": "No account linked"}

        if not conn.get_game_server():
            conn.cleanup()
            return {"status": "error", "device_id": device_id, "error": "Server resolve failed"}

        if not conn.connect_to_game_server():
            conn.cleanup()
            return {"status": "error", "device_id": device_id, "error": "Handshake failed"}

        # ── ACCURATE BAN CHECK (before lookup, same socket) ──
        try:
            ban = conn.check_ban_status()
        except Exception as e:
            logging.debug("ban check failed: %s", e)
            ban = {"banned": False, "reason": "", "remaining": "", "label": "Not Banned"}

        result = conn.lookup_player(aid, search_type="id")
        conn.cleanup()

        if not result:
            if ban["banned"]:
                return {"status": "error", "device_id": device_id,
                        "error": ban["label"], "ban": ban}
            return {"status": "error", "device_id": device_id, "error": "Lookup returned no data"}

        player = extract_player_data(result)
        if not player:
            return {"status": "error", "device_id": device_id, "error": "Parse failed"}

        # Merge ban result (authoritative)
        player["ban_status"]    = ban["label"]
        player["ban_reason"]    = ban["reason"]
        player["ban_remaining"] = ban["remaining"]
        player["is_banned"]     = ban["banned"]

        return {"status": "success", "device_id": device_id, "player_data": player}
    except Exception as exc:
        if conn:
            try: conn.cleanup()
            except Exception: pass
        return {"status": "error", "device_id": device_id, "error": str(exc)}

# ---------------- Utils ----------------
def generate_device_ids(count: int) -> List[str]:
    out = []
    for _ in range(count):
        imei = "".join(str(random.randint(0, 9)) for _ in range(15))
        md5 = hashlib.md5(imei.encode()).hexdigest()
        aid = "%016x" % random.getrandbits(64)
        adv = str(uuid.UUID(int=random.getrandbits(128)))
        out.append(f"and_{md5}{aid}{adv}")
    return out

def read_ids_from_text(text: str) -> List[str]:
    out = []
    for line in text.splitlines():
        r = line.strip()
        if r and not r.startswith("#"):
            out.append(r)
    return out

def save_line(did: str, p: Dict[str, Any]) -> str:
    lm = p.get("last_match") or {}
    lh = lm.get("hero_name", "N/A")
    ban = p.get("ban_status", "N/A")
    reason = p.get("ban_reason", "") or ""
    remaining = p.get("ban_remaining", "") or ""
    ban_f = ban
    if p.get("is_banned") or ("Banned" in ban) or ("Suspended" in ban):
        parts = [ban]
        if reason:    parts.append(f"reason={reason}")
        if remaining: parts.append(f"left={remaining}")
        ban_f = " | ".join(parts)
    return (f"Device ID: {did} | Name: {p.get('nickname','N/A')} | Role ID: {p.get('player_id','N/A')} | "
            f"Server ID: {p.get('server','N/A')} | Level: {p.get('level','N/A')} | Ban: {ban_f} | "
            f"Skin: {p.get('skin_count','N/A')} | Last Login: {p.get('last_login','N/A')} | "
            f"Country: {p.get('last_login_country','N/A')} | Rank: {p.get('current_rank','N/A')} | "
            f"High Rank: {p.get('high_rank','N/A')} | Win Rate: {p.get('win_rate','N/A')} | "
            f"Heroes: {p.get('hero_count',0)} | Matches: {p.get('total_battles',0)} | "
            f"Last Hero: {lh} | Squad: {p.get('squad','—')} | Collector: {p.get('collector_tier','None')} | "
            f"Reg: {p.get('create_country','N/A')}")