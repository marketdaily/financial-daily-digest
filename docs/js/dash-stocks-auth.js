// dashboard.html 內嵌 JS 抽出(dash-stocks-auth.js);7 檔按原始順序載入,順序不可換(全域相依)。2026-07-03 P5。
function search(q, db) {
  if (!q) return [];
  const lq = q.toLowerCase();
  const exact = [], symPre = [], namePre = [], symPart = [], namePart = [];
  const LIMIT = 12;
  for (let i = 0; i < db.length; i++) {
    const s = db[i][0], n = db[i][1];
    const ls = s.toLowerCase(), ln = n.toLowerCase();
    const zh = typeof US_ZH !== "undefined" && US_ZH[s] ? US_ZH[s] : "";
    if (ls === lq) exact.push(db[i]);
    else if (ls.startsWith(lq)) symPre.push(db[i]);
    else if (ln.startsWith(lq) || zh.startsWith(lq)) namePre.push(db[i]);
    else if (ls.includes(lq)) symPart.push(db[i]);
    else if (ln.includes(lq) || zh.includes(lq)) namePart.push(db[i]);
    if (exact.length + symPre.length >= LIMIT) break;
  }
  return [...exact, ...symPre, ...namePre, ...symPart, ...namePart].slice(0, LIMIT);
}

function renderDD(market, results, q) {
  const dd = document.getElementById(`${market}-dropdown`);
  if (!q) { dd.classList.remove("open"); return; }
  if (!results.length) {
    dd.innerHTML = `<div class="dropdown-empty">${T('dd_not_found')(q)}</div>`;
  } else {
    dd.innerHTML = results.map(([sym, name]) => {
      const zh = market === "us" && typeof US_ZH !== "undefined" ? (US_ZH[sym] || "") : "";
      return `<div class="dropdown-item" onclick="addStock('${market}','${sym}','${name.replace(/'/g,"&#39;")}')">
        <span class="d-ticker">${sym}</span><span class="d-name">${zh ? `<b style="color:rgba(255,255,255,0.9)">${zh}</b> ` : ""}${name}</span><span class="d-add">${T('dd_add')}</span>
      </div>`;
    }).join("");
  }
  dd.classList.add("open"); hiIdx[market] = -1;
}

function addStock(market, sym, name) {
  if (selected[market].find(s => s.sym === sym)) return;
  if (userCap !== Infinity && selected.us.length + selected.tw.length >= userCap) {
    updateStats();
    return;
  }
  selected[market].push({ sym, name });
  renderTags(market); updateStats();
  document.getElementById(`${market}-search`).value = "";
  document.getElementById(`${market}-dropdown`).classList.remove("open");
  scheduleSave();
}

function removeStock(market, sym) {
  selected[market] = selected[market].filter(s => s.sym !== sym);
  delete positionsMap[sym];
  renderTags(market); updateStats();
  scheduleSave();
}

// ── 持倉成本(選填):進場價/進場日 → 日報改用持有者框架給建議 ──
let _posEdit = { market: null, sym: null };

function openPosEdit(market, sym) {
  _posEdit = { market, sym };
  const p = positionsMap[sym] || {};
  document.getElementById("pos-title").textContent = `${T('pos_title')} — ${sym}`;
  document.getElementById("pos-price").value = p.entry_price ?? "";
  document.getElementById("pos-date").value = p.entry_date || "";
  document.getElementById("pos-err").style.display = "none";
  document.getElementById("pos-modal").classList.add("open");
  document.getElementById("pos-price").focus();
}

function closePosEdit() {
  document.getElementById("pos-modal").classList.remove("open");
  _posEdit = { market: null, sym: null };
}

function clearPosEdit() {
  const { market, sym } = _posEdit;
  if (sym && positionsMap[sym]) {
    delete positionsMap[sym];
    renderTags(market);
    scheduleSave();
  }
  closePosEdit();
}

function confirmPosEdit() {
  const { market, sym } = _posEdit;
  if (!sym) { closePosEdit(); return; }
  const err = document.getElementById("pos-err");
  const priceRaw = document.getElementById("pos-price").value.trim();
  const date = document.getElementById("pos-date").value;
  const price = Number(priceRaw);
  if (!priceRaw || !Number.isFinite(price) || price <= 0) {
    err.textContent = T('pos_err_price'); err.style.display = "block"; return;
  }
  if (date && date > new Date().toISOString().slice(0, 10)) {
    err.textContent = T('pos_err_date'); err.style.display = "block"; return;
  }
  positionsMap[sym] = { entry_price: price, ...(date ? { entry_date: date } : {}) };
  renderTags(market);
  scheduleSave();
  closePosEdit();
}

