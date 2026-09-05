from flask import Flask, jsonify, request
from flask_cors import CORS
import pg8000.dbapi
import urllib.parse
import os
import random

app = Flask(__name__)
CORS(app)

# ── Datenbankverbindung ───────────────────────────────────────────────────────
def get_db():
    url = urllib.parse.urlparse(os.environ["DATABASE_URL"])
    return pg8000.dbapi.connect(
        host=url.hostname,
        port=url.port or 5432,
        database=url.path.lstrip("/"),
        user=url.username,
        password=url.password,
        ssl_context=True,
    )

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

with app.app_context():
    init_db()

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

# ── Endpunkte ─────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.get("/dict")
def get_dict():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT original, lang, gl_word FROM words ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{"original": r[0], "lang": r[1], "gl": r[2]} for r in rows])

@app.post("/add")
def add_word():
    data = request.get_json(force=True)
    orig = (data.get("original") or "").strip()
    lang = (data.get("lang") or "en").strip()
    lower = orig.lower()
    if not lower:
        return jsonify({"error": "empty word"}), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT gl_word FROM words WHERE orig_lower=%s AND lang=%s", (lower, lang))
    row = cur.fetchone()
    if row:
        cur.close(); conn.close()
        return jsonify({"gl": row[0], "original": orig, "new": False})

    attempt = 0
    while True:
        gl = generate_gl_word(lower, attempt)
        cur.execute("SELECT 1 FROM words WHERE gl_word=%s", (gl,))
        if not cur.fetchone():
            break
        attempt += 1

    cur.execute(
        "INSERT INTO words (original, lang, gl_word, orig_lower) VALUES (%s,%s,%s,%s)",
        (orig, lang, gl, lower)
    )
    conn.commit()
    cur.close(); conn.close()
    return jsonify({"gl": gl, "original": orig, "new": True})

@app.get("/reverse")
def reverse_lookup():
    gl = (request.args.get("gl") or "").lower().strip()
    if not gl:
        return jsonify({"error": "missing gl"}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT original, lang FROM words WHERE gl_word=%s", (gl,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify({"original": row[0], "lang": row[1], "gl": gl})
