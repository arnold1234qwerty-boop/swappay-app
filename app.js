const tg = window.Telegram?.WebApp;
if (tg) { tg.expand(); tg.ready(); }

let user = { id: 0, name: "User", role: "user" };
let depMethod = 'crypto';
let activeAdminChatUser = null;

// Инициализация при старте (исправляет баг обновления страницы)
async function initApp() {
    const savedTheme = localStorage.getItem("theme") || "basic";
    document.getElementById("theme-select").value = savedTheme;
    document.body.setAttribute("data-theme", savedTheme);

    try {
        const res = await fetch("/api/auth", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ initData: tg?.initData || "" })
        });
        if (res.ok) {
            const data = await res.json();
            user = { id: data.user_id, name: data.first_name || data.username || "User", role: data.role };
            
            document.getElementById("bal-rub").innerText = data.balance_rub.toFixed(2);
            document.getElementById("bal-bonus").innerText = `${data.bonus_balance.toFixed(2)} ₽`;
            
            if (user.role === "admin") {
                document.getElementById("role-badge").innerText = "ADMIN";
                document.getElementById("nav-admin").classList.remove("hidden");
            }
        }
    } catch (e) { console.error(e); }
}

function changeTheme() {
    const t = document.getElementById("theme-select").value;
    document.body.setAttribute("data-theme", t);
    localStorage.setItem("theme", t);
}

// Навигация
function switchTab(tab) {
    document.querySelectorAll(".view").forEach(v => v.classList.add("hidden"));
    document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
    document.getElementById(`view-${tab}`).classList.remove("hidden");
    document.getElementById(`nav-${tab}`).classList.add("active");

    if (tab === "support") loadUserChat();
    if (tab === "admin") loadAdminChatsList();
}

function openModal(id) { 
    document.getElementById(id).classList.add("active"); 
    if (id === 'modal-ref') loadRefs();
}
function closeModal(id) { document.getElementById(id).classList.remove("active"); }

// --- ДЕПОЗИТ (С защитой от спама) ---
function setDep(el, method) {
    document.querySelectorAll("#dep-step-1 .pill").forEach(p => p.classList.remove("active"));
    el.classList.add("active");
    depMethod = method;
    calcDep();
}

function calcDep() {
    const v = parseFloat(document.getElementById("dep-amt").value) || 0;
    const h = document.getElementById("dep-hint");
    if (depMethod === 'crypto') h.innerText = `К оплате: ${(v*1.4).toFixed(2)} ₽`;
    else if (depMethod === 'kaspi') h.innerText = `К оплате: ${(v*8).toFixed(2)} ₸`;
    else h.innerText = `К оплате: ${(v*0.8).toFixed(2)} ₴`;
}

function depNext() {
    const amt = parseFloat(document.getElementById("dep-amt").value);
    if (!amt || amt < 100) return alert("Минимум 100 ₽");
    
    document.getElementById("dep-step-1").classList.add("hidden");
    document.getElementById("dep-step-2").classList.remove("hidden");
    const txt = document.getElementById("dep-confirm-txt");
    const fb = document.getElementById("dep-file-box");
    
    if (depMethod === 'crypto') {
        txt.innerHTML = `Подтвердите создание счета на <b>${amt} ₽</b>.<br>С комиссией: <b>${(amt*1.4).toFixed(2)} ₽</b>`;
        fb.classList.add("hidden");
    } else {
        txt.innerHTML = `Переведите нужную сумму по реквизитам и <b>обязательно</b> прикрепите PDF-чек. Без него оплата не пройдет.`;
        fb.classList.remove("hidden");
    }
}

async function depSubmit() {
    const btn = document.getElementById("btn-dep-submit");
    if (btn.disabled) return; // ANTI-SPAM GUARD

    const amt = parseFloat(document.getElementById("dep-amt").value);
    
    if (depMethod !== 'crypto') {
        const file = document.getElementById("dep-file").files[0];
        if (!file) return alert("Прикрепите PDF чек!");
        if (!file.name.toLowerCase().endswith(".pdf")) return alert("Только PDF!");
        
        btn.disabled = true;
        btn.innerText = "Отправка...";
        
        const fd = new FormData();
        fd.append("initData", tg?.initData || "");
        fd.append("amount_rub", amt);
        fd.append("currency", depMethod === 'kaspi' ? "KZT" : "UAH");
        fd.append("receipt", file);

        try {
            const r = await fetch("/api/deposit/pdf-receipt", { method: "POST", body: fd });
            if (r.ok) { alert("Чек отправлен!"); closeModal('modal-deposit'); }
            else alert("Ошибка");
        } catch(e) {}
        
        btn.disabled = false;
        btn.innerText = "Подтверждаю оплату";
    } else {
        btn.disabled = true;
        btn.innerText = "Создание счета...";
        try {
            const r = await fetch("/api/deposit/crypto", {
                method: "POST", headers: {"Content-Type":"application/json"},
                body: JSON.stringify({ initData: tg?.initData||"", amount_rub: amt })
            });
            const d = await r.json();
            if (r.ok && d.pay_url) { tg?.openTelegramLink ? tg.openTelegramLink(d.pay_url) : window.open(d.pay_url); closeModal('modal-deposit'); }
            else alert(d.detail || "Ошибка");
        } catch(e) {}
        btn.disabled = false;
        btn.innerText = "Подтверждаю оплату";
    }
}

