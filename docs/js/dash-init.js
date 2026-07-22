// dashboard.html 內嵌 JS 抽出(dash-init.js);7 檔按原始順序載入,順序不可換(全域相依)。2026-07-03 P5。
async function doChangePassword() {
  const email = localStorage.getItem("md-email");
  const oldPwd = document.getElementById("cpwd-old").value;
  const newPwd = document.getElementById("cpwd-new").value;
  const confirmPwd = document.getElementById("cpwd-confirm").value;
  const errEl = document.getElementById("cpwd-err");
  const okEl = document.getElementById("cpwd-ok");
  const btn = document.getElementById("cpwd-btn");
  errEl.style.display = "none"; okEl.style.display = "none";
  if (!oldPwd) { errEl.textContent = T('err_enter_old_pwd'); errEl.style.display = "block"; return; }
  if (newPwd.length < 6) { errEl.textContent = T('err_new_pwd_min6'); errEl.style.display = "block"; return; }
  if (newPwd !== confirmPwd) { errEl.textContent = T('err_pwd_mismatch'); errEl.style.display = "block"; return; }
  btn.disabled = true; btn.textContent = T('btn_processing');
  try {
    const res = await fetch(WORKER_URL + "/change-password", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, old_password: oldPwd, new_password: newPwd })
    });
    const data = await res.json();
    if (data.ok) {
      okEl.style.display = "block";
      if (localStorage.getItem("md-saved-pwd")) localStorage.setItem("md-saved-pwd", newPwd);
      document.getElementById("cpwd-old").value = "";
      document.getElementById("cpwd-new").value = "";
      document.getElementById("cpwd-confirm").value = "";
      setTimeout(() => { toggleChangePwd(); okEl.style.display = "none"; }, 3000);
    } else if (data.error === "wrong_password") {
      errEl.textContent = T('err_old_pwd_wrong'); errEl.style.display = "block";
    } else {
      errEl.textContent = T('err_change_failed'); errEl.style.display = "block";
    }
  } catch { errEl.textContent = T('err_network'); errEl.style.display = "block"; }
  finally { btn.disabled = false; btn.textContent = T('cpwd_submit'); }
}

// ── 自動儲存:選股 / 移除後即時存檔,不需手動按鈕 ──
let _saveTimer = null, _lastSaved = null;

function setSaveStatus(state, text) {
  const el = document.getElementById("save-status");
  if (!el) return;
  el.className = "save-status" + (state ? " " + state : "");
  el.textContent = text;
}

function curPayload() {
  const email = localStorage.getItem("md-email") || "";
  // 帶 password 給 /save-preferences (worker 需驗證,否則任何人能改別人偏好)
  const password = sessionStorage.getItem("md-pwd") || localStorage.getItem("md-saved-pwd") || "";
  return JSON.stringify({ email, password, us_stocks: selected.us.map(s=>s.sym), tw_stocks: selected.tw.map(s=>s.sym), digest_depth: selectedDepth, positions: positionsMap });
}

// 日報深度卡(全體用戶可選;合規結構 COMPLIANCE_STRUCTURE.md:個股分析內容不得依付費分級)
function setupDepthCard() {
  const card = document.getElementById("digest-depth-card");
  if (!card) return;
  card.style.display = "block";
  const lock = document.getElementById("depth-lock");
  if (lock) lock.style.display = "none";
  document.getElementById("depth-opts").classList.remove("locked");
  renderDepth();
}

function renderDepth() {
  document.querySelectorAll("#depth-opts .depth-opt").forEach(b => {
    b.classList.toggle("active", b.dataset.depth === selectedDepth);
  });
}

function selectDepth(d) {
  if (selectedDepth === d) return;
  selectedDepth = d;
  renderDepth();
  scheduleSave();
}

// 去抖動:連續選股只在停手 0.65 秒後送一次。
function scheduleSave() {
  clearTimeout(_saveTimer);
  setSaveStatus("", T('save_pending'));
  _saveTimer = setTimeout(doAutoSave, 650);
}

async function doAutoSave() {
  clearTimeout(_saveTimer);
  const email = localStorage.getItem("md-email");
  if (!email) return;
  const payload = curPayload();
  if (payload === _lastSaved) { setSaveStatus("saved", T('save_saved_short')); return; }
  setSaveStatus("saving", T('save_saving'));
  try {
    const res = await fetch(WORKER_URL + "/save-preferences", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: payload,
    });
    const data = await res.json();
    if (data.ok) {
      _lastSaved = payload;
      if (data.dropped > 0) {
        setSaveStatus("error", currentLang === 'zh'
          ? `⚠️ 最多可追蹤 ${data.cap} 檔,超過的 ${data.dropped} 檔未儲存`
          : `⚠️ You can track up to ${data.cap} stocks — ${data.dropped} not saved`);
      } else {
        setSaveStatus("saved", T('save_saved_long'));
      }
    } else {
      setSaveStatus("error", T('save_failed'));
    }
  } catch {
    setSaveStatus("error", T('save_net_err'));
  }
}

let _refCode = "";
let _refLink = "";

