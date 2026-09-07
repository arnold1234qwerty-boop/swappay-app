import sqlite3
import hmac
import hashlib
import json
from fastapi.staticfiles import StaticFiles # type: ignore
from fastapi.responses import FileResponse # type: ignore
from urllib.parse import parse_qsl
from fastapi import FastAPI, HTTPException, Request, Depends # type: ignore
from fastapi.middleware.cors import CORSMiddleware # type: ignore
from pydantic import BaseModel
import time
from importlib import import_module

BOT_TOKEN = "8695905699:AAGuQ_PWRFPcBmnWBO6FsTmj3_FIygaRwww" # Укажите токен вашего бота
DB_PATH = "bot_database.db"

app = FastAPI(title="SwapPay WebApp API")
# Настройка отдачи статических файлов (JS, CSS)
app.mount("/assets", StaticFiles(directory="."), name="assets")

# Главная страница Web App
@app.get("/")
def serve_html():
    return FileResponse("index.html")
    
@app.get("/app.js")
def serve_js():
    return FileResponse("app.js")

# Настройка CORS для работы с WebApp
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Простейший In-Memory Rate Limiter (Анти-флуд)
RATE_LIMIT_DATA = {}
def rate_limit(request: Request):
    client_ip = request.client.host
    current_time = time.time()
    if client_ip in RATE_LIMIT_DATA:
        last_time, count = RATE_LIMIT_DATA[client_ip]
        if current_time - last_time < 1: # 1 секунда окно
            if count > 5: # Макс 5 запросов в секунду
                raise HTTPException(status_code=429, detail="Too Many Requests")
            RATE_LIMIT_DATA[client_ip] = (last_time, count + 1)
        else:
            RATE_LIMIT_DATA[client_ip] = (current_time, 1)
    else:
        RATE_LIMIT_DATA[client_ip] = (current_time, 1)

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def validate_init_data(init_data: str) -> dict:
    """Валидация данных от Telegram WebApp."""
    try:
        parsed_data = dict(parse_qsl(init_data))
        if 'hash' not in parsed_data:
            raise ValueError("Hash is missing")
        
        received_hash = parsed_data.pop('hash')
        data_check_string = "\n".join([f"{k}={v}" for k, v in sorted(parsed_data.items())])
        
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if calculated_hash != received_hash:
            raise ValueError("Invalid hash")
            
        user_data = json.loads(parsed_data.get('user', '{}'))
        return user_data
    except Exception as e:
        raise HTTPException(status_code=401, detail="Unauthorized")

class AuthRequest(BaseModel):
    initData: str

@app.post("/api/auth", dependencies=[Depends(rate_limit)])
def authenticate_user(req: AuthRequest, db: sqlite3.Connection = Depends(get_db)):
    user_data = validate_init_data(req.initData)
    user_id = user_data.get('id')
    
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        # Регистрация нового пользователя
        cursor.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, balance_rub, bonus_balance, role, drop) 
            VALUES (?, ?, ?, ?, 0, 0, 'user', 'not')
        """, (user_id, user_data.get('username'), user_data.get('first_name'), user_data.get('last_name')))
        db.commit()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()

    return dict(user)

@app.get("/api/drop/transactions", dependencies=[Depends(rate_limit)])
def get_drop_transactions(initData: str, db: sqlite3.Connection = Depends(get_db)):
    user_data = validate_init_data(initData)
    
    cursor = db.cursor()
    cursor.execute("SELECT role, drop FROM users WHERE user_id = ?", (user_data['id'],))
    user = cursor.fetchone()
    
    if not user or (user['drop'] == 'not' and user['role'] != 'admin'):
        raise HTTPException(status_code=403, detail="Access denied")
        
    query = "SELECT * FROM transactions WHERE status = 'pending'"
    params = []
    
    if user['drop'] != 'all' and user['role'] != 'admin':
        query += " AND currency = ?"
        params.append(user['drop'].upper())
        
    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]

if __name__ == "__main__":
    # Инициализация структуры БД
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, 
            username TEXT, 
            first_name TEXT, 
            last_name TEXT, 
            balance_rub REAL DEFAULT 0, 
            bonus_balance REAL DEFAULT 0, 
            referrer_id INTEGER, 
            role TEXT DEFAULT 'user', 
            [drop] TEXT DEFAULT 'not', 
            is_subscribed INTEGER DEFAULT 0, 
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
            last_activity TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            user_id INTEGER, 
            type TEXT, 
            amount_rub REAL, 
            currency TEXT, 
            amount_original REAL, 
            status TEXT, 
            payment_method TEXT, 
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.close()
    import_module("uvicorn").run(app, host="0.0.0.0", port=7174)
