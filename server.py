"""Hub con cuentas, dispositivos y variables compartidas entre cuentas."""
import asyncio, hashlib, hmac, io, ipaddress, json, os, re, secrets, socket, sqlite3, time, zipfile
from pathlib import Path
from urllib.parse import urlparse
import aiohttp
from aiohttp import web, WSMsgType
from aiohttp.abc import AbstractResolver

HERE = Path(__file__).parent
try:
    VERSION = (HERE / "VERSION").read_text().strip() or "1.3"
except OSError:
    VERSION = "1.3"
VERSION_RE = re.compile(r"\d{1,3}\.\d{1,3}(\.\d{1,3})?")
DB = sqlite3.connect(os.environ.get("DB_PATH", HERE / "hub.db"), check_same_thread=False)
DB.executescript("""
CREATE TABLE IF NOT EXISTS users(name TEXT PRIMARY KEY, salt BLOB, hash BLOB, avatar TEXT);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user TEXT, exp REAL);
CREATE TABLE IF NOT EXISTS devices(owner TEXT, id TEXT, name TEXT, platform TEXT, kind TEXT, PRIMARY KEY(owner, id));
CREATE TABLE IF NOT EXISTS vars(id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, name TEXT, kind TEXT,
                                value TEXT, device_id TEXT, metric TEXT);
CREATE TABLE IF NOT EXISTS shares(var_id INTEGER, with_user TEXT, PRIMARY KEY(var_id, with_user));
CREATE TABLE IF NOT EXISTS api_keys(id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, label TEXT, hash TEXT UNIQUE,
                                    prefix TEXT, created REAL);
CREATE TABLE IF NOT EXISTS widgets(id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, name TEXT, text TEXT, size INTEGER,
                                   color TEXT, bg TEXT, opacity INTEGER, w INTEGER, h INTEGER, ontop INTEGER);
""")
DB.executescript("""
CREATE TABLE IF NOT EXISTS widget_devices(widget_id INTEGER, device_id TEXT, PRIMARY KEY(widget_id, device_id));
CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, owner TEXT, name TEXT, mime TEXT, data BLOB, size INTEGER, created REAL);
""")
DB.execute("""CREATE TABLE IF NOT EXISTS automations(id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, name TEXT, enabled INTEGER DEFAULT 1,
              var_id INTEGER, op TEXT, value TEXT, kind TEXT, url TEXT, body TEXT, cooldown INTEGER DEFAULT 60,
              last_state INTEGER, last_value TEXT, last_fired REAL, last_status TEXT, created REAL)""")
DB.execute("""CREATE TABLE IF NOT EXISTS connections(owner TEXT, service TEXT, cfg TEXT, PRIMARY KEY(owner, service))""")
DB.execute("""CREATE TABLE IF NOT EXISTS passkeys(id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, cred_id TEXT UNIQUE,
              pubkey BLOB, alg INTEGER, sign_count INTEGER, label TEXT, created REAL)""")
for alter in ("ALTER TABLE users ADD COLUMN lock_salt BLOB", "ALTER TABLE users ADD COLUMN lock_hash BLOB",
              "ALTER TABLE users ADD COLUMN unlocked_until REAL", "ALTER TABLE users ADD COLUMN uid TEXT",
              "ALTER TABLE users ADD COLUMN avatar TEXT", "ALTER TABLE vars ADD COLUMN param TEXT",
              "ALTER TABLE widgets ADD COLUMN data TEXT", "ALTER TABLE widgets ADD COLUMN rev INTEGER DEFAULT 1",
              "ALTER TABLE devices ADD COLUMN cameras TEXT", "ALTER TABLE devices ADD COLUMN client_version TEXT",
              "ALTER TABLE users ADD COLUMN debug INTEGER DEFAULT 0", "ALTER TABLE users ADD COLUMN banned REAL"):
    try:  # bases de datos de versiones anteriores no tenian estas columnas
        DB.execute(alter)
    except sqlite3.OperationalError:
        pass



DB.executescript("""
CREATE TABLE IF NOT EXISTS bans(kind TEXT, value TEXT, user TEXT, created REAL, PRIMARY KEY(kind, value));
CREATE TABLE IF NOT EXISTS user_ips(user TEXT, ip TEXT, last REAL, PRIMARY KEY(user, ip));
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
""")
if not DB.execute("SELECT 1 FROM users WHERE debug=1").fetchone():   # el servidor siempre tiene al menos un depurador
    _first = DB.execute("SELECT name FROM users WHERE name='crispo'").fetchone() or DB.execute("SELECT name FROM users ORDER BY rowid LIMIT 1").fetchone()
    if _first:
        DB.execute("UPDATE users SET debug=1 WHERE name=?", (_first[0],))
DB.commit()


def _num(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(float(v))))
    except (TypeError, ValueError):
        return default


def _col(v, default):
    return str(v).lower() if isinstance(v, str) and HEXRE.fullmatch(v) else default


def _url(v):
    v = str(v or "")[:500]
    return v if re.match(r"https?://", v) else ""


def clean_widget_data(d):
    """Valida el diseño completo de un widget: solo claves conocidas, numeros en rango, colores #rrggbb, URLs http(s)."""
    d = d if isinstance(d, dict) else {}
    out = {"w": _num(d.get("w"), 80, 1600, 360), "h": _num(d.get("h"), 40, 1200, 160),
           "bg": _col(d.get("bg"), "#808080"), "opacity": _num(d.get("opacity"), 0, 100, 60),
           "border": _col(d.get("border"), "#00a8f3"), "borderw": _num(d.get("borderw"), 0, 12, 0),
           "radius": _num(d.get("radius"), 0, 80, 16), "shadow": _num(d.get("shadow"), 0, 40, 0),
           "ontop": bool(d.get("ontop")), "objects": []}
    for o in (d.get("objects") or [])[:30]:
        if not isinstance(o, dict) or o.get("type") not in OBJ_TYPES:
            continue
        t = o["type"]
        c = {"id": re.sub(r"[^\w-]", "", str(o.get("id") or ""))[:16] or secrets.token_hex(4), "type": t,
             "x": _num(o.get("x"), -2000, 4000, 0), "y": _num(o.get("y"), -2000, 4000, 0),
             "w": _num(o.get("w"), 10, 2000, 100), "h": _num(o.get("h"), 10, 2000, 50)}
        if t == "text":
            c.update(text=str(o.get("text", ""))[:2000], size=_num(o.get("size"), 6, 200, 20),
                     color=_col(o.get("color"), "#ffffff"), bold=bool(o.get("bold")), italic=bool(o.get("italic")),
                     align=o.get("align") if o.get("align") in ("left", "center", "right") else "left",
                     valign=o.get("valign") if o.get("valign") in ("top", "middle", "bottom") else "top",
                     font=o.get("font") if o.get("font") in FONTS else "Segoe UI")
        elif t == "image":
            src = str(o.get("src") or "")
            src = src if src.startswith("asset:") and ASSETRE.fullmatch(src[6:]) else _url(src)
            c.update(src=src, fit=o.get("fit") if o.get("fit") in ("cover", "contain", "fill") else "cover",
                     radius=_num(o.get("radius"), 0, 200, 0))
        elif t == "document":
            a = str(o.get("asset") or "")
            c.update(asset=a if ASSETRE.fullmatch(a) else "", kind="pdf" if o.get("kind") == "pdf" else "text",
                     name=str(o.get("name", ""))[:80], size=_num(o.get("size"), 6, 80, 14), color=_col(o.get("color"), "#ffffff"))
        elif t == "camera":
            c.update(mirror=bool(o.get("mirror")), radius=_num(o.get("radius"), 0, 200, 0), device=str(o.get("device", ""))[:80])
        elif t == "website":
            c.update(url=_url(o.get("url")), radius=_num(o.get("radius"), 0, 200, 0))
        elif t == "shortcut":
            c.update(label=str(o.get("label", ""))[:60], target=str(o.get("target", ""))[:500],
                     bg=_col(o.get("bg"), "#b5e61d"), color=_col(o.get("color"), "#000000"),
                     size=_num(o.get("size"), 6, 80, 16), radius=_num(o.get("radius"), 0, 200, 8))
        out["objects"].append(c)
    return out


def default_widget_data():
    return clean_widget_data({"w": 360, "h": 160, "objects": [
        {"id": "t1", "type": "text", "x": 16, "y": 12, "w": 328, "h": 136, "text": "{saludo}, {usuario}", "size": 24}]})


def migrate_widgets():
    """Los widgets de la version anterior (un solo texto) pasan al formato con objetos."""
    for wid, text, size, color, bg, opacity, w, h, ontop in DB.execute(
            "SELECT id, text, size, color, bg, opacity, w, h, ontop FROM widgets WHERE data IS NULL").fetchall():
        w, h = w or 300, h or 120
        data = clean_widget_data({"w": w, "h": h, "bg": bg, "opacity": opacity, "radius": 12, "ontop": bool(ontop),
                                  "objects": [{"id": "t1", "type": "text", "x": 14, "y": 10, "w": w - 28, "h": h - 20,
                                               "text": text or "", "size": size or 18, "color": color}]})
        DB.execute("UPDATE widgets SET data=?, rev=1 WHERE id=?", (json.dumps(data), wid))
    DB.commit()


ALLOW_REGISTER = os.environ.get("ALLOW_REGISTER", "1") == "1"
SESSION_TTL = 30 * 86400
MAX_MSG = 25 * 1024 * 1024
NUM_METRICS = {"ram", "cpu", "uptime", "steam_hours", "steam_hours2w", "roblox_friends", "roblox_followers", "roblox_visits",
               "battery", "steps", "heart_rate", "sleep_hours", "distance_km", "calories",   # estas 6 las manda el telefono
               "disk", "net_down", "net_up", "cpu_temp", "gpu", "procs", "volume",            # PC
               "storage", "ram_free", "battery_temp",                                         # telefono
               "root_cpu_temp", "root_bat_current", "root_bat_voltage", "root_bat_cycles", "root_cpu_freq"}   # telefono con root (solo lectura)
TEXT_METRICS = {"app", "steam_game", "locked", "charging", "net_type"}
METRICS = NUM_METRICS | TEXT_METRICS | {"apptime"}   # apptime = minutos de hoy en la app `param`
MAX_VARS = 100
MAX_WIDGETS = 50
MAX_ASSET = 8 * 1024 * 1024
ASSET_QUOTA = 100 * 1024 * 1024
ASSET_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
               "pdf": "application/pdf", "txt": "text/plain", "md": "text/plain"}
MAGIC = {"png": b"\x89PNG", "jpg": b"\xff\xd8", "jpeg": b"\xff\xd8", "gif": b"GIF8", "webp": b"RIFF", "pdf": b"%PDF"}
FONTS = ["Segoe UI", "Arial", "Consolas", "Georgia", "Times New Roman", "Comic Sans MS", "Verdana", "Impact",
         "Courier New", "Trebuchet MS"]
OBJ_TYPES = {"text", "image", "document", "camera", "website", "shortcut"}
HEXRE = re.compile(r"#[0-9a-fA-F]{6}")
ASSETRE = re.compile(r"[\w-]{8,40}")
migrate_widgets()   # despues de las constantes que usa clean_widget_data

conn_status = {}   # (usuario, servicio) -> [texto, hora]  (solo en memoria)
conn_polled = {}   # (usuario, servicio) -> hora de la ultima consulta
conn_tests = {}
socks = {}     # usuario -> {ws: peer}
metrics = {}   # (usuario, device_id) -> {"ram":..,"cpu":..,"uptime":..}
fails = {}     # ip -> [timestamps] (freno de fuerza bruta)


# ---------- cuentas ----------
def hash_pw(pw, salt):
    return hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)


def client_ip(request):
    """IP real del cliente. Detras de Fly.io `request.remote` es siempre el proxy: sin esto, 8 contraseñas mal escritas
    de cualquier persona bloquearian el inicio de sesion de todos."""
    if os.environ.get("FLY_APP_NAME"):   # la cabecera solo es de fiar cuando la pone el proxy de Fly
        return request.headers.get("Fly-Client-IP") or request.remote
    return request.remote


def too_many_fails(ip):
    now = time.time()
    fails[ip] = [t for t in fails.get(ip, []) if now - t < 300]
    return len(fails[ip]) >= 8


def new_session(user):
    tok = secrets.token_urlsafe(32)
    DB.execute("INSERT INTO sessions VALUES(?,?,?)", (tok, user, time.time() + SESSION_TTL))
    DB.commit()
    return tok


def credentials(d):
    return str(d.get("user", "")).strip().lower(), str(d.get("password", ""))


async def register(request):
    if not ALLOW_REGISTER:
        return web.json_response({"error": "registro deshabilitado"}, status=403)
    blk = ban_block(request)
    if blk:
        return blk
    if maint_now():
        return maint_response()
    name, pw = credentials(await request.json())
    if DB.execute("SELECT 1 FROM bans WHERE kind='name' AND value=?", (name,)).fetchone():
        return web.json_response({"error": "usuario ya existe"}, status=409)
    if not (3 <= len(name) <= 32) or len(pw) < 8:
        return web.json_response({"error": "usuario 3-32 caracteres, contraseña mínimo 8"}, status=400)
    salt = secrets.token_bytes(16)
    try:
        DB.execute("INSERT INTO users(name, salt, hash) VALUES(?,?,?)", (name, salt, hash_pw(pw, salt)))
    except sqlite3.IntegrityError:
        return web.json_response({"error": "usuario ya existe"}, status=409)
    if not DB.execute("SELECT 1 FROM users WHERE debug=1").fetchone():   # la primera cuenta del servidor es depurador
        DB.execute("UPDATE users SET debug=1 WHERE name=?", (name,))
    DB.commit()
    record_ip(name, client_ip(request))
    return web.json_response({"token": new_session(name), "user": name, "debug": is_debugger(name)})


