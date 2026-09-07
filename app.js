const tg = window.Telegram?.WebApp;
if (tg) {
    tg.expand();
    tg.ready();
}

let currentUser = null;

// Авторизация пользователя при старте
async function authUser() {
    try {
        const response = await fetch('/api/auth', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                initData: tg?.initData || "" 
            })
        });

        if (!response.ok) throw new Error("Auth failed");
        
        currentUser = await response.json();
        renderUserData();
    } catch (e) {
        console.warn("Тестовый запуск вне Telegram:", e);
        // Фолбэк для тестов в обычном браузере
        currentUser = {
            user_id: 7531770025,
            first_name: "User",
            role: "admin",
            drop: "all",
            balance_rub: 350.00,
            bonus_balance: 0.00
        };
        renderUserData();
    }
}

function renderUserData() {
    document.getElementById('user-role').innerText = currentUser.role.toUpperCase();
    document.getElementById('user-tg-id').innerText = currentUser.user_id;
    document.getElementById('user-balance').innerText = `${currentUser.balance_rub.toFixed(2)} ₽`;
    document.getElementById('user-bonus').innerText = `${currentUser.bonus_balance.toFixed(2)} ₽`;

    // Показываем кнопки дропа и админа, если есть права
    const tabs = document.getElementById('nav-tabs');
    const tabDrop = document.getElementById('tab-drop');
    const tabAdmin = document.getElementById('tab-admin');

    if (currentUser.drop !== 'not' || currentUser.role === 'admin') {
        tabs.classList.remove('hidden');
        tabDrop.classList.remove('hidden');
    }
    if (currentUser.role === 'admin') {
        tabAdmin.classList.remove('hidden');
    }
}

function showView(viewName) {
    document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));

    document.getElementById(`view-${viewName}`).classList.remove('hidden');
    event.currentTarget.classList.add('active');

    if (viewName === 'drop') loadDropOrders();
}

async function loadDropOrders() {
    const list = document.getElementById('drop-list');
    try {
        const res = await fetch(`/api/drop/transactions?initData=${encodeURIComponent(tg?.initData || '')}`);
        const data = await res.json();

        if (!data.length) {
            list.innerHTML = `<p style="color: var(--text-muted); text-align: center;">Новых заявок пока нет</p>`;
            return;
        }

        list.innerHTML = data.map(item => `
            <div style="background: var(--bg-color); padding: 12px; border-radius: 8px; margin-bottom: 10px;">
                <div><b>Заявка #${item.id}</b> (${item.currency})</div>
                <div style="color: var(--text-muted); font-size: 13px; margin: 4px 0;">Сумма: ${item.amount_rub} ₽ (${item.amount_original})</div>
                <div style="display: flex; gap: 8px; margin-top: 8px;">
                    <button class="bot-btn" style="flex: 1; background: #2e7d32;" onclick="confirmOrder(${item.id})">Принять</button>
                    <button class="bot-btn" style="flex: 1; background: #c62828;" onclick="rejectOrder(${item.id})">Отклонить</button>
                </div>
            </div>
        `).join('');
    } catch(err) {
        list.innerText = "Ошибка загрузки списка заявок.";
    }
}

function openDepositModal() {
    if (tg?.showPopup) {
        tg.showPopup({
            title: "Пополнение баланса",
            message: "Выберите валюту / способ оплаты:",
            buttons: [
                { id: "kzt", type: "default", text: "🇰🇿 Kaspi (KZT)" },
                { id: "uah", type: "default", text: "🇺🇦 Monobank (UAH)" },
                { id: "crypto", type: "default", text: "💎 CryptoBot" },
                { type: "cancel" }
            ]
        }, (btnId) => {
            if (btnId) tg.showAlert(`Выбран способ: ${btnId}. Переход к реквизитам...`);
        });
    } else {
        alert("Выберите способ оплаты (Kaspi / Monobank / Crypto)");
    }
}

function openBuyModal() {
    tg?.showAlert("Минимальная сумма покупки: 25 ₽. Введите реквизиты и сумму для оформления.");
}

function openProfileModal() {
    tg?.showAlert(`Личный кабинет\nID: ${currentUser.user_id}\nБаланс: ${currentUser.balance_rub} ₽`);
}

function openRefModal() {
    const link = `t.me/SwapPayment_bot?start=ref_${currentUser.user_id}`;
    tg?.showAlert(`Ваша реферальная ссылка:\n${link}\n\nБонус: 5% от всех пополнений рефералов.`);
}

function openInfoModal() {
    tg?.showAlert("Курсы обмена:\n1 ₽ = 8 KZT (тенге)\n1 ₽ = 0.8 UAH (гривна)\nMBank: временно не работает.");
}

function openSupportModal() {
    tg?.openTelegramLink("https://t.me/твой_саппорт");
}

authUser();
