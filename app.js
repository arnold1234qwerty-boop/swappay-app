const tg = window.Telegram?.WebApp;
if (tg) {
    tg.expand();
    tg.ready();
}

const ADMIN_ID = 7531770025;

let currentUser = {
    user_id: ADMIN_ID, // По умолчанию для тестов
    role: "user",
    balance_rub: 350.00,
    bonus_balance: 0.00
};

let currentMethod = 'kaspi';

// Инициализация при старте
async function initApp() {
    try {
        const res = await fetch('/api/auth', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ initData: tg?.initData || "" })
        });
        if (res.ok) {
            currentUser = await res.json();
        }
    } catch (e) {
        console.warn("Локальный тест без бэкенда авторизации:", e);
    }

    renderUser();
}

function renderUser() {
    document.getElementById('balance').innerText = (currentUser.balance_rub || 0).toFixed(2);
    document.getElementById('bonus-balance').innerText = `${(currentUser.bonus_balance || 0).toFixed(2)} ₽`;
    document.getElementById('modal-buy-bal').innerText = `${(currentUser.balance_rub || 0).toFixed(2)} ₽`;

    // Проверка прав администратора
    if (currentUser.user_id === ADMIN_ID || currentUser.role === 'admin') {
        document.getElementById('user-role-badge').innerText = 'ADMIN';
        document.getElementById('admin-bottom-bar').classList.remove('hidden');
    } else {
        document.getElementById('user-role-badge').innerText = currentUser.role.toUpperCase();
    }

    // Реферальная ссылка
    const refLink = `https://t.me/SwapPayment_bot?start=ref_${currentUser.user_id}`;
    document.getElementById('ref-link-input').value = refLink;
}

// Управление шторками (модалками)
function openDepositModal() {
    document.getElementById('modal-deposit').classList.add('active');
}

function openBuyModal() {
    document.getElementById('modal-buy').classList.add('active');
}

function openRefModal() {
    document.getElementById('modal-ref').classList.add('active');
}

function openPromoModal() {
    document.getElementById('modal-promo').classList.add('active');
}

function closeModals() {
    document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('active'));
}

// Выбор метода пополнения и автокалькулятор
function selectMethod(el, method) {
    document.querySelectorAll('.method-pill').forEach(p => p.classList.remove('active'));
    el.classList.add('active');
    currentMethod = method;
    calcExchange();
}

function calcExchange() {
    const val = parseFloat(document.getElementById('deposit-amount').value) || 0;
    const calcEl = document.getElementById('deposit-calc');

    if (currentMethod === 'kaspi') {
        calcEl.innerText = `К оплате: ${(val * 8).toFixed(2)} ₸`;
    } else if (currentMethod === 'mono') {
        calcEl.innerText = `К оплате: ${(val * 0.8).toFixed(2)} ₴`;
    } else {
        calcEl.innerText = `К оплате: ≈ ${(val / 95).toFixed(2)} USDT`;
    }
}

function submitDeposit() {
    const amount = document.getElementById('deposit-amount').value;
    if (!amount || amount < 100) {
        alert("Минимальная сумма пополнения — 100 ₽");
        return;
    }
    closeModals();
    alert(`Заявка на ${amount} ₽ сформирована. Реквизиты отправлены в чат бота.`);
}

function copyRefLink() {
    const copyText = document.getElementById("ref-link-input");
    copyText.select();
    navigator.clipboard.writeText(copyText.value);
    alert("Ссылка скопирована в буфер!");
}

function openSupport() {
    if (tg?.openTelegramLink) {
        tg.openTelegramLink("https://t.me/ForestEclipse");
    } else {
        window.open("https://t.me/ForestEclipse", "_blank");
    }
}

// Переключение между вкладками (Кабинет / Админка)
function switchTab(tab) {
    if (tab === 'user') {
        document.getElementById('view-user').classList.remove('hidden');
        document.getElementById('view-admin').classList.add('hidden');
        document.getElementById('btn-tab-user').classList.add('active');
        document.getElementById('btn-tab-admin').classList.remove('active');
    } else if (tab === 'admin') {
        document.getElementById('view-user').classList.add('hidden');
        document.getElementById('view-admin').classList.remove('hidden');
        document.getElementById('btn-tab-user').classList.remove('active');
        document.getElementById('btn-tab-admin').classList.add('active');
    }
}

initApp();