async def login(request):
    blk = ban_block(request)
    if blk:
        return blk
    ip = client_ip(request)
    if too_many_fails(ip):
        return web.json_response({"error": "demasiados intentos, espera 5 min"}, status=429)
    name, pw = credentials(await request.json())
    row = DB.execute("SELECT salt, hash FROM users WHERE name=?", (name,)).fetchone()
    if not (row and hmac.compare_digest(hash_pw(pw, row[0]), row[1])):
        fails.setdefault(ip, []).append(time.time())
        return web.json_response({"error": "usuario o contraseña incorrectos"}, status=401)
    blk = ban_block(request, name) or maint_block(name)
    if blk:
        return blk
    record_ip(name, ip)
    return web.json_response({"token": new_session(name), "user": name, "debug": is_debugger(name)})


def user_from_token(tok):
    row = DB.execute("SELECT user, exp FROM sessions WHERE token=?", (tok,)).fetchone()
    return row[0] if row and row[1] > time.time() and not is_banned(row[0]) else None


# ---------- estado ----------
def clean_metrics(d):
    out = {k: v for k, v in d.items()
           if (k in NUM_METRICS and isinstance(v, (int, float)) and not isinstance(v, bool))
           or (k in TEXT_METRICS and isinstance(v, str))}
    for k in TEXT_METRICS & out.keys():
        out[k] = out[k][:60]
    if isinstance(d.get("apptimes"), dict):   # segundos de hoy por app; nunca se envia entero a otras cuentas
        out["apptimes"] = {str(k)[:40]: int(v) for k, v in list(d["apptimes"].items())[:200]
                           if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return out


def metric_value(m, metric, param):
    if metric == "apptime":
        if "apptimes" not in m or not param:
            return None
        p = param.strip().lower()
        return round(sum(v for k, v in m["apptimes"].items() if p in k.lower()) / 60)
    return m.get(metric)


def is_online(user, dev):
    if dev.startswith("@"):   # conexion de cuenta (steam, roblox): "en linea" si ya hay datos
        return (user, dev) in metrics
    return any(p["device_id"] == dev for p in socks.get(user, {}).values())


def state_for(u):
    row = DB.execute("SELECT avatar FROM users WHERE name=?", (u,)).fetchone()
    devices = [dict(id=i, name=n, platform=p, kind=k, owner=u, mine=True, online=is_online(u, i),
                    cameras=json.loads(cams) if cams else [], client_version=cv)
               for i, n, p, k, cams, cv in DB.execute(
                   "SELECT id, name, platform, kind, cameras, client_version FROM devices WHERE owner=? ORDER BY name", (u,))]
    variables, foreign = [], set()
    q = ("SELECT id, owner, name, kind, value, device_id, metric, param FROM vars WHERE owner=? "
         "OR id IN (SELECT var_id FROM shares WHERE with_user=?) ORDER BY id")
    for vid, owner, name, kind, value, dev, metric, param in DB.execute(q, (u, u)):
        v = dict(id=vid, name=name, kind=kind, mine=owner == u, owner=owner, metric=metric, device_id=dev, param=param)
        if kind == "auto":
            v["value"] = metric_value(metrics.get((owner, dev), {}), metric, param)
            v["online"] = is_online(owner, dev)
            if owner != u:
                foreign.add((owner, dev))
        else:
            v["value"] = value
        if owner == u:
            v["shared_with"] = [r[0] for r in DB.execute("SELECT with_user FROM shares WHERE var_id=?", (vid,))]
        variables.append(v)
    for owner, dev in foreign:  # PCs de otras personas cuyas variables me compartieron
        r = DB.execute("SELECT name, platform, kind FROM devices WHERE owner=? AND id=?", (owner, dev)).fetchone()
        if r:
            devices.append(dict(id=dev, name=r[0], platform=r[1], kind=r[2], owner=owner,
                                mine=False, online=is_online(owner, dev)))
    widgets = [dict(id=i, name=n, data=json.loads(data), rev=rev,
                    devices=[r[0] for r in DB.execute("SELECT device_id FROM widget_devices WHERE widget_id=?", (i,))])
               for i, n, data, rev in DB.execute(
                   "SELECT id, name, data, rev FROM widgets WHERE owner=? AND data IS NOT NULL ORDER BY id", (u,))]
    autos = [dict(id=i, name=n, enabled=bool(e), var_id=v, op=op, value=val, kind=k, url=u, body=b, cooldown=c,
                  last_fired=lf, last_status=ls)
             for i, n, e, v, op, val, k, u, b, c, lf, ls in DB.execute(
                 "SELECT id, name, enabled, var_id, op, value, kind, url, body, cooldown, last_fired, last_status "
                 "FROM automations WHERE owner=? ORDER BY id", (u,))]
    conns = []
    for svc, raw in DB.execute("SELECT service, cfg FROM connections WHERE owner=?", (u,)):
        c = json.loads(raw)
        st = conn_status.get((u, svc))
        conns.append(dict(service=svc, label=c.get("id") or c.get("user") or "", has_key=bool(c.get("key")),
                          status=st[0] if st else "", at=st[1] if st else None))
    return {"type": "state", "version": VERSION, "automations": autos, "connections": conns, "announce": announce_now(), "important": important_now(), "maintenance": maint_now(), "me": {"user": u, "debug": is_debugger(u), "avatar": row[0] if row else None, "lock": lock_info(u),
                                    "passkey_ok": HAVE_CRYPTO,
                                    "passkeys": [dict(id=i, label=l, created=c) for i, l, c in DB.execute(
                                        "SELECT id, label, created FROM passkeys WHERE owner=? ORDER BY id", (u,))]},
            "devices": devices, "variables": variables, "widgets": widgets,
            "keys": [dict(id=i, label=l, prefix=p, created=c) for i, l, p, c in DB.execute(
                "SELECT id, label, prefix, created FROM api_keys WHERE owner=? ORDER BY id", (u,))]}


async def send_user(u, msg, only=None):
    data = json.dumps(msg)
    for ws, peer in list(socks.get(u, {}).items()):
        if only and not only(peer):
            continue
        try:
            await ws.send_str(data)
        except Exception:
            pass


async def push(users):
    for u in set(users):
        await send_user(u, state_for(u))


def var_audience(vid):
    owner = DB.execute("SELECT owner FROM vars WHERE id=?", (vid,)).fetchone()
    if not owner:
        return set()
    return {owner[0]} | {r[0] for r in DB.execute("SELECT with_user FROM shares WHERE var_id=?", (vid,))}


def device_audience(owner, dev):
    users = {owner}
    users |= {r[0] for r in DB.execute(
        "SELECT s.with_user FROM shares s JOIN vars v ON v.id=s.var_id "
        "WHERE v.owner=? AND v.device_id=? AND v.kind='auto'", (owner, dev))}
    return users


async def push_values(owner, dev):
    """Actualizacion ligera de valores en vivo (sin rehacer toda la interfaz)."""
    rows = DB.execute("SELECT id, metric, param FROM vars WHERE owner=? AND device_id=? AND kind='auto'",
                      (owner, dev)).fetchall()
    if not rows:
        return
    m, on = metrics.get((owner, dev), {}), is_online(owner, dev)
    vals = {vid: {"value": metric_value(m, metric, param), "online": on} for vid, metric, param in rows}
    audience = {owner: set(vals)}
    for vid, wu in DB.execute(
            "SELECT s.var_id, s.with_user FROM shares s JOIN vars v ON v.id=s.var_id "
            "WHERE v.owner=? AND v.device_id=? AND v.kind='auto'", (owner, dev)):
        audience.setdefault(wu, set()).add(vid)
    for u, ids in audience.items():
        await send_user(u, {"type": "values", "vars": {str(i): vals[i] for i in ids}})
    schedule_automations(owner, set(vals))



# ---------- seguridad: bloqueo de cuenta (2.ª clave) y llaves de acceso (passkeys) ----------
UNLOCK_SECS = 600
try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_der_public_key
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False

# lo que cambia la cuenta: con el bloqueo activo, todo esto exige desbloquear antes
MUTATING = {"var_create", "var_set", "var_delete", "var_share", "var_unshare", "dev_rename", "dev_delete",
            "key_create", "key_delete", "widget_create", "widget_update", "widget_devices", "widget_delete",
            "set_avatar", "change_name", "change_password", "passkey_delete", "lock_set", "lock_disable",
            "automation_save", "automation_delete", "automation_toggle", "conn_save", "conn_delete"}


def lock_enabled(u):
    r = DB.execute("SELECT lock_hash FROM users WHERE name=?", (u,)).fetchone()
    return bool(r and r[0])


def lock_left(u):
    r = DB.execute("SELECT unlocked_until FROM users WHERE name=?", (u,)).fetchone()
    return max(0, int((r[0] or 0) - time.time())) if r else 0


def is_locked(u):
    return lock_enabled(u) and lock_left(u) <= 0


def lock_info(u):
    return {"enabled": lock_enabled(u), "left": lock_left(u)}


def check_password(u, pw):
    row = DB.execute("SELECT salt, hash FROM users WHERE name=?", (u,)).fetchone()
    return bool(row and hmac.compare_digest(hash_pw(pw, row[0]), row[1]))


def b64u(b):
    import base64
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(t):
    import base64
    t = str(t)
    return base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))


def cbor(data, i=0):
    """Lector minimo de CBOR (lo justo para WebAuthn): devuelve (valor, siguiente posicion)."""
    major, ai = data[i] >> 5, data[i] & 31
    i += 1
    if ai < 24:
        n = ai
    elif ai in (24, 25, 26, 27):
        size = {24: 1, 25: 2, 26: 4, 27: 8}[ai]
        n = int.from_bytes(data[i:i + size], "big")
        i += size
    else:
        raise ValueError("cbor no soportado")
    if major == 0:
        return n, i
    if major == 1:
        return -1 - n, i
    if major == 2:
        return bytes(data[i:i + n]), i + n
    if major == 3:
        return bytes(data[i:i + n]).decode(), i + n
    if major == 4:
        out = []
        for _ in range(n):
            v, i = cbor(data, i)
            out.append(v)
        return out, i
    if major == 5:
        out = {}
        for _ in range(n):
            k, i = cbor(data, i)
            v, i = cbor(data, i)
            out[k] = v
        return out, i
    if major == 6:
        return cbor(data, i)
    if major == 7:
        return {20: False, 21: True, 22: None}.get(n), i
    raise ValueError("cbor no soportado")


challenges = {}   # reto (b64url) -> (motivo, usuario, caduca)


def new_challenge(purpose, user=None):
    now = time.time()
    for k in [k for k, v in challenges.items() if v[2] < now]:
        del challenges[k]
    c = b64u(secrets.token_bytes(32))
    challenges[c] = (purpose, user, now + 300)
    return c


def rp_of(request):
    proto = request.headers.get("X-Forwarded-Proto", request.scheme)
    return request.host.split(":")[0], f"{proto}://{request.host}"


def check_client_data(raw, purpose, request, user=None):
    cd = json.loads(raw)
    ch = challenges.pop(cd.get("challenge", ""), None)
    if not ch or ch[0] != purpose or ch[2] < time.time() or (user and ch[1] != user):
        raise ValueError("reto inválido o caducado")
    if cd.get("type") != ("webauthn.create" if purpose == "reg" else "webauthn.get"):
        raise ValueError("tipo incorrecto")
    if cd.get("origin") != rp_of(request)[1]:
        raise ValueError("origen incorrecto")


def public_key_der(key):
    """COSE -> DER (SubjectPublicKeyInfo); soporta ES256 (-7) y RS256 (-257)."""
    alg = key.get(3)
    if key.get(1) == 2 and alg == -7 and key.get(-1) == 1:
        pub = ec.EllipticCurvePublicNumbers(int.from_bytes(key[-2], "big"), int.from_bytes(key[-3], "big"), ec.SECP256R1()).public_key()
    elif key.get(1) == 3 and alg == -257:
        pub = rsa.RSAPublicNumbers(int.from_bytes(key[-2], "big"), int.from_bytes(key[-1], "big")).public_key()
    else:
        raise ValueError("algoritmo no soportado")
    return pub.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo), alg


def bearer_user(request):
    auth = request.headers.get("Authorization", "")
    return user_from_token(auth[7:].strip()) if auth.startswith("Bearer ") else None


async def passkey_reg_begin(request):
    user = bearer_user(request)
    if not user:
        return web.json_response({"error": "sesión inválida"}, status=401)
    if not HAVE_CRYPTO:
        return web.json_response({"error": "el servidor necesita el paquete «cryptography» (pip install cryptography)"}, status=501)
    if is_locked(user):
        return web.json_response({"error": "cuenta bloqueada: desbloquéala con tu 2.ª clave"}, status=423)
    if DB.execute("SELECT COUNT(*) FROM passkeys WHERE owner=?", (user,)).fetchone()[0] >= 5:
        return web.json_response({"error": "máximo 5 llaves de seguridad"}, status=400)
    uid = DB.execute("SELECT uid FROM users WHERE name=?", (user,)).fetchone()[0]
    if not uid:
        uid = b64u(secrets.token_bytes(16))
        DB.execute("UPDATE users SET uid=? WHERE name=?", (uid, user))
        DB.commit()
    rp_id, _ = rp_of(request)
    return web.json_response({
        "challenge": new_challenge("reg", user), "rp": {"id": rp_id, "name": "hub"},
        "user": {"id": uid, "name": user, "displayName": user},
        "pubKeyCredParams": [{"type": "public-key", "alg": -7}, {"type": "public-key", "alg": -257}],
        "authenticatorSelection": {"residentKey": "preferred", "userVerification": "preferred"},
        "excludeCredentials": [{"id": r[0]} for r in DB.execute("SELECT cred_id FROM passkeys WHERE owner=?", (user,))]})


