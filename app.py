#!/usr/bin/env python3
"""Gerenciador simples de combustível para autoescolas (Python + SQLite)."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import hashlib, hmac, json, os, secrets, sqlite3, time

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT / "data")))
DB = DATA_DIR / "autoescola.sqlite3"
STATIC = ROOT / "static"
HOST, PORT = os.environ.get("HOST", "0.0.0.0"), int(os.environ.get("PORT", "8000"))
PRODUCTION = os.environ.get("APP_ENV") == "production"
SESSION_SECONDS = 60 * 60 * 12
ROLES = {"admin": "Administrador", "gestor": "Gestor", "instrutor": "Instrutor"}
SOURCE = "Inventário Nacional de Emissões Atmosféricas por Veículos Automotores Rodoviários, ano-base 2024, tabela de fatores de CO₂ (2004–2024). Estimativa de CO₂ direto da combustão."
SOURCE_URL = "https://www.gov.br/transportes/pt-br/assuntos/sustentabilidade/mudanca-do-clima/0_ineavar_2025.pdf"

def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; c.execute("PRAGMA foreign_keys=ON")
    return c

def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','gestor','instrutor')), active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, csrf TEXT NOT NULL, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS vehicles(id INTEGER PRIMARY KEY, model TEXT NOT NULL, plate TEXT NOT NULL UNIQUE COLLATE NOCASE, fuel_type TEXT NOT NULL CHECK(fuel_type IN ('gasolina','etanol')), active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS fuel_logs(id INTEGER PRIMARY KEY, vehicle_id INTEGER NOT NULL REFERENCES vehicles(id), user_id INTEGER NOT NULL REFERENCES users(id), log_date TEXT NOT NULL, distance_km REAL NOT NULL, liters REAL NOT NULL, price_per_liter REAL NOT NULL, emission_factor REAL NOT NULL, notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS emission_factors(fuel_type TEXT PRIMARY KEY, kg_per_liter REAL NOT NULL, source TEXT NOT NULL, source_url TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        """)
        c.executemany("INSERT OR IGNORE INTO emission_factors VALUES(?,?,?,?,CURRENT_TIMESTAMP)", [("gasolina",2.23,SOURCE,SOURCE_URL),("etanol",2.46,SOURCE,SOURCE_URL)])

def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return salt.hex()+":"+key.hex()

def verify_password(password, stored):
    try:
        salt, digest = stored.split(":")
        return hmac.compare_digest(password_hash(password, bytes.fromhex(salt)).split(":")[1], digest)
    except Exception: return False

def js(row): return dict(row) if row is not None else None

