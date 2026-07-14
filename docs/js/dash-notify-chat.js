// dashboard.html 內嵌 JS 抽出(dash-notify-chat.js);7 檔按原始順序載入,順序不可換(全域相依)。2026-07-03 P5。
async function setupPushCard(email, plan) {
  // 合規結構:即時推播(含個股操作傾向)對全體用戶開放,不得付費限定。
  const card = document.getElementById("push-alert-card");
  if (!card) return;
  card.style.display = "block";
  // iOS Safari:僅在「已加入主畫面(standalone)」時支援 web push
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const standalone = window.navigator.standalone === true || window.matchMedia("(display-mode: standalone)").matches;
  if (isIOS && !standalone) {
    // 還沒加入主畫面 → 啟用鈕沒作用,改顯示一鍵圖解引導
    document.getElementById("push-enable-btn").style.display = "none";
    document.getElementById("push-ios-box").style.display = "block";
    document.getElementById("push-unbound-box").style.display = "block";
    return;
  }
  if (!pushSupported()) {
    document.getElementById("push-enable-btn").disabled = true;
    document.getElementById("push-enable-btn").textContent = T('push_unsupported');
    document.getElementById("push-unbound-box").style.display = "block";
    return;
  }
  let subscribed = false;
  try {
    const reg = await navigator.serviceWorker.getRegistration();
    if (reg) { const s = await reg.pushManager.getSubscription(); subscribed = !!s; }
  } catch {}
  document.getElementById("push-bound-box").style.display = subscribed ? "block" : "none";
  document.getElementById("push-unbound-box").style.display = subscribed ? "none" : "block";
}
async function enablePush() {
  const email = localStorage.getItem("md-email");
  const password = sessionStorage.getItem("md-pwd") || localStorage.getItem("md-saved-pwd") || "";
  const errEl = document.getElementById("push-err");
  const btn = document.getElementById("push-enable-btn");
  errEl.style.display = "none";
  if (!pushSupported()) { errEl.textContent = T('push_unsupported'); errEl.style.display = "block"; return; }
  btn.disabled = true; btn.textContent = T('push_enabling');
  try {
    const perm = await Notification.requestPermission();
    if (perm !== "granted") { throw new Error(T('push_err_denied')); }
    const reg = await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlB64ToUint8Array(VAPID_PUBLIC_KEY),
      });
    }
    const res = await fetch(`${WORKER_URL}/push/subscribe`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, subscription: sub.toJSON() }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error === "auth" ? T('push_err_auth') : T('push_err_save'));
    document.getElementById("push-bound-box").style.display = "block";
    document.getElementById("push-unbound-box").style.display = "none";
  } catch (e) {
    errEl.textContent = e.message || T('push_err_generic'); errEl.style.display = "block";
  } finally {
    btn.disabled = false; btn.textContent = T('push_enable_btn');
  }
}
// ── iOS 加入主畫面圖解引導 ──
function isInAppBrowser() {
  return /Line\/|FBAN|FBAV|Instagram|Messenger|MicroMessenger/i.test(navigator.userAgent);
}
function openIosGuide() {
  const inapp = isInAppBrowser();
  document.getElementById("ios-guide-inapp").style.display = inapp ? "block" : "none";
  document.getElementById("ios-guide-steps").style.display = inapp ? "none" : "flex";
  // 分享鈕跳動箭頭:只有 iPhone Safari 的分享鈕在正下方(iPad 在右上)
  const isIphone = /iphone|ipod/i.test(navigator.userAgent);
  document.getElementById("ios-guide-arrow").style.display = (!inapp && isIphone) ? "block" : "none";
  document.getElementById("ios-guide-overlay").style.display = "block";
  document.body.style.overflow = "hidden";
}
function closeIosGuide() {
  document.getElementById("ios-guide-overlay").style.display = "none";
  document.body.style.overflow = "";
}
async function copyGuideLink() {
  const url = "https://marketdaily.ai/dashboard.html";
  const btn = document.getElementById("ios-guide-copy-btn");
  try {
    await navigator.clipboard.writeText(url);
  } catch {
    const tmp = document.createElement("input");
    tmp.value = url; document.body.appendChild(tmp);
    tmp.select(); document.execCommand("copy"); tmp.remove();
  }
  btn.textContent = T('ios_guide_copied');
}
// ── 即時提醒紀錄 feed ──
let _alertsLoaded = false;
function timeAgo(ts) {
  const d = new Date(ts); const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return T('time_just_now');
  if (s < 3600) return T('time_min_ago')(Math.floor(s / 60));
  if (s < 86400) return T('time_hr_ago')(Math.floor(s / 3600));
  if (s < 86400 * 7) return T('time_day_ago')(Math.floor(s / 86400));
  return d.toLocaleDateString(currentLang === "en" ? "en-US" : "zh-TW", { month: "numeric", day: "numeric" });
}
function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
async function setupAlertsFeed(email, plan) {
  const card = document.getElementById("alerts-feed-card");
  if (!card) return;
  card.style.display = "block";
  await loadAlertHistory();
  // 從推播點進來 → #alert-<id> 捲到那一則、#alerts 捲到列表頂
  handleAlertHash();
}

