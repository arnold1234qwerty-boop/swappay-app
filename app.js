const tg = window.Telegram?.WebApp;
if (tg) {
    tg.expand();
    tg.ready();
}

let user = { role: "user", balance_rub: 0, bonus_balance: 0 };
let currentMethod = "crypto";
let selectedFile = null;

async function init() {
    try {
        const res = await fetch("/api/auth", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ initData: tg?.initData || "" })
        });
        if (res.ok) {
            user = await res.json();
            renderUser();
        }
    } catch (e) {
        console.error(e);
    }
}

function renderUser() {
    document.getElementById("balance-val").innerText = (user.balance_rub || 0).toFixed(2);
    document.getElementById("bonus-val").innerText = `${(user.bonus_balance || 0).toFixed(2)} ₽`;

    if (user.role === "admin") {
        document.getElementById("user-role-badge").innerText = "SUPER ADMIN";
        document.getElementById("nav-admin").classList.remove("hidden");
        loadAdminStats();
    }
}

function switchView(tab) {
    document.querySelectorAll(".view").forEach(v => v.classList.add("hidden"));
    document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));

    if (tab === "home") {
        document.getElementById("tab-home").classList.remove("hidden");
        document.getElementById("nav-home").classList.add("active");
    } else if (tab === "support") {
        document.getElementById("tab-support").classList.remove("hidden");
        document.getElementById("nav-support").classList.add("active");
        loadChat();
    } else if (tab === "admin") {
        document.getElementById("tab-admin").classList.remove("hidden");
        document.getElementById("nav-admin").classList.add("active");
        loadAdminStats();
    }
}

// ДЕПОЗИТ
function openDeposit() {
    document.getElementById("modal-deposit").classList.add("active");
    recalc();
}

function closeDeposit() {
    document.getElementById("modal-deposit").classList.remove("active");
}

function setMethod(el, method) {
    document.querySelectorAll(".pill").forEach(p => p.classList.remove("active"));
    el.classList.add("active");
    currentMethod = method;

    const pdfSec = document.getElementById("pdf-section");
    const btn = document.getElementById("btn-dep-action");

    if (method === "crypto") {
        pdfSec.classList.add("hidden");
        btn.innerText = "Перейти к оплате";
    } else {
        pdfSec.classList.remove("hidden");
        btn.innerText = "Отправить чек на проверку";
    }
    recalc();
}

function recalc() {
    const val = parseFloat(document.getElementById("dep-amount").value) || 0;
    const desc = document.getElementById("crypto-desc");

    if (currentMethod === "crypto") {
        desc.innerText = `К оплате в CryptoBot: ${(val * 1.4).toFixed(2)} ₽ (+40% наценка)`;
    } else if (currentMethod === "kaspi") {
        desc.innerText = `Реквизиты Kaspi: +7 777 000 0000 | Сумма: ${(val * 8).toFixed(2)} ₸`;
    } else {
        desc.innerText = `Реквизиты Monobank: 4441 1111 2222 3333 | Сумма: ${(val * 0.8).toFixed(2)} ₴`;
    }
}

function fileChosen(input) {
    if (input.files && input.files[0]) {
        const file = input.files[0];
        if (!file.name.toLowerCase().endsWith(".pdf")) {
            alert("Разрешены исключительно PDF файлы!");
            input.value = "";
            return;
        }
        selectedFile = file;
        document.getElementById("pdf-name").innerText = `✅ Выбран: ${file.name}`;
    }
}

