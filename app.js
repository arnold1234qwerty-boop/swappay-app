const tg = window.Telegram?.WebApp;

if (tg) {
    tg.expand();
    tg.ready();
    const setHeight = () => document.documentElement.style.setProperty('--tg-viewport-stable-height', `${tg.viewportStableHeight || window.innerHeight}px`);
    tg.onEvent('viewportChanged', setHeight);
    setHeight();
}

let user = { id: 0, role: "user" };
let depMethod = 'crypto';
let activeAdminChatUser = null;
let chatInterval = null;

let currentReviewTxId = null;
let currentReviewStars = 5;
let renderedMessagesCount = 0;
let renderedAdminMessagesCount = 0;
let particleInterval = null;

// --- ИНЖЕКТ CSS ДЛЯ ПАРТИКЛОВ ---
const particleStyle = document.createElement('style');
particleStyle.innerHTML = `
    .particle {
        position: fixed;
        top: -50px;
        z-index: 0; /* Под карточками, чтобы не мешать тексту */
        pointer-events: none;
        animation: fall linear forwards;
        opacity: 0.6;
    }
    @keyframes fall {
        to { transform: translateY(110vh) rotate(360deg); }
    }
`;
document.head.appendChild(particleStyle);

// --- ГЛОБАЛЬНАЯ ТАКТИЛЬНАЯ ОТДАЧА ---
document.addEventListener('touchstart', (e) => {
    if (e.target.closest('.btn') || e.target.closest('.pill') || e.target.closest('.nav-btn')) {
        if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    }
}, {passive: true});

function showToast(message) {
    const toast = document.getElementById("toast");
    toast.innerText = message;
    toast.classList.add("show");
    if(tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    setTimeout(() => { toast.classList.remove("show"); }, 3000);
}

async function initApp() {
    const t = localStorage.getItem("theme") || "basic";
    const p = localStorage.getItem("particles") || "none";
    
    document.getElementById("theme-select").value = t;
    // Ожидаем, что в index.html появится селект для партиклов с id="particles-select"
    const pSelect = document.getElementById("particles-select");
    if(pSelect) pSelect.value = p;
    
    if (t === "custom") {
        const bg = localStorage.getItem("custom_bg");
        if (bg) {
            document.body.style.backgroundImage = `url(${bg})`;
            document.body.classList.add("custom-bg-active");
        }
    } else {
        document.body.style.backgroundImage = "";
        document.body.classList.remove("custom-bg-active");
        document.body.setAttribute("data-theme", t);
    }
    
    setParticles(p); // Запуск партиклов
    
    try {
        const r = await fetch("/api/auth", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ initData: tg?.initData || "" })
        });
        
        if (r.ok) {
            user = await r.json();
            document.getElementById("user-display").innerText = `@${user.username || user.first_name || "Пользователь"}`;
            document.getElementById("bal-rub").innerText = user.balance_rub.toFixed(2);
            document.getElementById("bal-bonus").innerText = `${user.bonus_balance.toFixed(2)} ₽`;
            document.getElementById("ref-link").value = `https://t.me/swapaapaaAPP_bot?start=ref_${user.user_id}`;

            if (user.role === "admin") document.getElementById("nav-admin").classList.remove("hidden");
            
            const startParam = tg?.initDataUnsafe?.start_param;
            if (startParam && startParam.startsWith('review_')) {
                currentReviewTxId = parseInt(startParam.split('_')[1]);
                openModal('modal-review-add');
            }
        }
    } catch (e) { showToast("Ошибка связи с сервером"); }
}

function changeTheme() {
    const t = document.getElementById("theme-select").value;
    if (t === "custom") {
        document.getElementById("custom-bg-input").click();
    } else {
        document.body.style.backgroundImage = "";
        document.body.classList.remove("custom-bg-active");
        document.body.setAttribute("data-theme", t);
        localStorage.setItem("theme", t);
        localStorage.removeItem("custom_bg");
    }
}

function loadCustomBg(input) {
    if (input.files && input.files[0]) {
        const reader = new FileReader();
        reader.onload = function(e) {
            const b64 = e.target.result;
            localStorage.setItem("theme", "custom");
            localStorage.setItem("custom_bg", b64);
            document.body.setAttribute("data-theme", "basic"); 
            document.body.classList.add("custom-bg-active");
            document.body.style.backgroundImage = `url(${b64})`;
        };
        reader.readAsDataURL(input.files[0]);
    }
}

