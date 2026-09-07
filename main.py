import os
import asyncio
import sqlite3
import hmac
import hashlib
import json
import re
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
USDT_RATE = 95.0

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
        support_status TEXT DEFAULT 'closed',
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

async def send_tg_message(chat_id, text: str, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload)
    except Exception:
        pass

async def send_tg_document(chat_id, filename: str, file_bytes: bytes, caption: str, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    try:
        files = {"document": (filename, file_bytes, "application/pdf")}
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        async with httpx.AsyncClient(timeout=20.0) as client:
            await client.post(url, data=data, files=files)
    except Exception:
        pass

async def send_log(text: str):
    await send_tg_message(LOG_CHAT_ID, text)

async def answer_callback_query(callback_query_id: str, text: str, show_alert: bool = False):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json={"callback_query_id": callback_query_id, "text": text, "show_alert": show_alert})
    except Exception:
        pass

async def tg_polling_worker():
    """Фоновый воркер для обработки инлайн-кнопок из Telegram"""
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=5"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        if "callback_query" in update:
                            cb = update["callback_query"]
                            cb_id = cb["id"]
                            cb_data = cb.get("data", "")
                            msg = cb.get("message", {})
                            chat_id = msg.get("chat", {}).get("id")
                            msg_id = msg.get("message_id")

                            if cb_data.startswith("accept_tx_") or cb_data.startswith("reject_tx_"):
                                tx_id = int(cb_data.split("_")[2])
                                action = cb_data.split("_")[0]
                                
                                conn = get_db()
                                cur = conn.cursor()
                                cur.execute("SELECT status, user_id, amount_rub, currency FROM transactions WHERE id = ?", (tx_id,))
                                tx = cur.fetchone()
                                
                                if not tx:
                                    await answer_callback_query(cb_id, "Транзакция не найдена", True)
                                    conn.close()
                                    continue
                                
                                if tx["status"] != "pending":
                                    await answer_callback_query(cb_id, "Этот чек уже обработан другим администратором!", True)
                                    conn.close()
                                    continue

                                if action == "accept":
                                    cur.execute("UPDATE transactions SET status = 'completed' WHERE id = ?", (tx_id,))
                                    cur.execute("UPDATE users SET balance_rub = balance_rub + ? WHERE user_id = ?", (tx["amount_rub"], tx["user_id"]))
                                    conn.commit()
                                    await answer_callback_query(cb_id, "Чек принят! Баланс зачислен.")
                                    await send_tg_message(tx["user_id"], f"✅ <b>Ваш чек #{tx_id} подтвержден!</b>\nНачислено: <code>{tx['amount_rub']} ₽</code>")
                                    await send_log(f"✅ Чек #{tx_id} ({tx['amount_rub']} ₽) принят админом.")
                                    
                                    # Убираем кнопки
                                    try:
                                        await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageReplyMarkup", json={"chat_id": chat_id, "message_id": msg_id, "reply_markup": {"inline_keyboard": []}})
                                    except: pass

                                elif action == "reject":
                                    cur.execute("UPDATE transactions SET status = 'rejected' WHERE id = ?", (tx_id,))
                                    conn.commit()
                                    await answer_callback_query(cb_id, "Чек отклонен.")
                                    await send_tg_message(tx["user_id"], f"❌ <b>Ваш чек #{tx_id} был отклонен.</b>\nПожалуйста, обратитесь в поддержку, если считаете это ошибкой.")
                                    await send_log(f"❌ Чек #{tx_id} ({tx['amount_rub']} ₽) отклонен админом.")
                                    try:
                                        await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageReplyMarkup", json={"chat_id": chat_id, "message_id": msg_id, "reply_markup": {"inline_keyboard": []}})
                                    except: pass
                                
                                conn.close()
        except Exception:
            pass
        await asyncio.sleep(2)

async def crypto_polling_worker():
    while True:
        try:
            if crypto_invoices:
                invoice_ids = list(crypto_invoices.keys())
                ids_param = ",".join(map(str, invoice_ids))
                headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(f"https://pay.crypt.bot/api/getInvoices?invoice_ids={ids_param}", headers=headers)
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
    w1 = asyncio.create_task(crypto_polling_worker())
    w2 = asyncio.create_task(tg_polling_worker())
    yield
    w1.cancel()
    w2.cancel()

app = FastAPI(lifespan=lifespan)