// ── 一鍵套組 + 批量貼上 ──
const BUNDLES = {
  us: [
    { id: "mag7",      i18n: "bundle_mag7",       syms: ["AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA"] },
    { id: "ai",        i18n: "bundle_ai",         syms: ["NVDA","AMD","AVGO","TSM","MSFT"] },
    { id: "etf",       i18n: "bundle_etf_us",     syms: ["VOO","QQQ","VTI","SPY"] },
    { id: "dividend",  i18n: "bundle_dividend_us",syms: ["JNJ","KO","PG","XOM","PEP"] },
    { id: "finance",   i18n: "bundle_finance_us", syms: ["JPM","BAC","V","MA","BRK.B"] }
  ],
  tw: [
    { id: "blue",      i18n: "bundle_blue_tw",    syms: ["2330","2317","2454","2308","2412"] },
    { id: "etf",       i18n: "bundle_etf_tw",     syms: ["0050","006208","00878","00919"] },
    { id: "fin",       i18n: "bundle_fin_tw",     syms: ["2882","2891","2885","2884"] },
    { id: "semi",      i18n: "bundle_semi_tw",    syms: ["2330","2454","2303","3711","3034"] }
  ]
};

function renderQuickRow(market) {
  const wrap = document.getElementById(`${market}-quick`);
  if (!wrap) return;
  const bundles = BUNDLES[market] || [];
  const chips = bundles.map(b =>
    `<button type="button" class="bundle-chip" onclick="addBundle('${market}','${b.id}')">${T(b.i18n)}</button>`
  ).join("");
  wrap.innerHTML =
    `<span class="quick-label">${T("quick_label")}</span>` +
    chips +
    `<button type="button" class="bulk-chip" onclick="openBulk('${market}')">${T("bulk_chip")}</button>`;
}

function addBundle(market, bundleId) {
  const bundle = (BUNDLES[market] || []).find(b => b.id === bundleId);
  if (!bundle) return;
  const db = market === "us" ? US_STOCKS : TW_STOCKS;
  let added = 0, dupe = 0, capped = 0;
  for (const sym of bundle.syms) {
    if (selected[market].find(s => s.sym === sym)) { dupe++; continue; }
    if (userCap !== Infinity && selected.us.length + selected.tw.length >= userCap) { capped++; continue; }
    const found = db.find(([s]) => s === sym);
    selected[market].push({ sym, name: found ? found[1] : sym });
    added++;
  }
  renderTags(market); updateStats();
  if (added > 0) scheduleSave();
  if (capped > 0) {
    setSaveStatus("warn", "⚠️ " + T("bundle_capped")(added, capped));
  } else if (added === 0 && dupe > 0) {
    setSaveStatus("", "✓ " + T("bundle_all_have"));
  } else {
    setSaveStatus("saved", T("bundle_added")(added));
  }
}

let bulkMarket = "us";

function openBulk(market) {
  bulkMarket = market;
  const modal = document.getElementById("bulk-modal");
  if (!modal) return;
  document.getElementById("bulk-title").textContent = T(`bulk_title_${market}`);
  document.getElementById("bulk-desc").innerHTML = T(`bulk_desc_${market}`);
  const ta = document.getElementById("bulk-textarea");
  ta.value = "";
  ta.placeholder = T(`bulk_ph_${market}`);
  document.getElementById("bulk-cancel").textContent = T("bulk_cancel");
  document.getElementById("bulk-confirm").textContent = T("bulk_confirm");
  document.getElementById("bulk-result").style.display = "none";
  modal.classList.add("open");
  setTimeout(() => ta.focus(), 50);
}

function closeBulk() {
  const m = document.getElementById("bulk-modal");
  if (m) m.classList.remove("open");
}

