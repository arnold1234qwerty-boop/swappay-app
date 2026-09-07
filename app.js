const tg = window.Telegram?.WebApp;
if (tg) {
    tg.expand();
    tg.ready();
}

let currentUser = {
    user_id: 0,
    role: "user",
    drop: "not",
    balance_rub: 0.00,
    bonus_balance: 0.00
};

let currentMethod = 'crypto';

async function initApp() {
    try {
        const res = await fetch('/api/auth', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ initData: tg?.initData || "" })
        });
        if (res.ok) {
            currentUser = await res.json();
            renderUser();
        }
    } catch (e) {
        console.error("Auth error", e);
    }
}

function renderUser() {
    document.getElementById('balance').innerText = (currentUser.balance_rub || 0).toFixed(2);
    document.getElementById('bonus-balance').innerText = `${(currentUser.bonus_balance || 0).toFixed(2)} ₽`;

    if (currentUser.role === 'admin') {
        document.getElementById('user-role-badge').innerText = 'SUPER ADMIN';
        document.getElementById('admin-bottom-bar').classList.remove('hidden');
    } else {
        document.getElementById('user-role-badge').innerText = currentUser.role.toUpperCase();
    }
}

function openDepositModal() {
    document.getElementById('modal-deposit').classList.add('active');
    calcExchange();
}

function closeModals() {
    document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('active'));
}

function selectMethod(el, method) {
    document.querySelectorAll('.method-pill').forEach(p => p.classList.remove('active'));
    el.classList.add('active');
    currentMethod = method;
    calcExchange();
}

function calcExchange() {
    const val = parseFloat(document.getElementById('deposit-amount').value) || 0;
    const calcEl = document.getElementById('deposit-calc');

    if (currentMethod === 'crypto') {
        const total = (val * 1.4).toFixed(2);
        calcEl.innerText = `К оплате в CryptoBot: ${total} ₽ (+40% комиссия)`;
    } else if (currentMethod === 'kaspi') {
        calcEl.innerText = `К оплате: ${(val * 8).toFixed(2)} ₸`;
    } else {
        calcEl.innerText = `К оплате: ${(val * 0.8).toFixed(2)} ₴`;
    }
}

async function submitDeposit() {
    const amount = parseFloat(document.getElementById('deposit-amount').value);
    if (!amount || amount < 100) {
        alert("Минимальная сумма — 100 ₽");
        return;
    }

    if (currentMethod === 'crypto') {
        const btn = document.getElementById('btn-deposit-submit');
        btn.disabled = true;
        btn.innerText = "Создаем счет...";

        try {
            const res = await fetch('/api/deposit/crypto', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    amount_rub: amount,
                    initData: tg?.initData || ""
                })
            });

            const data = await res.json();
            if (res.ok && data.pay_url) {
                closeModals();
                // Открываем инвойс прямо в клиенте Telegram
                if (tg?.openTelegramLink) {
                    tg.openTelegramLink(data.pay_url);
                } else {
                    window.open(data.pay_url, "_blank");
                }
            } else {
                alert(data.detail || "Не удалось создать счет");
            }
        } catch (e) {
            alert("Ошибка сети при обращении к серверу");
        } finally {
            btn.disabled = false;
            btn.innerText = "Перейти к оплате";
        }
    } else {
        alert("Для Kaspi и Mono загрузка чека будет следующим шагом.");
    }
}

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