async def passkey_reg_finish(request):
    user = bearer_user(request)
    if not user:
        return web.json_response({"error": "sesión inválida"}, status=401)
    if not HAVE_CRYPTO:
        return web.json_response({"error": "falta el paquete «cryptography»"}, status=501)
    if is_locked(user):
        return web.json_response({"error": "cuenta bloqueada: desbloquéala con tu 2.ª clave"}, status=423)
    try:
        d = await request.json()
        r = d["response"]
        check_client_data(unb64u(r["clientDataJSON"]), "reg", request, user)
        auth = cbor(unb64u(r["attestationObject"]))[0]["authData"]
        if auth[:32] != hashlib.sha256(rp_of(request)[0].encode()).digest() or not auth[32] & 1 or not auth[32] & 0x40:
            raise ValueError("datos de la llave inválidos")
        i = 37 + 16
        n = int.from_bytes(auth[i:i + 2], "big")
        cred = auth[i + 2:i + 2 + n]
        key = cbor(auth, i + 2 + n)[0]
        der, alg = public_key_der(key)
        if b64u(cred) != d.get("rawId"):
            raise ValueError("identificador no coincide")
        DB.execute("INSERT INTO passkeys(owner, cred_id, pubkey, alg, sign_count, label, created) VALUES(?,?,?,?,?,?,?)",
                   (user, b64u(cred), der, alg, int.from_bytes(auth[33:37], "big"),
                    (str(d.get("label", "")).strip() or "mi llave")[:40], time.time()))
        DB.commit()
    except sqlite3.IntegrityError:
        return web.json_response({"error": "esa llave ya está registrada"}, status=409)
    except Exception as e:
        return web.json_response({"error": "no se pudo registrar la llave: " + str(e)[:80]}, status=400)
    await push({user})
    return web.json_response({"ok": True})


async def passkey_login_begin(request):
    if not HAVE_CRYPTO:
        return web.json_response({"error": "el servidor necesita el paquete «cryptography»"}, status=501)
    return web.json_response({"challenge": new_challenge("get"), "rpId": rp_of(request)[0], "userVerification": "preferred"})


async def passkey_login_finish(request):
    ip = client_ip(request)
    if too_many_fails(ip):
        return web.json_response({"error": "demasiados intentos, espera 5 min"}, status=429)
    try:
        if not HAVE_CRYPTO:
            raise ValueError("falta el paquete «cryptography»")
        d = await request.json()
        r = d["response"]
        row = DB.execute("SELECT id, owner, pubkey, alg, sign_count FROM passkeys WHERE cred_id=?", (d.get("rawId"),)).fetchone()
        if not row:
            raise ValueError("llave desconocida")
        raw_cd, auth, sig = unb64u(r["clientDataJSON"]), unb64u(r["authenticatorData"]), unb64u(r["signature"])
        check_client_data(raw_cd, "get", request)
        if auth[:32] != hashlib.sha256(rp_of(request)[0].encode()).digest() or not auth[32] & 1:
            raise ValueError("datos de la llave inválidos")
        pub = load_der_public_key(row[2])
        signed = auth + hashlib.sha256(raw_cd).digest()
        if row[3] == -7:
            pub.verify(sig, signed, ec.ECDSA(hashes.SHA256()))
        else:
            pub.verify(sig, signed, padding.PKCS1v15(), hashes.SHA256())
        count = int.from_bytes(auth[33:37], "big")
        if (count or row[4]) and count <= row[4]:
            raise ValueError("contador de la llave inválido")
        DB.execute("UPDATE passkeys SET sign_count=? WHERE id=?", (count, row[0]))
        DB.commit()
    except (InvalidSignature if HAVE_CRYPTO else ValueError, ValueError, KeyError, IndexError, TypeError):
        fails.setdefault(ip, []).append(time.time())
        return web.json_response({"error": "no se pudo verificar la llave"}, status=401)
    blk = ban_block(request, row[1]) or maint_block(row[1])
    if blk:
        return blk
    record_ip(row[1], client_ip(request))
    return web.json_response({"token": new_session(row[1]), "user": row[1], "debug": is_debugger(row[1])})


def rename_user(old, new):
    """Cambia el nombre de usuario en todas las tablas y en la memoria."""
    for sql in ("UPDATE users SET name=? WHERE name=?", "UPDATE sessions SET user=? WHERE user=?",
                "UPDATE devices SET owner=? WHERE owner=?", "UPDATE vars SET owner=? WHERE owner=?",
                "UPDATE shares SET with_user=? WHERE with_user=?", "UPDATE widgets SET owner=? WHERE owner=?",
                "UPDATE api_keys SET owner=? WHERE owner=?", "UPDATE assets SET owner=? WHERE owner=?",
                "UPDATE passkeys SET owner=? WHERE owner=?", "UPDATE automations SET owner=? WHERE owner=?",
                "UPDATE connections SET owner=? WHERE owner=?"):
        DB.execute(sql, (new, old))
    DB.commit()
    for k in [k for k in metrics if k[0] == old]:
        metrics[(new, k[1])] = metrics.pop(k)
    for d in (conn_status, conn_polled):
        for k in [k for k in d if k[0] == old]:
            d[(new, k[1])] = d.pop(k)


def related_users(u):
    """Cuentas que comparten variables con `u` (o al revés): hay que avisarles de un cambio de nombre."""
    a = {r[0] for r in DB.execute("SELECT s.with_user FROM shares s JOIN vars v ON v.id=s.var_id WHERE v.owner=?", (u,))}
    b = {r[0] for r in DB.execute("SELECT v.owner FROM shares s JOIN vars v ON v.id=s.var_id WHERE s.with_user=?", (u,))}
    return (a | b) - {u}



# ---------- automatizaciones: avisos (webhooks) cuando una variable cumple una condicion ----------
OPS = {"eq", "ne", "gt", "lt", "ge", "le", "contains", "starts", "changes"}
MAX_AUTOMATIONS = 20
REMOTE_MIN = (1, 5)   # clientes que entienden la orden `fire_webhook`
ALLOW_PRIVATE = os.environ.get("AUTOMATION_ALLOW_PRIVATE") == "1"   # solo para pruebas locales
UNITS = {"ram": "%", "cpu": "%", "uptime": " h", "steam_hours": " h", "steam_hours2w": " h", "battery": "%",
         "heart_rate": " lpm", "sleep_hours": " h", "distance_km": " km", "calories": " kcal"}
pending_hooks = {}   # id -> (usuario, future) con la respuesta de un dispositivo
fire_times = {}      # usuario -> [instantes] (limite de envios por minuto)
test_times = {}      # id de automatizacion -> ultimo «probar»


def to_num(x):
    try:
        return float(str(x).replace("%", "").replace(",", ".").strip())
    except ValueError:
        return None


def holds(op, cur, ref):
    """¿Se cumple `cur <op> ref`? Numeros si ambos lo son; si no, texto sin distinguir mayusculas."""
    if cur is None:
        return False
    a, b = to_num(cur), to_num(ref)
    if op in ("gt", "lt", "ge", "le"):
        if a is None or b is None:
            return False
        return {"gt": a > b, "lt": a < b, "ge": a >= b, "le": a <= b}[op]
    if op == "eq":
        return a == b if a is not None and b is not None else str(cur).strip().lower() == str(ref).strip().lower()
    if op == "ne":
        return not holds("eq", cur, ref)
    t, r = str(cur).lower(), str(ref).lower()
    return r in t if op == "contains" else t.startswith(r)


def var_raw(owner, vid):
    """(nombre, valor crudo, texto para mostrar) de una variable propia; el valor es None si no hay dato (equipo apagado)."""
    r = DB.execute("SELECT name, kind, value, device_id, metric, param FROM vars WHERE id=? AND owner=?", (vid, owner)).fetchone()
    if not r:
        return None
    name, kind, value, dev, metric, param = r
    if kind != "auto":
        return name, value, value or ""
    if not is_online(owner, dev):
        return name, None, "sin conexión"
    v = metric_value(metrics.get((owner, dev), {}), metric, param)
    if v is None:
        return name, None, "—"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if metric == "apptime":
        return name, v, f"{v // 60} h {v % 60} min" if v >= 60 else f"{v} min"
    return name, v, f"{v}{UNITS.get(metric, '')}"


def automation_ctx(owner):
    c = {}
    for (vid,) in DB.execute("SELECT id FROM vars WHERE owner=?", (owner,)).fetchall():
        name, _, text = var_raw(owner, vid)
        c[name.strip().lower()] = text
    now = time.localtime()
    c["hora"], c["fecha"] = time.strftime("%H:%M", now), time.strftime("%Y-%m-%d", now)
    return c


def render(tpl, ctx, as_json=False):
    def sub(m):
        v = ctx.get(m.group(1).strip().lower())
        if v is None:
            return m.group(0)
        return json.dumps(str(v), ensure_ascii=False)[1:-1] if as_json else str(v)
    return re.sub(r"\{([^{}]+)\}", sub, tpl)


def build_body(kind, name, tpl, ctx):
    if kind == "discord":
        text = render(tpl.strip() or "{variable}: {valor}", ctx)[:1900]
        return json.dumps({"content": text, "allowed_mentions": {"parse": []}}, ensure_ascii=False)
    if tpl.strip():
        return render(tpl, ctx, as_json=True)
    return json.dumps({"automatizacion": name, "variable": ctx.get("variable"), "valor": ctx.get("valor")}, ensure_ascii=False)


class SafeResolver(AbstractResolver):
    """Solo resuelve a direcciones públicas: el servidor nunca debe poder llamar a redes privadas (SSRF)."""

    async def resolve(self, host, port=0, family=socket.AF_INET):
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        out = []
        for fam, _, _, _, sa in infos:
            if not ipaddress.ip_address(sa[0]).is_global and not ALLOW_PRIVATE:
                raise OSError("dirección no pública")
            out.append({"hostname": host, "host": sa[0], "port": port, "family": fam, "proto": 0, "flags": 0})
        if not out:
            raise OSError("sin direcciones")
        return out

    async def close(self):
        pass


async def post_from_server(url, body):
    if urlparse(url).scheme != "https" and not ALLOW_PRIVATE:
        raise ValueError("el servidor solo manda a direcciones https")
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(resolver=SafeResolver()), timeout=aiohttp.ClientTimeout(total=10)) as s:
        async with s.post(url, data=body.encode("utf-8"), allow_redirects=False,
                          headers={"Content-Type": "application/json", "User-Agent": "hub-automations"}) as r:
            await r.content.read(512)
            return r.status


def remote_peer(owner):
    """Un dispositivo del dueño conectado y con cliente >= 1.5 (prefiere Windows)."""
    best = None
    for w, peer in socks.get(owner, {}).items():
        cv = re.match(r"(\d+)\.(\d+)", peer.get("cv") or "")
        if peer["kind"] != "agent" or not cv or (int(cv.group(1)), int(cv.group(2))) < REMOTE_MIN:
            continue
        if best is None or peer["platform"] == "Windows":
            best = (w, peer)
    return best


async def via_device(owner, w, url, body):
    rid = secrets.token_hex(8)
    fut = asyncio.get_running_loop().create_future()
    pending_hooks[rid] = (owner, fut)
    try:
        await w.send_json({"type": "fire_webhook", "id": rid, "url": url, "body": body})
        return await asyncio.wait_for(fut, 15)
    except asyncio.TimeoutError:
        return {"ok": False, "error": "sin respuesta"}
    finally:
        pending_hooks.pop(rid, None)


def device_name(owner, dev):
    r = DB.execute("SELECT name FROM devices WHERE owner=? AND id=?", (owner, dev)).fetchone()
    return r[0] if r else "?"


async def fire(owner, a, raw, text, var_name):
    """Manda el webhook: por un dispositivo del dueño si hay uno conectado (así sirve también para tu red local); si no, el servidor."""
    aid, name, kind, url, tpl = a["id"], a["name"], a["kind"], a["url"], a["body"]
    now = time.time()
    fire_times[owner] = [t for t in fire_times.get(owner, []) if now - t < 60]
    if len(fire_times[owner]) >= 30:
        status = "demasiados envíos por minuto: se omitió"
    else:
        fire_times[owner].append(now)
        ctx = automation_ctx(owner)
        ctx.update(valor=text, variable=var_name, automatizacion=name)
        body = build_body(kind, name, tpl, ctx)
        status, peer = None, remote_peer(owner)
        if peer:
            res = await via_device(owner, peer[0], url, body)
            who = device_name(owner, peer[1]["device_id"])
            if res.get("ok"):
                status = f"enviado desde «{who}» (código {res.get('status')})"
            else:
                status = f"falló en «{who}»: {res.get('error') or res.get('status')}"
        if status is None or status.startswith("falló"):
            try:
                code = await post_from_server(url, body)
                status = f"enviado desde el servidor (código {code})" if 200 <= code < 300 else f"el servidor recibió el código {code}"
            except Exception as e:
                why = "no se puede desde el servidor (dirección privada o http)" if isinstance(e, (OSError, ValueError)) and "direcci" in str(e) else str(e)[:100] or type(e).__name__
                status = (status + " · " if status else "") + "error: " + why
    DB.execute("UPDATE automations SET last_fired=?, last_status=? WHERE id=?", (now, status[:240], aid))
    DB.commit()
    await push({owner})


async def check_automations(owner, var_ids):
    if maint_now():   # en mantenimiento las automatizaciones se pausan
        return
    ids = ",".join(str(int(i)) for i in var_ids)
    rows = DB.execute("SELECT id, name, var_id, op, value, kind, url, body, cooldown, last_state, last_value, last_fired "
                      f"FROM automations WHERE owner=? AND enabled=1 AND var_id IN ({ids})", (owner,)).fetchall()
    for aid, name, vid, op, ref, kind, url, body, cooldown, last_state, last_value, last_fired in rows:
        got = var_raw(owner, vid)
        if not got or got[1] is None:
            continue
        vname, raw, text = got
        if op == "changes":
            state = last_value is not None and str(raw) != last_value
            fire_it = state
        else:
            state = holds(op, raw, ref)
            fire_it = state and not last_state
        DB.execute("UPDATE automations SET last_state=?, last_value=? WHERE id=?", (int(state), str(raw), aid))
        if fire_it and time.time() - (last_fired or 0) >= (cooldown or 0):
            a = dict(id=aid, name=name, kind=kind, url=url, body=body)
            asyncio.get_running_loop().create_task(fire(owner, a, raw, text, vname))
    DB.commit()