// --- ДВИЖОК ПАРТИКЛОВ (ОПТИМИЗИРОВАННЫЙ) ---
function changeParticles() {
    const type = document.getElementById("particles-select").value;
    setParticles(type);
}

function setParticles(type) {
    localStorage.setItem('particles', type);
    document.querySelectorAll('.particle').forEach(p => p.remove());
    clearInterval(particleInterval);

    if (type === 'none') return;

    const emojis = {
        'snow': ['❄️', '🌨'],
        'leaves': ['🍂', '🍃', '🍁'],
        'money': ['💵', '💸', '💰'],
        'water': ['🛢️', '💧', '🧊'] // 5-литровые бутылки воды и капли
    }[type];

    if(!emojis) return;

    const maxParticles = 25; // Ограничение для оптимизации
    particleInterval = setInterval(() => {
        if(document.querySelectorAll('.particle').length > maxParticles) return;

        const p = document.createElement('div');
        p.className = 'particle';
        p.innerText = emojis[Math.floor(Math.random() * emojis.length)];
        p.style.left = Math.random() * 100 + 'vw';
        p.style.animationDuration = (Math.random() * 3 + 4) + 's'; // От 4 до 7 секунд
        p.style.fontSize = (Math.random() * 10 + 15) + 'px'; // Размер 15-25px
        document.body.appendChild(p);

        setTimeout(() => { p.remove(); }, 7000);
    }, 450);
}

function switchTab(tab) {
    document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
    document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
    setTimeout(() => { 
        document.getElementById(`view-${tab}`).classList.add("active"); 
        document.getElementById(`nav-${tab}`).classList.add("active"); 
    }, 50);
    
    clearInterval(chatInterval);
    
    if (tab === "support") {
        renderedMessagesCount = 0;
        document.getElementById("user-chat-box").innerHTML = ""; 
        loadUserChat(); 
        chatInterval = setInterval(loadUserChat, 3000);
    } else if (tab === "quests") {
        loadQuests();
    } else if (tab === "admin") {
        loadAdminData();
    } else if (tab === "reviews") {
        loadReviews();
    }
}

function openModal(id, ptype = null) {
    document.getElementById(id).classList.add("active");
    if (id === 'modal-purchase' && ptype) {
        document.getElementById('pur-type').value = ptype;
        document.getElementById("pur-amt").value = "";
        document.getElementById("pur-desc").value = "";
        document.getElementById("pur-file").value = "";
        document.getElementById("pur-file-label").innerText = "📸 Прикрепить фото (QR/Реквизиты)";
        
        if (ptype === 'usdt') {
            document.getElementById('pur-title').innerText = "Покупка USDT (TRC-20)";
            document.getElementById('pur-desc').placeholder = "Ваш кошелек (начинается с T...)";
            document.getElementById('usdt-rate-box').classList.remove('hidden');
            document.getElementById('usdt-calc-hint').classList.remove('hidden');
            document.getElementById('pur-photo-box').classList.add('hidden');
        } else {
            document.getElementById('pur-title').innerText = "Оплата услуги / товара";
            document.getElementById('pur-desc').placeholder = "Ссылка или реквизиты услуги";
            document.getElementById('usdt-rate-box').classList.add('hidden');
            document.getElementById('usdt-calc-hint').classList.add('hidden');
            document.getElementById('pur-photo-box').classList.remove('hidden');
        }
    }
}

function closeModal(id) { document.getElementById(id).classList.remove("active"); }

function setDep(el, method) {
    document.querySelectorAll("#modal-deposit .pill").forEach(p => p.classList.remove("active"));
    el.classList.add("active"); depMethod = method; calcDep();
    if (method === 'crypto') { document.getElementById("dep-file-box").classList.add("hidden"); document.getElementById("btn-dep-submit").innerText = "Перейти к оплате"; }
    else { document.getElementById("dep-file-box").classList.remove("hidden"); document.getElementById("btn-dep-submit").innerText = "Отправить чек"; }
}

function calcDep() {
    const v = parseFloat(document.getElementById("dep-amt").value) || 0;
    document.getElementById("dep-hint").innerText = depMethod === 'crypto' ? `К оплате: ${(v * 1.4).toFixed(2)} ₽` : depMethod === 'kaspi' ? `К оплате: ${(v * 8).toFixed(2)} ₸` : `К оплате: ${(v * 0.8).toFixed(2)} ₴`;
}