class API(BaseHTTPRequestHandler):
    server_version = "FuelSchool/1.0"
    def log_message(self, *_): pass
    def respond(self, status, obj=None, headers=None):
        body = b"" if obj is None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.send_header("X-Content-Type-Options","nosniff"); self.send_header("Cache-Control","no-store")
        for k,v in (headers or {}).items(): self.send_header(k,v)
        self.end_headers()
        if body: self.wfile.write(body)
    def body(self):
        n = int(self.headers.get("Content-Length",0))
        if n>100_000: raise ValueError("Requisição muito grande")
        return json.loads(self.rfile.read(n) or b"{}")
    def current(self):
        cookie=self.headers.get("Cookie",""); token=""
        for part in cookie.split(";"):
            if part.strip().startswith("session="): token=part.strip()[8:]
        if not token: return None
        with connect() as c:
            row=c.execute("SELECT u.*,s.csrf,s.expires FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?",(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            if not row or row["expires"]<int(time.time()) or not row["active"]: return None
            return js(row)
    def require(self, roles=None, write=False):
        u=self.current()
        if not u: self.respond(401,{"error":"Faça login para continuar."}); return None
        if roles and u["role"] not in roles: self.respond(403,{"error":"Seu perfil não tem permissão para esta ação."}); return None
        if write and not hmac.compare_digest(self.headers.get("X-CSRF-Token",""),u["csrf"]): self.respond(403,{"error":"Token de segurança inválido. Atualize a página."}); return None
        return u
    def do_GET(self):
        p=urlparse(self.path).path
        if p.startswith("/api/"): return self.api_get(p)
        path = STATIC / ("index.html" if p=="/" else p.lstrip("/"))
        if not path.resolve().is_relative_to(STATIC.resolve()) or not path.is_file(): self.send_error(404); return
        data=path.read_bytes(); typ="text/html; charset=utf-8" if path.suffix==".html" else "text/css; charset=utf-8" if path.suffix==".css" else "text/javascript; charset=utf-8"
        self.send_response(200); self.send_header("Content-Type",typ); self.send_header("Content-Length",str(len(data))); self.send_header("X-Content-Type-Options","nosniff"); self.end_headers(); self.wfile.write(data)
    def api_get(self,p):
        try:
            with connect() as c:
                if p=="/api/status":
                    return self.respond(200,{"setup_required":c.execute("SELECT COUNT(*) FROM users").fetchone()[0]==0})
                if p=="/api/me":
                    u=self.current(); return self.respond(200,{"user":{k:u[k] for k in ("id","name","email","role")} if u else None,"csrf":u["csrf"] if u else None})
                u=self.require()
                if not u:return
                if p=="/api/vehicles": return self.respond(200,{"vehicles":[js(x) for x in c.execute("SELECT * FROM vehicles WHERE active=1 ORDER BY model")]})
                if p=="/api/logs":
                    sql="SELECT l.*,v.model,v.plate,v.fuel_type,u.name AS author, l.liters*l.price_per_liter AS total_cost,l.distance_km/l.liters AS km_per_liter,l.liters*l.emission_factor AS co2_kg FROM fuel_logs l JOIN vehicles v ON v.id=l.vehicle_id JOIN users u ON u.id=l.user_id"
                    args=()
                    if u["role"]=="instrutor": sql+=" WHERE l.user_id=?"; args=(u["id"],)
                    sql+=" ORDER BY l.log_date DESC,l.id DESC LIMIT 500"
                    return self.respond(200,{"logs":[js(x) for x in c.execute(sql,args)]})
                if p=="/api/users":
                    if u["role"]!="admin":return self.respond(403,{"error":"Apenas administrador."})
                    return self.respond(200,{"users":[js(x) for x in c.execute("SELECT id,name,email,role,active,created_at FROM users ORDER BY name")]})
                if p=="/api/factors": return self.respond(200,{"factors":[js(x) for x in c.execute("SELECT * FROM emission_factors ORDER BY fuel_type")]})
            self.respond(404,{"error":"Rota não encontrada."})
        except Exception as e: self.respond(400,{"error":str(e)})
    def do_POST(self): self.api_write("POST")
    def do_PUT(self): self.api_write("PUT")
    def do_DELETE(self): self.api_write("DELETE")
    def api_write(self,method):
        p=urlparse(self.path).path
        try: d=self.body() if method!="DELETE" else {}
        except Exception as e: return self.respond(400,{"error":str(e)})
        try:
            with connect() as c:
                if p=="/api/setup" and method=="POST":
                    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0]:return self.respond(409,{"error":"O administrador inicial já foi criado."})
                    
                    self.validate_user(d,True); c.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,'admin')",(d["name"].strip(),d["email"].strip().lower(),password_hash(d["password"])))
                    # O login abre outra conexão; confirmar o usuário antes de consultá-lo.
                    c.commit()
                    return self.login(d["email"],d["password"])
                if p=="/api/login" and method=="POST":
                    row=c.execute("SELECT * FROM users WHERE email=? COLLATE NOCASE AND active=1",(d.get("email",""),)).fetchone()
                    if not row or not verify_password(d.get("password",""),row["password_hash"]):return self.respond(401,{"error":"E-mail ou senha incorretos."})
                    return self.new_session(row["id"])
                if p=="/api/logout" and method=="POST":
                    raw=self.headers.get("Cookie",""); tok=next((x.strip()[8:] for x in raw.split(";") if x.strip().startswith("session=")),"")
                    if tok:c.execute("DELETE FROM sessions WHERE token_hash=?",(hashlib.sha256(tok.encode()).hexdigest(),))
                    return self.respond(200,{"ok":True}, {"Set-Cookie":"session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"})
                u=self.require(write=True)
                if not u:return
                if p=="/api/users" and method=="POST":
                    if u["role"]!="admin":return self.respond(403,{"error":"Apenas administrador."})
                    self.validate_user(d,False); c.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)",(d["name"].strip(),d["email"].strip().lower(),password_hash(d["password"]),d["role"]))
                    return self.respond(201,{"ok":True})
                if p=="/api/vehicles" and method=="POST":
                    if u["role"] not in ("admin","gestor"):return self.respond(403,{"error":"Sem permissão."})
                    if not d.get("model") or not d.get("plate") or d.get("fuel_type") not in ("gasolina","etanol"):return self.respond(400,{"error":"Informe modelo, placa e combustível válido."})
                    c.execute("INSERT INTO vehicles(model,plate,fuel_type) VALUES(?,?,?)",(d["model"].strip(),d["plate"].strip().upper(),d["fuel_type"]))
                    return self.respond(201,{"ok":True})
                if p=="/api/logs" and method=="POST":
                    if u["role"] not in ("admin","gestor","instrutor"):return self.respond(403,{"error":"Sem permissão."})
                    v=c.execute("SELECT * FROM vehicles WHERE id=? AND active=1",(d.get("vehicle_id"),)).fetchone()
                    if not v:return self.respond(400,{"error":"Selecione um veículo ativo."})
                    try: dist=float(d.get("distance_km",0)); liters=float(d.get("liters",0)); price=float(d.get("price_per_liter",0))
                    except Exception:return self.respond(400,{"error":"Distância, litros e preço devem ser números."})
                    if dist<=0 or liters<=0 or price<0 or dist>1e7 or liters>1e6:return self.respond(400,{"error":"Confira distância, litros e preço informados."})
                    factor=c.execute("SELECT kg_per_liter FROM emission_factors WHERE fuel_type=?",(v["fuel_type"],)).fetchone()[0]
                    c.execute("INSERT INTO fuel_logs(vehicle_id,user_id,log_date,distance_km,liters,price_per_liter,emission_factor,notes) VALUES(?,?,?,?,?,?,?,?)",(v["id"],u["id"],d.get("log_date"),dist,liters,price,factor,str(d.get("notes",""))[:500]))
                    return self.respond(201,{"ok":True})
                if p.startswith("/api/users/") and method=="PUT":
                    if u["role"]!="admin":return self.respond(403,{"error":"Apenas administrador."})
                    uid=int(p.rsplit("/",1)[1]); target=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
                    if not target:return self.respond(404,{"error":"Usuário não encontrado."})
                    if uid==u["id"] and (d.get("active")==False or d.get("role")!="admin"):return self.respond(400,{"error":"Não é possível remover sua própria permissão de administrador."})
                    role=d.get("role",target["role"]); active=1 if d.get("active",bool(target["active"])) else 0
                    if role not in ROLES:return self.respond(400,{"error":"Perfil inválido."})
                    if target["role"]=="admin" and (role!="admin" or not active) and c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]<=1:return self.respond(400,{"error":"Mantenha pelo menos um administrador ativo."})
                    c.execute("UPDATE users SET role=?,active=? WHERE id=?",(role,active,uid))
                    if not active:c.execute("DELETE FROM sessions WHERE user_id=?",(uid,))
                    return self.respond(200,{"ok":True})
                if p.startswith("/api/vehicles/") and method=="DELETE":
                    if u["role"] not in ("admin","gestor"):return self.respond(403,{"error":"Sem permissão."})
                    c.execute("UPDATE vehicles SET active=0 WHERE id=?",(int(p.rsplit("/",1)[1]),)); return self.respond(200,{"ok":True})
                if p.startswith("/api/factors/") and method=="PUT":
                    if u["role"]!="admin":return self.respond(403,{"error":"Apenas administrador."})
                    fuel=p.rsplit("/",1)[1]; value=float(d.get("kg_per_liter",0))
                    if fuel not in ("gasolina","etanol") or not 0<value<20:return self.respond(400,{"error":"Fator inválido."})
                    c.execute("UPDATE emission_factors SET kg_per_liter=?,updated_at=CURRENT_TIMESTAMP WHERE fuel_type=?",(value,fuel)); return self.respond(200,{"ok":True})
            self.respond(404,{"error":"Rota não encontrada."})
        except sqlite3.IntegrityError: self.respond(409,{"error":"Esse e-mail ou placa já está cadastrado."})
        except Exception as e: self.respond(400,{"error":str(e)})
    def validate_user(self,d,first):
        if len(str(d.get("name","" )).strip())<2 or "@" not in str(d.get("email","")):raise ValueError("Informe nome e e-mail válidos.")
        if len(str(d.get("password","")))<10:raise ValueError("A senha deve ter pelo menos 10 caracteres.")
        if not first and d.get("role") not in ("gestor","instrutor"):raise ValueError("Escolha o perfil Gestor ou Instrutor.")
    def login(self,email,password):
        with connect() as c: row=c.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE",(email.strip(),)).fetchone()
        return self.new_session(row["id"])
    def new_session(self,uid):
        tok=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(24); expiry=int(time.time())+SESSION_SECONDS
        with connect() as c: c.execute("INSERT INTO sessions VALUES(?,?,?,?)",(hashlib.sha256(tok.encode()).hexdigest(),uid,csrf,expiry))
        secure = "; Secure" if PRODUCTION else ""
        return self.respond(200,{"ok":True},{"Set-Cookie":f"session={tok}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_SECONDS}{secure}"})

if __name__=="__main__":
    init_db(); print(f"Sistema disponível em http://{HOST}:{PORT}"); ThreadingHTTPServer((HOST,PORT),API).serve_forever()