def schedule_automations(owner, ids):
    if ids:
        asyncio.get_running_loop().create_task(check_automations(owner, set(ids)))


def clean_automation(owner, msg):
    """Valida lo que manda el portal; devuelve (campos, error)."""
    name = str(msg.get("name", "")).strip()[:40]
    if not name:
        return None, "ponle un nombre a la automatización"
    vid = msg.get("var_id")
    if not DB.execute("SELECT 1 FROM vars WHERE id=? AND owner=?", (vid, owner)).fetchone():
        return None, "elige una de tus variables"
    op = msg.get("op")
    if op not in OPS:
        return None, "elige una condición"
    value = str(msg.get("value", "")).strip()[:80]
    if op != "changes" and value == "":
        return None, "escribe el valor de la condición"
    kind = msg.get("kind")
    if kind not in ("discord", "webhook"):
        return None, "elige el destino"
    url = str(msg.get("url", "")).strip()[:500]
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return None, "la dirección del webhook debe empezar por https://"
    if kind == "discord" and u.scheme != "https":
        return None, "los webhooks de discord usan https"
    tpl = str(msg.get("body", ""))[:2000]
    if kind == "webhook" and tpl.strip():
        try:
            json.loads(render(tpl, {"valor": "x", "variable": "x", "automatizacion": "x"}, as_json=True))
        except ValueError:
            return None, "el cuerpo no es un JSON válido"
    try:
        cooldown = max(10, min(86400, int(msg.get("cooldown", 60))))
    except (TypeError, ValueError):
        cooldown = 60
    return dict(name=name, var_id=vid, op=op, value=value, kind=kind, url=url, body=tpl, cooldown=cooldown), None


# ---------- conexiones de cuenta: steam y roblox (solo datos publicos; nunca contraseñas) ----------
SERVICES = {"steam": 60, "roblox": 300}   # segundos entre consultas
STEAM_KEY_RE = re.compile(r"[0-9A-Fa-f]{32}")
STEAM_ID_RE = re.compile(r"[\w.\-]{2,64}")
ROBLOX_RE = re.compile(r"\w{3,20}")


def safe_err(e):
    """Texto de error SIN la URL (las consultas a Steam llevan la API key en la URL)."""
    if isinstance(e, aiohttp.ClientResponseError):
        return f"http {e.status}"
    if isinstance(e, (asyncio.TimeoutError, aiohttp.ClientError)):
        return "sin respuesta"
    return str(e)[:80] if isinstance(e, ValueError) else type(e).__name__


async def jget(s, url, **kw):
    async with s.get(url, timeout=aiohttp.ClientTimeout(total=10), **kw) as r:
        r.raise_for_status()
        return await r.json(content_type=None)


async def poll_steam(s, cfg):
    key, sid, base, out = cfg["key"], cfg["id"], "https://api.steampowered.com", {}
    if not sid.isdigit():   # nombre de perfil personalizado -> ID numerica
        r = await jget(s, base + "/ISteamUser/ResolveVanityURL/v1/", params={"key": key, "vanityurl": sid})
        sid = r["response"].get("steamid") or ""
        if not sid:
            raise ValueError("no existe ese nombre de perfil")
    r = await jget(s, base + "/ISteamUser/GetPlayerSummaries/v2/", params={"key": key, "steamids": sid})
    if not r["response"]["players"]:
        raise ValueError("perfil no encontrado")
    out["steam_game"] = (r["response"]["players"][0].get("gameextrainfo") or "ninguno")[:60]
    r = await jget(s, base + "/IPlayerService/GetOwnedGames/v1/", params={"key": key, "steamid": sid, "include_played_free_games": 1})
    games = r["response"].get("games")
    if games is None:
        return out, "conectado (juego actual). tus horas son privadas: en steam pon «detalles del juego» en público"
    out["steam_hours"] = round(sum(g.get("playtime_forever", 0) for g in games) / 60, 1)
    out["steam_hours2w"] = round(sum(g.get("playtime_2weeks", 0) for g in games) / 60, 1)
    return out, "conectado"


async def poll_roblox(s, cfg):
    if not cfg.get("uid"):
        async with s.post("https://users.roblox.com/v1/usernames/users", timeout=aiohttp.ClientTimeout(total=10),
                          json={"usernames": [cfg["user"]], "excludeBannedUsers": True}) as r:
            r.raise_for_status()
            d = await r.json()
        if not d["data"]:
            raise ValueError("no existe ese usuario de roblox")
        cfg["uid"] = d["data"][0]["id"]
    uid, out = cfg["uid"], {}
    for k in ("friends", "followers"):
        out["roblox_" + k] = (await jget(s, f"https://friends.roblox.com/v1/users/{uid}/{k}/count"))["count"]
    games = (await jget(s, f"https://games.roblox.com/v2/users/{uid}/games",
                        params={"accessFilter": "Public", "limit": 50, "sortOrder": "Asc"}))["data"]
    ids = ",".join(str(g["id"]) for g in games)
    out["roblox_visits"] = sum(g.get("visits", 0) for g in (await jget(
        s, "https://games.roblox.com/v1/games", params={"universeIds": ids}))["data"]) if ids else 0
    return out, "conectado"


async def poll_conn(owner, svc):
    r = DB.execute("SELECT cfg FROM connections WHERE owner=? AND service=?", (owner, svc)).fetchone()
    if not r:
        return
    cfg = json.loads(r[0])
    conn_polled[(owner, svc)] = time.time()
    old = conn_status.get((owner, svc))
    try:
        async with aiohttp.ClientSession() as s:
            data, note = await (poll_steam if svc == "steam" else poll_roblox)(s, cfg)
        metrics[(owner, "@" + svc)] = {**metrics.get((owner, "@" + svc), {}), **data}
        text = note
        DB.execute("UPDATE connections SET cfg=? WHERE owner=? AND service=?", (json.dumps(cfg), owner, svc))
        DB.commit()
    except Exception as e:
        text = "error: " + safe_err(e)
    conn_status[(owner, svc)] = [text, time.time()]
    await push_values(owner, "@" + svc)
    if not old or old[0] != text:
        await push({owner})


async def conn_loop():
    sem = asyncio.Semaphore(8)

    async def one(owner, svc):
        async with sem:
            await poll_conn(owner, svc)
    while True:
        await asyncio.sleep(15)
        try:
            await maint_tick()
            if maint_now():
                continue
            now, due = time.time(), []
            for owner, svc in DB.execute("SELECT owner, service FROM connections").fetchall():
                if now - conn_polled.get((owner, svc), 0) < SERVICES.get(svc, 300):
                    continue   # solo se consulta lo que alguna variable usa
                if DB.execute("SELECT 1 FROM vars WHERE owner=? AND device_id=?", (owner, "@" + svc)).fetchone():
                    due.append(one(owner, svc))
            if due:
                await asyncio.gather(*due, return_exceptions=True)
        except Exception:
            pass


async def start_background(app):
    app["conn_task"] = asyncio.create_task(conn_loop())
    app["purge_task"] = asyncio.create_task(purge_loop())


# ---------- modo de depuración y moderación ----------
from collections import deque
EVENTS = deque(maxlen=60)   # errores y acciones de depuración recientes
START_TIME = time.time()
BAN_KEEP_DAYS = 30          # una cuenta suspendida conserva sus datos este tiempo (y se puede restaurar)


def is_debugger(u):
    r = DB.execute("SELECT debug FROM users WHERE name=?", (u,)).fetchone()
    return bool(r and r[0])


def is_banned(u):
    r = DB.execute("SELECT banned FROM users WHERE name=?", (u,)).fetchone()
    return bool(r and r[0])


def banned_ip(ip):
    return bool(ip and DB.execute("SELECT 1 FROM bans WHERE kind='ip' AND value=?", (ip,)).fetchone())


def ban_block(request, name=None):
    if banned_ip(client_ip(request)) or (name and is_banned(name)):
        return web.json_response({"error": "cuenta suspendida", "banned": True}, status=403)
    return None


async def ban_info(request):
    return web.json_response({"banned": banned_ip(client_ip(request))})


def record_ip(user, ip):
    if ip:
        DB.execute("INSERT OR REPLACE INTO user_ips(user, ip, last) VALUES(?,?,?)", (user, ip, time.time()))
        DB.commit()


def kv_get(k, default=None):
    r = DB.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def kv_set(k, v):
    DB.execute("INSERT OR REPLACE INTO kv(k, v) VALUES(?,?)", (k, v))
    DB.commit()


def announce_now():
    try:
        a = json.loads(kv_get("announce") or "null")
    except ValueError:
        return None
    return a if a and a.get("until", 0) > time.time() else None


def parse_changelog_md(text):
    """CHANGELOG.md -> [{"v": "1.5", "k": "grande"|"parche", "p": [puntos]}] (las más nuevas primero)."""
    out, cur = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            v = line[3:].strip()
            cur = {"v": v, "k": "parche" if v.count(".") == 2 else "grande", "p": []} if VERSION_RE.fullmatch(v) else None
            if cur:
                out.append(cur)
        elif cur and line.lstrip().startswith("- "):
            cur["p"].append(line.lstrip()[2:].strip()[:500])
    return out


MAINT_BLOCK = {"/api/push", "/api/register", "/api/asset", "/api/passkey/register/begin", "/api/passkey/register/finish"}
_maint_sig = [None]


def maint_now():
    """Mantenimiento vigente: {"msg", "until" (hora de regreso o None si es indefinido), "id", "by"} o None. Caduca solo a la hora fijada."""
    try:
        m = json.loads(kv_get("maintenance") or "null")
    except ValueError:
        return None
    if not m or (m.get("until") and m["until"] <= time.time()):
        return None
    return m


def maint_response():
    return web.json_response({"error": "en mantenimiento", "status": 503, "maintenance": maint_now()}, status=503,
                             headers={"Retry-After": "60", "Cache-Control": "no-store"})


def maint_block(name):
    return maint_response() if maint_now() and not is_debugger(name) else None


async def maint_tick():
    """Avisa a todos cuando el mantenimiento empieza, termina (también al llegar la hora fijada) o cambia."""
    m = maint_now()
    sig = json.dumps(m, sort_keys=True) if m else None
    if sig != _maint_sig[0]:
        _maint_sig[0] = sig
        for u in list(socks):
            await send_user(u, {"type": "maintenance", "maintenance": m})


def important_now():
    try:
        return json.loads(kv_get("important") or "null")
    except ValueError:
        return None


async def notice_info(request):
    """Aviso importante vigente: público, para mostrarlo al abrir el portal aunque no haya sesión."""
    return web.json_response({"important": important_now(), "maintenance": maint_now()}, headers={"Cache-Control": "no-store"})


def changelog_list():
    raw = kv_get("changelog_json")
    if raw:
        try:
            return json.loads(raw)
        except ValueError:
            pass
    try:
        return parse_changelog_md((HERE / "CHANGELOG.md").read_text(encoding="utf8"))
    except OSError:
        return []


def clean_changelog(lst):
    """Valida lo que manda el editor: versiones válidas y distintas, tipo conocido, puntos de texto."""
    out, seen = [], set()
    for x in (lst if isinstance(lst, list) else [])[:100]:
        if not isinstance(x, dict):
            continue
        v = str(x.get("v", "")).strip()
        if not VERSION_RE.fullmatch(v) or v in seen:
            return None, f"versión no válida o repetida: «{v[:12]}»"
        seen.add(v)
        pts = [str(q).strip()[:500] for q in (x.get("p") or [])[:30] if str(q).strip()]
        out.append({"v": v, "k": "grande" if x.get("k") == "grande" else "parche", "p": pts})
    out.sort(key=lambda x: [int(n) for n in x["v"].split(".")], reverse=True)
    return out, None


def log_event(user, text):
    line = f"{time.strftime('%H:%M:%S')} {user}: {text}"
    EVENTS.append(line)
    print("[depuración]", line)


async def kick_user(u):
    """Cierra todas las sesiones de una cuenta y desconecta sus equipos ya."""
    DB.execute("DELETE FROM sessions WHERE user=?", (u,))
    DB.commit()
    for w in list(socks.get(u, {})):
        try:
            await w.send_json({"type": "kick"})
            await w.close()
        except Exception:
            pass


def dbg_users():
    out = []
    for name, debug, banned in DB.execute("SELECT name, debug, banned FROM users ORDER BY name").fetchall():
        ip = DB.execute("SELECT ip FROM user_ips WHERE user=? ORDER BY last DESC LIMIT 1", (name,)).fetchone()
        out.append(dict(name=name, debug=bool(debug), banned=banned,
                        devices=DB.execute("SELECT COUNT(*) FROM devices WHERE owner=?", (name,)).fetchone()[0],
                        vars=DB.execute("SELECT COUNT(*) FROM vars WHERE owner=?", (name,)).fetchone()[0],
                        online=bool(socks.get(name)), ip=ip[0] if ip else ""))
    return out