function parseBulkInput(text, market) {
  const db = market === "us" ? US_STOCKS : TW_STOCKS;
  const tokens = text.split(/[\s,，、;；|]+/).map(t => t.trim()).filter(Boolean);
  const matches = [], unknown = [];
  const seen = new Set();
  for (const raw of tokens) {
    let found = null;
    const upper = raw.toUpperCase();
    found = db.find(([s]) => s.toUpperCase() === upper);
    if (!found) {
      const lo = raw.toLowerCase();
      found = db.find(([s, n]) => {
        if (n.toLowerCase() === lo) return true;
        if (market === "us" && typeof US_ZH !== "undefined" && US_ZH[s] === raw) return true;
        return false;
      });
    }
    if (!found) {
      const lo = raw.toLowerCase();
      found = db.find(([s, n]) => {
        if (n.toLowerCase().includes(lo)) return true;
        if (market === "us" && typeof US_ZH !== "undefined" && US_ZH[s] && US_ZH[s].includes(raw)) return true;
        return false;
      });
    }
    if (found) {
      if (!seen.has(found[0])) { seen.add(found[0]); matches.push(found); }
    } else {
      unknown.push(raw);
    }
  }
  return { matches, unknown };
}

function confirmBulk() {
  const text = document.getElementById("bulk-textarea").value;
  const { matches, unknown } = parseBulkInput(text, bulkMarket);
  const market = bulkMarket;
  let added = 0, dupe = 0, capped = 0;
  for (const [sym, name] of matches) {
    if (selected[market].find(s => s.sym === sym)) { dupe++; continue; }
    if (userCap !== Infinity && selected.us.length + selected.tw.length >= userCap) { capped++; continue; }
    selected[market].push({ sym, name });
    added++;
  }
  renderTags(market); updateStats();
  if (added > 0) scheduleSave();
  const parts = [];
  if (added > 0) parts.push(`<span class="ok">${T("bulk_added")(added)}</span>`);
  if (dupe > 0) parts.push(T("bulk_dupe")(dupe));
  if (capped > 0) parts.push(`<span class="err">${T("bulk_capped")(capped)}</span>`);
  if (unknown.length > 0) parts.push(`<span class="err">${T("bulk_unknown")(unknown.length)}: ${unknown.slice(0,8).map(u=>`<b>${u}</b>`).join(", ")}${unknown.length>8?"…":""}</span>`);
  if (parts.length === 0) parts.push(T("bulk_nothing"));
  const res = document.getElementById("bulk-result");
  res.innerHTML = parts.join("<br>");
  res.style.display = "";
  if (added > 0 && unknown.length === 0 && capped === 0) {
    setTimeout(closeBulk, 1100);
  }
}

function renderTags(market) {
  const el = document.getElementById(`${market}-tags`);
  if (!selected[market].length) {
    el.innerHTML = `<span class="tags-empty">${market === "us" ? T('us_tags_empty') : T('tw_tags_empty')}</span>`; return;
  }
  el.innerHTML = selected[market].map(({ sym, name }) => {
    const zh = market === "us" && typeof US_ZH !== "undefined" ? (US_ZH[sym] || "") : "";
    const label = zh || name;
    const nameHtml = label && label !== sym ? `<span style="font-weight:400;opacity:0.7;font-size:11px"> ${label}</span>` : "";
    const pos = positionsMap[sym];
    const costHtml = pos && Number(pos.entry_price) > 0
      ? `<span class="tag-cost" onclick="openPosEdit('${market}','${sym}')" title="${T('pos_chip_title')}">@${Number(pos.entry_price)}</span>`
      : `<span class="tag-cost empty" onclick="openPosEdit('${market}','${sym}')" title="${T('pos_chip_title')}">${T('pos_chip_add')}</span>`;
    return `<div class="tag">${sym}${nameHtml} ${costHtml}<span class="tag-x" onclick="removeStock('${market}','${sym}')">×</span></div>`;
  }).join("");
}