function calcUsdt() {
    if (document.getElementById('pur-type').value !== 'usdt') return;
    document.getElementById("usdt-calc-hint").innerText = `Получите: ~${((parseFloat(document.getElementById("pur-amt").value) || 0) / 95).toFixed(2)} USDT`;
}

async function depSubmit() {
    const btn = document.getElementById("btn-dep-submit"); if (btn.disabled) return;
    const amt = parseFloat(document.getElementById("dep-amt").value);
    if (!amt || amt < 100) return showToast("Минимум 100 ₽");
    btn.disabled = true; const origText = btn.innerText; btn.innerText = "Обработка...";
    try {
        if (depMethod !== 'crypto') {
            const file = document.getElementById("dep-file").files[0];
            if (!file) throw new Error();
            const fd = new FormData(); fd.append("initData", tg?.initData || ""); fd.append("amount_rub", amt); fd.append("currency", depMethod === 'kaspi' ? "KZT" : "UAH"); fd.append("receipt", file);
            const r = await fetch("/api/deposit/pdf-receipt", { method: "POST", body: fd });
            if (r.ok) { showToast("Чек передан в обработку!"); closeModal('modal-deposit'); }
        } else {
            const r = await fetch("/api/deposit/crypto", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ initData: tg?.initData || "", amount_rub: amt }) });
            const d = await r.json();
            if (r.ok && d.pay_url) { tg?.openTelegramLink ? tg.openTelegramLink(d.pay_url) : window.open(d.pay_url); closeModal('modal-deposit'); }
        }
    } catch (e) { showToast("Ошибка. Проверьте файл и сумму."); }
    finally { btn.disabled = false; btn.innerText = origText; }
}

async function submitPurchase() {
    const btn = document.getElementById("btn-pur"); if (btn.disabled) return;
    const ptype = document.getElementById("pur-type").value, amt = parseFloat(document.getElementById("pur-amt").value), desc = document.getElementById("pur-desc").value;
    if (!amt || !desc) return showToast("Заполните все поля!");
    if (amt < 25) return showToast("Мин. сумма заказа 25 ₽");
    btn.disabled = true; btn.innerText = "Отправка...";
    try {
        const fd = new FormData(); fd.append("initData", tg?.initData || ""); fd.append("ptype", ptype); fd.append("amount", amt); fd.append("details", desc);
        if (ptype === 'service' && document.getElementById("pur-file").files.length > 0) fd.append("photo", document.getElementById("pur-file").files[0]);
        const r = await fetch("/api/purchase", { method: "POST", body: fd });
        if (r.ok) { showToast("Заказ отправлен в работу!"); closeModal('modal-purchase'); await initApp(); } 
        else showToast((await r.json()).detail || "Произошла ошибка");
    } catch (e) { showToast("Сбой соединения."); }
    finally { btn.disabled = false; btn.innerText = "Создать заказ"; }
}

