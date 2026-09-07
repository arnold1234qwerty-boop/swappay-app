import os
import asyncio
import sqlite3
import hmac
import hashlib
import json
from urllib.parse import parse_qsl
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
import httpx

BOT_TOKEN = os.getenv("BOT_TOKEN", "8695905699:AAH2i5C825HkRrS3bkgAMp-UOE-PxV4tB04")
CRYPTOBOT_TOKEN = "631597:AAKH5PkslQyUSTvJPyZTmtEaC0bMyo117NB"
LOG_CHAT_ID = "-5401409248"
SUPER_ADMIN_ID = 7531770025
DB_PATH = "bot_database.db"

CRYPTO_RATE_MULTIPLIER = 1.4  # Комиссия 40%

# Хранилище счетов в памяти {invoice_id: {"user_id": int, "amount_rub": float}}
crypto_invoices = {}

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        role TEXT DEFAULT 'user',
        drop_role TEXT DEFAULT 'not',
        balance_rub REAL DEFAULT 0.0,
        bonus_balance REAL DEFAULT 0.0,
        referrer_id INTEGER DEFAULT NULL
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        amount_rub REAL,
        currency TEXT,
        status TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    # Назначение абсолютных прав администратору
    cursor.execute("""
    INSERT INTO users (user_id, role, drop_role, balance_rub, bonus_balance)
    VALUES (?, 'admin', 'all', 0.0, 0.0)
    ON CONFLICT(user_id) DO UPDATE SET role = 'admin', drop_role = 'all'
    """, (SUPER_ADMIN_ID,))
    conn.commit()
    conn.close()

# --- ЛОГИРОВАНИЕ В ТЕЛЕГРАМ-КОНФУ ---
async def send_log(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": LOG_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=payload)
    except Exception as e:
        print(f"[Log Error] {e}")

# --- ФОНОВЫЙ WORKER ДЛЯ КРИПТОБОТА ---
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

                                    # Начисляем баланс в SQLite
                                    conn = sqlite3.connect(DB_PATH)
                                    cur = conn.cursor()
                                    cur.execute("UPDATE users SET balance_rub = balance_rub + ? WHERE user_id = ?", (amt, uid))
                                    cur.execute("""
                                    INSERT INTO transactions (user_id, type, amount_rub, currency, status)
                                    VALUES (?, 'deposit', ?, 'CRYPTO', 'completed')
                                    """, (uid, amt))
                                    conn.commit()
                                    conn.close()

                                    # Уведомление юзера в ЛС
                                    notify_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                                    await client.post(notify_url, json={
                                        "chat_id": uid,
                                        "text": f"✅ <b>Баланс пополнен!</b>\nНачислено: <code>{amt:.2f} ₽</code> через CryptoBot."
                                    })

                                    # Лог в конфу
                                    await send_log(
                                        f"💎 <b>Успешное пополнение CryptoBot</b>\n"
                                        f"Пользователь: <code>{uid}</code>\n"
                                        f"Зачислено на баланс: <b>{amt:.2f} ₽</b>\n"
                                        f"ID инвойса: <code>{inv_id}</code>"
                                    )
        except Exception as err:
            print(f"[Crypto Worker Error] {err}")

        await asyncio.sleep(5)

# --- ЖИЗНЕННЫЙ ЦИКЛ FASTAPI ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    worker_task = asyncio.create_task(crypto_polling_worker())
    yield
    worker_task.cancel()

app = FastAPI(lifespan=lifespan)

# --- ВАЛИДАЦИЯ INITDATA ---
def validate_telegram_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(status_code=401, detail="Отсутствуют данные авторизации")
    
    vals = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = vals.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="Отсутствует цифровая подпись")

    check_str = "\n".join(f"{k}={v}" for k, v in sorted(vals.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, check_str.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        raise HTTPException(status_code=403, detail="Неверная цифровая подпись")

    return json.loads(vals.get("user", "{}"))

# --- РОУТЫ СТАТИКИ ---
@app.get("/")
def serve_html():
    return FileResponse("index.html")

@app.get("/app.js")
def serve_js():
    return FileResponse("app.js")

# --- API ---
@app.post("/api/auth")
async def auth_user(request: Request):
    body = await request.json()
    tg_user = validate_telegram_data(body.get("initData", ""))
    uid = tg_user.get("id")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id, role, drop_role, balance_rub, bonus_balance FROM users WHERE user_id = ?", (uid,))
    row = cur.fetchone()

    if not row:
        role = "admin" if uid == SUPER_ADMIN_ID else "user"
        drop_role = "all" if uid == SUPER_ADMIN_ID else "not"
        cur.execute("INSERT INTO users (user_id, role, drop_role) VALUES (?, ?, ?)", (uid, role, drop_role))
        conn.commit()
        user_info = {"user_id": uid, "role": role, "drop": drop_role, "balance_rub": 0.0, "bonus_balance": 0.0}
    else:
        user_info = {"user_id": row[0], "role": row[1], "drop": row[2], "balance_rub": row[3], "bonus_balance": row[4]}

    conn.close()
    return user_info

@app.post("/api/deposit/crypto")
async def create_crypto_invoice(request: Request):
    body = await request.json()
    tg_user = validate_telegram_data(body.get("initData", ""))
    uid = tg_user.get("id")
    
    amount_rub = float(body.get("amount_rub", 0))
    if amount_rub < 100:
        raise HTTPException(status_code=400, detail="Минимальная сумма пополнения — 100 ₽")

    total_crypto_rub = round(amount_rub * CRYPTO_RATE_MULTIPLIER, 2)

    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}
    payload = {
        "amount": str(total_crypto_rub),
        "currency_type": "fiat",
        "fiat": "RUB",
        "description": f"Пополнение SwapPay на {amount_rub} ₽ (+40% наценка)",
        "payload": str(uid)
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        res_data = resp.json()

    if not res_data.get("ok"):
        raise HTTPException(status_code=500, detail="Ошибка создания счета в CryptoBot")

    invoice = res_data["result"]
    inv_id = invoice["invoice_id"]
    pay_url = invoice["pay_url"]

    # Фиксируем инвойс для воркера
    crypto_invoices[inv_id] = {
        "user_id": uid,
        "amount_rub": amount_rub
    }

    # Логируем попытку создания инвойса в конфу
    await send_log(
        f"📝 <b>Создан счет CryptoBot</b>\n"
        f"Пользователь: <code>{uid}</code>\n"
        f"К зачислению: <b>{amount_rub:.2f} ₽</b>\n"
        f"К оплате юзером: <b>{total_crypto_rub:.2f} ₽</b>\n"
        f"Invoice ID: <code>{inv_id}</code>"
    )

    return {"pay_url": pay_url, "invoice_id": inv_id}
