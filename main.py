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
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://google.com") # Замените на ссылку вашего Mini App
SUPER_ADMIN_ID = 7531770025
DB_PATH = "bot_database.db"

CRYPTO_RATE_MULTIPLIER = 1.4

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
        bonus_used REAL DEFAULT 0.0,
        currency TEXT,
        status TEXT,
        receipt_filename TEXT DEFAULT NULL,
        details TEXT DEFAULT NULL,
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
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient() as client: await client.post(url, json=payload)
    except Exception: pass

async def send_tg_document(chat_id, filename: str, file_bytes: bytes, caption: str, reply_markup=None, is_photo=False):
    endpoint = "sendPhoto" if is_photo else "sendDocument"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{endpoint}"
    try:
        file_field = "photo" if is_photo else "document"
        mime = "image/jpeg" if is_photo else "application/pdf"
        files = {file_field: (filename, file_bytes, mime)}
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        if reply_markup: data["reply_markup"] = json.dumps(reply_markup)
        async with httpx.AsyncClient(timeout=20.0) as client:
            await client.post(url, data=data, files=files)
    except Exception: pass

async def answer_callback_query(callback_query_id: str, text: str, show_alert: bool = False):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    try:
        async with httpx.AsyncClient() as client: await client.post(url, json={"callback_query_id": callback_query_id, "text": text, "show_alert": show_alert})
    except Exception: pass

