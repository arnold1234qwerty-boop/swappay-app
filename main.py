import os
import asyncio
import sqlite3
import hmac
import hashlib
import json
from urllib.parse import parse_qsl
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
import httpx

BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN")
LOG_CHAT_ID = os.getenv("LOG_CHAT_ID", "-5401409248")
SUPER_ADMIN_ID = 7531770025
DB_PATH = "bot_database.db"

CRYPTO_RATE_MULTIPLIER = 1.4
MIN_DEPOSIT = 100.0

crypto_invoices = {}

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT DEFAULT '',
        first_name TEXT DEFAULT '',
        role TEXT DEFAULT 'user',
        drop_role TEXT DEFAULT 'not',
        balance_rub REAL DEFAULT 0.0,
        bonus_balance REAL DEFAULT 0.0,
        referrer_id INTEGER DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        amount_rub REAL,
        currency TEXT,
        status TEXT,
        receipt_filename TEXT DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS promocodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        amount REAL,
        max_uses INTEGER,
        current_uses INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS used_promocodes (
        user_id INTEGER,
        promocode_id INTEGER,
        PRIMARY KEY(user_id, promocode_id)
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS support_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        sender TEXT,
        text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("""
    INSERT INTO users (user_id, role, drop_role, balance_rub, bonus_balance)
    VALUES (?, 'admin', 'all', 0.0, 0.0)
    ON CONFLICT(user_id) DO UPDATE SET role = 'admin', drop_role = 'all'
    """, (SUPER_ADMIN_ID,))
    conn.commit()
    conn.close()

async def send_tg_message(chat_id, text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    except Exception as e:
        pass

async def send_tg_document(chat_id, filename: str, file_bytes: bytes, caption: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    try:
        files = {"document": (filename, file_bytes, "application/pdf")}
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        async with httpx.AsyncClient(timeout=20.0) as client:
            await client.post(url, data=data, files=files)
    except Exception:
        pass

async def send_tg_photo(chat_id, filename: str, file_bytes: bytes, caption: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    try:
        files = {"photo": (filename, file_bytes, "image/jpeg")}
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        async with httpx.AsyncClient(timeout=20.0) as client:
            await client.post(url, data=data, files=files)
    except Exception:
        pass

async def send_log(text: str):
    await send_tg_message(LOG_CHAT_ID, text)

async def crypto_polling_worker():
    while True:
        try:
            if crypto_invoices:
                invoice_ids = list(crypto_invoices.keys())
                ids_param = ",".join(map(str, invoice_ids))
                url = f"https://pay.crypt.bot/api/getInvoices?invoice_ids={ids_param}"
                headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}

                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("ok"):
                            for item in data.get("result", {}).get("items", []):
                                inv_id = item["invoice_id"]
                                if item["status"] == "paid" and inv_id in crypto_invoices:
                                    inv_data = crypto_invoices.pop(inv_id)
                                    uid = inv_data["user_id"]
                                    amt = inv_data["amount_rub"]

                                    conn = get_db()
                                    cur = conn.cursor()
                                    cur.execute("UPDATE users SET balance_rub = balance_rub + ? WHERE user_id = ?", (amt, uid))
                                    cur.execute("INSERT INTO transactions (user_id, type, amount_rub, currency, status) VALUES (?, 'deposit', ?, 'CRYPTO', 'completed')", (uid, amt))
                                    conn.commit()
                                    conn.close()

                                    await send_tg_message(uid, f"✅ <b>Баланс пополнен!</b>\nНачислено: <code>{amt:.2f} ₽</code> через CryptoBot.")
                                    await send_log(f"💎 <b>CryptoBot Пополнение</b>\nЮзер: <code>{uid}</code>\nСумма: <b>{amt:.2f} ₽</b>")
        except Exception:
            pass
        await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    worker = asyncio.create_task(crypto_polling_worker())
    yield
    worker.cancel()

app = FastAPI(lifespan=lifespan)

def validate_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(status_code=401, detail="Нет данных")
    vals = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = vals.pop("hash", None)
    check_str = "\n".join(f"{k}={v}" for k, v in sorted(vals.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, check_str.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise HTTPException(status_code=403, detail="Ошибка подписи")
    return json.loads(vals.get("user", "{}"))

@app.get("/")
def serve_root(): return FileResponse("index.html")
@app.get("/app.js")
def serve_app_js(): return FileResponse("app.js")

@app.post("/api/auth")
async def api_auth(request: Request):
    body = await request.json()
    user_info = validate_init_data(body.get("initData", ""))
    uid = user_info.get("id")
    uname = user_info.get("username", "")
    fname = user_info.get("first_name", "")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
    row = cur.fetchone()

    if not row:
        role = "admin" if uid == SUPER_ADMIN_ID else "user"
        drop_role = "all" if uid == SUPER_ADMIN_ID else "not"
        cur.execute("INSERT INTO users (user_id, username, first_name, role, drop_role) VALUES (?, ?, ?, ?, ?)", (uid, uname, fname, role, drop_role))
        conn.commit()
        data = {"user_id": uid, "username": uname, "first_name": fname, "role": role, "drop": drop_role, "balance_rub": 0.0, "bonus_balance": 0.0}
    else:
        cur.execute("UPDATE users SET username = ?, first_name = ? WHERE user_id = ?", (uname, fname, uid))
        conn.commit()
        data = {"user_id": uid, "username": uname, "first_name": fname, "role": row["role"], "drop": row["drop_role"], "balance_rub": row["balance_rub"], "bonus_balance": row["bonus_balance"]}
    conn.close()
    return data

@app.post("/api/deposit/crypto")
async def create_crypto(request: Request):
    body = await request.json()
    uid = validate_init_data(body.get("initData", "")).get("id")
    amount = float(body.get("amount_rub", 0))

    if amount < MIN_DEPOSIT:
        raise HTTPException(status_code=400, detail=f"Мин. сумма {MIN_DEPOSIT} ₽")

    total_with_fee = round(amount * CRYPTO_RATE_MULTIPLIER, 2)
    payload = {"amount": str(total_with_fee), "currency_type": "fiat", "fiat": "RUB", "description": f"SwapPay: {amount} ₽", "payload": str(uid)}
    
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://pay.crypt.bot/api/createInvoice", json=payload, headers={"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN})
        res_data = resp.json()

    if not res_data.get("ok"): raise HTTPException(status_code=500, detail="Ошибка CryptoBot")
    inv = res_data["result"]
    crypto_invoices[inv["invoice_id"]] = {"user_id": uid, "amount_rub": amount}
    return {"pay_url": inv["pay_url"]}

@app.post("/api/deposit/pdf-receipt")
async def upload_receipt(initData: str = Form(...), amount_rub: float = Form(...), currency: str = Form(...), receipt: UploadFile = File(...)):
    uid = validate_init_data(initData).get("id")
    if not receipt.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Только PDF!")

    file_bytes = await receipt.read()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO transactions (user_id, type, amount_rub, currency, status, receipt_filename) VALUES (?, 'deposit', ?, ?, 'pending', ?)", (uid, amount_rub, currency.upper(), receipt.filename))
    tx_id = cur.lastrowid
    cur.execute("SELECT user_id FROM users WHERE drop_role = 'all' OR drop_role = ?", (currency.lower(),))
    drops = cur.fetchall()
    conn.commit()
    conn.close()

    caption = f"📥 <b>Чек #{tx_id}</b>\nЮзер: <code>{uid}</code>\nСумма: <b>{amount_rub:.2f} ₽</b> ({currency.upper()})"
    for d in drops:
        await send_tg_document(d["user_id"], receipt.filename, file_bytes, caption)
    await send_log(f"📄 <b>Чек #{tx_id}</b> загружен от <code>{uid}</code>")
    return {"status": "ok"}

@app.post("/api/purchase")
async def purchase_item(initData: str = Form(...), amount: float = Form(...), details: str = Form(...), photo: Optional[UploadFile] = File(None)):
    uid = validate_init_data(initData).get("id")
    if amount < 25: raise HTTPException(status_code=400, detail="Минимум 25 ₽")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT balance_rub FROM users WHERE user_id = ?", (uid,))
    bal = cur.fetchone()["balance_rub"]
    if bal < amount:
        conn.close()
        raise HTTPException(status_code=400, detail="Недостаточно средств")

    cur.execute("UPDATE users SET balance_rub = balance_rub - ? WHERE user_id = ?", (amount, uid))
    cur.execute("INSERT INTO transactions (user_id, type, amount_rub, status) VALUES (?, 'purchase', ?, 'pending')", (uid, amount))
    tx_id = cur.lastrowid
    conn.commit()
    conn.close()

    cap = f"🛍 <b>Новая заявка на оплату #{tx_id}</b>\nОт: <code>{uid}</code>\nСумма списания: <b>{amount} ₽</b>\nДетали: {details}"
    if photo:
        p_bytes = await photo.read()
        await send_tg_photo(LOG_CHAT_ID, photo.filename, p_bytes, cap)
    else:
        await send_log(cap)
    return {"status": "ok"}

@app.post("/api/promo/activate")
async def activate_promo(request: Request):
    body = await request.json()
    uid = validate_init_data(body.get("initData", "")).get("id")
    code = body.get("code", "").upper().strip()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM promocodes WHERE code = ? AND is_active = 1", (code,))
    promo = cur.fetchone()
    if not promo:
        conn.close()
        raise HTTPException(status_code=400, detail="Промокод не найден или неактивен")

    if promo["current_uses"] >= promo["max_uses"]:
        conn.close()
        raise HTTPException(status_code=400, detail="Лимит активаций исчерпан")

    cur.execute("SELECT 1 FROM used_promocodes WHERE user_id = ? AND promocode_id = ?", (uid, promo["id"]))
    if cur.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Вы уже использовали этот промокод")

    cur.execute("INSERT INTO used_promocodes (user_id, promocode_id) VALUES (?, ?)", (uid, promo["id"]))
    cur.execute("UPDATE promocodes SET current_uses = current_uses + 1 WHERE id = ?", (promo["id"],))
    cur.execute("UPDATE users SET bonus_balance = bonus_balance + ? WHERE user_id = ?", (promo["amount"], uid))
    conn.commit()
    conn.close()
    return {"status": "ok", "amount": promo["amount"]}

@app.get("/api/referral/stats")
async def ref_stats(initData: str):
    uid = validate_init_data(initData).get("id")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM users WHERE referrer_id = ?", (uid,))
    refs = cur.fetchone()["cnt"]
    conn.close()
    return {"referrals": refs, "link": f"https://t.me/ТВОЙ_БОТ?start=ref_{uid}"}

@app.get("/api/support/chats")
async def get_support_chats(initData: str):
    uid = validate_init_data(initData).get("id")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT role FROM users WHERE user_id = ?", (uid,))
    if cur.fetchone()["role"] != "admin": raise HTTPException(status_code=403)
    
    cur.execute("""
    SELECT DISTINCT sm.user_id, u.first_name, u.username 
    FROM support_messages sm 
    JOIN users u ON sm.user_id = u.user_id
    """)
    chats = [dict(r) for r in cur.fetchall()]
    conn.close()
    return chats

@app.get("/api/support/messages")
async def get_messages(initData: str, target_uid: Optional[int] = None):
    uid = validate_init_data(initData).get("id")
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT role FROM users WHERE user_id = ?", (uid,))
    is_admin = cur.fetchone()["role"] == "admin"
    chat_uid = target_uid if (is_admin and target_uid) else uid

    cur.execute("""
    SELECT sm.sender, sm.text, sm.created_at, u.first_name 
    FROM support_messages sm 
    JOIN users u ON sm.user_id = u.user_id 
    WHERE sm.user_id = ? ORDER BY sm.id ASC
    """, (chat_uid,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

@app.post("/api/support/send")
async def send_support(request: Request):
    body = await request.json()
    uid = validate_init_data(body.get("initData", "")).get("id")
    text = body.get("text", "").strip()
    target_uid = body.get("target_uid")

    if not text: raise HTTPException(status_code=400)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT role FROM users WHERE user_id = ?", (uid,))
    is_admin = cur.fetchone()["role"] == "admin"

    if is_admin and target_uid:
        cur.execute("INSERT INTO support_messages (user_id, sender, text) VALUES (?, 'admin', ?)", (target_uid, text))
        await send_tg_message(target_uid, f"👨‍💻 <b>Ответ поддержки:</b>\n\n{text}")
    else:
        cur.execute("INSERT INTO support_messages (user_id, sender, text) VALUES (?, 'user', ?)", (uid, text))
        await send_log(f"🆘 <b>Саппорт:</b> {uid}\n«{text}»")
    
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.get("/api/admin/stats")
async def admin_stats(initData: str):
    uid = validate_init_data(initData).get("id")
    conn = get_db()
    cur = conn.cursor()
    if cur.execute("SELECT role FROM users WHERE user_id = ?", (uid,)).fetchone()["role"] != "admin": raise HTTPException(status_code=403)
    
    cur.execute("SELECT COUNT(*) as c FROM users")
    users = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM transactions")
    txs = cur.fetchone()["c"]
    cur.execute("SELECT COALESCE(SUM(amount_rub), 0) as t FROM transactions WHERE status = 'completed' AND type = 'deposit'")
    trn = cur.fetchone()["t"]
    conn.close()
    return {"total_users": users, "total_tx": txs, "turnover": trn}