// 推播 url 錨點分派:#alert-<id>=那一則、#alerts=列表頂端
function handleAlertHash() {
  const h = location.hash || "";
  if (h.indexOf("#alert-") === 0) scrollToAlertItem(h.slice(7));
  else if (h === "#alerts") scrollToAlerts();
}

// 捲到「被點的那一則」提醒並高亮;找不到(太舊被裁掉)→ 退回捲到列表頂
function scrollToAlertItem(id) {
  const card = document.getElementById("alerts-feed-card");
  if (!card || card.style.display === "none" || !id) return;
  const safe = (window.CSS && CSS.escape) ? CSS.escape(id) : id;
  const el = document.querySelector('#alerts-feed-list .alert-item[data-alert-id="' + safe + '"]');
  if (!el) { scrollToAlerts(); return; }
  let tries = 0;
  const tick = () => {
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    if (++tries < 5) setTimeout(tick, 420);
  };
  tick();
  const prevBg = el.style.background;
  el.style.transition = "box-shadow .4s, background .4s";
  el.style.boxShadow = "0 0 0 2px rgba(255,176,0,.75)";
  el.style.background = "rgba(255,176,0,.10)";
  setTimeout(() => { el.style.boxShadow = ""; el.style.background = prevBg; }, 2600);
}

// 可靠捲到提醒紀錄:其他卡片(股票/大盤)非同步載入會改變高度,
// 故連續校正多次,蓋過版面跳動;並高亮一下讓人知道「到了」。
function scrollToAlerts() {
  const card = document.getElementById("alerts-feed-card");
  if (!card || card.style.display === "none") return;
  let tries = 0;
  const tick = () => {
    card.scrollIntoView({ behavior: "smooth", block: "start" });
    if (++tries < 5) setTimeout(tick, 420);
  };
  tick();
  card.style.transition = "box-shadow .4s";
  card.style.boxShadow = "0 0 0 2px rgba(255,176,0,.65)";
  setTimeout(() => { card.style.boxShadow = ""; }, 2200);
}