async def edit_message_text(chat_id, message_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None: payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient() as client: await client.post(url, json=payload)
    except Exception: pass

async def tg_polling_worker():
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=5"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    for update in resp.json().get("result", []):
                        offset = update["update_id"] + 1
                        
                        # Обработка обычных сообщений (Команда /start)
                        if "message" in update and "text" in update["message"]:
                            msg = update["message"]
                            chat_id = msg["chat"]["id"]
                            text = msg["text"]

                            # Если это ответ админа (Отклонение заказа)
                            if "reply_to_message" in msg:
                                reply_text = msg["reply_to_message"].get("text", msg["reply_to_message"].get("caption", ""))
                                match = re.search(r'Заказ #(\d+)', reply_text)
                                if match:
                                    tx_id = int(match.group(1))
                                    reason = text
                                    conn = get_db()
                                    cur = conn.cursor()
                                    cur.execute("SELECT status, user_id, amount_rub, bonus_used FROM transactions WHERE id = ? AND status = 'pending'", (tx_id,))
                                    tx = cur.fetchone()
                                    if tx:
                                        # Корректный возврат средств
                                        rub_to_return = tx["amount_rub"] - tx["bonus_used"]
                                        cur.execute("UPDATE users SET balance_rub = balance_rub + ?, bonus_balance = bonus_balance + ? WHERE user_id = ?", 
                                                    (rub_to_return, tx["bonus_used"], tx["user_id"]))
                                        cur.execute("UPDATE transactions SET status = 'rejected' WHERE id = ?", (tx_id,))
                                        conn.commit()
                                        await send_tg_message(tx["user_id"], f"❌ <b>Ваш заказ #{tx_id} отклонен!</b>\nПричина: <i>{reason}</i>\nСредства возвращены на баланс.")
                                        await send_tg_message(LOG_CHAT_ID, f"Заказ #{tx_id} отклонен. Пользователь уведомлен.")
                                    conn.close()
                            
                            # Команда /start
                            elif text.startswith("/start"):
                                markup = {"inline_keyboard": [[{"text": "📱 Открыть SwapPay", "web_app": {"url": WEBAPP_URL}}]]}
                                welcome_text = (
                                    "👋 <b>Добро пожаловать в SwapPay!</b>\n\n"
                                    "Мы помогаем оплачивать покупки на RU маркетплейсах, "
                                    "зарубежных сервисах и продаем USDT за местную валюту.\n\n"
                                    "Вся работа, пополнения и заказы происходят внутри нашего удобного Mini App.\n\n"
                                    "👇 Нажмите кнопку ниже, чтобы начать!"
                                )
                                await send_tg_message(chat_id, welcome_text, markup)

                        # Обработка инлайн кнопок
                        if "callback_query" in update:
                            cb = update["callback_query"]
                            cb_id, cb_data = cb["id"], cb.get("data", "")
                            msg = cb.get("message", {})
                            chat_id, msg_id = msg.get("chat", {}).get("id"), msg.get("message_id")

                            if cb_data.startswith("accept_tx_") or cb_data.startswith("reject_tx_"):
                                tx_id = int(cb_data.split("_")[2])
                                action = cb_data.split("_")[0]
                                conn = get_db()
                                cur = conn.cursor()
                                cur.execute("SELECT status, user_id, amount_rub FROM transactions WHERE id = ?", (tx_id,))
                                tx = cur.fetchone()
                                if not tx or tx["status"] != "pending":
                                    await answer_callback_query(cb_id, "Уже обработан!", True); conn.close(); continue
                                
                                if action == "accept":
                                    cur.execute("UPDATE transactions SET status = 'completed' WHERE id = ?", (tx_id,))
                                    cur.execute("UPDATE users SET balance_rub = balance_rub + ? WHERE user_id = ?", (tx["amount_rub"], tx["user_id"]))
                                    await answer_callback_query(cb_id, "Чек принят!")
                                    await send_tg_message(tx["user_id"], f"✅ <b>Ваш баланс пополнен!</b>\nСумма: {tx['amount_rub']} ₽")
                                elif action == "reject":
                                    cur.execute("UPDATE transactions SET status = 'rejected' WHERE id = ?", (tx_id,))
                                    await answer_callback_query(cb_id, "Чек отклонен.")
                                    await send_tg_message(tx["user_id"], f"❌ <b>Ваш чек #{tx_id} отклонен.</b> Попробуйте снова или обратитесь в поддержку.")
                                conn.commit(); conn.close()
                                await edit_message_text(chat_id, msg_id, msg.get("text", msg.get("caption", "")) + f"\n\n<b>Статус:</b> {'Принят' if action == 'accept' else 'Отклонен'}", {"inline_keyboard": []})

                            elif cb_data.startswith("order_done_"):
                                tx_id = int(cb_data.split("_")[2])
                                conn = get_db()
                                cur = conn.cursor()
                                cur.execute("SELECT status, user_id FROM transactions WHERE id = ?", (tx_id,))
                                tx = cur.fetchone()
                                if tx and tx["status"] == "pending":
                                    cur.execute("UPDATE transactions SET status = 'completed' WHERE id = ?", (tx_id,))
                                    conn.commit()
                                    await answer_callback_query(cb_id, "Заказ выполнен!")
                                    await send_tg_message(tx["user_id"], f"✅ <b>Ваш заказ #{tx_id} успешно выполнен!</b>")
                                    await edit_message_text(chat_id, msg_id, msg.get("text", msg.get("caption", "")) + "\n\n✅ <b>ВЫПОЛНЕН</b>", {"inline_keyboard": []})
                                else:
                                    await answer_callback_query(cb_id, "Заказ уже обработан!", True)
                                conn.close()

                            elif cb_data.startswith("order_reject_"):
                                await answer_callback_query(cb_id, "Чтобы отклонить, сделайте Reply (Ответить) на это сообщение и укажите причину возврата!", True)
        except Exception: pass
        await asyncio.sleep(2)

async def crypto_polling_worker():
    while True:
        try:
            if crypto_invoices:
                ids_param = ",".join(map(str, crypto_invoices.keys()))
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(f"https://pay.crypt.bot/api/getInvoices?invoice_ids={ids_param}", headers={"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN})
                    if resp.status_code == 200 and resp.json().get("ok"):
                        for item in resp.json()["result"]["items"]:
                            if item["status"] == "paid" and item["invoice_id"] in crypto_invoices:
                                inv_data = crypto_invoices.pop(item["invoice_id"])
                                uid, amt = inv_data["user_id"], inv_data["amount_rub"]
                                conn = get_db()
                                conn.execute("UPDATE users SET balance_rub = balance_rub + ? WHERE user_id = ?", (amt, uid))
                                conn.execute("INSERT INTO transactions (user_id, type, amount_rub, currency, status) VALUES (?, 'deposit', ?, 'CRYPTO', 'completed')", (uid, amt))
                                conn.commit(); conn.close()
                                await send_tg_message(uid, f"✅ <b>Баланс пополнен!</b>\nНачислено: {amt:.2f} ₽ через CryptoBot.")
        except Exception: pass
        await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    w1, w2 = asyncio.create_task(crypto_polling_worker()), asyncio.create_task(tg_polling_worker())
    yield
    w1.cancel(); w2.cancel()

app = FastAPI(lifespan=lifespan)

def validate_init_data(init_data: str) -> dict:
    if not init_data: raise HTTPException(status_code=401)
    vals = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = vals.pop("hash", None)
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(secret_key, "\n".join(f"{k}={v}" for k, v in sorted(vals.items())).encode(), hashlib.sha256).hexdigest(), received_hash):
        raise HTTPException(status_code=403)
    return json.loads(vals.get("user", "{}"))

@app.get("/")
def serve_root(): return FileResponse("index.html")

@app.get("/app.js")
def serve_app_js(): return FileResponse("app.js")

@app.post("/api/auth")
async def api_auth(request: Request):
    user_data = validate_init_data((await request.json()).get("initData", ""))
    uid, fname, uname = user_data.get("id"), user_data.get("first_name", ""), user_data.get("username", "")
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
    if not row:
        conn.execute("INSERT INTO users (user_id, first_name, username, role) VALUES (?, ?, ?, 'user')", (uid, fname, uname))
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
    conn.close()
    return dict(row)

@app.post("/api/deposit/crypto")
async def create_crypto(request: Request):
    body = await request.json()
    uid, amount = validate_init_data(body.get("initData", "")).get("id"), float(body.get("amount_rub", 0))
    if amount < 100: raise HTTPException(status_code=400, detail="Мин. сумма 100 ₽")
    payload = {"amount": str(round(amount * CRYPTO_RATE_MULTIPLIER, 2)), "currency_type": "fiat", "fiat": "RUB", "description": "SwapPay"}
    async with httpx.AsyncClient() as client:
        res = (await client.post("https://pay.crypt.bot/api/createInvoice", json=payload, headers={"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN})).json()
    crypto_invoices[res["result"]["invoice_id"]] = {"user_id": uid, "amount_rub": amount}
    return {"pay_url": res["result"]["pay_url"]}

@app.post("/api/deposit/pdf-receipt")
async def upload_receipt(initData: str = Form(...), amount_rub: float = Form(...), currency: str = Form(...), receipt: UploadFile = File(...)):
    uid = validate_init_data(initData).get("id")
    file_bytes = await receipt.read()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO transactions (user_id, type, amount_rub, currency, status, receipt_filename) VALUES (?, 'deposit', ?, ?, 'pending', ?)", (uid, amount_rub, currency.upper(), receipt.filename))
    tx_id = cur.lastrowid
    drops = cur.execute("SELECT user_id FROM users WHERE drop_role = 'all' OR drop_role = ?", (currency.lower(),)).fetchall()
    conn.commit(); conn.close()

    caption = f"📥 <b>Чек #{tx_id}</b>\nЮзер: <code>{uid}</code>\nСумма: <b>{amount_rub:.2f} ₽</b> ({currency.upper()})"
    markup = {"inline_keyboard": [[{"text": "✅ Подтвердить", "callback_data": f"accept_tx_{tx_id}"}, {"text": "❌ Отклонить", "callback_data": f"reject_tx_{tx_id}"}]]}
    for d in drops: await send_tg_document(d["user_id"], receipt.filename, file_bytes, caption, markup, is_photo=False)
    await send_tg_message(uid, f"⏳ <b>Ваш чек на {amount_rub} ₽ передан на проверку.</b> Ожидайте уведомления!")
    return {"status": "ok"}

@app.post("/api/purchase")
async def handle_purchase(
    initData: str = Form(...), 
    ptype: str = Form(...), 
    amount: float = Form(...), 
    details: str = Form(""), 
    photo: Optional[UploadFile] = File(None)
):
    uid = validate_init_data(initData).get("id")
    if amount < 25: raise HTTPException(status_code=400, detail="Минимум 25 ₽")
    if ptype == "usdt" and not re.match(r'^T[A-Za-z1-9]{33}$', details):
        raise HTTPException(status_code=400, detail="Неверный формат TRC-20 кошелька")

    conn = get_db()
    user = conn.execute("SELECT balance_rub, bonus_balance FROM users WHERE user_id = ?", (uid,)).fetchone()
    if user["balance_rub"] + user["bonus_balance"] < amount:
        conn.close(); raise HTTPException(status_code=400, detail="Недостаточно средств")

    bonus_use = min(amount, user["bonus_balance"])
    rub_use = amount - bonus_use
    
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance_rub = balance_rub - ?, bonus_balance = bonus_balance - ? WHERE user_id = ?", (rub_use, bonus_use, uid))
    cur.execute("INSERT INTO transactions (user_id, type, amount_rub, bonus_used, status, details) VALUES (?, ?, ?, ?, 'pending', ?)", (uid, ptype, amount, bonus_use, details))
    tx_id = cur.lastrowid
    conn.commit(); conn.close()

    text = f"📦 <b>Новый Заказ #{tx_id}</b>\nЮзер: <code>{uid}</code>\nТип: {ptype.upper()}\nСумма: <b>{amount} ₽</b>\nДетали:\n<code>{details}</code>"
    markup = {"inline_keyboard": [[{"text": "✅ Выполнен", "callback_data": f"order_done_{tx_id}"}, {"text": "❌ Отклонить", "callback_data": f"order_reject_{tx_id}"}]]}
    
    if photo and photo.filename:
        file_bytes = await photo.read()
        await send_tg_document(LOG_CHAT_ID, photo.filename, file_bytes, text, markup, is_photo=True)
    else:
        await send_tg_message(LOG_CHAT_ID, text, markup)
        
    await send_tg_message(uid, f"⏳ <b>Ваш заказ #{tx_id} на сумму {amount} ₽ принят в обработку!</b>")
    return {"status": "ok"}

@app.post("/api/promo/activate")
async def activate_promo(request: Request):
    body = await request.json()
    uid = validate_init_data(body.get("initData", "")).get("id")
    code = body.get("code", "").strip().upper()
    conn = get_db()
    promo = conn.execute("SELECT * FROM promocodes WHERE code = ? AND is_active = 1", (code,)).fetchone()
    if not promo or promo["current_uses"] >= promo["max_uses"]:
        conn.close(); raise HTTPException(status_code=400, detail="Промокод не найден или истек")
    used = conn.execute("SELECT 1 FROM used_promocodes WHERE user_id = ? AND promocode_id = ?", (uid, promo["id"])).fetchone()
    if used: conn.close(); raise HTTPException(status_code=400, detail="Вы уже использовали этот промокод")

    conn.execute("UPDATE promocodes SET current_uses = current_uses + 1 WHERE id = ?", (promo["id"],))
    conn.execute("INSERT INTO used_promocodes (user_id, promocode_id) VALUES (?, ?)", (uid, promo["id"]))
    conn.execute("UPDATE users SET bonus_balance = bonus_balance + ? WHERE user_id = ?", (promo["amount"], uid))
    conn.commit(); conn.close()
    return {"status": "ok", "amount": promo["amount"]}

@app.get("/api/support/messages")
async def get_messages(initData: str, target_uid: Optional[int] = None):
    uid = validate_init_data(initData).get("id")
    conn = get_db()
    is_admin = conn.execute("SELECT role FROM users WHERE user_id = ?", (uid,)).fetchone()["role"] == "admin"
    chat_uid = target_uid if (is_admin and target_uid) else uid
    rows = conn.execute("SELECT sender, text FROM support_messages WHERE user_id = ? ORDER BY id ASC", (chat_uid,)).fetchall()
    status = conn.execute("SELECT support_status FROM users WHERE user_id = ?", (chat_uid,)).fetchone()["support_status"]
    conn.close()
    return {"messages": [dict(r) for r in rows], "status": status}

@app.post("/api/support/send")
async def send_support(request: Request):
    body = await request.json()
    uid, text, target_uid = validate_init_data(body.get("initData", "")).get("id"), body.get("text", "").strip(), body.get("target_uid")
    if not text: raise HTTPException(status_code=400)
    conn = get_db()
    is_admin = conn.execute("SELECT role FROM users WHERE user_id = ?", (uid,)).fetchone()["role"] == "admin"
    if is_admin and target_uid:
        conn.execute("INSERT INTO support_messages (user_id, sender, text) VALUES (?, 'admin', ?)", (target_uid, text))
        await send_tg_message(target_uid, f"👨‍💻 <b>Поддержка:</b>\n{text}")
    else:
        conn.execute("UPDATE users SET support_status = 'active' WHERE user_id = ?", (uid,))
        conn.execute("INSERT INTO support_messages (user_id, sender, text) VALUES (?, 'user', ?)", (uid, text))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/support/close")
async def close_support(request: Request):
    body = await request.json()
    if get_db().execute("SELECT role FROM users WHERE user_id = ?", (validate_init_data(body.get("initData", "")).get("id"),)).fetchone()["role"] != "admin": raise HTTPException(status_code=403)
    conn = get_db()
    conn.execute("UPDATE users SET support_status = 'closed' WHERE user_id = ?", (body.get("target_uid"),))
    conn.commit(); conn.close()
    return {"status": "ok"}