def dbg_status():
    n = lambda q: DB.execute(q).fetchone()[0]
    try:
        size = os.path.getsize(DB.execute("PRAGMA database_list").fetchone()[2])
    except OSError:
        size = 0
    return dict(version=VERSION, uptime=int(time.time() - START_TIME), users=n("SELECT COUNT(*) FROM users"),
                banned=n("SELECT COUNT(*) FROM users WHERE banned IS NOT NULL"),
                connected=sum(len(v) for v in socks.values()),
                devices_online=sum(1 for u, v in socks.items() for p in v.values() if p["device_id"]),
                variables=n("SELECT COUNT(*) FROM vars"), connections=n("SELECT COUNT(*) FROM connections"),
                automations=n("SELECT COUNT(*) FROM automations"), db_kb=size // 1024, events=list(EVENTS)[-20:])


def ban_account(target, by):
    """Suspende la cuenta, y prohíbe sus IP y dispositivos (salvo los de depuradores, locales o privados). Devuelve lo omitido."""
    now = time.time()
    DB.execute("UPDATE users SET banned=? WHERE name=?", (now, target))
    safe_ips = {r[0] for r in DB.execute("SELECT ip FROM user_ips WHERE user IN (SELECT name FROM users WHERE debug=1)")}
    safe_devs = {r[0] for r in DB.execute("SELECT id FROM devices WHERE owner IN (SELECT name FROM users WHERE debug=1)")}
    skipped = 0
    for (ip,) in DB.execute("SELECT ip FROM user_ips WHERE user=? AND last>?", (target, now - 30 * 86400)).fetchall():
        try:
            ok = ipaddress.ip_address(ip).is_global
        except ValueError:
            ok = False
        if ok and ip not in safe_ips:
            DB.execute("INSERT OR REPLACE INTO bans(kind, value, user, created) VALUES('ip',?,?,?)", (ip, target, now))
        else:
            skipped += 1
    for (dev,) in DB.execute("SELECT id FROM devices WHERE owner=?", (target,)).fetchall():
        if dev not in safe_devs:
            DB.execute("INSERT OR REPLACE INTO bans(kind, value, user, created) VALUES('device',?,?,?)", (dev, target, now))
        else:
            skipped += 1
    DB.commit()
    return skipped


def purge_user(u):
    """Borra una cuenta y todo lo suyo. Las prohibiciones se conservan y el nombre queda reservado."""
    q = lambda sql, *a: DB.execute(sql, a)
    q("DELETE FROM shares WHERE var_id IN (SELECT id FROM vars WHERE owner=?)", u)
    q("DELETE FROM shares WHERE with_user=?", u)
    q("DELETE FROM automations WHERE owner=?", u)
    q("DELETE FROM vars WHERE owner=?", u)
    q("DELETE FROM widget_devices WHERE widget_id IN (SELECT id FROM widgets WHERE owner=?)", u)
    for t in ("widgets", "assets", "api_keys", "passkeys", "connections", "devices", "sessions"):
        q(f"DELETE FROM {t} WHERE {'user' if t == 'sessions' else 'owner'}=?", u)
    q("DELETE FROM user_ips WHERE user=?", u)
    q("INSERT OR REPLACE INTO bans(kind, value, user, created) VALUES('name',?,?,?)", u, u, time.time())
    q("DELETE FROM users WHERE name=?", u)
    DB.commit()
    for d in (metrics, conn_status, conn_polled):
        for k in [k for k in d if k[0] == u]:
            d.pop(k, None)


async def purge_loop():
    while True:
        await asyncio.sleep(3600)
        try:
            for (u,) in DB.execute("SELECT name FROM users WHERE banned IS NOT NULL AND banned<? AND debug=0",
                                   (time.time() - BAN_KEEP_DAYS * 86400,)).fetchall():
                related = related_users(u)
                purge_user(u)
                log_event("sistema", f"cuenta «{u}» borrada tras {BAN_KEEP_DAYS} días suspendida")
                await push(related)
        except Exception as e:
            EVENTS.append(f"{time.strftime('%H:%M:%S')} error en la limpieza: {type(e).__name__}")


async def handle_debug(ws, user, msg, toast):
    t = msg.get("type")
    target = str(msg.get("user", "")).strip().lower()
    exists = lambda: DB.execute("SELECT 1 FROM users WHERE name=?", (target,)).fetchone()
    if t == "dbg_users":
        return await ws.send_json({"type": "dbg_users", "users": dbg_users()})
    if t == "dbg_status":
        return await ws.send_json({"type": "dbg_status", "data": dbg_status()})
    if t == "dbg_announce":
        text = str(msg.get("text", "")).strip()[:300]
        if not text:
            return await toast("escribe el aviso")
        mins = max(1, min(10080, int(float(msg.get("minutes") or 60))))
        a = {"id": secrets.token_hex(4), "text": text, "until": time.time() + mins * 60, "by": user}
        kv_set("announce", json.dumps(a))
        log_event(user, f"aviso global: {text[:60]}")
    elif t == "dbg_announce_clear":
        kv_set("announce", "null")
        log_event(user, "aviso global quitado")
        a = None
    elif t in ("dbg_important", "dbg_important_clear"):
        if t == "dbg_important":
            text = str(msg.get("text", "")).strip()[:600]
            if not text:
                return await toast("escribe el aviso importante")
            imp = {"id": secrets.token_hex(4), "text": text, "by": user}
            kv_set("important", json.dumps(imp))
            log_event(user, f"aviso importante: {text[:60]}")
        else:
            imp = None
            kv_set("important", "null")
            log_event(user, "aviso importante cancelado")
        for u in list(socks):
            await send_user(u, {"type": "important", "important": imp})
        return await toast("aviso importante publicado" if imp else "aviso importante cancelado")
    elif t in ("dbg_maint_start", "dbg_maint_end"):
        if t == "dbg_maint_start":
            until = msg.get("until")
            now = time.time()
            if until is not None:
                try:
                    until = float(until)
                except (TypeError, ValueError):
                    return await toast("hora no válida")
                if not (now + 30 <= until <= now + 30 * 86400):
                    return await toast("la hora de regreso debe ser futura (máximo 30 días)")
            m = {"id": secrets.token_hex(4), "msg": str(msg.get("msg", "")).strip()[:200] or "estamos mejorando el hub",
                 "until": until, "start": now, "by": user}
            kv_set("maintenance", json.dumps(m))
            log_event(user, "mantenimiento iniciado " + ("(indefinido)" if until is None else f"hasta {time.strftime('%H:%M', time.localtime(until))}"))
        else:
            kv_set("maintenance", "null")
            log_event(user, "mantenimiento terminado")
        await maint_tick()
        return await toast("mantenimiento iniciado" if t == "dbg_maint_start" else "mantenimiento terminado")
    elif t == "dbg_changelog_set":
        lst, err = clean_changelog(msg.get("list"))
        if err:
            return await toast(err)
        kv_set("changelog_json", json.dumps(lst))
        log_event(user, f"changelog editado ({len(lst)} versiones)")
        return await toast("changelog guardado")
    elif t == "dbg_notify":
        if not exists():
            return await toast("no existe esa cuenta")
        await send_user(target, {"type": "toast", "text": str(msg.get("text", ""))[:200]})
        log_event(user, f"aviso a {target}")
        return await toast("aviso enviado")
    elif t in ("dbg_signout", "dbg_grant", "dbg_ban", "dbg_unban", "dbg_delete"):
        if not exists():
            return await toast("no existe esa cuenta")
        tdebug = is_debugger(target)
        if t == "dbg_signout":
            await kick_user(target)
            log_event(user, f"cerró las sesiones de {target}")
        elif t == "dbg_grant":
            on = bool(msg.get("on"))
            if not on and tdebug and DB.execute("SELECT COUNT(*) FROM users WHERE debug=1").fetchone()[0] <= 1:
                return await toast("no se puede quitar al último depurador")
            if on and is_banned(target):
                return await toast("esa cuenta está suspendida")
            DB.execute("UPDATE users SET debug=? WHERE name=?", (int(on), target))
            DB.commit()
            log_event(user, f"{'dio' if on else 'quitó'} la depuración a {target}")
            await push({target})
        elif t in ("dbg_ban", "dbg_delete") and (tdebug or target == user):
            return await toast("no se puede suspender ni borrar a un depurador (quítale la depuración primero)")
        elif t == "dbg_ban":
            skipped = ban_account(target, user)
            await send_user(target, {"type": "banned"})
            await kick_user(target)
            log_event(user, f"suspendió a {target} ({skipped} IP/dispositivos omitidos por seguridad)")
            await toast(f"cuenta suspendida" + (f" · {skipped} IP o dispositivos no se prohibieron (locales o de depuradores)" if skipped else ""))
        elif t == "dbg_unban":
            DB.execute("UPDATE users SET banned=NULL WHERE name=?", (target,))
            DB.execute("DELETE FROM bans WHERE user=?", (target,))
            DB.commit()
            log_event(user, f"restauró a {target}")
        elif t == "dbg_delete":
            if str(msg.get("confirm", "")).strip().lower() != target:
                return await toast("escribe el nombre exacto para confirmar")
            related = related_users(target)
            await kick_user(target)
            purge_user(target)
            log_event(user, f"borró definitivamente a {target}")
            await push(related)
        await ws.send_json({"type": "dbg_users", "users": dbg_users()})
        return
    else:
        return
    if t in ("dbg_announce", "dbg_announce_clear"):
        for u in list(socks):
            await send_user(u, {"type": "announce", "announce": a})
        await toast("listo")


# ---------- websocket ----------
async def handle(ws, user, me, msg):
    t = msg.get("type")
    toast = lambda text: ws.send_json({"type": "toast", "text": text})
    result = lambda op, ok, text="": ws.send_json({"type": "result", "op": op, "ok": ok, "text": text})

    if t in MUTATING and is_locked(user):
        return await ws.send_json({"type": "locked"})
    if (t not in ("hello", "changelog_get") and not (isinstance(t, str) and t.startswith("dbg_")) and maint_now()
            and not is_debugger(user)):
        return   # en mantenimiento: solo los depuradores pueden cambiar cosas (y los equipos siguen conectados)
    if t == "changelog_get":
        return await result("changelog_get", True, json.dumps(changelog_list()))
    if isinstance(t, str) and t.startswith("dbg_"):
        if is_debugger(user):
            await handle_debug(ws, user, msg, toast)
        return

    if t == "hello":
        dev = str(msg.get("device_id", ""))[:64]
        if not dev:
            return
        if DB.execute("SELECT 1 FROM bans WHERE kind='device' AND value=?", (dev,)).fetchone():
            await ws.send_json({"type": "banned"})
            await ws.close()
            return
        if is_locked(user) and not DB.execute("SELECT 1 FROM devices WHERE owner=? AND id=?", (user, dev)).fetchone():
            return await ws.send_json({"type": "locked"})   # añadir un equipo nuevo es un cambio de la cuenta
        me.update(device_id=dev, platform=str(msg.get("platform", "?"))[:40],
                  kind="agent" if msg.get("kind") == "agent" else "web")
        name = str(msg.get("name", "dispositivo"))[:40]
        DB.execute("INSERT OR IGNORE INTO devices(owner, id, name, platform, kind) VALUES(?,?,?,?,?)", (user, dev, name, me["platform"], me["kind"]))
        DB.execute("UPDATE devices SET platform=?, kind=? WHERE owner=? AND id=?", (me["platform"], me["kind"], user, dev))
        cv = str(msg.get("client_version", ""))[:12]   # version del cliente (app / agente); los antiguos no la mandan
        me["cv"] = cv if VERSION_RE.fullmatch(cv) else ""
        DB.execute("UPDATE devices SET client_version=? WHERE owner=? AND id=?", (cv if VERSION_RE.fullmatch(cv) else None, user, dev))
        DB.commit()
        await push(device_audience(user, dev))

    elif t == "metrics":
        if me["device_id"] and isinstance(msg.get("data"), dict):
            metrics[(user, me["device_id"])] = clean_metrics(msg["data"])
            await push_values(user, me["device_id"])

    elif t == "var_create":
        name = str(msg.get("name", "")).strip()[:40]
        if not name:
            return await toast("la variable necesita un nombre")
        if DB.execute("SELECT COUNT(*) FROM vars WHERE owner=?", (user,)).fetchone()[0] >= MAX_VARS:
            return await toast("límite de variables alcanzado")
        if msg.get("kind") == "auto":
            dev, metric = str(msg.get("device_id", "")), msg.get("metric")
            param = str(msg.get("param", "")).strip()[:40] if metric == "apptime" else None
            ok = DB.execute("SELECT 1 FROM devices WHERE owner=? AND id=? AND kind='agent'", (user, dev)).fetchone()
            if not ok and dev in ("@steam", "@roblox") and isinstance(metric, str) and metric.startswith(dev[1:] + "_"):
                ok = DB.execute("SELECT 1 FROM connections WHERE owner=? AND service=?", (user, dev[1:])).fetchone()
            if not ok or metric not in METRICS:
                return await toast("elige un dispositivo con agente y una métrica válida")
            if metric == "apptime" and not param:
                return await toast("escribe el nombre de la app (por ejemplo roblox)")
            DB.execute("INSERT INTO vars(owner,name,kind,device_id,metric,param) VALUES(?,?,?,?,?,?)",
                       (user, name, "auto", dev, metric, param))
        else:
            DB.execute("INSERT INTO vars(owner,name,kind,value) VALUES(?,?,?,?)",
                       (user, name, "manual", str(msg.get("value", ""))[:2000]))
        DB.commit()
        await push({user})

    elif t == "var_set":
        vid = msg.get("id")
        if DB.execute("SELECT 1 FROM vars WHERE id=? AND owner=? AND kind='manual'", (vid, user)).fetchone():
            DB.execute("UPDATE vars SET value=? WHERE id=?", (str(msg.get("value", ""))[:2000], vid))
            DB.commit()
            await push(var_audience(vid))
            schedule_automations(user, {vid})

    elif t == "var_delete":
        vid = msg.get("id")
        aud = var_audience(vid)
        if DB.execute("SELECT 1 FROM vars WHERE id=? AND owner=?", (vid, user)).fetchone():
            DB.execute("DELETE FROM shares WHERE var_id=?", (vid,))
            DB.execute("DELETE FROM automations WHERE var_id=?", (vid,))
            DB.execute("DELETE FROM vars WHERE id=?", (vid,))
        else:  # variable de otra persona: solo dejo de verla
            DB.execute("DELETE FROM shares WHERE var_id=? AND with_user=?", (vid, user))
        DB.commit()
        await push(aud | {user})

    elif t in ("var_share", "var_unshare"):
        vid, target = msg.get("id"), str(msg.get("user", "")).strip().lower()
        if not DB.execute("SELECT 1 FROM vars WHERE id=? AND owner=?", (vid, user)).fetchone():
            return
        if t == "var_share":
            if target == user:
                return await toast("ya es tuya")
            if not DB.execute("SELECT 1 FROM users WHERE name=?", (target,)).fetchone():
                return await toast(f"no existe el usuario «{target}»")
            DB.execute("INSERT OR IGNORE INTO shares VALUES(?,?)", (vid, target))
        else:
            DB.execute("DELETE FROM shares WHERE var_id=? AND with_user=?", (vid, target))
        DB.commit()
        await push(var_audience(vid) | {target})

    elif t == "dev_rename":
        dev, name = str(msg.get("device_id", "")), str(msg.get("name", "")).strip()[:40]
        if name:
            DB.execute("UPDATE devices SET name=? WHERE owner=? AND id=?", (name, user, dev))
            DB.commit()
            await push(device_audience(user, dev))

    elif t == "dev_delete":
        dev = str(msg.get("device_id", ""))
        for w, peer in list(socks.get(user, {}).items()):   # si esta conectado: se revoca su sesion y se le manda cerrar sesion ya
            if peer["device_id"] == dev:
                DB.execute("DELETE FROM sessions WHERE token=? AND user=?", (peer.get("token"), user))
                DB.commit()
                try:
                    await w.send_json({"type": "kick"})
                    await w.close()
                except Exception:
                    pass
        aud = device_audience(user, dev)
        ids = [r[0] for r in DB.execute("SELECT id FROM vars WHERE owner=? AND device_id=?", (user, dev))]
        for vid in ids:
            DB.execute("DELETE FROM shares WHERE var_id=?", (vid,))
            DB.execute("DELETE FROM automations WHERE var_id=?", (vid,))
        DB.execute("DELETE FROM vars WHERE owner=? AND device_id=?", (user, dev))
        DB.execute("DELETE FROM devices WHERE owner=? AND id=?", (user, dev))
        DB.execute("DELETE FROM widget_devices WHERE device_id=? AND widget_id IN (SELECT id FROM widgets WHERE owner=?)", (dev, user))   # el id sale del hardware: dos cuentas pueden compartir PC
        DB.commit()
        metrics.pop((user, dev), None)
        await push(aud)

    elif t == "key_create":
        label = str(msg.get("label", "")).strip()[:40] or "mi llave"
        if DB.execute("SELECT COUNT(*) FROM api_keys WHERE owner=?", (user,)).fetchone()[0] >= 10:
            return await toast("máximo 10 llaves")
        key = "hub_" + secrets.token_urlsafe(32)
        DB.execute("INSERT INTO api_keys(owner,label,hash,prefix,created) VALUES(?,?,?,?,?)",
                   (user, label, key_hash(key), key[:8], time.time()))
        DB.commit()
        await ws.send_json({"type": "key_created", "key": key, "label": label})   # la unica vez que se ve entera
        await push({user})

    elif t == "key_delete":
        DB.execute("DELETE FROM api_keys WHERE id=? AND owner=?", (msg.get("id"), user))
        DB.commit()
        await push({user})

    elif t == "widget_create":
        if DB.execute("SELECT COUNT(*) FROM widgets WHERE owner=?", (user,)).fetchone()[0] >= MAX_WIDGETS:
            return await toast("límite de widgets alcanzado")
        data = clean_widget_data(msg["data"]) if isinstance(msg.get("data"), dict) else default_widget_data()
        wid = DB.execute("INSERT INTO widgets(owner,name,data,rev) VALUES(?,?,?,1)",
                         (user, (str(msg.get("name", "")).strip() or "widget")[:40], json.dumps(data))).lastrowid
        DB.commit()
        await ws.send_json({"type": "widget_created", "id": wid})
        await push({user})

    elif t == "widget_update":
        wid = msg.get("id")
        if DB.execute("SELECT 1 FROM widgets WHERE id=? AND owner=?", (wid, user)).fetchone():
            if isinstance(msg.get("data"), dict):
                DB.execute("UPDATE widgets SET data=?, rev=rev+1 WHERE id=?", (json.dumps(clean_widget_data(msg["data"])), wid))
            if "name" in msg:
                DB.execute("UPDATE widgets SET name=? WHERE id=?", ((str(msg["name"]).strip() or "widget")[:40], wid))
            DB.commit()
            await push({user})

    elif t == "widget_devices":
        wid = msg.get("id")
        if DB.execute("SELECT 1 FROM widgets WHERE id=? AND owner=?", (wid, user)).fetchone():
            mine = {r[0] for r in DB.execute("SELECT id FROM devices WHERE owner=?", (user,))}
            wanted = {str(d) for d in (msg.get("devices") or []) if str(d) in mine}
            DB.execute("DELETE FROM widget_devices WHERE widget_id=?", (wid,))
            DB.executemany("INSERT INTO widget_devices VALUES(?,?)", [(wid, d) for d in wanted])
            DB.execute("UPDATE widgets SET rev=rev+1 WHERE id=?", (wid,))
            DB.commit()
            await push({user})

    elif t == "widget_delete":
        wid = msg.get("id")
        if DB.execute("SELECT 1 FROM widgets WHERE id=? AND owner=?", (wid, user)).fetchone():
            DB.execute("DELETE FROM widget_devices WHERE widget_id=?", (wid,))
            DB.execute("DELETE FROM widgets WHERE id=?", (wid,))
            DB.commit()
            gc_assets(user)
            await push({user})

    elif t == "set_avatar":
        data = msg.get("data", "")
        if isinstance(data, str) and data.startswith("data:image/") and len(data) < 300_000:
            DB.execute("UPDATE users SET avatar=? WHERE name=?", (data, user))
            DB.commit()
            await push({user})

    elif t == "update_device":   # el portal pide a un equipo con el agente/app que se actualice
        dev = str(msg.get("device_id", ""))
        if not DB.execute("SELECT 1 FROM devices WHERE owner=? AND id=?", (user, dev)).fetchone():
            return
        if not is_online(user, dev):
            return await toast("ese equipo está desconectado: ábrelo primero")
        await send_user(user, {"type": "update_now"}, only=lambda p: p["device_id"] == dev and p["kind"] == "agent")
        await toast("orden de actualización enviada")

    elif t == "unlock":
        key = "u:" + user
        if too_many_fails(key):
            return await result("unlock", False, "demasiados intentos, espera 5 min")
        row = DB.execute("SELECT lock_salt, lock_hash FROM users WHERE name=?", (user,)).fetchone()
        if not (row and row[1]):
            return await result("unlock", False, "el bloqueo no está activado")
        if not hmac.compare_digest(hash_pw(str(msg.get("key", "")), row[0]), row[1]):
            fails.setdefault(key, []).append(time.time())
            return await result("unlock", False, "2.ª clave incorrecta")
        DB.execute("UPDATE users SET unlocked_until=? WHERE name=?", (time.time() + UNLOCK_SECS, user))
        DB.commit()
        await result("unlock", True, "cuenta desbloqueada por 10 minutos")
        await push({user})

    elif t == "lock_now":
        DB.execute("UPDATE users SET unlocked_until=0 WHERE name=?", (user,))
        DB.commit()
        await push({user})

    elif t in ("lock_set", "lock_disable", "change_password", "change_name"):
        key = "u:" + user
        if too_many_fails(key):
            return await result(t, False, "demasiados intentos, espera 5 min")
        pw = str(msg.get("password", ""))
        if not check_password(user, pw):
            fails.setdefault(key, []).append(time.time())
            return await result(t, False, "la contraseña de la cuenta no es correcta")
        if t == "lock_set":
            k2 = str(msg.get("key", ""))
            if len(k2) < 6:
                return await result(t, False, "la 2.ª clave debe tener al menos 6 caracteres")
            if k2 == pw:
                return await result(t, False, "la 2.ª clave debe ser distinta de la contraseña")
            salt = secrets.token_bytes(16)
            DB.execute("UPDATE users SET lock_salt=?, lock_hash=?, unlocked_until=0 WHERE name=?", (salt, hash_pw(k2, salt), user))
            DB.commit()
            await result(t, True, "bloqueo activado")
            await push({user})
        elif t == "lock_disable":
            DB.execute("UPDATE users SET lock_salt=NULL, lock_hash=NULL, unlocked_until=0 WHERE name=?", (user,))
            DB.commit()
            await result(t, True, "bloqueo desactivado")
            await push({user})
        elif t == "change_password":
            new = str(msg.get("new", ""))
            if len(new) < 8:
                return await result(t, False, "la contraseña nueva debe tener al menos 8 caracteres")
            if new == pw:
                return await result(t, False, "la contraseña nueva es igual a la actual")
            salt = secrets.token_bytes(16)
            DB.execute("UPDATE users SET salt=?, hash=? WHERE name=?", (salt, hash_pw(new, salt), user))
            DB.commit()
            await result(t, True, "contraseña cambiada")
        else:   # change_name
            new = str(msg.get("name", "")).strip().lower()
            if not 3 <= len(new) <= 32:
                return await result(t, False, "el nombre debe tener entre 3 y 32 caracteres")
            if new == user:
                return await result(t, False, "ese ya es tu nombre")
            if DB.execute("SELECT 1 FROM users WHERE name=?", (new,)).fetchone():
                return await result(t, False, "ese nombre ya está en uso")
            others = related_users(user)
            rename_user(user, new)
            await result(t, True, "nombre cambiado a «" + new + "»")
            mine = socks.pop(user, {})
            socks.setdefault(new, {})
            for w in list(mine):   # las conexiones viejas se cierran y los clientes vuelven a entrar con su sesión
                try:
                    await w.close()
                except Exception:
                    pass
            await push(others)

    elif t == "passkey_delete":
        DB.execute("DELETE FROM passkeys WHERE id=? AND owner=?", (msg.get("id"), user))
        DB.commit()
        await push({user})

    elif t == "webhook_result":   # un dispositivo contesta a `fire_webhook`
        h = pending_hooks.get(msg.get("id"))
        if h and h[0] == user and not h[1].done():
            h[1].set_result({"ok": bool(msg.get("ok")), "status": msg.get("status"), "error": str(msg.get("error", ""))[:120]})

    elif t == "automation_save":
        f, err = clean_automation(user, msg)
        if err:
            return await result("automation", False, err)
        aid = msg.get("id")
        cur = var_raw(user, f["var_id"])
        raw = cur[1] if cur else None
        base = int(holds(f["op"], raw, f["value"])) if f["op"] != "changes" else 0   # lo que ya se cumple al crearla no dispara
        if aid:
            if not DB.execute("SELECT 1 FROM automations WHERE id=? AND owner=?", (aid, user)).fetchone():
                return await result("automation", False, "esa automatización ya no existe")
            DB.execute("UPDATE automations SET name=?, var_id=?, op=?, value=?, kind=?, url=?, body=?, cooldown=?, last_state=?, last_value=? "
                       "WHERE id=? AND owner=?", (f["name"], f["var_id"], f["op"], f["value"], f["kind"], f["url"], f["body"], f["cooldown"],
                                                  base, None if raw is None else str(raw), aid, user))
        else:
            if DB.execute("SELECT COUNT(*) FROM automations WHERE owner=?", (user,)).fetchone()[0] >= MAX_AUTOMATIONS:
                return await result("automation", False, "máximo 20 automatizaciones")
            DB.execute("INSERT INTO automations(owner, name, enabled, var_id, op, value, kind, url, body, cooldown, last_state, last_value, created) "
                       "VALUES(?,?,1,?,?,?,?,?,?,?,?,?,?)", (user, f["name"], f["var_id"], f["op"], f["value"], f["kind"], f["url"], f["body"],
                                                            f["cooldown"], base, None if raw is None else str(raw), time.time()))
        DB.commit()
        await result("automation", True, "automatización guardada")
        await push({user})

    elif t == "automation_delete":
        DB.execute("DELETE FROM automations WHERE id=? AND owner=?", (msg.get("id"), user))
        DB.commit()
        await push({user})

    elif t == "automation_toggle":
        DB.execute("UPDATE automations SET enabled=?, last_state=NULL WHERE id=? AND owner=?", (int(bool(msg.get("enabled"))), msg.get("id"), user))
        DB.commit()
        await push({user})

    elif t == "automation_test":   # manda el aviso ahora, sin esperar a que se cumpla la condición
        aid = msg.get("id")
        r = DB.execute("SELECT id, name, var_id, kind, url, body FROM automations WHERE id=? AND owner=?", (aid, user)).fetchone()
        if not r:
            return
        if time.time() - test_times.get(aid, 0) < 5:
            return await toast("espera unos segundos entre pruebas")
        test_times[aid] = time.time()
        got = var_raw(user, r[2]) or ("?", None, "?")
        a = dict(id=r[0], name=r[1], kind=r[3], url=r[4], body=r[5])
        asyncio.get_running_loop().create_task(fire(user, a, got[1], got[2], got[0]))
        await toast("prueba enviada: mira el estado de la automatización")

    elif t == "conn_save":
        svc = msg.get("service")
        if svc not in SERVICES:
            return
        old = DB.execute("SELECT cfg FROM connections WHERE owner=? AND service=?", (user, svc)).fetchone()
        old = json.loads(old[0]) if old else {}
        if svc == "steam":
            key, sid = str(msg.get("key", "")).strip(), str(msg.get("id", "")).strip()
            key = key or old.get("key", "")   # vacío = conservar la que ya hay (nunca se manda de vuelta al portal)
            if not STEAM_KEY_RE.fullmatch(key):
                return await result("conn", False, "la api key de steam son 32 letras y números")
            if not STEAM_ID_RE.fullmatch(sid):
                return await result("conn", False, "escribe tu id de steam o el nombre de tu perfil")
            cfg = {"key": key, "id": sid}
        else:
            name = str(msg.get("user", "")).strip()
            if not ROBLOX_RE.fullmatch(name):
                return await result("conn", False, "escribe tu nombre de usuario de roblox")
            cfg = {"user": name}
        DB.execute("INSERT OR REPLACE INTO connections(owner, service, cfg) VALUES(?,?,?)", (user, svc, json.dumps(cfg)))
        DB.commit()
        conn_status[(user, svc)] = ["conectando…", time.time()]
        await result("conn", True, "conexión guardada")
        await push({user})
        asyncio.get_running_loop().create_task(poll_conn(user, svc))

    elif t == "conn_delete":
        svc = msg.get("service")
        dev = "@" + str(svc)
        aud = {user}
        for (vid,) in DB.execute("SELECT id FROM vars WHERE owner=? AND device_id=?", (user, dev)).fetchall():
            aud |= var_audience(vid)
            DB.execute("DELETE FROM shares WHERE var_id=?", (vid,))
            DB.execute("DELETE FROM automations WHERE var_id=?", (vid,))
        DB.execute("DELETE FROM vars WHERE owner=? AND device_id=?", (user, dev))
        DB.execute("DELETE FROM connections WHERE owner=? AND service=?", (user, svc))
        DB.commit()
        metrics.pop((user, dev), None)
        conn_status.pop((user, svc), None)
        conn_polled.pop((user, svc), None)
        await push(aud)

    elif t == "conn_test":
        svc = msg.get("service")
        if svc not in SERVICES:
            return
        if time.time() - conn_tests.get((user, svc), 0) < 10:
            return await toast("espera unos segundos entre pruebas")
        conn_tests[(user, svc)] = time.time()
        asyncio.get_running_loop().create_task(poll_conn(user, svc))
        await toast("consultando…")

    elif t == "cameras":   # el agente de un PC informa de sus camaras (para elegirlas desde el editor)
        if me["kind"] == "agent" and me["device_id"]:
            names = [str(x)[:80] for x in (msg.get("list") or [])[:20] if isinstance(x, str)]
            DB.execute("UPDATE devices SET cameras=? WHERE owner=? AND id=?", (json.dumps(names), user, me["device_id"]))
            DB.commit()
            await push({user})

    elif t == "cameras_refresh":   # el editor pide que los agentes vuelvan a buscar camaras
        if not any(p["kind"] == "agent" for p in socks.get(user, {}).values()):
            return await toast("ningún pc con el agente está conectado ahora")
        await send_user(user, {"type": "scan_cameras"}, only=lambda p: p["kind"] == "agent")

    elif t == "request_win_avatar":
        agents = [p for p in socks.get(user, {}).values() if p["kind"] == "agent" and p["platform"] == "Windows"]
        if not agents:
            return await toast("ejecuta el agente en tu pc con windows para leer su foto de perfil")
        await send_user(user, {"type": "want_avatar"}, only=lambda p: p in agents)

    elif t == "avatar":  # llega del agente; el navegador la reduce y la guarda
        data = msg.get("data", "")
        if me["kind"] == "agent" and isinstance(data, str) and data.startswith("data:image/") and len(data) < 3_000_000:
            await send_user(user, {"type": "avatar_candidate", "data": data}, only=lambda p: p["kind"] == "web")


async def ws_handler(request):
    ws = web.WebSocketResponse(max_msg_size=MAX_MSG, heartbeat=20)
    await ws.prepare(request)
    try:  # el primer mensaje debe ser {"type":"auth","token":...}
        first = await asyncio.wait_for(ws.receive_json(), 10)
    except Exception:
        await ws.close()
        return ws
    if banned_ip(client_ip(request)):
        await ws.send_json({"type": "banned"})
        await ws.close()
        return ws
    tok = first.get("token", "") if first.get("type") == "auth" else ""
    srow = DB.execute("SELECT user, exp FROM sessions WHERE token=?", (tok,)).fetchone() if tok else None
    if srow and srow[1] > time.time() and is_banned(srow[0]):
        await ws.send_json({"type": "banned"})
        await ws.close()
        return ws
    user = user_from_token(tok)
    if user:
        record_ip(user, client_ip(request))
    if not user:
        await ws.send_json({"type": "auth_error"})
        await ws.close()
        return ws

    me = {"device_id": None, "platform": "?", "kind": "web", "token": first.get("token")}
    socks.setdefault(user, {})[ws] = me
    await ws.send_json(state_for(user))
    async for m in ws:
        if m.type != WSMsgType.TEXT:
            continue
        try:
            await handle(ws, user, me, json.loads(m.data))
        except Exception as e:  # un mensaje malo no debe tumbar la conexion
            print("error en mensaje:", repr(e))
            EVENTS.append(f"{time.strftime('%H:%M:%S')} error: {type(e).__name__}: {str(e)[:100]}")
    socks.get(user, {}).pop(ws, None)
    if me["device_id"] and user_exists(user):
        await push(device_audience(user, me["device_id"]))
    return ws


def user_exists(u):
    return bool(DB.execute("SELECT 1 FROM users WHERE name=?", (u,)).fetchone())


def gc_assets(user):
    """Borra archivos subidos hace mas de 1 h que ya ningun widget usa."""
    used = "".join(r[0] for r in DB.execute("SELECT data FROM widgets WHERE owner=? AND data IS NOT NULL", (user,)))
    for aid, in DB.execute("SELECT id FROM assets WHERE owner=? AND created<?", (user, time.time() - 3600)).fetchall():
        if aid not in used:
            DB.execute("DELETE FROM assets WHERE id=?", (aid,))
    DB.commit()


async def asset_upload(request):
    """POST /api/asset con Authorization: Bearer <sesion> y el archivo en el cuerpo (cabecera X-Filename)."""
    auth = request.headers.get("Authorization", "")
    user = user_from_token(auth[7:].strip()) if auth.startswith("Bearer ") else None
    if not user:
        return web.json_response({"error": "sesión inválida"}, status=401)
    if is_locked(user):
        return web.json_response({"error": "cuenta bloqueada: desbloquéala en el portal (ajustes)"}, status=423)
    name = request.headers.get("X-Filename", "archivo")[:80]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ASSET_TYPES:
        return web.json_response({"error": "tipo no permitido (png, jpg, gif, webp, pdf, txt, md)"}, status=415)
    data = await request.read()
    if len(data) > MAX_ASSET:
        return web.json_response({"error": "máximo 8 MB por archivo"}, status=413)
    if ext in MAGIC and not data.startswith(MAGIC[ext]):
        return web.json_response({"error": "el archivo no coincide con su tipo"}, status=415)
    if ext in ("txt", "md"):
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return web.json_response({"error": "el texto debe estar en UTF-8"}, status=415)
    if DB.execute("SELECT COALESCE(SUM(size),0) FROM assets WHERE owner=?", (user,)).fetchone()[0] + len(data) > ASSET_QUOTA:
        return web.json_response({"error": "cuota de 100 MB llena"}, status=413)
    aid = secrets.token_urlsafe(18)
    DB.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?)", (aid, user, name, ASSET_TYPES[ext], data, len(data), time.time()))
    DB.commit()
    return web.json_response({"id": aid, "name": name, "kind": "pdf" if ext == "pdf" else "text" if ext in ("txt", "md") else "image"})