async function handleDepositSubmit() {
    const amount = parseFloat(document.getElementById("dep-amount").value);
    if (!amount || amount < 100) {
        alert("Минимальная сумма пополнения — 100 ₽");
        return;
    }

    if (currentMethod === "crypto") {
        try {
            const res = await fetch("/api/deposit/crypto", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ amount_rub: amount, initData: tg?.initData || "" })
            });
            const data = await res.json();
            if (res.ok && data.pay_url) {
                closeDeposit();
                if (tg?.openTelegramLink) tg.openTelegramLink(data.pay_url);
                else window.open(data.pay_url, "_blank");
            } else {
                alert(data.detail || "Ошибка выставления счета");
            }
        } catch (e) {
            alert("Ошибка сети");
        }
    } else {
        if (!selectedFile) {
            alert("Пожалуйста, прикрепите PDF-чек оплаты!");
            return;
        }
        const formData = new FormData();
        formData.append("initData", tg?.initData || "");
        formData.append("amount_rub", amount);
        formData.append("currency", currentMethod === "kaspi" ? "KZT" : "UAH");
        formData.append("receipt", selectedFile);

        try {
            const res = await fetch("/api/deposit/pdf-receipt", {
                method: "POST",
                body: formData
            });
            const data = await res.json();
            if (res.ok) {
                alert("Чек получен! Ожидайте подтверждения дропом.");
                closeDeposit();
            } else {
                alert(data.detail || "Ошибка отправки чека");
            }
        } catch (e) {
            alert("Ошибка отправки файла");
        }
    }
}

// ЧАТ ПОДДЕРЖКИ
async function loadChat() {
    try {
        const res = await fetch(`/api/support/messages?initData=${encodeURIComponent(tg?.initData || "")}`);
        const data = await res.json();
        const box = document.getElementById("chat-messages");
        box.innerHTML = `
            <div class="msg-operator">
                <div class="tag">ОПЕРАТОР</div>
                <div class="bubble">Здравствуйте! Чем можем помочь?</div>
            </div>
        `;
        data.forEach(m => {
            if (m.sender === "user") {
                box.innerHTML += `
                    <div class="msg-user">
                        <div class="tag">ЮЗЕР</div>
                        <div class="bubble">${m.text}</div>
                    </div>
                `;
            } else {
                box.innerHTML += `
                    <div class="msg-operator">
                <div class="tag">ОПЕРАТОР</div>
                        <div class="bubble">${m.text}</div>
                    </div>
                `;
            }
        });
        box.scrollTop = box.scrollHeight;
    } catch (e) {}
}

async function sendSupportMessage() {
    const input = document.getElementById("support-input");
    const text = input.value.trim();
    if (!text) return;

    input.value = "";
    const box = document.getElementById("chat-messages");
    box.innerHTML += `
        <div class="msg-user">
            <div class="tag">ЮЗЕР</div>
            <div class="bubble">${text}</div>
        </div>
    `;
    box.scrollTop = box.scrollHeight;

    await fetch("/api/support/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: tg?.initData || "", text: text })
    });
}

// АДМИНКА
async function loadAdminStats() {
    try {
        const res = await fetch(`/api/admin/stats?initData=${encodeURIComponent(tg?.initData || "")}`);
        if (res.ok) {
            const data = await res.json();
            document.getElementById("admin-turnover").innerHTML = `${data.turnover.toFixed(2)} <span>₽</span>`;
            document.getElementById("admin-users-cnt").innerText = data.total_users;
            document.getElementById("admin-tx-cnt").innerText = data.total_tx;
        }
    } catch (e) {}
}

async function createPromo() {
    const code = document.getElementById("promo-code").value;
    const amount = document.getElementById("promo-amount").value;
    if (!code || !amount) return alert("Заполните поля!");

    const res = await fetch("/api/admin/promocode/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: tg?.initData || "", code: code, amount: amount })
    });
    if (res.ok) {
        alert("Промокод успешно создан!");
        document.getElementById("promo-code").value = "";
        document.getElementById("promo-amount").value = "";
    } else {
        const d = await res.json();
        alert(d.detail || "Ошибка");
    }
}

async function runSql() {
    const q = document.getElementById("sql-query").value;
    const res = await fetch("/api/admin/sql", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: tg?.initData || "", query: q })
    });
    const d = await res.json();
    document.getElementById("sql-res").innerText = JSON.stringify(d, null, 2);
}

init();