// App/分頁已開著時點通知:只有 hash 變,init 不會重跑 → 監聽 hashchange 補捲
window.addEventListener("hashchange", () => {
  const h = location.hash || "";
  if (h === "#alerts" || h.indexOf("#alert-") === 0) { loadAlertHistory(true).then(handleAlertHash); }
});
async function loadAlertHistory(force) {
  if (_alertsLoaded && !force) return;
  const listEl = document.getElementById("alerts-feed-list");
  const loadingEl = document.getElementById("alerts-feed-loading");
  const emptyEl = document.getElementById("alerts-feed-empty");
  const email = localStorage.getItem("md-email");
  const password = sessionStorage.getItem("md-pwd") || localStorage.getItem("md-saved-pwd") || "";
  if (!email) return;
  if (loadingEl) loadingEl.style.display = "block";
  if (emptyEl) emptyEl.style.display = "none";
  try {
    const res = await fetch(`${WORKER_URL}/alerts/list`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    _alertsLoaded = true;
    // 清掉舊卡(保留 loading/empty 兩個固定節點)
    [...listEl.querySelectorAll(".alert-item")].forEach((n) => n.remove());
    if (loadingEl) loadingEl.style.display = "none";
    const alerts = (data && data.alerts) || [];
    if (!alerts.length) { if (emptyEl) emptyEl.style.display = "block"; return; }
    for (const a of alerts) {
      const sev = a.severity >= 9 ? "#f87171" : (a.kind === "political" ? "#4AF626" : (a.kind === "supply_chain" ? "#4ade80" : "#FFB000"));
      const icon = a.kind === "political" ? "🏛️" : (a.kind === "supply_chain" ? "🔗" : (a.severity >= 9 ? "🚨" : "📈"));
      const item = document.createElement("div");
      item.className = "alert-item";
      if (a.id) item.dataset.alertId = a.id;  // 供推播深連結(#alert-<id>)捲到這則
      item.style.cssText = "padding:13px 15px;background:rgba(255,255,255,0.03);border:1px solid var(--input-border);border-left:3px solid " + sev + ";border-radius:12px;scroll-margin-top:80px;";
      item.innerHTML =
        '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px;">' +
          '<span style="font-size:13px;font-weight:800;color:#fff;">' + icon + " " + escapeHtml(a.name || a.ticker || T('alert_default_label')) + (a.speculative ? ' <span style="font-size:11px;color:var(--text2);font-weight:600;">' + T('alert_speculative_tag') + '</span>' : "") + '</span>' +
          '<span style="font-size:11px;color:var(--text2);white-space:nowrap;">' + timeAgo(a.ts) + '</span>' +
        '</div>' +
        '<div style="font-size:13px;color:rgba(255,255,255,0.92);line-height:1.5;margin-bottom:' + (a.reason || a.stance || a.action ? "10px" : "0") + ';font-weight:600;">' + escapeHtml(a.title) + '</div>' +
        (a.reason ? '<div style="font-size:12px;line-height:1.6;margin-bottom:6px;"><span style="font-weight:800;color:#4AF626;">' + T('alert_why_heading') + '</span><br><span style="color:var(--text2);">' + escapeHtml(a.reason) + '</span></div>' : "") +
        ((a.stance || a.action) ? '<div style="font-size:12px;line-height:1.6;"><span style="font-weight:800;color:#FFC74D;">' + T('alert_position_heading') + '</span><br><span style="color:#FFD98A;">' + escapeHtml([a.stance, a.action].filter(Boolean).join(" — ")) + '</span></div>' : "") +
        (a.url && a.url.indexOf("dashboard.html") === -1 ? '<a href="' + escapeHtml(a.url) + '" target="_blank" rel="noopener" style="display:inline-block;margin-top:10px;font-size:12px;color:#FFC74D;font-weight:700;text-decoration:none;">' + T('alert_source_link') + '</a>' : "");
      listEl.appendChild(item);
    }
  } catch (e) {
    if (loadingEl) loadingEl.style.display = "none";
    if (emptyEl) { emptyEl.textContent = T('alerts_load_failed'); emptyEl.style.display = "block"; }
  }
}

async function disablePush() {
  const email = localStorage.getItem("md-email");
  const password = sessionStorage.getItem("md-pwd") || localStorage.getItem("md-saved-pwd") || "";
  const btn = document.getElementById("push-disable-btn");
  btn.disabled = true; btn.textContent = T('push_disabling');
  try {
    let endpoint = null;
    const reg = await navigator.serviceWorker.getRegistration();
    if (reg) { const s = await reg.pushManager.getSubscription(); if (s) { endpoint = s.endpoint; await s.unsubscribe(); } }
    await fetch(`${WORKER_URL}/push/unsubscribe`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, endpoint }),
    });
    document.getElementById("push-bound-box").style.display = "none";
    document.getElementById("push-unbound-box").style.display = "block";
  } catch {} finally {
    btn.disabled = false; btn.textContent = T('push_disable_btn');
  }
}

