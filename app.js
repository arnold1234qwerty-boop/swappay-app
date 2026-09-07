const tg = window.Telegram?.WebApp;

if (tg) {
    tg.expand();
    tg.ready();
    // Фикс для правильного отображения на телефонах
    document.body.style.height = `${tg.viewportStableHeight}px`;
}

let user = { id: 0, role: "user" };
let depMethod = 'crypto';
let activeAdminChatUser = null;
let chatInterval = null;

// Система уведомлений внутри приложения
function showToast(message) {
    const toast = document.getElementById("toast");
    toast.innerText = message;
    toast.classList.add("show");
    if(tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    setTimeout(() => { toast.classList.remove("show"); }, 3000);
}

async function initApp() {
    const t = localStorage.getItem("theme") || "basic";
    document.getElementById("theme-select").value = t;
    
    if (t === "custom") {
        const bg = localStorage.getItem("custom_bg");
        if (bg) document.body.style.backgroundImage = `url(${bg})`;
    } else {
        document.body.removeAttribute("style"); 
        if (tg) document.body.style.height = `${tg.viewportStableHeight}px`;
        document.body.setAttribute("data-theme", t);
    }
    
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
            document.getElementById("ref-link").value = `https://t.me/SwapPay_Bot?start=ref_${user.user_id}`;

            if (user.role === "admin") {
                document.getElementById("role-badge").innerText = "ADMIN";
                document.getElementById("nav-admin").classList.remove("hidden");
            }
        }
    } catch (e) {
        console.error("Auth error:", e);
    }
}

function changeTheme() {
    const t = document.getElementById("theme-select").value;
    if (t === "custom") {
        document.getElementById("custom-bg-input").click();
    } else {
        document.body.style.backgroundImage = "";
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
            document.body.setAttribute("data-theme", "basic"); // Сброс цветов подложки
            document.body.style.backgroundImage = `url(${b64})`;
        };
        reader.readAsDataURL(input.files[0]);
    }
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
        loadUserChat();
        chatInterval = setInterval(loadUserChat, 3000);
    }
    
    if (tab === "admin") {
        document.getElementById("admin-chat-list").innerHTML = 
            `<div class="pill" onclick="openAdminChat(${user.id}, 'Тестовый чат')">💬 Открыть чат поддержки (Тест)</div>`;
    }
}

function openModal(id, ptype = null) {
    document.getElementById(id).classList.add("active");
    
    if (id === 'modal-purchase' && ptype) {
        document.getElementById('pur-type').value = ptype;
        // Очищаем форму перед открытием
        document.getElementById("pur-amt").value = "";
        document.getElementById("pur-desc").value = "";
        document.getElementById("pur-file").value = "";
        document.getElementById("pur-file-label").innerText = "📸 Прикрепить фото (QR/Реквизиты)";
        
        if (ptype === 'usdt') {
            document.getElementById('pur-title').innerText = "Покупка USDT (TRC-20)";
            document.getElementById('pur-desc').placeholder = "Ваш кошелек (начинается с T...)";
            document.getElementById('usdt-rate-box').classList.remove('hidden');
            document.getElementById('usdt-calc-hint').classList.remove('hidden');
            document.getElementById('pur-photo-box').classList.add('hidden'); // USDT фото не нужно
        } else {
            document.getElementById('pur-title').innerText = "Оплата услуги / товара";
            document.getElementById('pur-desc').placeholder = "Ссылка или реквизиты услуги";
            document.getElementById('usdt-rate-box').classList.add('hidden');
            document.getElementById('usdt-calc-hint').classList.add('hidden');
            document.getElementById('pur-photo-box').classList.remove('hidden'); // Показываем загрузку фото
        }
    }
}

function closeModal(id) {
    document.getElementById(id).classList.remove("active");
}