async function loadReferral(email) {
  try {
    const pwd = sessionStorage.getItem("md-pwd") || localStorage.getItem("md-saved-pwd") || "";
    const res = await fetch(WORKER_URL + "/referral-stats", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password: pwd })
    });
    if (!res.ok) return;
    const data = await res.json();
    _refCode = data.code || "";
    _refLink = data.link || `https://marketdaily.ai/?ref=${_refCode}&utm_source=referral&utm_medium=user&utm_campaign=share`;
    const setTxt = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
    setTxt("ref-link-display", _refLink);
    setTxt("ref-clicks", data.clicks ?? 0);
    setTxt("ref-signups", data.total_referrals ?? 0);
    setTxt("ref-rewards", data.total_bonus_days ?? 0);
    renderRecentReferrals(data.recent_referrals || []);
    renderBonusBadge(data.total_bonus_days || 0);
  } catch {}
}

function renderRecentReferrals(list) {
  const host = document.getElementById("ref-recent-list");
  if (!host) return;
  if (!list.length) {
    host.innerHTML = `<div style="font-size:12px;color:var(--text2);padding:8px 0;">${T('ref_recent_empty')}</div>`;
    return;
  }
  host.innerHTML = list.map(r => {
    const d = r.ts ? new Date(r.ts).toLocaleDateString() : "";
    return `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px dashed var(--border);font-size:13px;color:var(--text);"><span>${r.email}</span><span style="color:var(--text2);font-size:12px;">${d}</span></div>`;
  }).join("");
}

function renderBonusBadge(days) {
  const host = document.getElementById("ref-bonus-badge");
  if (!host) return;
  if (!days) { host.style.display = "none"; return; }
  host.style.display = "block";
  host.innerHTML = T('ref_bonus_badge').replace("{days}", days);
}

function shareText() {
  return (T('share_msg_template') || "我在用 MarketDaily,每天 7 點 AI 財經日報,現在限時免費:{link}").replace("{link}", _refLink);
}

function copyRefLink() {
  if (!_refLink) return;
  navigator.clipboard.writeText(_refLink).then(() => {
    const btn = document.getElementById("copy-ref-btn");
    btn.textContent = T('ref_copied');
    btn.classList.add("copied");
    setTimeout(() => { btn.textContent = T('ref_copy_btn'); btn.classList.remove("copied"); }, 2000);
  });
}

function shareToFacebook() {
  if (!_refLink) return;
  window.open(`https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(_refLink)}&quote=${encodeURIComponent(shareText())}`, "_blank");
}

function shareToX() {
  if (!_refLink) return;
  window.open(`https://twitter.com/intent/tweet?text=${encodeURIComponent(shareText())}`, "_blank");
}

async function init() {
  applyLang(localStorage.getItem('md-lang-v2') || 'zh');
  US_STOCKS = typeof US_STOCKS_FULL !== 'undefined' ? US_STOCKS_FULL : [];
  TW_STOCKS = typeof TW_STOCKS_FULL !== 'undefined' ? TW_STOCKS_FULL : [];

  // 切換帳號偵測:URL ?email= 或 hero 剛輸的 email 跟舊 session 不同 → 清舊登入
  const urlEmail = (new URLSearchParams(window.location.search).get("email") || "").trim().toLowerCase();
  const heroEmail = (localStorage.getItem("md-hero-email") || "").trim().toLowerCase();
  const storedEmail = (localStorage.getItem("md-email") || "").trim().toLowerCase();
  const incoming = urlEmail || heroEmail;
  if (incoming && storedEmail && incoming !== storedEmail) {
    localStorage.removeItem("md-email");
    localStorage.removeItem("md-plan");
    localStorage.removeItem("md-saved-email");
    localStorage.removeItem("md-saved-pwd");
  }

  const savedEmail = localStorage.getItem("md-saved-email") || ""; const savedPwd = localStorage.getItem("md-saved-pwd") || "";
  if (savedEmail) { document.getElementById("login-email").value = savedEmail; document.getElementById("login-password").value = savedPwd; document.getElementById("remember-me").checked = true; }
  if (urlEmail && !savedEmail) { document.getElementById("login-email").value = urlEmail; document.getElementById("login-password").focus(); history.replaceState(null, "", "dashboard.html"); }
  const email = localStorage.getItem("md-email"); const plan = localStorage.getItem("md-plan") || "free";
  if (email) showDashboard(email, plan);
}
init();

// ── 加到主畫面(PWA)/長開分頁的舊頁救援:回到前景時自動補同步 ──
// standalone PWA 重開不會重新載入頁面,舊頁面實例可活好幾天:
// ①別台裝置加的股看不到 ②網站新版本吃不到。visibilitychange 是唯一可靠的補救點。
const _pageLoadTs = Date.now();
let _lastHiddenTs = 0;
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") { _lastHiddenTs = Date.now(); return; }
  const email = localStorage.getItem("md-email");
  if (!email || !_lastHiddenTs) return;
  const awayMs = Date.now() - _lastHiddenTs;
  // 頁面實例超過 24h 且離開超過 1 分鐘 → 直接重載吃新部署(不打斷使用中的人)
  if (Date.now() - _pageLoadTs > 86400e3 && awayMs > 60e3) { location.reload(); return; }
  // 離開超過 30s → 重拉伺服器偏好(跨裝置加的股)+重建限時動態+大盤
  if (awayMs > 30e3) {
    loadPreferences(email).then(() => { loadStories(email); });
    loadMarketOverview();
  } else if (typeof refreshQuotes === "function") {
    refreshQuotes();
  }
});