// ── AI 投資助手 ──
let _chatHistory = [], _chatRemaining = 30, _chatBusy = false, _chatErr = "";

async function setupChatCard(email, plan) {
  // 合規結構:AI 投資助手對全體登入用戶開放(每日 30 則一體適用),不得付費限定。
  const fab = document.getElementById("chat-fab");
  if (!fab) return;
  fab.style.display = "flex";
  let remaining = 30;
  // POST + password 取個人剩餘額度(worker 不洩漏 plan 給未授權 caller)
  const pwd = sessionStorage.getItem("md-pwd") || localStorage.getItem("md-saved-pwd") || "";
  try {
    const res = await fetch(`${WORKER_URL}/chat-status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password: pwd }),
    });
    if (res.ok) { const d = await res.json(); if (typeof d.remaining === "number" && pwd) remaining = d.remaining; }
  } catch {}
  document.getElementById("chat-box").style.display = "flex";
  const locked = document.getElementById("chat-locked-box");
  if (locked) locked.style.display = "none";
  _chatRemaining = remaining;
  renderChat();
}

// AI 助手浮動彈窗開關
function toggleChatPopup(force) {
  const popup = document.getElementById("chat-popup");
  const fab = document.getElementById("chat-fab");
  if (!popup) return;
  const open = (force === undefined) ? !popup.classList.contains("open") : force;
  popup.classList.toggle("open", open);
  if (fab) fab.textContent = open ? "✕" : "💬";
  if (open) {
    renderChat();
    setTimeout(() => { const i = document.getElementById("chat-input"); if (i) i.focus(); }, 120);
  }
}

function chatEsc(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : s; return d.innerHTML; }

// 把持股整理成「代號 公司名」字串給 AI —— 台股才不會只剩數字。
function holdingsText() {
  if (typeof selected === "undefined") return "";
  const fmt = (arr, isUS) => (arr || []).map(s => {
    const zh = isUS && typeof US_ZH !== "undefined" ? (US_ZH[s.sym] || "") : "";
    const nm = zh || s.name || "";
    return (nm && nm !== s.sym) ? `${s.sym} ${nm}` : s.sym;
  });
  const parts = [];
  const us = fmt(selected.us, true), tw = fmt(selected.tw, false);
  if (us.length) parts.push("美股:" + us.join("、"));
  if (tw.length) parts.push("台股:" + tw.join("、"));
  return parts.join(";");
}

function renderChat() {
  const box = document.getElementById("chat-messages");
  if (!box) return;
  let html = _chatHistory.length
    ? _chatHistory.map(m => `<div class="chat-msg ${m.role === "user" ? "user" : "ai"}">${chatEsc(m.content)}</div>`).join("")
    : `<div class="chat-msg ai">${chatEsc(T('chat_greeting'))}</div>`;
  if (_chatBusy) html += `<div class="chat-msg ai thinking">${chatEsc(T('chat_thinking'))}</div>`;
  if (_chatErr) html += `<div class="chat-msg err">${chatEsc(_chatErr)}</div>`;
  box.innerHTML = html;
  box.scrollTop = box.scrollHeight;
  const meta = document.getElementById("chat-meta");
  if (meta) meta.textContent = T('chat_remaining_pre') + _chatRemaining;
}

async function sendChat() {
  if (_chatBusy) return;
  const input = document.getElementById("chat-input");
  const text = (input.value || "").trim();
  if (!text) return;
  const email = localStorage.getItem("md-email");
  if (!email) return;
  let password = sessionStorage.getItem("md-pwd") || localStorage.getItem("md-saved-pwd");
  if (!password) { password = prompt(T('chat_prompt_pwd')); if (!password) return; }
  _chatErr = "";
  _chatHistory.push({ role: "user", content: text });
  input.value = ""; input.style.height = "auto";
  _chatBusy = true; renderChat();
  const sendBtn = document.getElementById("chat-send");
  if (sendBtn) sendBtn.disabled = true;
  try {
    const res = await fetch(WORKER_URL + "/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, messages: _chatHistory, holdings: holdingsText() }),
    });
    const data = await res.json();
    _chatBusy = false;
    if (data.reply) {
      _chatHistory.push({ role: "assistant", content: data.reply });
      if (typeof data.remaining === "number") _chatRemaining = data.remaining;
    } else {
      _chatHistory.pop();
      input.value = text;
      _chatErr = data.error === "daily_limit" ? T('chat_err_limit')
        : data.error === "auth" ? T('chat_err_auth')
        : data.error === "not_premium" ? T('chat_err_premium')
        : T('chat_err_generic');
    }
  } catch {
    _chatBusy = false;
    _chatHistory.pop();
    input.value = text;
    _chatErr = T('chat_err_generic');
  }
  if (sendBtn) sendBtn.disabled = false;
  renderChat();
  input.focus();
}

// 直接沿用登入時的密碼,不再請用戶重輸;只有取不到(換頁/未登入)才補問。
// Styled password modal — replaces ugly native prompt() for sensitive ops
function askPassword(opts = {}) {
  return new Promise(resolve => {
    const modal = document.getElementById("pwd-modal");
    const input = document.getElementById("pwd-modal-input");
    const err = document.getElementById("pwd-modal-err");
    const title = document.getElementById("pwd-modal-title");
    const desc = document.getElementById("pwd-modal-desc");
    const okBtn = document.getElementById("pwd-modal-ok");
    const cancelBtn = document.getElementById("pwd-modal-cancel");
    title.textContent = opts.title || "確認你的身份";
    desc.textContent = opts.desc || "為了保護你的 LINE 不被別人綁走,需要再輸入一次密碼。";
    if (opts.errorText) { err.textContent = opts.errorText; err.style.display = "block"; }
    else { err.style.display = "none"; }
    input.value = "";
    modal.style.display = "flex";
    setTimeout(() => input.focus(), 40);
    const done = (pwd) => {
      modal.style.display = "none";
      okBtn.onclick = null; cancelBtn.onclick = null; input.onkeydown = null;
      resolve(pwd);
    };
    okBtn.onclick = () => done(input.value || null);
    cancelBtn.onclick = () => done(null);
    input.onkeydown = (e) => { if (e.key === "Enter") done(input.value || null); else if (e.key === "Escape") done(null); };
  });
}

async function loadAdminStats() {
  try {
    const email = localStorage.getItem("md-email");
    const password = sessionStorage.getItem("md-pwd") || localStorage.getItem("md-saved-pwd") || "";
    const res = await fetch(WORKER_URL + "/admin-stats", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password })
    });
    if (!res.ok) return;
    const data = await res.json();
    const total = data.totalSubscribers ?? data.total ?? 0;
    document.getElementById("admin-total").textContent = Number.isFinite(total) ? total : "—";
  } catch {}
}

// session 無可用密碼導致 get-preferences 驗證失敗時,送回登入頁重新輸入(保留 md-email/md-plan,不清身份)。
// 不動 set-password/login/retry 既有流程,只重用既有登入畫面。
function requireReauth(email) {
  const dash = document.getElementById("dashboard");
  const ls = document.getElementById("login-screen");
  if (dash) dash.style.display = "none";
  if (ls) ls.style.display = "flex";
  const lf = document.getElementById("login-form"); if (lf) lf.style.display = "block";
  const sf = document.getElementById("set-password-form"); if (sf) sf.style.display = "none";
  const ei = document.getElementById("login-email"); if (ei) ei.value = email;
  const pi = document.getElementById("login-password"); if (pi) { pi.value = ""; setTimeout(() => pi.focus(), 60); }
  const err = document.getElementById("login-err");
  if (err) { err.textContent = (currentLang === "en") ? "Session expired — please re-enter your password." : "登入逾時,請重新輸入密碼"; err.style.display = "block"; }
}