function updateStats() {
  const us = selected.us, tw = selected.tw;
  document.getElementById("stat-us").textContent = T('unit_count')(us.length);
  document.getElementById("stat-tw").textContent = T('unit_count')(tw.length);
  const statNm = (s, isUS) => {
    const zh = isUS && typeof US_ZH !== "undefined" ? (US_ZH[s.sym] || "") : "";
    return zh || s.name || s.sym;
  };
  document.getElementById("stat-us-list").textContent = us.length ? us.slice(0,3).map(s=>statNm(s,true)).join(" · ") + (us.length > 3 ? " …" : "") : T('not_set');
  document.getElementById("stat-tw-list").textContent = tw.length ? tw.slice(0,2).map(s=>statNm(s,false)).join(" · ") + (tw.length > 2 ? " …" : "") : T('not_set');

  const n = us.length + tw.length;
  const atCap = userCap !== Infinity && n >= userCap;
  const countEl = document.getElementById("cap-count");
  if (countEl) {
    countEl.textContent = userCap === Infinity ? T('cap_count_unlimited')(n) : T('cap_count_capped')(n, userCap);
    countEl.classList.toggle("full", atCap);
  }
  ["us", "tw"].forEach(m => {
    const inp = document.getElementById(`${m}-search`);
    if (inp) {
      inp.disabled = atCap;
      inp.placeholder = atCap
        ? T('search_ph_full')(userCap)
        : (m === "us" ? T('search_ph_us') : T('search_ph_tw'));
    }
  });
}

["us","tw"].forEach(market => {
  const input = document.getElementById(`${market}-search`);
  input.addEventListener("input", () => {
    const db = market === "us" ? US_STOCKS : TW_STOCKS;
    renderDD(market, search(input.value.trim(), db), input.value.trim());
  });
  input.addEventListener("keydown", e => {
    const dd = document.getElementById(`${market}-dropdown`);
    const items = dd.querySelectorAll(".dropdown-item");
    if (e.key === "ArrowDown") { e.preventDefault(); hiIdx[market] = Math.min(hiIdx[market]+1, items.length-1); items.forEach((el,i) => el.classList.toggle("hi", i===hiIdx[market])); }
    else if (e.key === "ArrowUp") { e.preventDefault(); hiIdx[market] = Math.max(hiIdx[market]-1, 0); items.forEach((el,i) => el.classList.toggle("hi", i===hiIdx[market])); }
    else if (e.key === "Enter") { e.preventDefault(); if (hiIdx[market] >= 0 && items[hiIdx[market]]) items[hiIdx[market]].click(); else if (input.value.trim()) { const sym = input.value.trim().toUpperCase(); addStock(market, sym, sym); } }
    else if (e.key === "Escape") dd.classList.remove("open");
  });
  document.addEventListener("click", e => { if (!input.closest(".search-wrap").contains(e.target)) document.getElementById(`${market}-dropdown`).classList.remove("open"); });
});

let _pendingEmail = "";

async function doLogin() {
  const email = document.getElementById("login-email").value.trim().toLowerCase();
  const password = document.getElementById("login-password").value;
  const errEl = document.getElementById("login-err");
  const btn = document.getElementById("login-btn");
  errEl.style.display = "none";
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { errEl.textContent = T('err_invalid_email'); errEl.style.display = "block"; return; }
  btn.disabled = true; btn.textContent = T('btn_verifying');
  try {
    const res = await fetch(WORKER_URL + "/check-subscriber", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!data.subscribed && !data.needsPasswordSetup) { errEl.textContent = T('err_no_record'); errEl.style.display = "block"; return; }
    if (data.error === "wrong_password") { errEl.textContent = T('err_wrong_pwd'); errEl.style.display = "block"; return; }
    if (data.needsPasswordEntry) { errEl.textContent = T('err_need_pwd'); errEl.style.display = "block"; return; }
    if (data.needsPasswordSetup) { _pendingEmail = email; document.getElementById("login-form").style.display = "none"; document.getElementById("set-password-form").style.display = "block"; return; }
    if (document.getElementById("remember-me").checked) { localStorage.setItem("md-saved-email", email); localStorage.setItem("md-saved-pwd", password); }
    else { localStorage.removeItem("md-saved-email"); localStorage.removeItem("md-saved-pwd"); }
    localStorage.setItem("md-email", email); localStorage.setItem("md-plan", data.plan || "free");
    sessionStorage.setItem("md-pwd", password);
    showDashboard(email, data.plan || "free");
  } catch { errEl.textContent = T('err_network'); errEl.style.display = "block"; }
  finally { btn.disabled = false; btn.textContent = T('login_btn'); }
}