def validate_init_data(init_data: str) -> dict:
    if not init_data: raise HTTPException(status_code=401, detail="Нет данных")
    vals = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = vals.pop("hash", None)
    check_str = "\n".join(f"{k}={v}" for k, v in sorted(vals.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(secret_key, check_str.encode(), hashlib.sha256).hexdigest(), received_hash):
        raise HTTPException(status_code=403, detail="Ошибка подписи")
    return json.loads(vals.get("user", "{}"))

@app.get("/")
def serve_root(): return FileResponse("index.html")
@app.get("/app.js")
def serve_app_js(): return FileResponse("app.js")

@app.post("/api/auth")
async def api_auth(request: Request):
    body = await request.json()
    uid = validate_init_data(body.get("initData", "")).get("id")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO users (user_id, role) VALUES (?, 'user')", (uid,))
        conn.commit()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
        row = cur.fetchone()
    conn.close()
    return dict(row)

@app.post("/api/deposit/crypto")
async def create_crypto(request: Request):
    body = await request.json()
    uid = validate_init_data(body.get("initData", "")).get("id")
    amount = float(body.get("amount_rub", 0))
    if amount < 100: raise HTTPException(status_code=400, detail="Мин. сумма 100 ₽")

    total_with_fee = round(amount * CRYPTO_RATE_MULTIPLIER, 2)
    payload = {"amount": str(total_with_fee), "currency_type": "fiat", "fiat": "RUB", "description": f"SwapPay", "payload": str(uid)}
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://pay.crypt.bot/api/createInvoice", json=payload, headers={"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN})
        res_data = resp.json()
    if not res_data.get("ok"): raise HTTPException(status_code=500, detail="Ошибка CryptoBot")
    crypto_invoices[res_data["result"]["invoice_id"]] = {"user_id": uid, "amount_rub": amount}
    return {"pay_url": res_data["result"]["pay_url"]}

@app.post("/api/deposit/pdf-receipt")
async def upload_receipt(initData: str = Form(...), amount_rub: float = Form(...), currency: str = Form(...), receipt: UploadFile = File(...)):
    uid = validate_init_data(initData).get("id")
    if not receipt.filename.lower().endswith(".pdf"): raise HTTPException(status_code=400, detail="Только PDF!")
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
    markup = {"inline_keyboard": [[{"text": "✅ Подтвердить", "callback_data": f"accept_tx_{tx_id}"}, {"text": "❌ Отклонить", "callback_data": f"reject_tx_{tx_id}"}]]}
    
    for d in drops:
        await send_tg_document(d["user_id"], receipt.filename, file_bytes, caption, markup)
    await send_log(f"📄 <b>Чек #{tx_id}</b> загружен.")
    return {"status": "ok"}

@app.post("/api/purchase")
async def handle_purchase(request: Request):
    body = await request.json()
    uid = validate_init_data(body.get("initData", "")).get("id")
    ptype = body.get("type")
    amount = float(body.get("amount", 0))
    details = body.get("details", "")

    if amount < 25: raise HTTPException(status_code=400, detail="Минимум 25 ₽")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT balance_rub, bonus_balance FROM users WHERE user_id = ?", (uid,))
    user = cur.fetchone()

    total_funds = user["balance_rub"] + user["bonus_balance"]
    if total_funds < amount:
        conn.close()
        raise HTTPException(status_code=400, detail="Недостаточно средств")

    # Идемпотентное списание: сначала бонусы, потом рубли
    bonus_to_use = min(amount, user["bonus_balance"])
    rub_to_use = amount - bonus_to_use

    if ptype == "usdt":
        if not re.match(r'^T[A-Za-z1-9]{33}$', details):
            conn.close()
            raise HTTPException(status_code=400, detail="Неверный формат TRC-20 кошелька")
        usdt_amt = round(amount / USDT_RATE, 2)
        desc = f"Вывод {usdt_amt} USDT на {details}"
    else:
        desc = f"Оплата услуги: {details}"

    cur.execute("UPDATE users SET balance_rub = balance_rub - ?, bonus_balance = bonus_balance - ? WHERE user_id = ?", (rub_to_use, bonus_to_use, uid))
    cur.execute("INSERT INTO transactions (user_id, type, amount_rub, status) VALUES (?, 'purchase', ?, 'pending')", (uid, amount))
    tx_id = cur.lastrowid
    conn.commit()
    conn.close()

    await send_log(f"🛍 <b>Новый заказ #{tx_id}</b>\nОт: <code>{uid}</code>\nСумма: <b>{amount} ₽</b>\nДетали: {desc}")
    return {"status": "ok"}

# --- ПОДДЕРЖКА ---
@app.get("/api/support/messages")
async def get_messages(initData: str, target_uid: Optional[int] = None):
    uid = validate_init_data(initData).get("id")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT role, support_status FROM users WHERE user_id = ?", (uid,))
    u = cur.fetchone()
    is_admin = u["role"] == "admin"
    
    chat_uid = target_uid if (is_admin and target_uid) else uid
    cur.execute("SELECT sender, text, created_at FROM support_messages WHERE user_id = ? ORDER BY id ASC", (chat_uid,))
    rows = [dict(r) for r in cur.fetchall()]
    
    cur.execute("SELECT support_status FROM users WHERE user_id = ?", (chat_uid,))
    status = cur.fetchone()["support_status"]
    conn.close()
    return {"messages": rows, "status": status}

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
        await send_tg_message(target_uid, f"👨‍💻 <b>Поддержка:</b>\n{text}")
    else:
        cur.execute("UPDATE users SET support_status = 'active' WHERE user_id = ?", (uid,))
        cur.execute("INSERT INTO support_messages (user_id, sender, text) VALUES (?, 'user', ?)", (uid, text))
        await send_log(f"🆘 <b>Саппорт от {uid}:</b>\n{text}")
    
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.post("/api/support/close")
async def close_support(request: Request):
    body = await request.json()
    uid = validate_init_data(body.get("initData", "")).get("id")
    target_uid = body.get("target_uid")
    action = body.get("action") # 'dm' or 'resolved'

    conn = get_db()
    cur = conn.cursor()
    if cur.execute("SELECT role FROM users WHERE user_id = ?", (uid,)).fetchone()["role"] != "admin": raise HTTPException(status_code=403)
    
    cur.execute("UPDATE users SET support_status = 'closed' WHERE user_id = ?", (target_uid,))
    conn.commit()
    conn.close()

    if action == "resolved":
        await send_tg_message(target_uid, "✅ Ваше обращение в поддержку было закрыто как решенное. Спасибо, что используете SwapPay!")
    else:
        await send_tg_message(target_uid, "Оператор закрыл чат и переведет общение в личные сообщения.")
    
    return {"status": "ok"}