async def asset_get(request):
    """GET /asset/<id>: el id es imposible de adivinar. Se sirve sin poder ejecutar scripts (sandbox + nosniff)."""
    row = DB.execute("SELECT mime, data FROM assets WHERE id=?", (request.match_info["id"],)).fetchone()
    if not row:
        return web.Response(status=404)
    headers = {"Access-Control-Allow-Origin": "*", "X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"}
    if row[0] != "application/pdf":   # el visor de PDF no arranca dentro de un sandbox; el resto sí va sin poder ejecutar nada
        headers["Content-Security-Policy"] = "sandbox"
    return web.Response(body=row[1], content_type=row[0], charset="utf-8" if row[0] == "text/plain" else None, headers=headers)


async def editor_page(request):
    return web.FileResponse(HERE / "editor.html", headers={"Cache-Control": "no-cache"})


async def widget_js(request):
    return web.FileResponse(HERE / "widget.js", headers={"Cache-Control": "no-cache"})


def key_hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


push_log = {}   # id de llave -> [timestamps]


async def api_push(request):
    """POST /api/push  con  Authorization: Bearer hub_...  y  {"vars": {"pasos": "8421", ...}}  (o {"name":..,"value":..})."""
    auth = request.headers.get("Authorization", "")
    row = DB.execute("SELECT id, owner FROM api_keys WHERE hash=?", (key_hash(auth[7:].strip()),)).fetchone() \
        if auth.startswith("Bearer ") else None
    if not row:
        return web.json_response({"error": "llave inválida"}, status=401)
    kid, user = row
    if is_locked(user):
        return web.json_response({"error": "cuenta bloqueada: desbloquéala en el portal (ajustes)"}, status=423)
    now = time.time()
    push_log[kid] = [t for t in push_log.get(kid, []) if now - t < 60]
    if len(push_log[kid]) >= 120:
        return web.json_response({"error": "demasiadas peticiones (máx. 120/min)"}, status=429)
    push_log[kid].append(now)
    try:
        d = await request.json()
    except ValueError:
        return web.json_response({"error": "JSON inválido"}, status=400)
    items = d.get("vars") if isinstance(d, dict) and isinstance(d.get("vars"), dict) else \
        {d.get("name"): d.get("value")} if isinstance(d, dict) and d.get("name") else None
    if not items:
        return web.json_response({"error": 'usa {"vars": {"nombre": "valor"}}'}, status=400)
    done, skipped, aud, touched = 0, [], set(), set()
    for name, value in items.items():
        name, value = str(name).strip()[:40], str(value)[:2000]
        row = DB.execute("SELECT id, kind FROM vars WHERE owner=? AND lower(name)=lower(?)", (user, name)).fetchone()
        if row and row[1] != "manual":
            skipped.append(name)
            continue
        if row:
            DB.execute("UPDATE vars SET value=? WHERE id=?", (value, row[0]))
            vid = row[0]
        elif name and DB.execute("SELECT COUNT(*) FROM vars WHERE owner=?", (user,)).fetchone()[0] < MAX_VARS:
            vid = DB.execute("INSERT INTO vars(owner,name,kind,value) VALUES(?,?,?,?)", (user, name, "manual", value)).lastrowid
        else:
            skipped.append(name)
            continue
        aud |= var_audience(vid)
        touched.add(vid)
        done += 1
    DB.commit()
    await push(aud | {user})
    schedule_automations(user, touched)
    return web.json_response({"updated": done, "skipped": skipped})


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