async function doSetPassword() {
  const password = document.getElementById("new-password").value;
  const confirm = document.getElementById("confirm-password").value;
  const errEl = document.getElementById("set-pwd-err"); const btn = document.getElementById("set-pwd-btn");
  errEl.style.display = "none";
  if (password.length < 6) { errEl.textContent = T('err_pwd_min6'); errEl.style.display = "block"; return; }
  if (password !== confirm) { errEl.textContent = T('err_pwd_mismatch'); errEl.style.display = "block"; return; }
  btn.disabled = true; btn.textContent = T('btn_setting');
  try {
    const res = await fetch(WORKER_URL + "/set-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: _pendingEmail, password }) });
    const data = await res.json();
    if (!data.ok) { errEl.textContent = T('err_set_failed'); errEl.style.display = "block"; return; }
    if (document.getElementById("remember-me") && document.getElementById("remember-me").checked) { localStorage.setItem("md-saved-email", _pendingEmail); localStorage.setItem("md-saved-pwd", password); }
    localStorage.setItem("md-email", _pendingEmail); localStorage.setItem("md-plan", data.plan || "free");
    sessionStorage.setItem("md-pwd", password);
    showDashboard(_pendingEmail, data.plan || "free");
  } catch { errEl.textContent = T('err_network'); errEl.style.display = "block"; }
  finally { btn.disabled = false; btn.textContent = T('setpwd_btn'); }
}

function showLoginForm() {
  document.getElementById("login-form").style.display = "block";
  document.getElementById("set-password-form").style.display = "none";
  document.getElementById("set-pwd-err").style.display = "none";
}

function doLogout() {
  if (_quotesRefreshTimer) { clearInterval(_quotesRefreshTimer); _quotesRefreshTimer = null; }
  if (_countdownTimer) { clearInterval(_countdownTimer); _countdownTimer = null; }
  const wrap = document.getElementById("sync-countdown"); if (wrap) wrap.style.display = "none";
  localStorage.removeItem("md-email"); localStorage.removeItem("md-plan");
  sessionStorage.removeItem("md-pwd");
  document.getElementById("dashboard").style.display = "none";
  document.getElementById("login-screen").style.display = "flex";
  document.getElementById("login-form").style.display = "block";
  document.getElementById("set-password-form").style.display = "none";
  const savedEmail = localStorage.getItem("md-saved-email") || "";
  const savedPwd = localStorage.getItem("md-saved-pwd") || "";
  document.getElementById("login-email").value = savedEmail;
  document.getElementById("login-password").value = savedPwd;
  document.getElementById("remember-me").checked = !!savedEmail;
}

async function showDashboard(email, plan) {
  if (window.mdIdentify) window.mdIdentify(email);
  if (window.mdTrack) window.mdTrack("login_success", { plan: plan || "free" });
  document.getElementById("login-screen").style.display = "none";
  document.getElementById("dashboard").style.display = "block";
  if (typeof renderQuickRow === 'function') { renderQuickRow('us'); renderQuickRow('tw'); }
  setTimeout(function () { if (window.mdStockTour) window.mdStockTour(); }, 700);
  // 從 preferences.html redirect 過來時自動 scroll 到股票卡(支援 #stocks 或 ?focus=stocks)
  const want = location.hash === "#stocks" || new URLSearchParams(location.search).get("focus") === "stocks";
  if (want) {
    setTimeout(function () {
      const el = document.getElementById("stocks");
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 400);
  }
  const name = email.split("@")[0];
  document.getElementById("hero-name").textContent = T('hero_name_greeting')(name);
  document.getElementById("nav-email").textContent = email;
  const planBadge = document.getElementById("plan-badge");
  if (planBadge) {
    planBadge.textContent = plan === "admin" ? T('hdr_plan_admin') : plan === "free" ? T('hdr_plan_free') : T('hdr_plan_paid');
    planBadge.classList.toggle("admin", plan === "admin");
    planBadge.style.display = "inline-flex";
  }
  if (plan === "admin") {
    document.getElementById("admin-panel").style.display = "block";
    loadAdminStats();
  }
  setupPushCard(email, plan);
  setupAlertsFeed(email, plan);
  setupChatCard(email, plan);
  await loadPreferences(email);
  loadReferral(email);
  loadStories(email);
  loadMarketOverview();
}

// ── 自有 Web Push 即時推播(免費無上限,不經 LINE)──
const VAPID_PUBLIC_KEY = "BIP9LicS6GBRTJ0hwW6iihX6L5o41zY46xhoZ8c7PLIbWfUM3Gtb05BNN_Pn8k7zrd-w9LieG3WCnzbrAEn8uQ8";
function urlB64ToUint8Array(b64) {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const base64 = (b64 + pad).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}
function pushSupported() {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}