// --- ПОКУПКА ---
async function submitPurchase() {
    const btn = document.getElementById("btn-pur");
    if (btn.disabled) return;
    
    const amt = parseFloat(document.getElementById("pur-amt").value);
    const desc = document.getElementById("pur-desc").value;
    const file = document.getElementById("pur-photo").files[0];
    
    if (!amt || !desc) return alert("Заполните сумму и реквизиты");
    
    btn.disabled = true;
    btn.innerText = "Отправка...";
    
    const fd = new FormData();
    fd.append("initData", tg?.initData || "");
    fd.append("amount", amt);
    fd.append("details", desc);
    if (file) fd.append("photo", file);

    try {
        const r = await fetch("/api/purchase", { method: "POST", body: fd });
        const d = await r.json();
        if (r.ok) { alert("Заявка создана!"); closeModal('modal-purchase'); }
        else alert(d.detail || "Ошибка");
    } catch(e) {}
    btn.disabled = false;
    btn.innerText = "Создать заявку";
}

// --- ПРОМОКОД И РЕФЕРАЛЫ ---
async function activatePromo() {
    const btn = document.getElementById("btn-promo");
    if (btn.disabled) return;
    const c = document.getElementById("promo-val").value;
    if (!c) return;
    
    btn.disabled = true;
    btn.innerText = "Проверка...";
    try {
        const r = await fetch("/api/promo/activate", {
            method: "POST", headers: {"Content-Type":"application/json"},
            body: JSON.stringify({ initData: tg?.initData||"", code: c })
        });
        const d = await r.json();
        if (r.ok) { alert(`Успех! Начислено: ${d.amount} ₽`); closeModal('modal-promo'); initApp(); }
        else alert(d.detail);
    } catch(e) {}
    btn.disabled = false;
    btn.innerText = "Активировать";
}

async function loadRefs() {
    try {
        const r = await fetch(`/api/referral/stats?initData=${encodeURIComponent(tg?.initData||"")}`);
        if (r.ok) {
            const d = await r.json();
            document.getElementById("ref-count").innerText = d.referrals;
            document.getElementById("ref-link").value = d.link;
        }
    } catch(e){}
}

// --- ПОДДЕРЖКА (ЮЗЕР) ---
async function loadUserChat() {
    const r = await fetch(`/api/support/messages?initData=${encodeURIComponent(tg?.initData||"")}`);
    const d = await r.json();
    const b = document.getElementById("user-chat-box");
    b.innerHTML = "";
    d.forEach(m => {
        const isUser = m.sender === 'user';
        b.innerHTML += `
            <div class="msg ${isUser ? 'right' : 'left'}">
                <div style="font-size:10px; opacity:0.7; margin-bottom:4px;">${isUser ? user.name : 'Оператор'}</div>
                <div>${m.text}</div>
            </div>`;
    });
    b.scrollTop = b.scrollHeight;
}

async function sendMsgUser() {
    const i = document.getElementById("user-chat-input");
    const v = i.value.trim();
    if (!v) return;
    i.value = "";
    await fetch("/api/support/send", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ initData: tg?.initData||"", text: v })
    });
    loadUserChat();
}

// --- ПОДДЕРЖКА (АДМИН) ---
async function loadAdminChatsList() {
    const r = await fetch(`/api/support/chats?initData=${encodeURIComponent(tg?.initData||"")}`);
    if (r.ok) {
        const d = await r.json();
        const l = document.getElementById("admin-chat-list");
        l.innerHTML = "";
        d.forEach(c => {
            const n = c.first_name || c.username || c.user_id;
            l.innerHTML += `<div class="chat-item" onclick="openAdminChat(${c.user_id}, '${n}')">💬 ${n} (ID: ${c.user_id})</div>`;
        });
    }
}

async function openAdminChat(uid, name) {
    activeAdminChatUser = uid;
    document.getElementById("view-admin").classList.add("hidden");
    document.getElementById("view-admin-chat").classList.remove("hidden");
    document.getElementById("admin-chat-title").innerText = `Чат: ${name}`;
    
    const r = await fetch(`/api/support/messages?initData=${encodeURIComponent(tg?.initData||"")}&target_uid=${uid}`);
    const d = await r.json();
    const b = document.getElementById("admin-chat-box");
    b.innerHTML = "";
    d.forEach(m => {
        const isUser = m.sender === 'user';
        b.innerHTML += `
            <div class="msg ${isUser ? 'left' : 'right'}">
                <div style="font-size:10px; opacity:0.7; margin-bottom:4px;">${isUser ? name : 'Вы'}</div>
                <div>${m.text}</div>
            </div>`;
    });
    b.scrollTop = b.scrollHeight;
}

async function sendMsgAdmin() {
    const i = document.getElementById("admin-chat-input");
    const v = i.value.trim();
    if (!v || !activeAdminChatUser) return;
    i.value = "";
    await fetch("/api/support/send", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ initData: tg?.initData||"", text: v, target_uid: activeAdminChatUser })
    });
    openAdminChat(activeAdminChatUser, document.getElementById("admin-chat-title").innerText.replace("Чат: ", ""));
}

window.onload = initApp;
