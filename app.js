const tg = window.Telegram?.WebApp;
if (tg) { tg.expand(); tg.ready(); }

let user = { id: 0, role: "user" };
let depMethod = 'crypto';
let activeAdminChatUser = null;
let chatInterval = null;

async function initApp() {
    const savedTheme = localStorage.getItem("theme") || "basic";
    document.getElementById("theme-select").value = savedTheme;
    document.body.setAttribute("data-theme", savedTheme);

    try {
        const res = await fetch("/api/auth", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ initData: tg?.initData || "" })
        });
        if (res.ok) {
            const data = await res.json();
            user = data;
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

// Анимация вкладок
function switchTab(tab) {
    document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
    document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
    
    // Небольшая задержка для плавного перестроения DOM
    setTimeout(() => {
        document.getElementById(`view-${tab}`).classList.add("active");
        document.getElementById(`nav-${tab}`).classList.add("active");
    }, 50);

    clearInterval(chatInterval);
    if (tab === "support") {
        loadUserChat();
        chatInterval = setInterval(loadUserChat, 3000);
    }
    if (tab === "admin") loadAdminChatsList();
}

function openModal(id) { document.getElementById(id).classList.add("active"); }
function closeModal(id) { document.getElementById(id).classList.remove("active"); }

// --- ДЕПОЗИТ ---
function setDep(el, method) {
    document.querySelectorAll("#modal-deposit .pill").forEach(p => p.classList.remove("active"));
    el.classList.add("active");
    depMethod = method;
    calcDep();
    
    const fb = document.getElementById("dep-file-box");
    const btn = document.getElementById("btn-dep-submit");
    if (method === 'crypto') {
        fb.classList.add("hidden");
        btn.innerText = "Перейти к оплате";
    } else {
        fb.classList.remove("hidden");
        btn.innerText = "Отправить чек";
    }
}

function calcDep() {
    const v = parseFloat(document.getElementById("dep-amt").value) || 0;
    const h = document.getElementById("dep-hint");
    if (depMethod === 'crypto') h.innerText = `К оплате: ${(v*1.4).toFixed(2)} ₽`;
    else if (depMethod === 'kaspi') h.innerText = `К оплате: ${(v*8).toFixed(2)} ₸`;
    else h.innerText = `К оплате: ${(v*0.8).toFixed(2)} ₴`;
}

async function depSubmit() {
    const btn = document.getElementById("btn-dep-submit");
    if (btn.disabled) return;
    const amt = parseFloat(document.getElementById("dep-amt").value);
    if (!amt || amt < 100) return alert("Минимум 100 ₽");
    
    btn.disabled = true;
    btn.innerText = "Обработка...";
    
    try {
        if (depMethod !== 'crypto') {
            const file = document.getElementById("dep-file").files[0];
            if (!file) { alert("Прикрепите PDF чек!"); throw new Error(); }
            
            const fd = new FormData();
            fd.append("initData", tg?.initData || "");
            fd.append("amount_rub", amt);
            fd.append("currency", depMethod === 'kaspi' ? "KZT" : "UAH");
            fd.append("receipt", file);

            const r = await fetch("/api/deposit/pdf-receipt", { method: "POST", body: fd });
            if (r.ok) {
                alert("Чек отправлен! Ожидайте подтверждения.");
                closeModal('modal-deposit');
                // Сброс формы, чтобы предотвратить залипание
                document.getElementById("dep-amt").value = "";
                document.getElementById("dep-file").value = "";
                document.getElementById("dep-file-label").innerText = "📄 Прикрепить чек (.PDF)";
            } else { alert("Ошибка при отправке"); }
        } else {
            const r = await fetch("/api/deposit/crypto", {
                method: "POST", headers: {"Content-Type":"application/json"},
                body: JSON.stringify({ initData: tg?.initData||"", amount_rub: amt })
            });
            const d = await r.json();
            if (r.ok && d.pay_url) { tg?.openTelegramLink ? tg.openTelegramLink(d.pay_url) : window.open(d.pay_url); closeModal('modal-deposit'); }
            else alert("Ошибка создания счета");
        }
    } catch(e) {}
    
    btn.disabled = false;
    btn.innerText = depMethod === 'crypto' ? "Перейти к оплате" : "Отправить чек";
}

// --- ПОКУПКА ---
async function submitPurchase() {
    const btn = document.getElementById("btn-pur");
    if (btn.disabled) return;
    
    const ptype = document.getElementById("pur-type").value;
    const amt = parseFloat(document.getElementById("pur-amt").value);
    const desc = document.getElementById("pur-desc").value;
    if (!amt || !desc) return alert("Заполните поля!");
    
    btn.disabled = true;
    btn.innerText = "Отправка...";
    
    try {
        const r = await fetch("/api/purchase", {
            method: "POST", headers: {"Content-Type":"application/json"},
            body: JSON.stringify({ initData: tg?.initData||"", type: ptype, amount: amt, details: desc })
        });
        const d = await r.json();
        if (r.ok) { alert("Заявка создана! Баланс списан."); closeModal('modal-purchase'); initApp(); }
        else alert(d.detail || "Ошибка");
    } catch(e) {}
    
    btn.disabled = false;
    btn.innerText = "Оплатить";
}

// --- ПРОМОКОД ---
async function activatePromo() {
    const btn = document.getElementById("btn-promo");
    if (btn.disabled) return;
    const c = document.getElementById("promo-val").value;
    if (!c) return;
    
    btn.disabled = true;
    
    try {
        /* Эмуляция запроса для примера, т.к. бэкенд не реализовал полную логику активации, но структура есть */
        alert("Код отправлен на проверку");
        closeModal('modal-promo');
    } catch(e) {}
    btn.disabled = false;
}

// --- ПОДДЕРЖКА (ЮЗЕР) ---
async function loadUserChat() {
    try {
        const r = await fetch(`/api/support/messages?initData=${encodeURIComponent(tg?.initData||"")}`);
        if (!r.ok) return;
        const d = await r.json();
        const b = document.getElementById("user-chat-box");
        
        document.getElementById("sup-status").innerText = d.status === 'closed' ? "Чат закрыт" : "Чат с поддержкой";
        if (d.status === 'closed') document.getElementById("user-chat-input").disabled = true;
        
        // Предотвращение лишних обновлений DOM, если сообщений столько же
        if (b.children.length === d.messages.length) return; 
        
        b.innerHTML = "";
        d.messages.forEach(m => {
            const isU = m.sender === 'user';
            b.innerHTML += `<div class="msg ${isU ? 'right' : 'left'}"><div>${m.text}</div></div>`;
        });
        b.scrollTop = b.scrollHeight;
    } catch(e) {}
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
function switchAdminTab(t) {
    document.querySelectorAll(".atab").forEach(b => b.classList.remove("active"));
    event.target.classList.add("active");
    if(t==='chats') { document.getElementById("admin-sec-chats").classList.remove("hidden"); document.getElementById("admin-sec-promo").classList.add("hidden"); loadAdminChatsList(); }
    else { document.getElementById("admin-sec-chats").classList.add("hidden"); document.getElementById("admin-sec-promo").classList.remove("hidden"); }
}

async function loadAdminChatsList() {
    // В реальном проекте здесь эндпоинт получения списка чатов.
    document.getElementById("admin-chat-list").innerHTML = `<div class="pill" onclick="openAdminChat(${user.id}, 'Тестовый чат')">💬 Открыть свой чат (Тест)</div>`;
}

async function openAdminChat(uid, name) {
    activeAdminChatUser = uid;
    document.getElementById("view-admin").classList.remove("active");
    setTimeout(() => { document.getElementById("view-admin-chat").classList.add("active"); }, 50);
    document.getElementById("admin-chat-title").innerText = `Чат: ${name}`;
    
    clearInterval(chatInterval);
    const fetchChat = async () => {
        const r = await fetch(`/api/support/messages?initData=${encodeURIComponent(tg?.initData||"")}&target_uid=${uid}`);
        const d = await r.json();
        const b = document.getElementById("admin-chat-box");
        if (b.children.length === d.messages.length) return; 
        b.innerHTML = "";
        d.messages.forEach(m => {
            const isU = m.sender === 'user';
            b.innerHTML += `<div class="msg ${isU ? 'left' : 'right'}"><div>${m.text}</div></div>`;
        });
        b.scrollTop = b.scrollHeight;
    };
    fetchChat();
    chatInterval = setInterval(fetchChat, 3000);
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
}

async function closeSupportAdmin(action) {
    if(!activeAdminChatUser) return;
    await fetch("/api/support/close", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ initData: tg?.initData||"", target_uid: activeAdminChatUser, action: action })
    });
    alert("Чат закрыт!");
    switchTab('admin');
}

window.onload = initApp;