function setDep(el, method) {
    document.querySelectorAll("#modal-deposit .pill").forEach(p => p.classList.remove("active"));
    el.classList.add("active");
    depMethod = method;
    calcDep();
    
    if (method === 'crypto') {
        document.getElementById("dep-file-box").classList.add("hidden");
        document.getElementById("btn-dep-submit").innerText = "Перейти к оплате";
    } else {
        document.getElementById("dep-file-box").classList.remove("hidden");
        document.getElementById("btn-dep-submit").innerText = "Отправить чек";
    }
}

function calcDep() {
    const v = parseFloat(document.getElementById("dep-amt").value) || 0;
    const h = document.getElementById("dep-hint");
    h.innerText = depMethod === 'crypto' ? `К оплате: ${(v * 1.4).toFixed(2)} ₽` 
        : depMethod === 'kaspi' ? `К оплате: ${(v * 8).toFixed(2)} ₸` 
        : `К оплате: ${(v * 0.8).toFixed(2)} ₴`;
}

function calcUsdt() {
    if (document.getElementById('pur-type').value !== 'usdt') return;
    const v = parseFloat(document.getElementById("pur-amt").value) || 0;
    document.getElementById("usdt-calc-hint").innerText = `Получите: ~${(v / 95).toFixed(2)} USDT`;
}

async function depSubmit() {
    const btn = document.getElementById("btn-dep-submit");
    if (btn.disabled) return;
    
    const amt = parseFloat(document.getElementById("dep-amt").value);
    if (!amt || amt < 100) return alert("Минимум 100 ₽");
    
    btn.disabled = true;
    const originalText = btn.innerText;
    btn.innerText = "Обработка...";
    
    try {
        if (depMethod !== 'crypto') {
            const file = document.getElementById("dep-file").files[0];
            if (!file) throw new Error("Файл не выбран");
            
            const fd = new FormData();
            fd.append("initData", tg?.initData || "");
            fd.append("amount_rub", amt);
            fd.append("currency", depMethod === 'kaspi' ? "KZT" : "UAH");
            fd.append("receipt", file);
            
            const r = await fetch("/api/deposit/pdf-receipt", { method: "POST", body: fd });
            if (r.ok) {
                showToast("Чек передан в обработку! Ожидайте начисления.");
                closeModal('modal-deposit');
            }
        } else {
            const r = await fetch("/api/deposit/crypto", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ initData: tg?.initData || "", amount_rub: amt })
            });
            const d = await r.json();
            if (r.ok && d.pay_url) {
                tg?.openTelegramLink ? tg.openTelegramLink(d.pay_url) : window.open(d.pay_url);
                closeModal('modal-deposit');
            }
        }
    } catch (e) {
        alert("Ошибка. Проверьте правильность файла и суммы.");
    } finally {
        btn.disabled = false;
        btn.innerText = originalText;
    }
}

async function submitPurchase() {
    const btn = document.getElementById("btn-pur");
    if (btn.disabled) return;
    
    const ptype = document.getElementById("pur-type").value;
    const amt = parseFloat(document.getElementById("pur-amt").value);
    const desc = document.getElementById("pur-desc").value;
    
    if (!amt || !desc) return alert("Заполните все поля!");
    if (amt < 25) return alert("Минимальная сумма заказа 25 ₽");
    
    btn.disabled = true;
    btn.innerText = "Отправка...";
    
    try {
        const fd = new FormData();
        fd.append("initData", tg?.initData || "");
        fd.append("ptype", ptype);
        fd.append("amount", amt);
        fd.append("details", desc);
        
        // Если прикрепили фото (QR)
        if (ptype === 'service') {
            const fileInput = document.getElementById("pur-file");
            if (fileInput.files.length > 0) {
                fd.append("photo", fileInput.files[0]);
            }
        }

        const r = await fetch("/api/purchase", { method: "POST", body: fd });
        
        if (r.ok) {
            showToast("Заказ успешно отправлен в работу!");
            closeModal('modal-purchase');
            await initApp(); // Мгновенное обновление баланса
        } else {
            alert((await r.json()).detail || "Произошла ошибка");
        }
    } catch (e) {
        alert("Сбой соединения.");
    } finally {
        btn.disabled = false;
        btn.innerText = "Создать заказ";
    }
}

