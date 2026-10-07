from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from pathlib import Path
from datetime import datetime, timedelta
import hashlib, hmac, sqlite3, secrets, base64, json, os

APP = FastAPI(title="Emprego Real API", version="1.3-mobile")

APP.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB = os.getenv("DATABASE_URL", "sqlite:///./emprego_real.db")
SQLITE = "emprego_real.db"

def conn():
    c = sqlite3.connect(SQLITE)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        city TEXT DEFAULT '',
        min_salary REAL DEFAULT 0,
        experience TEXT DEFAULT 'sem_experiencia',
        schedule TEXT DEFAULT 'qualquer',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        source_id TEXT NOT NULL,
        title TEXT NOT NULL,
        company TEXT NOT NULL,
        location TEXT DEFAULT '',
        description TEXT DEFAULT '',
        url TEXT DEFAULT '',
        salary_min REAL DEFAULT 0,
        salary_max REAL DEFAULT 0,
        no_experience INTEGER DEFAULT 0,
        experience_required TEXT DEFAULT '',
        schedule TEXT DEFAULT '',
        active INTEGER DEFAULT 1,
        created_at TEXT NOT NULL,
        UNIQUE(source, source_id)
    );
    CREATE TABLE IF NOT EXISTS favorites (
        user_id INTEGER,
        job_id INTEGER,
        UNIQUE(user_id, job_id)
    );
    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        job_id INTEGER,
        status TEXT DEFAULT 'interesse',
        created_at TEXT NOT NULL,
        UNIQUE(user_id, job_id)
    );
    """)
    # Dados de demonstração para o primeiro teste
    count = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    if count == 0:
        demo = [
            ("demo","1","Auxiliar de Loja","Empresa Exemplo","São Paulo - SP",
             "Atendimento, organização e reposição. Não exige experiência.",
             "https://example.com",1800,2200,1,"sem_experiencia","5x2"),
            ("demo","2","Assistente Administrativo Júnior","Empresa Exemplo","São Paulo - SP",
             "Rotinas administrativas e apoio ao escritório. Treinamento oferecido.",
             "https://example.com",2200,2800,1,"sem_experiencia","5x2"),
            ("demo","3","Repositor de Mercadorias","Empresa Exemplo","São Paulo - SP",
             "Abastecimento e organização de loja.",
             "https://example.com",1900,2400,0,"6 meses","6x1"),
        ]
        c.executemany("""INSERT INTO jobs
        (source,source_id,title,company,location,description,url,salary_min,salary_max,
         no_experience,experience_required,schedule,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [x+(datetime.utcnow().isoformat(),) for x in demo])
    c.commit(); c.close()

init_db()

def pwd_hash(password):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120000)
    return base64.b64encode(salt+dk).decode()

def pwd_ok(password, encoded):
    try:
        raw = base64.b64decode(encoded)
        salt, expected = raw[:16], raw[16:]
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120000)
        return hmac.compare_digest(got, expected)
    except Exception:
        return False

TOKENS = {}

class Register(BaseModel):
    name: str
    email: EmailStr
    password: str
    city: str = ""
    min_salary: float = 0
    experience: str = "sem_experiencia"
    schedule: str = "qualquer"

class Login(BaseModel):
    email: EmailStr
    password: str

class Profile(BaseModel):
    name: str
    city: str = ""
    min_salary: float = 0
    experience: str = "sem_experiencia"
    schedule: str = "qualquer"

def user_from_token(token):
    uid = TOKENS.get(token)
    if not uid:
        raise HTTPException(401, "Sessão inválida")
    return uid

@APP.get("/health")
def health():
    return {"ok": True, "app": "Emprego Real", "version": "1.3-mobile"}

@APP.post("/auth/register")
def register(x: Register):
    c=conn()
    if c.execute("SELECT id FROM users WHERE email=?", (x.email,)).fetchone():
        c.close(); raise HTTPException(409,"E-mail já cadastrado")
    cur=c.execute("""INSERT INTO users(name,email,password_hash,city,min_salary,experience,schedule,created_at)
                     VALUES(?,?,?,?,?,?,?,?)""",
                  (x.name,x.email,pwd_hash(x.password),x.city,x.min_salary,x.experience,x.schedule,datetime.utcnow().isoformat()))
    c.commit(); uid=cur.lastrowid; c.close()
    token=secrets.token_urlsafe(32); TOKENS[token]=uid
    return {"token":token,"user_id":uid}

@APP.post("/auth/login")
def login(x: Login):
    c=conn(); u=c.execute("SELECT * FROM users WHERE email=?", (x.email,)).fetchone(); c.close()
    if not u or not pwd_ok(x.password,u["password_hash"]):
        raise HTTPException(401,"E-mail ou senha inválidos")
    token=secrets.token_urlsafe(32); TOKENS[token]=u["id"]
    return {"token":token,"user_id":u["id"]}

