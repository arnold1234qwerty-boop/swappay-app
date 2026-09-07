import os
import asyncio
import sqlite3
import hmac
import hashlib
import json
from urllib.parse import parse_qsl
from contextlib import asynccontextmanager
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
import httpx

# --- НАСТРОЙКИ И ОКРУЖЕНИЕ ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "8695905699:AAE6kSsZ2qZYiaXNm5UnewmIb5LOCaXIRXY")
CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN", "631597:AAPLkExOrHaBuMUBEZsNlhJY5k5y4KYbtqp")
LOG_CHAT_ID = os.getenv("LOG_CHAT_ID", "-5401409248")
SUPER_ADMIN_ID = 7531770025
DB_PATH = "bot_database.db"

CRYPTO_RATE_MULTIPLIER = 1.4  # Комиссия 40%
RATES = {"KZT": 8.0, "UAH": 0.8}
MIN_DEPOSIT = 100.0

crypto_invoices = {}

# --- БАЗА ДАННЫХ ---
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
        require_balance INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1
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
    # Абсолютные права администратора
    cur.execute("""
    INSERT INTO users (user_id, role, drop_role, balance_rub, bonus_balance)
    VALUES (?, 'admin', 'all', 0.0, 0.0)
    ON CONFLICT(user_id) DO UPDATE SET role = 'admin', drop_role = 'all'
    """, (SUPER_ADMIN_ID,))
    conn.commit()
    conn.close()

# --- ТЕЛЕГРАМ ЛОГИ И УВЕДОМЛЕНИЯ ---
async def send_tg_message(chat_id, text: str, parse_mode: str = "HTML"):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode})
    except Exception as e:
        print(f"[TG Error] {e}")