async function activatePromo() {
    const code = document.getElementById("promo-input").value;
    if (!code) return;
    
    try {
        const r = await fetch("/api/promo/activate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ initData: tg?.initData || "", code: code })
        });
        
        const d = await r.json();
        if (r.ok) {
            showToast(`Промокод активирован: +${d.amount} ₽ !`);
            closeModal('modal-promo');
            await initApp();
        } else {
            alert(d.detail || "Ошибка активации");
        }
    } catch (e) {}
}

function copyRef() {
    const link = document.getElementById("ref-link");
    link.select();
    document.execCommand("copy");
    showToast("Реферальная ссылка скопирована!");
}

async function loadUserChat() {
    try {
        const r = await fetch(`/api/support/messages?initData=${encodeURIComponent(tg?.initData || "")}`);
        if (!r.ok) return;
        
        const d = await r.json();
        const b = document.getElementById("user-chat-box");
        
        // Логика закрытого чата: прячем инпут, показываем кнопку возобновления
        if (d.status === 'closed') {
            document.getElementById("sup-status").innerText = "Диалог завершен";
            document.getElementById("user-chat-input-wrap").classList.add("hidden");
            document.getElementById("btn-reopen-chat").classList.remove("hidden");
        } else {
            document.getElementById("sup-status").innerText = "Чат с поддержкой";
            document.getElementById("user-chat-input-wrap").classList.remove("hidden");
            document.getElementById("btn-reopen-chat").classList.add("hidden");
        }
        
        if (b.children.length === d.messages.length) return;
        
        b.innerHTML = "";
        d.messages.forEach(m => {
            b.innerHTML += `<div class="msg ${m.sender === 'user' ? 'right' : 'left'}"><div>${m.text}</div></div>`;
        });
        b.scrollTop = b.scrollHeight;
    } catch (e) {}
}

function reopenChat() {
    // Включаем инпут визуально, бекенд сам сменит статус при отправке нового сообщения
    document.getElementById("user-chat-input-wrap").classList.remove("hidden");
    document.getElementById("btn-reopen-chat").classList.add("hidden");
    document.getElementById("sup-status").innerText = "Новый диалог";
}

async function sendMsgUser() {
    const i = document.getElementById("user-chat-input");
    const v = i.value.trim();
    if (!v) return;
    
    i.value = "";
    await fetch("/api/support/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: tg?.initData || "", text: v })
    });
    
    loadUserChat();
}

async function openAdminChat(uid, name) {
    activeAdminChatUser = uid;
    document.getElementById("view-admin").classList.remove("active");
    setTimeout(() => document.getElementById("view-admin-chat").classList.add("active"), 50);
    
    clearInterval(chatInterval);
    
    const fetchChat = async () => {
        const r = await fetch(`/api/support/messages?initData=${encodeURIComponent(tg?.initData || "")}&target_uid=${uid}`);
        const d = await r.json();
        const b = document.getElementById("admin-chat-box");
        
        if (b.children.length === d.messages.length) return;
        
        b.innerHTML = "";
        d.messages.forEach(m => {
            b.innerHTML += `<div class="msg ${m.sender === 'user' ? 'left' : 'right'}"><div>${m.text}</div></div>`;
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
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: tg?.initData || "", text: v, target_uid: activeAdminChatUser })
    });
}

async function closeSupportAdmin(action) {
    if (!activeAdminChatUser) return;
    
    await fetch("/api/support/close", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: tg?.initData || "", target_uid: activeAdminChatUser, action: action })
    });
    
    alert("Чат закрыт!");
    switchTab('admin');
}

window.onload = initApp;
