from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
import psycopg2.extras
import os
import random

app = FastAPI(title="Gibberlink Dictionary API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── GL-Wort-Erzeugung ─────────────────────────────────────────────────────────
VOWELS     = ['a', 'e', 'i', 'o', 'u']
CONSONANTS = ['b', 'd', 'f', 'g', 'k', 'l', 'm', 'n', 'p', 'r', 's', 't', 'v', 'z']

def generate_gl_word(original: str, attempt: int = 0) -> str:
    seed = sum(ord(c) for c in original.lower()) + attempt * 997
    r = random.Random(seed)
    n_syl = r.randint(1, 3)
    word = ''
    for _ in range(n_syl):
        word += r.choice(CONSONANTS) + r.choice(VOWELS)
        if r.random() < 0.35:
            word += r.choice(CONSONANTS)
    return word

# ── Datenbank ─────────────────────────────────────────────────────────────────
def get_db():
    return psycopg2.connect(os.environ["DATABASE_URL"])

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS words (
            id         SERIAL PRIMARY KEY,
            original   TEXT NOT NULL,
            lang       TEXT NOT NULL DEFAULT 'en',
            gl_word    TEXT NOT NULL,
            orig_lower TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE (orig_lower, lang),
            UNIQUE (gl_word)
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

@app.on_event("startup")
async def startup():
    init_db()

# ── Endpunkte ─────────────────────────────────────────────────────────────────
@app.get("/dict")
def get_dict():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT original, lang, gl_word AS gl FROM words ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return list(rows)

class AddRequest(BaseModel):
    original: str
    lang: str = "en"

@app.post("/add")
def add_word(req: AddRequest):
    orig = req.original.strip()
    lower = orig.lower()
    if not lower:
        raise HTTPException(400, "empty word")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT gl_word FROM words WHERE orig_lower=%s AND lang=%s", (lower, req.lang))
    row = cur.fetchone()
    if row:
        cur.close(); conn.close()
        return {"gl": row[0], "original": orig, "new": False}

    # GL-Wort erzeugen, Kollisionen auflösen
    attempt = 0
    while True:
        gl = generate_gl_word(lower, attempt)
        cur.execute("SELECT 1 FROM words WHERE gl_word=%s", (gl,))
        if not cur.fetchone():
            break
        attempt += 1

    cur.execute(
        "INSERT INTO words (original, lang, gl_word, orig_lower) VALUES (%s,%s,%s,%s)",
        (orig, req.lang, gl, lower)
    )
    conn.commit()
    cur.close(); conn.close()
    return {"gl": gl, "original": orig, "new": True}

@app.get("/reverse")
def reverse_lookup(gl: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT original, lang FROM words WHERE gl_word=%s", (gl.lower().strip(),))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        raise HTTPException(404, "not found")
    return {"original": row[0], "lang": row[1], "gl": gl}

@app.get("/health")
def health():
    return {"ok": True}