async def send_tg_document(chat_id, filename: str, file_bytes: bytes, caption: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    try:
        files = {"document": (filename, file_bytes, "application/pdf")}
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        async with httpx.AsyncClient(timeout=20.0) as client:
            await client.post(url, data=data, files=files)
    except Exception as e:
        print(f"[TG Doc Error] {e}")

async def send_log(text: str):
    await send_tg_message(LOG_CHAT_ID, text)

# --- ФОНОВЫЙ WORKER CRYPTOBOT ---
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
                                    cur.execute("""
                                    INSERT INTO transactions (user_id, type, amount_rub, currency, status)
                                    VALUES (?, 'deposit', ?, 'CRYPTO', 'completed')
                                    """, (uid, amt))
                                    conn.commit()
                                    conn.close()

                                    await send_tg_message(
                                        uid,
                                        f"✅ <b>Баланс пополнен!</b>\nНачислено: <code>{amt:.2f} ₽</code> через CryptoBot."
                                    )
                                    await send_log(
                                        f"💎 <b>Успешное пополнение CryptoBot</b>\n"
                                        f"Пользователь: <code>{uid}</code>\n"
                                        f"Зачислено: <b>{amt:.2f} ₽</b>\n"
                                        f"Инвойс: <code>{inv_id}</code>"
                                    )
        except Exception as err:
            print(f"[Crypto Worker Error] {err}")
        await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    worker = asyncio.create_task(crypto_polling_worker())
    yield
    worker.cancel()

app = FastAPI(lifespan=lifespan)

# --- АВТОРИЗАЦИЯ И ВАЛИДАЦИЯ ---
def validate_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(status_code=401, detail="Нет данных авторизации")
    vals = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = vals.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="Отсутствует подпись")

    check_str = "\n".join(f"{k}={v}" for k, v in sorted(vals.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, check_str.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        raise HTTPException(status_code=403, detail="Неверная цифровая подпись")
    return json.loads(vals.get("user", "{}"))

# --- СТАТИКА ---
@app.get("/")
def serve_root():
    return FileResponse("index.html")

@app.get("/app.js")
def serve_app_js():
    return FileResponse("app.js")

# --- ПОЛЬЗОВАТЕЛЬСКИЙ API ---
@app.post("/api/auth")
async def api_auth(request: Request):
    body = await request.json()
    user_info = validate_init_data(body.get("initData", ""))
    uid = user_info.get("id")
    uname = user_info.get("username", "")
    fname = user_info.get("first_name", "")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id, role, drop_role, balance_rub, bonus_balance FROM users WHERE user_id = ?", (uid,))
    row = cur.fetchone()

    if not row:
        role = "admin" if uid == SUPER_ADMIN_ID else "user"
        drop_role = "all" if uid == SUPER_ADMIN_ID else "not"
        cur.execute("""
        INSERT INTO users (user_id, username, first_name, role, drop_role)
        VALUES (?, ?, ?, ?, ?)
        """, (uid, uname, fname, role, drop_role))
        conn.commit()
        data = {"user_id": uid, "role": role, "drop": drop_role, "balance_rub": 0.0, "bonus_balance": 0.0}
    else:
        # Обновляем имя
        cur.execute("UPDATE users SET username = ?, first_name = ? WHERE user_id = ?", (uname, fname, uid))
        conn.commit()
        data = {"user_id": row["user_id"], "role": row["role"], "drop": row["drop_role"], "balance_rub": row["balance_rub"], "bonus_balance": row["bonus_balance"]}

    conn.close()
    return data

@app.post("/api/deposit/crypto")
async def create_crypto(request: Request):
    body = await request.json()
    user = validate_init_data(body.get("initData", ""))
    uid = user.get("id")
    amount = float(body.get("amount_rub", 0))

    if amount < MIN_DEPOSIT:
        raise HTTPException(status_code=400, detail=f"Минимальная сумма — {MIN_DEPOSIT} ₽")

    total_with_fee = round(amount * CRYPTO_RATE_MULTIPLIER, 2)
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}
    payload = {
        "amount": str(total_with_fee),
        "currency_type": "fiat",
        "fiat": "RUB",
        "description": f"SwapPay: пополнение на {amount} ₽",
        "payload": str(uid)
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post("https://pay.crypt.bot/api/createInvoice", json=payload, headers=headers)
        res_data = resp.json()

    if not res_data.get("ok"):
        raise HTTPException(status_code=500, detail="Ошибка сервиса CryptoBot")

    inv = res_data["result"]
    inv_id = inv["invoice_id"]
    crypto_invoices[inv_id] = {"user_id": uid, "amount_rub": amount}

    await send_log(
        f"💳 <b>Запрос CryptoBot</b>\n"
        f"Юзер: <code>{uid}</code>\n"
        f"Сумма: <b>{amount:.2f} ₽</b> (К оплате: {total_with_fee:.2f} ₽)\n"
        f"Инвойс: <code>{inv_id}</code>"
    )
    return {"pay_url": inv["pay_url"], "invoice_id": inv_id}

@app.post("/api/deposit/pdf-receipt")
async def upload_receipt(
    initData: str = Form(...),
    amount_rub: float = Form(...),
    currency: str = Form(...),
    receipt: UploadFile = File(...)
):
    user = validate_init_data(initData)
    uid = user.get("id")

    if not receipt.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Разрешены только чеки в формате PDF!")

    file_bytes = await receipt.read()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO transactions (user_id, type, amount_rub, currency, status, receipt_filename)
    VALUES (?, 'deposit', ?, ?, 'pending', ?)
    """, (uid, amount_rub, currency.upper(), receipt.filename))
    tx_id = cur.lastrowid

    # Поиск подходящих дропов
    cur.execute("SELECT user_id FROM users WHERE drop_role = 'all' OR drop_role = ?", (currency.lower(),))
    drops = cur.fetchall()
    conn.commit()
    conn.close()

    caption = (
        f"📥 <b>Новый чек на пополнение #{tx_id}</b>\n"
        f"Пользователь: <code>{uid}</code>\n"
        f"Сумма: <b>{amount_rub:.2f} ₽</b> ({currency.upper()})\n"
        f"Статус: Ожидает подтверждения"
    )

    # Рассылка дропам
    for d in drops:
        await send_tg_document(d["user_id"], receipt.filename, file_bytes, caption)

    # Лог в общую конфy
    await send_log(f"📄 <b>Загружен чек #{tx_id}</b> от <code>{uid}</code> на {amount_rub:.2f} ₽ ({currency.upper()})")

    return {"status": "ok", "tx_id": tx_id}

# --- ПОДДЕРЖКА (ЧАТ) ---
@app.get("/api/support/messages")
async def get_messages(initData: str):
    user = validate_init_data(initData)
    uid = user.get("id")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT sender, text, created_at FROM support_messages WHERE user_id = ? ORDER BY id ASC", (uid,))
    rows = cur.fetchall()
    conn.close()
    return [{"sender": r["sender"], "text": r["text"], "time": r["created_at"]} for r in rows]

@app.post("/api/support/send")
async def send_support(request: Request):
    body = await request.json()
    user = validate_init_data(body.get("initData", ""))
    uid = user.get("id")
    text = body.get("text", "").strip()

    if not text:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO support_messages (user_id, sender, text) VALUES (?, 'user', ?)", (uid, text))
    conn.commit()
    conn.close()

    await send_log(f"🆘 <b>Обращение в поддержку</b> от <code>{uid}</code>:\n«{text}»")
    return {"status": "ok"}

# --- АДМИН ПАНЕЛЬ ---
def check_admin(init_data: str):
    user = validate_init_data(init_data)
    uid = user.get("id")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT role FROM users WHERE user_id = ?", (uid,))
    row = cur.fetchone()
    conn.close()
    if not row or row["role"] != "admin":
        raise HTTPException(status_code=403, detail="Доступ запрещен")
    return uid

@app.get("/api/admin/stats")
async def admin_stats(initData: str):
    check_admin(initData)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM users")
    total_users = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) as cnt FROM transactions")
    total_tx = cur.fetchone()["cnt"]

    cur.execute("SELECT COALESCE(SUM(amount_rub), 0) as total FROM transactions WHERE status = 'completed' AND type = 'deposit'")
    turnover = cur.fetchone()["total"]

    cur.execute("SELECT * FROM transactions ORDER BY id DESC LIMIT 50")
    txs = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT 50")
    users = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM promocodes ORDER BY id DESC")
    promos = [dict(r) for r in cur.fetchall()]
    conn.close()

    return {
        "total_users": total_users,
        "total_tx": total_tx,
        "turnover": turnover,
        "transactions": txs,
        "users": users,
        "promocodes": promos
    }

@app.post("/api/admin/promocode/create")
async def create_promo(request: Request):
    body = await request.json()
    check_admin(body.get("initData", ""))
    code = body.get("code", "").strip().upper()
    amount = float(body.get("amount", 0))
    max_uses = int(body.get("max_uses", 1))

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO promocodes (code, amount, max_uses) VALUES (?, ?, ?)", (code, amount, max_uses))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Такой промокод уже существует")
    conn.close()
    return {"status": "ok"}

@app.post("/api/admin/sql")
async def run_sql(request: Request):
    body = await request.json()
    check_admin(body.get("initData", ""))
    query = body.get("query", "").strip()

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(query)
        if query.lower().startswith("select"):
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return {"type": "select", "result": rows}
        else:
            conn.commit()
            conn.close()
            return {"type": "execute", "result": "Успешно выполнено"}
    except Exception as err:
        conn.close()
        raise HTTPException(status_code=400, detail=str(err))