async def index(request):
    return web.FileResponse(HERE / "index.html", headers={"Cache-Control": "no-cache"})


README = """hub - proyecto completo

Para alojarlo en tu propio PC:
  1. Instala Python 3.10 o superior.
  2. pip install aiohttp psutil cryptography
  3. python server.py
  4. Abre http://localhost:8765 y crea tu cuenta.
Otros equipos de tu red entran con http://IP-DE-TU-PC:8765 (abre el puerto 8765 en el firewall).

Variables de entorno opcionales: PORT, DB_PATH (donde se guarda la base de datos), ALLOW_REGISTER=0
(cierra el registro cuando ya creaste tus cuentas).

Para internet: Dockerfile y fly.toml sirven para Fly.io. Usa siempre HTTPS fuera de tu red.
agent.py es el agente de escritorio; la carpeta android (si viene) es el codigo de la app del telefono.
Este programa no esta enfocado en seguridad: no guardes informacion sensible en el.
"""
PROJECT_FILES = ["VERSION", "CHANGELOG.md", "DESPLIEGUE.md", "server.py", "index.html", "editor.html", "widget.js", "i18n.js", "agent.py", "requirements.txt",
                 "Dockerfile", "fly.toml", "hub.apk", "HubSetup.exe"]


async def project_zip(request):
    """Descarga el codigo del proyecto (nunca la base de datos ni nada con datos de usuarios)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("hub/LEEME.txt", README)
        for name in PROJECT_FILES:
            if (HERE / name).is_file():
                z.write(HERE / name, "hub/" + name)
        android = HERE.parent / "android"
        if android.is_dir():
            for f in android.rglob("*"):
                rel = f.relative_to(android).parts
                if f.is_file() and not {"build", ".gradle", ".idea"} & set(rel) and f.name != "local.properties":
                    z.write(f, "android/" + "/".join(rel))
    return web.Response(body=buf.getvalue(), content_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="hub-proyecto.zip"'})


def external_url(name):
    """URL https de un archivo pesado alojado fuera (APK_URL, INSTALLER_URL), o None."""
    u = os.environ.get(name, "").strip()
    return u if u.startswith("https://") else None


async def installer_file(request):
    if external_url("INSTALLER_URL"):
        raise web.HTTPFound(external_url("INSTALLER_URL"))
    f = HERE / "HubSetup.exe"
    if not f.exists():
        return web.Response(status=404, text="el instalador de windows todavía no está en este servidor")
    return web.FileResponse(f, headers={"Content-Type": "application/vnd.microsoft.portable-executable",
                                        "Content-Disposition": 'attachment; filename="HubSetup.exe"'})


async def i18n_file(request):
    return web.FileResponse(HERE / "i18n.js", headers={"Cache-Control": "no-cache"})


async def version_info(request):
    return web.json_response({"version": VERSION})


async def apk_file(request):
    if external_url("APK_URL"):
        raise web.HTTPFound(external_url("APK_URL"))
    f = HERE / "hub.apk"
    if not f.exists():
        return web.Response(status=404, text="la app de android todavía no está en este servidor")
    return web.FileResponse(f, headers={"Content-Type": "application/vnd.android.package-archive",
                                        "Content-Disposition": 'attachment; filename="hub.apk"'})


async def agent_file(request):
    return web.FileResponse(HERE / "agent.py", headers={"Content-Disposition": 'attachment; filename="agent.py"'})


# ---------- páginas de error y de respuesta (404, error de api, respuesta correcta) ----------
import difflib, html as _html
PAGE_CSS = """
:root{--bg:#fef7ff;--surf:#f3edf7;--surf-hi:#ece6f0;--on:#1d1b20;--on-var:#49454f;--pri:#6750a4;--on-pri:#fff;--pri-c:#eaddff;--on-pri-c:#21005d;
 --err-c:#f9dedc;--on-err:#410e0b;--err:#b3261e;--warn-c:#ffdea6;--warn:#8a5100;--ok-c:#c4eed0;--ok:#1e6b3a;--spring:cubic-bezier(.34,1.56,.64,1)}
@media(prefers-color-scheme:dark){:root{--bg:#141218;--surf:#211f26;--surf-hi:#2b2930;--on:#e6e0e9;--on-var:#cac4d0;--pri:#d0bcff;--on-pri:#381e72;--pri-c:#4f378b;--on-pri-c:#eaddff;
 --err-c:#601410;--on-err:#f9dedc;--err:#f2b8b5;--warn-c:#5c3b00;--warn:#ffb951;--ok-c:#0d3a1f;--ok:#8fd6a3}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:var(--bg);color:var(--on);font:16px/1.5 system-ui,"Segoe UI",Roboto,sans-serif;text-transform:lowercase;
 display:flex;align-items:center;justify-content:center;padding:24px 16px}
.u,code,pre,.p,.json{text-transform:none}.m{text-transform:uppercase}
html[data-lang=pi] body,html[data-lang=pi] button,html[data-lang=pi] a.b1,html[data-lang=pi] a.b2{text-transform:none}
.page{width:100%;max-width:580px;animation:pop .6s var(--spring)}@keyframes pop{from{transform:scale(.94);opacity:0}to{transform:none;opacity:1}}
button,a.b1,a.b2{font:inherit;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;height:52px;padding:0 28px;border:none;font-size:16px;font-weight:500;
 transition:border-radius .35s var(--spring),transform .2s;text-transform:lowercase}
.b1{background:var(--pri);color:var(--on-pri);border-radius:26px 12px 26px 26px}.b1:hover{border-radius:26px}
.b2{background:var(--surf);color:var(--on);border-radius:26px}.b2:hover{border-radius:12px 26px 26px 26px}
.row{display:flex;gap:10px;flex-wrap:wrap;justify-content:center}
.card{background:var(--surf-hi);border-radius:44px 16px 44px 44px;padding:24px 26px}
.top{display:flex;align-items:center;gap:14px;margin-bottom:14px}
.top h1{margin:0;font-size:26px;font-weight:500;line-height:1.1}.top p{margin:3px 0 0;font-size:13.5px;color:var(--on-var)}
.badge{width:76px;height:76px;flex:none;border-radius:30px 12px 30px 30px;display:flex;align-items:center;justify-content:center;font-size:30px;font-weight:500;transform:rotate(-6deg)}
.badge>*{transform:rotate(6deg)}.badge svg{width:42px;height:42px;fill:currentColor}
.badge.err{background:var(--err-c);color:var(--err)}.badge.ok{background:var(--ok-c);color:var(--ok)}
.req{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.m{font-size:12px;font-weight:500;padding:3px 12px;border-radius:999px;background:var(--pri-c);color:var(--on-pri-c)}
.p{font-family:ui-monospace,Consolas,monospace;font-size:13px;background:var(--surf);border-radius:12px;padding:4px 12px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.st{margin-left:auto;font-size:12px;font-weight:500;padding:3px 12px;border-radius:999px}.st.err{background:var(--err-c);color:var(--err)}.st.ok{background:var(--ok-c);color:var(--ok)}
.json{position:relative;background:var(--surf);border-radius:20px 8px 20px 20px;padding:14px 16px;font:13px/1.6 ui-monospace,Consolas,monospace;margin-bottom:14px;white-space:pre-wrap;word-break:break-word}
.json .k{color:var(--pri)}.json .s{color:var(--ok)}.json .n{color:var(--warn)}
.copy{position:absolute;top:10px;right:10px;height:34px;padding:0 14px;border-radius:17px 8px 17px 17px;background:var(--pri-c);color:var(--on-pri-c);font-size:13px}.copy:hover{border-radius:17px}
.tip{font-size:14px;line-height:1.5;color:var(--on-var);margin:0 0 16px}.tip code{font-size:12.5px;background:var(--surf);padding:1px 7px;border-radius:8px;color:var(--on)}
.meta{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:16px}
.meta div{background:var(--surf);border-radius:18px 8px 18px 18px;padding:10px 14px}.meta small{display:block;font-size:11.5px;color:var(--on-var)}.meta b{font-size:16px;font-weight:500;text-transform:none}
.digits{display:flex;justify-content:center;align-items:center;gap:10px;margin:0 0 26px}
.d{width:112px;height:128px;display:flex;align-items:center;justify-content:center;font-size:76px;font-weight:500;line-height:1;transition:transform .45s var(--spring),border-radius .45s var(--spring)}
.d.a{background:var(--pri-c);color:var(--on-pri-c);border-radius:56px 20px 56px 56px;transform:rotate(-5deg)}
.d.b{background:var(--warn-c);color:var(--warn);border-radius:50%;width:132px;height:132px;transform:rotate(4deg)}
.d.c{background:var(--ok-c);color:var(--ok);border-radius:20px 56px 56px 56px;transform:rotate(-3deg)}
.d:hover{transform:rotate(0) scale(1.08);border-radius:40px}
.c404{text-align:center}.c404 h1{margin:0 0 8px;font-size:28px;font-weight:500}.c404 p{margin:0 0 20px;color:var(--on-var)}
.c404 .p{display:inline-block;margin-bottom:18px}.foot{text-align:center;margin-top:14px;font-size:12.5px;color:var(--on-var)}
@media(max-width:480px){.d{width:84px;height:100px;font-size:56px}.d.b{width:100px;height:100px}.st{margin-left:0}}
"""
PAGE_WARN = '<svg viewBox="0 0 24 24"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>'
PAGE_OK = '<svg viewBox="0 0 24 24"><path d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z"/></svg>'


def page(title, body, script=""):
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{title}</title><style>{PAGE_CSS}</style><script src="/i18n.js"></script></head><body>{body}{script}</body></html>')


def wants_html(request):
    return "text/html" in request.headers.get("Accept", "") and request.headers.get("Sec-Fetch-Dest", "document") in ("document", "")


def api_routes():
    return sorted({r.resource.canonical for r in app.router.routes() if r.resource and r.resource.canonical.startswith("/api/")})


def highlight(text):
    def sub(m):
        if m.group(1):
            return f'<span class="{"k" if m.group(2) else "s"}">{m.group(1)}</span>{m.group(2) or ""}'
        return f'<span class="n">{m.group(3) or m.group(4)}</span>'
    esc = _html.escape(text, quote=False)
    return re.sub(r'("(?:\\.|[^"\\])*")(\s*:)?|(-?\d+(?:\.\d+)?)|(true|false|null)', sub, esc)


def go_buttons():
    return ('<div class="row"><a class="b1" href="/?view=auto">ver cómo usar la api</a><a class="b2" href="/">volver al inicio</a></div>')


def error_page(request, status, allowed=None):
    path = request.path
    if not path.startswith("/api/"):
        body = (f'<div class="page c404"><div class="digits"><div class="d a">4</div><div class="d b">0</div><div class="d c">4</div></div>'
                f'<div class="card"><h1>página no encontrada</h1><div class="p u">{_html.escape(path[:200])}</div>'
                '<p>esta dirección no existe o se movió de lugar. revisa que esté bien escrita o vuelve al inicio.</p>'
                '<div class="row"><a class="b1" href="/">volver al inicio</a><button class="b2" onclick="history.length>1?history.back():location.href=\'/\'">ir atrás</button></div></div>'
                '<p class="foot">error 404 · hub</p></div>')
        return page("404", body)
    routes = api_routes()
    near = difflib.get_close_matches(path, routes, n=1, cutoff=0.6)
    if status == 405:
        title, sub = "esa ruta usa otro método", "esta ruta no se abre desde la barra del navegador: usa el método de abajo con curl o con tu app."
        data = {"error": "método no permitido", "status": 405, "permitido": sorted(allowed or [])}
        chips = "".join(f'<span class="m">{m}</span>' for m in sorted(allowed or []))
        tip = '<p class="tip">para escribir variables manda tu llave en la cabecera <code class="u">Authorization: Bearer hub_…</code>.</p>' if path == "/api/push" else ""
    else:
        title, sub = "esa ruta de la api no existe", "aquí no hay nada que devolver"
        data = {"error": "ruta no encontrada", "status": 404, "rutas": routes}
        chips = f'<span class="m">{_html.escape(request.method)}</span>'
        tip = (f'<p class="tip">quizá quisiste usar <code class="u">{_html.escape(near[0])}</code>. para escribir variables manda tu llave en la cabecera '
               '<code class="u">Authorization: Bearer hub_…</code>.</p>') if near else ""
    body = (f'<div class="page"><div class="top"><div class="badge err">{PAGE_WARN if status == 405 else "<span>404</span>"}</div><div><h1>{title}</h1><p>{sub}</p></div></div>'
            f'<div class="card"><div class="req">{chips}<span class="p u">{_html.escape(path[:200])}</span><span class="st err u">{status} · {"method not allowed" if status == 405 else "not found"}</span></div>'
            f'<div class="json u">{highlight(json.dumps(data, indent=2, ensure_ascii=False))}</div>{tip}{go_buttons()}</div></div>')
    return page(str(status), body)


def ok_page(request, raw, ms):
    try:
        text = json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
    except ValueError:
        text = raw.decode("utf-8", "replace")
    body = (f'<div class="page"><div class="top"><div class="badge ok">{PAGE_OK}</div><div><h1>todo salió bien</h1><p>la api respondió correctamente</p></div></div>'
            f'<div class="card"><div class="req"><span class="m">{_html.escape(request.method)}</span><span class="p u">{_html.escape(request.path[:200])}</span><span class="st ok u">200 · ok</span></div>'
            f'<div class="json u"><button class="copy" id="cp">copiar</button>{highlight(text)}<pre id="raw" hidden>{_html.escape(text, quote=False)}</pre></div>'
            f'<div class="meta"><div><small>tiempo</small><b>{ms} ms</b></div><div><small>tamaño</small><b>{len(raw)} B</b></div><div><small>tipo</small><b>json</b></div></div>'
            f'{go_buttons()}</div></div>')
    script = ('<script>var b=document.getElementById("cp");b.onclick=function(){var t=document.getElementById("raw").textContent;'
              'try{navigator.clipboard.writeText(t)}catch(e){}var o=b.textContent;b.textContent=(window.HubI18n?HubI18n.tr("copiado"):"copiado");'
              'setTimeout(function(){b.textContent=o},1400)};</script>')
    return page("200", body, script)


@web.middleware
async def pages_mw(request, handler):
    t0 = time.perf_counter()
    if request.path in MAINT_BLOCK and maint_now():
        u = bearer_user(request)
        if not (u and is_debugger(u)):
            return maint_response()
    try:
        resp = await handler(request)
    except web.HTTPException as ex:
        if ex.status not in (404, 405):
            raise
        headers = {"Cache-Control": "no-store"}
        if wants_html(request) and not isinstance(ex, web.HTTPFound):
            return web.Response(text=error_page(request, ex.status, getattr(ex, "allowed_methods", None)), status=ex.status,
                                content_type="text/html", headers=headers)
        if request.path.startswith("/api/"):
            data = ({"error": "método no permitido", "status": 405, "permitido": sorted(getattr(ex, "allowed_methods", []) or [])} if ex.status == 405
                    else {"error": "ruta no encontrada", "status": 404, "rutas": api_routes()})
            return web.json_response(data, status=ex.status, headers=headers)
        raise
    if (request.method == "GET" and request.path.startswith("/api/") and resp.status == 200 and resp.content_type == "application/json"
            and isinstance(resp.body, bytes) and wants_html(request)):
        return web.Response(text=ok_page(request, resp.body, round((time.perf_counter() - t0) * 1000)), content_type="text/html",
                            headers={"Cache-Control": "no-store"})
    return resp


app = web.Application(client_max_size=MAX_ASSET + 1024 * 1024, middlewares=[pages_mw])
app.on_startup.append(start_background)
app.add_routes([web.get("/", index), web.get("/agent.py", agent_file), web.get("/hub.apk", apk_file), web.get("/i18n.js", i18n_file), web.get("/instalar.exe", installer_file), web.get("/project.zip", project_zip), web.get("/api/version", version_info), web.get("/api/ban", ban_info), web.get("/api/notice", notice_info),
                web.post("/api/passkey/register/begin", passkey_reg_begin), web.post("/api/passkey/register/finish", passkey_reg_finish),
                web.post("/api/passkey/login/begin", passkey_login_begin), web.post("/api/passkey/login/finish", passkey_login_finish), web.get("/ws", ws_handler),
                web.post("/api/register", register), web.post("/api/login", login), web.post("/api/push", api_push),
                web.post("/api/asset", asset_upload), web.get("/asset/{id}", asset_get),
                web.get("/editor", editor_page), web.get("/widget.js", widget_js)])

if __name__ == "__main__":
    print(f"Hub en http://{lan_ip()}:8765  (registro {'abierto' if ALLOW_REGISTER else 'cerrado'})")
    web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8765)), print=None)