async function activatePromo() {
    const code = document.getElementById("promo-input").value; if (!code) return;
    try {
        const r = await fetch("/api/promo/activate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ initData: tg?.initData || "", code: code }) });
        const d = await r.json();
        if (r.ok) { showToast(`Активировано: +${d.amount} ₽ !`); closeModal('modal-promo'); await initApp(); } 
        else showToast(d.detail || "Ошибка активации");
    } catch (e) {}
}

function copyRef() { document.getElementById("ref-link").select(); document.execCommand("copy"); showToast("Ссылка скопирована!"); }

// --------- ЗАДАНИЯ (QUESTS) ---------
async function loadQuests() {
    try {
        const r = await fetch(`/api/quests?initData=${encodeURIComponent(tg?.initData || "")}`);
        const d = await r.json();
        const b = document.getElementById("quests-list");
        b.innerHTML = "";
        d.quests.forEach(q => {
            let pct = Math.min((q.progress / q.max) * 100, 100);
            b.innerHTML += `
            <div class="pill" style="flex-direction: column; align-items: stretch; gap: 8px;">
                <div style="display: flex; justify-content: space-between;">
                    <b style="font-size: 13px;">${q.title}</b>
                    <span style="color: #10b981; font-weight: 800; font-size: 12px;">+${q.reward} ₽</span>
                </div>
                <div style="font-size: 11px; color: var(--text-secondary);">${q.desc}</div>
                <div style="width: 100%; background: var(--bg-body); border-radius: 10px; height: 6px; overflow: hidden; margin-top: 4px;">
                    <div style="height: 100%; width: ${pct}%; background: var(--accent-main); border-radius: 10px;"></div>
                </div>
                <div style="font-size: 10px; text-align: right; color: var(--text-secondary);">${q.progress} / ${q.max}</div>
            </div>`;
        });
    } catch (e) {}
}

// --------- ОТЗЫВЫ ---------
async function loadReviews() {
    try {
        const r = await fetch(`/api/reviews?initData=${encodeURIComponent(tg?.initData || "")}`);
        const d = await r.json();
        const b = document.getElementById("reviews-list");
        b.innerHTML = "";
        d.reviews.forEach(rv => {
            let starsHtml = '⭐️'.repeat(rv.stars);
            b.innerHTML += `
            <div class="pill" style="flex-direction: column; align-items: flex-start; gap: 5px;">
                <div style="width: 100%; display: flex; justify-content: space-between; align-items: center;">
                    <div style="font-size: 11px; color: var(--accent-main); font-weight: 800;">@${rv.first_name || "Пользователь"}</div>
                    <div style="font-size: 10px; color:var(--text-secondary);">${rv.created_at.split(' ')[0]}</div>
                </div>
                <div style="font-size: 10px; color: #10b981;">Заказ на ${rv.amount_rub} ₽ &nbsp;|&nbsp; ${starsHtml}</div>
                <div style="font-size: 13px; margin-top: 4px;">${rv.text}</div>
            </div>`;
        });
        if (d.reviews.length === 0) b.innerHTML = "<div style='font-size:12px; color:var(--text-secondary); text-align:center;'>Отзывов пока нет</div>";
    } catch(e){}
}

function setReviewStars(num) {
    currentReviewStars = num;
    for(let i=1; i<=5; i++) {
        const starEl = document.getElementById(`star-${i}`);
        if(i <= num) { starEl.style.opacity = "1"; starEl.style.transform = "scale(1.2)"; } 
        else { starEl.style.opacity = "0.3"; starEl.style.transform = "scale(1)"; }
    }
}

async function submitReview() {
    if(!currentReviewTxId) return showToast("Оставить отзыв можно только по кнопке из уведомления!");
    const txt = document.getElementById("review-text").value;
    if(!txt) return showToast("Напишите текст отзыва!");
    try {
        const r = await fetch("/api/reviews", { 
            method: "POST", headers: { "Content-Type": "application/json" }, 
            body: JSON.stringify({ initData: tg?.initData || "", text: txt, stars: currentReviewStars, tx_id: currentReviewTxId }) 
        });
        const d = await r.json();
        if (r.ok) {
            showToast("Спасибо за ваш отзыв!"); closeModal("modal-review-add"); document.getElementById("review-text").value = "";
            currentReviewTxId = null; if (document.getElementById("view-reviews").classList.contains("active")) loadReviews();
        } else showToast(d.detail || "Ошибка");
    } catch(e){ showToast("Ошибка соединения"); }
}

// --------- ПОДДЕРЖКА ---------
async function loadUserChat() {
    try {
        const r = await fetch(`/api/support/messages?initData=${encodeURIComponent(tg?.initData || "")}`);
        const d = await r.json(); 
        const b = document.getElementById("user-chat-box");
        
        if (d.status === 'closed') {
            document.getElementById("sup-status").innerText = "Диалог завершен"; 
            document.getElementById("user-chat-input-wrap").classList.add("hidden"); 
            document.getElementById("btn-reopen-chat").classList.remove("hidden");
        }
        
        // Append-Only
        if (d.messages.length > renderedMessagesCount) {
            for(let i = renderedMessagesCount; i < d.messages.length; i++) {
                let m = d.messages[i];
                let div = document.createElement('div');
                div.className = `msg ${m.sender === 'user' ? 'right' : 'left'}`;
                div.innerHTML = `<div>${m.text}</div>`;
                b.appendChild(div);
            }
            b.scrollTop = b.scrollHeight;
            renderedMessagesCount = d.messages.length;
        }
    } catch (e) {}
}

function reopenChat() {
    document.getElementById("btn-reopen-chat").classList.add("hidden");
    document.getElementById("user-chat-input-wrap").classList.remove("hidden");
    
    let secs = 10;
    document.getElementById("sup-status").innerText = `Поиск оператора... ${secs}с`;
    
    // Инпут разблокирован. Таймер просто визуально тикает, давая фору
    const intv = setInterval(() => {
        secs--;
        if(secs > 0) {
            document.getElementById("sup-status").innerText = `Поиск оператора... ${secs}с`;
        } else {
            clearInterval(intv);
            document.getElementById("sup-status").innerText = "Чат с поддержкой";
        }
    }, 1000);
}

async function sendMsgUser() {
    const i = document.getElementById("user-chat-input"), v = i.value.trim(); if (!v) return; i.value = "";
    await fetch("/api/support/send", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ initData: tg?.initData || "", text: v }) }); 
    loadUserChat();
}

