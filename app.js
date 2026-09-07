const tg = window.Telegram.WebApp;
tg.expand(); // Открываем на весь экран

const API_URL = 'http://127.0.0.1:7174/api';
let currentUser = null;

async function initApp() {
    if (!tg.initData) {
        document.getElementById('app').innerHTML = '<div class="card">Пожалуйста, откройте приложение через Telegram.</div>';
        return;
    }

    try {
        const response = await fetch(`${API_URL}/auth`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ initData: tg.initData })
        });

        if (!response.ok) throw new Error('Auth failed');
        
        currentUser = await response.json();
        updateUI();
    } catch (error) {
        tg.showAlert('Ошибка авторизации. Попробуйте перезапустить приложение.');
    }
}

function updateUI() {
    // Обновляем балансы
    document.getElementById('balance').textContent = currentUser.balance_rub.toFixed(2);
    document.getElementById('bonus-balance').textContent = currentUser.bonus_balance.toFixed(2);

    // Логика отображения вкладок для особых ролей
    const nav = document.getElementById('nav');
    const dropTab = document.getElementById('drop-tab');
    const adminTab = document.getElementById('admin-tab');
    let showNav = false;

    if (currentUser.drop !== 'not' || currentUser.role === 'admin') {
        dropTab.classList.remove('hidden');
        showNav = true;
    }
    
    if (currentUser.role === 'admin') {
        adminTab.classList.remove('hidden');
        showNav = true;
    }

    if (showNav) nav.classList.remove('hidden');
}

function switchTab(tabId) {
    document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
    event.target.classList.add('active');

    document.getElementById('view-user').classList.add('hidden');
    document.getElementById('view-drop').classList.add('hidden');
    document.getElementById('view-admin').classList.add('hidden');

    document.getElementById(`view-${tabId}`).classList.remove('hidden');

    if (tabId === 'drop') loadDropTransactions();
}

async function loadDropTransactions() {
    try {
        const res = await fetch(`${API_URL}/drop/transactions?initData=${encodeURIComponent(tg.initData)}`);
        const txs = await res.json();
        
        const list = document.getElementById('drop-tx-list');
        if (txs.length === 0) {
            list.innerHTML = '<p style="color: var(--hint-color)">Нет заявок в ожидании.</p>';
            return;
        }

        list.innerHTML = txs.map(tx => `
            <div style="border-bottom: 1px solid var(--hint-color); padding-bottom: 8px; margin-bottom: 8px;">
                <strong>ID:</strong> ${tx.id} | <strong>Сумма:</strong> ${tx.amount_rub} ₽ (${tx.amount_original} ${tx.currency})<br>
                <button onclick="processTx(${tx.id}, 'completed')" style="margin-top:8px; width:48%">Принять</button>
                <button onclick="processTx(${tx.id}, 'rejected')" style="margin-top:8px; width:48%; background-color:#e53935">Отклонить</button>
            </div>
        `).join('');
    } catch (e) {
        tg.showAlert('Ошибка загрузки заявок');
    }
}

function openDeposit() {
    tg.showPopup({
        title: 'Пополнение баланса',
        message: 'Выберите метод пополнения',
        buttons: [
            { id: 'kzt', type: 'default', text: 'Kaspi (KZT)' },
            { id: 'uah', type: 'default', text: 'Monobank (UAH)' },
            { id: 'crypto', type: 'default', text: 'CryptoBot' },
            { type: 'cancel' }
        ]
    }, function(buttonId) {
        if (buttonId) {
            // Здесь логика перехода на форму ввода суммы
            tg.showAlert(`Выбран метод: ${buttonId}. Интеграция формы в разработке.`);
        }
    });
}

function openReferrals() {
    const refLink = `t.me/SwapPayment_bot?start=ref_${currentUser.user_id}`;
    tg.showAlert(`Ваша реферальная ссылка:\n${refLink}\n\nВы получаете 5% от суммы пополнения реферала.`);
}

tg.ready();
initApp();