@APP.get("/me")
def me(token: str):
    uid=user_from_token(token); c=conn()
    u=c.execute("SELECT id,name,email,city,min_salary,experience,schedule FROM users WHERE id=?",(uid,)).fetchone()
    c.close()
    return dict(u)

@APP.put("/me")
def update_me(x: Profile, token: str):
    uid=user_from_token(token); c=conn()
    c.execute("""UPDATE users SET name=?,city=?,min_salary=?,experience=?,schedule=? WHERE id=?""",
              (x.name,x.city,x.min_salary,x.experience,x.schedule,uid))
    c.commit(); c.close(); return {"ok":True}

def compatibility(job, user):
    score=100; reasons=[]
    city=(user["city"] or "").lower().strip()
    loc=(job["location"] or "").lower()
    if city and city not in loc:
        score-=25; reasons.append("A localização pode exigir deslocamento.")
    if user["min_salary"] and job["salary_max"] and job["salary_max"] < user["min_salary"]:
        score-=30; reasons.append("A faixa salarial pode ficar abaixo do seu mínimo.")
    exp=user["experience"]
    if exp=="sem_experiencia" and not job["no_experience"]:
        score-=25; reasons.append("A vaga indica alguma experiência.")
    if job["no_experience"]:
        reasons.append("A vaga aceita candidatos sem experiência.")
    if user["schedule"]!="qualquer" and job["schedule"] and user["schedule"] not in job["schedule"]:
        score-=15; reasons.append("O horário pode não coincidir com sua preferência.")
    if score>=75: label="🟢 Você pode se candidatar"
    elif score>=50: label="🟡 Vale tentar"
    else: label="🔴 Fora do perfil"
    return score,label,reasons

@APP.get("/jobs")
def jobs(q: str="", city: str="", no_experience: bool=False, min_salary: float=0, token: str|None=None):
    c=conn()
    rows=c.execute("""SELECT * FROM jobs WHERE active=1
                     AND (?='' OR title LIKE ? OR company LIKE ?)
                     AND (?='' OR location LIKE ?)
                     AND (?=0 OR no_experience=1)
                     AND (?=0 OR salary_max>=?)
                     ORDER BY id DESC""",
                   (q,f"%{q}%",f"%{q}%",city,f"%{city}%",int(no_experience),min_salary,min_salary)).fetchall()
    user=None
    if token:
        try:
            uid=user_from_token(token)
            user=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
        except: pass
    out=[]
    for r in rows:
        d=dict(r)
        if user:
            s,l,rs=compatibility(r,user); d.update({"compatibility_score":s,"compatibility":l,"reasons":rs})
        else:
            d.update({"compatibility_score":None,"compatibility":"Faça login para analisar","reasons":[]})
        out.append(d)
    c.close(); return out

@APP.post("/favorites/{job_id}")
def favorite(job_id:int, token:str):
    uid=user_from_token(token); c=conn()
    c.execute("INSERT OR IGNORE INTO favorites(user_id,job_id) VALUES(?,?)",(uid,job_id))
    c.commit(); c.close(); return {"ok":True}

@APP.delete("/favorites/{job_id}")
def unfavorite(job_id:int, token:str):
    uid=user_from_token(token); c=conn()
    c.execute("DELETE FROM favorites WHERE user_id=? AND job_id=?",(uid,job_id))
    c.commit(); c.close(); return {"ok":True}

@APP.get("/favorites")
def favorites(token:str):
    uid=user_from_token(token); c=conn()
    rows=c.execute("""SELECT j.* FROM jobs j JOIN favorites f ON f.job_id=j.id WHERE f.user_id=?""",(uid,)).fetchall()
    c.close(); return [dict(x) for x in rows]

@APP.post("/applications/{job_id}")
def apply(job_id:int, token:str):
    uid=user_from_token(token); c=conn()
    c.execute("""INSERT OR IGNORE INTO applications(user_id,job_id,status,created_at)
                 VALUES(?,?,?,?)""",(uid,job_id,"interesse",datetime.utcnow().isoformat()))
    c.commit(); c.close(); return {"ok":True}

@APP.get("/applications")
def applications(token:str):
    uid=user_from_token(token); c=conn()
    rows=c.execute("""SELECT a.id,a.status,a.created_at,j.title,j.company,j.location,j.url
                      FROM applications a JOIN jobs j ON j.id=a.job_id
                      WHERE a.user_id=? ORDER BY a.id DESC""",(uid,)).fetchall()
    c.close(); return [dict(x) for x in rows]

@APP.get("/admin/stats")
def stats():
    c=conn()
    result={
        "users":c.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "jobs":c.execute("SELECT COUNT(*) FROM jobs WHERE active=1").fetchone()[0],
        "favorites":c.execute("SELECT COUNT(*) FROM favorites").fetchone()[0],
        "applications":c.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    }
    c.close(); return result
