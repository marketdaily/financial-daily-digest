(function () {
  "use strict";
  if (window.MDTour) return;

  var STYLE = [
    "#md-tour-fab{position:fixed;right:18px;bottom:18px;z-index:99990;",
    "display:inline-flex;align-items:center;gap:7px;padding:13px 18px;",
    "background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;border:none;",
    "border-radius:30px;font-size:15px;font-weight:800;cursor:pointer;",
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans TC',sans-serif;",
    "box-shadow:0 8px 28px rgba(99,102,241,0.5);transition:transform .15s;}",
    "#md-tour-fab:hover{transform:translateY(-2px);}",
    "#md-tour-fab:active{transform:translateY(0);}",
    "#md-tour-overlay{position:fixed;inset:0;z-index:99997;cursor:default;}",
    "#md-tour-hole{position:fixed;z-index:99998;border-radius:12px;",
    "border:3px solid #818cf8;box-shadow:0 0 0 9999px rgba(8,8,22,0.80);",
    "pointer-events:none;transition:top .2s,left .2s,width .2s,height .2s;}",
    "#md-tour-bubble{position:fixed;z-index:100000;width:300px;max-width:88vw;",
    "background:#1a1b2e;border:1px solid rgba(129,140,248,0.4);border-radius:16px;",
    "padding:20px;box-shadow:0 20px 60px rgba(0,0,0,0.6);",
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans TC',sans-serif;}",
    ".md-t-prog{font-size:12px;font-weight:700;color:#818cf8;",
    "letter-spacing:1px;margin-bottom:8px;}",
    ".md-t-title{font-size:19px;font-weight:800;color:#fff;",
    "line-height:1.4;margin-bottom:8px;}",
    ".md-t-body{font-size:15px;color:rgba(255,255,255,0.78);",
    "line-height:1.75;margin-bottom:16px;}",
    ".md-t-btns{display:flex;gap:8px;}",
    ".md-t-b1{flex:1;padding:12px;background:#6366f1;color:#fff;border:none;",
    "border-radius:10px;font-size:15px;font-weight:800;cursor:pointer;",
    "font-family:inherit;min-height:46px;}",
    ".md-t-b1:hover{background:#4f46e5;}",
    ".md-t-b2{padding:12px 14px;background:rgba(255,255,255,0.08);color:#c7c9d8;",
    "border:1px solid rgba(255,255,255,0.14);border-radius:10px;font-size:15px;",
    "font-weight:700;cursor:pointer;font-family:inherit;min-height:46px;}",
    ".md-t-b2:hover{background:rgba(255,255,255,0.14);}",
    ".md-t-skip{display:block;width:100%;margin-top:12px;padding:6px;",
    "background:none;border:none;color:rgba(255,255,255,0.4);font-size:13px;",
    "cursor:pointer;font-family:inherit;}",
    ".md-t-skip:hover{color:rgba(255,255,255,0.7);}"
  ].join("");

  var steps = [], idx = 0, tourId = "default", active = false;
  var els = {};

  // 跟隨網站語言(各頁存 md-lang-v2,舊頁可能用 md-lang;預設 zh)。
  function lang() {
    try {
      var v = localStorage.getItem("md-lang-v2") || localStorage.getItem("md-lang");
      return v === "en" ? "en" : "zh";
    } catch (e) { return "zh"; }
  }
  var UI = {
    zh: { fab: "新手教學", next: "下一步 →", done: "完成 ✓", prev: "上一步", skip: "跳過教學" },
    en: { fab: "Guide", next: "Next →", done: "Done ✓", prev: "Back", skip: "Skip" }
  };
  function T(k) { return UI[lang()][k]; }
  // 步驟文字可給字串或 {zh,en};物件則依語言取值。
  function txt(v) {
    if (v && typeof v === "object") return v[lang()] || v.zh || v.en || "";
    return v == null ? "" : v;
  }

  function injectStyle() {
    if (document.getElementById("md-tour-style")) return;
    var s = document.createElement("style");
    s.id = "md-tour-style";
    s.textContent = STYLE;
    document.head.appendChild(s);
  }

  function injectFab() {
    if (document.getElementById("md-tour-fab") || !document.body) return;
    var b = document.createElement("button");
    b.id = "md-tour-fab";
    b.type = "button";
    b.innerHTML = "<span>❓</span> " + T("fab");
    b.setAttribute("aria-label", T("fab"));
    b.addEventListener("click", start);
    document.body.appendChild(b);
  }

  function tourDone(id) {
    try { return localStorage.getItem("md-tour-done:" + id) === "1"; }
    catch (e) { return false; }
  }
  function markDone(id) {
    try { localStorage.setItem("md-tour-done:" + id, "1"); } catch (e) {}
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
    });
  }

  function mount(stepArr, opts) {
    opts = opts || {};
    steps = stepArr || [];
    tourId = opts.tourId || "default";
    injectStyle();
    if (document.body) injectFab();
    else document.addEventListener("DOMContentLoaded", injectFab);
    if (opts.auto && !tourDone(tourId)) {
      setTimeout(function () { if (!active) start(); }, 700);
    }
  }

  function setFab(visible) {
    var fab = document.getElementById("md-tour-fab");
    if (fab) fab.style.display = visible ? "" : "none";
  }

  function start() {
    if (active || !steps.length) return;
    active = true;
    idx = 0;
    markDone(tourId);
    setFab(false);
    buildOverlay();
    show();
  }

  function buildOverlay() {
    var ov = document.createElement("div");
    ov.id = "md-tour-overlay";
    var hole = document.createElement("div");
    hole.id = "md-tour-hole";
    var bubble = document.createElement("div");
    bubble.id = "md-tour-bubble";
    document.body.appendChild(ov);
    document.body.appendChild(hole);
    document.body.appendChild(bubble);
    els = { overlay: ov, hole: hole, bubble: bubble };
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
  }

  function onKey(e) { if (e.key === "Escape") finish(true); }

  function isVisible(el) {
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function show() {
    var step = steps[idx];
    if (!step) { finish(true); return; }
    var el = step.selector ? document.querySelector(step.selector) : null;
    if (step.selector && (!el || !isVisible(el))) { idx++; show(); return; }
    if (el) {
      try { el.scrollIntoView({ behavior: "smooth", block: "center" }); } catch (e) {}
      setTimeout(function () { render(el, step); }, 340);
    } else {
      render(null, step);
    }
  }

  function holeRect(el) {
    var hole = els.hole, pad = 7;
    var r = el.getBoundingClientRect();
    hole.style.display = "block";
    hole.style.top = (r.top - pad) + "px";
    hole.style.left = (r.left - pad) + "px";
    hole.style.width = (r.width + pad * 2) + "px";
    hole.style.height = (r.height + pad * 2) + "px";
  }

  function centerDark() {
    var hole = els.hole;
    hole.style.display = "block";
    hole.style.border = "none";
    hole.style.top = "50%";
    hole.style.left = "50%";
    hole.style.width = "0px";
    hole.style.height = "0px";
  }

  function render(el, step) {
    if (el) {
      els.hole.style.border = "3px solid #818cf8";
      holeRect(el);
    } else {
      centerDark();
    }
    var bubble = els.bubble;
    bubble.innerHTML = bubbleHTML(step);
    bubble.querySelector("#md-t-next").addEventListener("click", next);
    var prevBtn = bubble.querySelector("#md-t-prev");
    if (prevBtn) prevBtn.addEventListener("click", prev);
    bubble.querySelector("#md-t-skip").addEventListener("click", function () { finish(true); });
    positionBubble(el);
  }

  function bubbleHTML(step) {
    var isLast = idx === steps.length - 1;
    return "<div class='md-t-prog'>" + (idx + 1) + " / " + steps.length + "</div>"
      + "<div class='md-t-title'>" + esc(txt(step.title)) + "</div>"
      + "<div class='md-t-body'>" + esc(txt(step.body)) + "</div>"
      + "<div class='md-t-btns'>"
      + (idx > 0 ? "<button type='button' id='md-t-prev' class='md-t-b2'>" + T("prev") + "</button>" : "")
      + "<button type='button' id='md-t-next' class='md-t-b1'>"
      + (isLast ? T("done") : T("next")) + "</button>"
      + "</div>"
      + "<button type='button' id='md-t-skip' class='md-t-skip'>" + T("skip") + "</button>";
  }

  function positionBubble(el) {
    var bubble = els.bubble;
    bubble.style.display = "block";
    var bw = bubble.offsetWidth, bh = bubble.offsetHeight;
    var vw = window.innerWidth, vh = window.innerHeight;
    var top, left;
    if (!el) {
      top = (vh - bh) / 2;
      left = (vw - bw) / 2;
    } else {
      var r = el.getBoundingClientRect();
      if (r.bottom + bh + 18 < vh) top = r.bottom + 14;
      else if (r.top - bh - 18 > 0) top = r.top - bh - 14;
      else top = Math.max(12, (vh - bh) / 2);
      left = r.left + r.width / 2 - bw / 2;
    }
    left = Math.max(12, Math.min(left, vw - bw - 12));
    top = Math.max(12, Math.min(top, vh - bh - 12));
    bubble.style.top = top + "px";
    bubble.style.left = left + "px";
  }

  function reposition() {
    if (!active) return;
    var step = steps[idx];
    var el = step && step.selector ? document.querySelector(step.selector) : null;
    if (el) holeRect(el);
    positionBubble(el);
  }

  function next() {
    idx++;
    if (idx >= steps.length) finish(true);
    else show();
  }
  function prev() {
    if (idx > 0) { idx--; show(); }
  }

  function finish(complete) {
    if (!active) return;
    active = false;
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("resize", reposition);
    window.removeEventListener("scroll", reposition, true);
    if (els.overlay) els.overlay.remove();
    if (els.hole) els.hole.remove();
    if (els.bubble) els.bubble.remove();
    els = {};
    setFab(true);
    if (complete) markDone(tourId);
  }

  window.MDTour = { mount: mount, start: start };
})();