// --------- АДМИНКА ---------
async function loadAdminData() {
    try {
        const rs = await fetch(`/api/admin/stats?initData=${encodeURIComponent(tg?.initData || "")}`);
        if(rs.ok) {
            const st = await rs.json();
            document.getElementById("stat-turnover").innerText = st.turnover.toLocaleString();
            document.getElementById("stat-conv").innerText = `${st.conversion}%`;
            document.getElementById("stat-profit-rub").innerText = st.profit_rub.toLocaleString();
            document.getElementById("stat-profit-kzt").innerText = st.profit_kzt.toLocaleString();
        }
        const rt = await fetch(`/api/admin/tickets?initData=${encodeURIComponent(tg?.initData || "")}`);
        if(rt.ok) {
            const tk = await rt.json();
            const b = document.getElementById("admin-chat-list"); b.innerHTML = "";
            tk.forEach(t => { b.innerHTML += `<div class="pill" onclick="openAdminChat(${t.user_id}, '${t.first_name}')">💬 ${t.first_name} (ID: ${t.user_id})</div>`; });
            if (tk.length === 0) b.innerHTML = "<div style='font-size:12px; color:var(--text-secondary); text-align:center;'>Нет открытых чатов</div>";
        }
    } catch (e) {}
}

async function adminCreatePromo() {
    const code = document.getElementById("adm-promo-code").value, amt = document.getElementById("adm-promo-amt").value, uses = document.getElementById("adm-promo-uses").value;
    if(!code || !amt || !uses) return showToast("Заполните все поля");
    try {
        const r = await fetch("/api/admin/promo/create", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ initData: tg?.initData || "", code: code, amount: amt, max_uses: uses }) });
        if(r.ok) { showToast("Промокод создан!"); document.getElementById("adm-promo-code").value = ""; } 
        else showToast("Код уже существует");
    } catch(e) {}
}

async function adminExecSql() {
    const query = document.getElementById("adm-sql-input").value; if(!query) return;
    try {
        const r = await fetch("/api/admin/sql", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ initData: tg?.initData || "", query: query }) });
        const d = await r.json();
        const resBox = document.getElementById("adm-sql-res");
        resBox.style.display = "block"; resBox.innerText = JSON.stringify(d, null, 2);
    } catch(e) {}
}

async function openAdminChat(uid, name) {
    activeAdminChatUser = uid; document.getElementById("view-admin").classList.remove("active");
    setTimeout(() => document.getElementById("view-admin-chat").classList.add("active"), 50);
    
    clearInterval(chatInterval);
    renderedAdminMessagesCount = 0;
    document.getElementById("admin-chat-box").innerHTML = ""; 
    
    const fetchChat = async () => {
        const r = await fetch(`/api/support/messages?initData=${encodeURIComponent(tg?.initData || "")}&target_uid=${uid}`);
        const d = await r.json(); 
        const b = document.getElementById("admin-chat-box");
        
        if (d.messages.length > renderedAdminMessagesCount) {
            for(let i = renderedAdminMessagesCount; i < d.messages.length; i++) {
                let m = d.messages[i];
                let div = document.createElement('div');
                div.className = `msg ${m.sender === 'user' ? 'left' : 'right'}`;
                div.innerHTML = `<div>${m.text}</div>`;
                b.appendChild(div);
            }
            b.scrollTop = b.scrollHeight;
            renderedAdminMessagesCount = d.messages.length;
        }
    };
    fetchChat(); chatInterval = setInterval(fetchChat, 3000);
}

async function sendMsgAdmin() {
    const i = document.getElementById("admin-chat-input"), v = i.value.trim(); if (!v || !activeAdminChatUser) return; i.value = "";
    await fetch("/api/support/send", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ initData: tg?.initData || "", text: v, target_uid: activeAdminChatUser }) });
}

async function closeSupportAdmin(action) {
    if (!activeAdminChatUser) return;
    await fetch("/api/support/close", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ initData: tg?.initData || "", target_uid: activeAdminChatUser, action: action }) });
    showToast("Чат закрыт!"); switchTab('admin');
}

window.onload = initApp;
