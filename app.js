const tg = window.Telegram?.WebApp;
if (tg) {
    tg.expand();
    tg.ready();
}

let currentUser = {
    user_id: 0,
    balance_rub: 0,
    bonus_balance: 0,
    role: 'user',
    drop: 'not'
};

async function init() {
    try {
        const res = await fetch('/api/auth', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ initData: tg?.initData || "" })
        });
        if (res.ok) {
            currentUser = await res.json();
            renderUI();
        }
    } catch (e) {
        console.error("Auth error", e);
    }
}

function renderUI() {
    document.getElementById('balance').innerText = (currentUser.balance_rub || 0).toFixed(2);
    document.getElementById('bonus-balance').innerText = `${(currentUser.bonus_balance || 0).toFixed(2)} ₽`;
    document.getElementById('user-role-badge').innerText = currentUser.role.toUpperCase();

    // Открытие нижней панели при правах Drop или Admin
    if (currentUser.drop !== 'not' || currentUser.role === 'admin') {
        document.getElementById('bottom-bar').classList.remove('hidden');
        if (currentUser.drop !== 'not') document.getElementById('nav-drop').classList.remove('hidden');
        if (currentUser.role === 'admin') document.getElementById('nav-admin').classList.remove('hidden');
    }
}

function openDeposit() {
    if (tg?.showPopup) {
        tg.showPopup({
            title: 'Пополнение баланса',
            message: 'Минимальная сумма: 100 ₽\nВыберите способ оплаты:',
            buttons: [
                { id: 'kzt', type: 'default', text: '🇰🇿 Kaspi Bank' },
                { id: 'uah', type: 'default', text: '🇺🇦 Monobank' },
                { id: 'crypto', type: 'default', text: '💎 CryptoBot' },
                { type: 'cancel' }
            ]
        }, (id) => {
            if (id) tg.showAlert(`Вы выбрали: ${id.toUpperCase()}. Отправка реквизитов...`);
        });
    }
}

function openBuy() {
    tg?.showAlert("Оплата товаров/услуг:\nМинимальная сумма покупки — 25 ₽.\nФункционал создания заявки готов к подключению.");
}

function openCrypto() {
    tg?.showAlert("Покупка USDT:\nТекущий расчетный курс: 1 USDT = 95.00 ₽.\nВывод на сеть TRC-20.");
}

function openReferrals() {
    const link = `https://t.me/SwapPayment_bot?start=ref_${currentUser.user_id}`;
    tg?.showAlert(`👥 Ваша реферальная ссылка:\n${link}\n\nВы получаете 5% от всех пополнений приглашенных пользователей.`);
}

function openPromo() {
    tg?.showPopup({
        title: 'Активация промокода',
        message: 'Для активации бонусного баланса введите промокод в чат боту с командой /promo КОД.',
        buttons: [{ type: 'ok' }]
    });
}

function openSupport() {
    tg?.openTelegramLink("https://t.me/твой_саппорт");
}

init();
