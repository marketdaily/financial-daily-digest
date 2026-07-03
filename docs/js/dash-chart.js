// dashboard.html 內嵌 JS 抽出(dash-chart.js);7 檔按原始順序載入,順序不可換(全域相依)。2026-07-03 P5。
async function loadChart(sym, period) {
  const canvas = document.getElementById("story-chart-canvas");
  const msg = document.getElementById("story-chart-msg");
  if (!canvas) return;
  const reqId = ++_chartReqId;
  _chartData = null;
  _chartHover = null;
  if (_chartAnimId) { cancelAnimationFrame(_chartAnimId); _chartAnimId = null; }
  if (msg) msg.textContent = T('chart_loading');
  const c0 = canvas.getContext("2d");
  if (c0) c0.clearRect(0, 0, canvas.width, canvas.height);
  try {
    const res = await fetch(`${WORKER_URL}/stock-chart?ticker=${encodeURIComponent(sym)}&range=${period}`);
    const data = await res.json();
    if (reqId !== _chartReqId) return;
    const points = (data && data.points) || [];
    if (points.length < 2) { if (msg) msg.textContent = T('chart_no_data'); return; }
    if (msg) msg.textContent = "";
    _chartData = { points, prevClose: data.prevClose };
    bindChartPointer(canvas);
    animateChart(canvas);
  } catch {
    if (reqId !== _chartReqId) return;
    if (msg) msg.textContent = T('chart_load_failed');
  }
}

function animateChart(canvas) {
  if (_chartAnimId) cancelAnimationFrame(_chartAnimId);
  const dur = 480, t0 = performance.now();
  const step = (now) => {
    const p = Math.min(1, (now - t0) / dur);
    renderChart(canvas, 1 - Math.pow(1 - p, 3), null);
    if (p < 1) { _chartAnimId = requestAnimationFrame(step); }
    else { _chartAnimId = null; renderChart(canvas, 1, _chartHover); }
  };
  _chartAnimId = requestAnimationFrame(step);
}

function niceStep(raw) {
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  let s = 1;
  if (norm > 5) s = 10; else if (norm > 2.5) s = 5; else if (norm > 2) s = 2.5; else if (norm > 1) s = 2;
  return s * mag;
}

function roundRectPath(ctx, x, y, w, h, r) {
  ctx.beginPath();
  if (ctx.roundRect) { ctx.roundRect(x, y, w, h, r); return; }
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function fmtChartDate(sec, full) {
  const d = new Date(sec * 1000);
  const md = `${d.getMonth() + 1}/${d.getDate()}`;
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (_chartPeriod === "1D") return full ? `${md} ${hm}` : hm;
  if (_chartPeriod === "5D") return full ? `${md} ${hm}` : md;
  return md;
}

function renderChart(canvas, progress, hoverIdx) {
  const cd = _chartData;
  if (!cd) return;
  const points = cd.points, prevClose = cd.prevClose, n = points.length;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const W = rect.width, H = rect.height;
  if (!W || !H) return;
  if (canvas.width !== Math.round(W * dpr)) canvas.width = Math.round(W * dpr);
  if (canvas.height !== Math.round(H * dpr)) canvas.height = Math.round(H * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  const closes = points.map(p => p.c);
  const first = closes[0], last = closes[n - 1];
  let lo = Math.min.apply(null, closes), hi = Math.max.apply(null, closes);
  if (prevClose != null) { lo = Math.min(lo, prevClose); hi = Math.max(hi, prevClose); }
  const pad = (hi - lo) * 0.14 || 1;
  lo -= pad; hi += pad;

  const padL = 10, padR = 52, padT = 12, padB = 22;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const xAt = i => padL + (i / (n - 1)) * plotW;
  const yAt = v => padT + (1 - (v - lo) / (hi - lo)) * plotH;
  _chartGeom = { padL, plotW, n };

  const up = last >= first;
  const line = up ? "#f87171" : "#34d399";
  const rgb = up ? "248,113,113" : "52,211,153";
  const fmt = v => v >= 1000 ? Math.round(v).toLocaleString() : v.toFixed(2);

  // horizontal gridlines + price axis
  ctx.font = "10px -apple-system,system-ui,sans-serif";
  ctx.textBaseline = "middle";
  ctx.textAlign = "right";
  const step = niceStep((hi - lo) / 4);
  for (let g = Math.ceil(lo / step) * step; g < hi; g += step) {
    const gy = yAt(g);
    ctx.strokeStyle = "rgba(255,255,255,0.05)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padL, gy);
    ctx.lineTo(padL + plotW, gy);
    ctx.stroke();
    ctx.fillStyle = "rgba(226,232,240,0.38)";
    ctx.fillText(fmt(g), W - 6, gy);
  }

  // prev close reference line
  if (prevClose != null && prevClose > lo && prevClose < hi) {
    ctx.save();
    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = "rgba(255,255,255,0.22)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padL, yAt(prevClose));
    ctx.lineTo(padL + plotW, yAt(prevClose));
    ctx.stroke();
    ctx.restore();
  }

  // time axis
  ctx.textAlign = "center";
  ctx.fillStyle = "rgba(226,232,240,0.38)";
  for (let k = 0; k < 4; k++) {
    const idx = Math.round(k / 3 * (n - 1));
    const tx = Math.max(padL + 16, Math.min(padL + plotW - 16, xAt(idx)));
    ctx.fillText(fmtChartDate(points[idx].t, false), tx, H - 9);
  }

  // area + line, revealed by progress
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, 0, padL + plotW * progress + 0.5, H);
  ctx.clip();

  const grad = ctx.createLinearGradient(0, padT, 0, padT + plotH);
  grad.addColorStop(0, `rgba(${rgb},0.26)`);
  grad.addColorStop(1, `rgba(${rgb},0)`);
  ctx.beginPath();
  ctx.moveTo(xAt(0), yAt(closes[0]));
  for (let i = 1; i < n; i++) ctx.lineTo(xAt(i), yAt(closes[i]));
  ctx.lineTo(xAt(n - 1), padT + plotH);
  ctx.lineTo(xAt(0), padT + plotH);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  ctx.beginPath();
  ctx.moveTo(xAt(0), yAt(closes[0]));
  for (let i = 1; i < n; i++) ctx.lineTo(xAt(i), yAt(closes[i]));
  ctx.strokeStyle = line;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.shadowColor = line;
  ctx.shadowBlur = 7;
  ctx.stroke();
  ctx.shadowBlur = 0;
  ctx.restore();

  if (progress < 1) return;

  // last price marker + pill on right axis
  const lx = xAt(n - 1), ly = yAt(last);
  ctx.save();
  ctx.setLineDash([2, 3]);
  ctx.globalAlpha = 0.5;
  ctx.strokeStyle = line;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(lx, ly);
  ctx.lineTo(W - padR + 2, ly);
  ctx.stroke();
  ctx.restore();

  ctx.beginPath();
  ctx.arc(lx, ly, 3, 0, Math.PI * 2);
  ctx.fillStyle = line;
  ctx.fill();

  const plbl = fmt(last);
  ctx.font = "bold 10px -apple-system,system-ui,sans-serif";
  const pw = ctx.measureText(plbl).width + 12, ph = 16;
  const py = Math.max(padT + ph / 2, Math.min(ly, H - padB - ph / 2));
  ctx.fillStyle = line;
  roundRectPath(ctx, W - pw - 2, py - ph / 2, pw, ph, 4);
  ctx.fill();
  ctx.fillStyle = "#0b1020";
  ctx.textAlign = "center";
  ctx.fillText(plbl, W - pw / 2 - 2, py);

  // crosshair + tooltip
  if (hoverIdx != null && hoverIdx >= 0 && hoverIdx < n) {
    const hx = xAt(hoverIdx), hv = closes[hoverIdx], hy = yAt(hv);
    ctx.save();
    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = "rgba(255,255,255,0.3)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(hx, padT); ctx.lineTo(hx, padT + plotH);
    ctx.moveTo(padL, hy); ctx.lineTo(padL + plotW, hy);
    ctx.stroke();
    ctx.restore();

    ctx.beginPath();
    ctx.arc(hx, hy, 5, 0, Math.PI * 2);
    ctx.fillStyle = "#0b1020";
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = line;
    ctx.stroke();

    const tDate = fmtChartDate(points[hoverIdx].t, true);
    const tPrice = "$" + fmt(hv);
    ctx.font = "10px -apple-system,system-ui,sans-serif";
    const w1 = ctx.measureText(tDate).width;
    ctx.font = "bold 11px -apple-system,system-ui,sans-serif";
    const w2 = ctx.measureText(tPrice).width;
    const tw = Math.max(w1, w2) + 16, th = 34;
    let tx = hx + 10;
    if (tx + tw > padL + plotW) tx = hx - 10 - tw;
    tx = Math.max(padL, tx);
    const ty = padT + 4;
    ctx.fillStyle = "rgba(15,18,32,0.96)";
    ctx.strokeStyle = "rgba(255,255,255,0.12)";
    ctx.lineWidth = 1;
    roundRectPath(ctx, tx, ty, tw, th, 6);
    ctx.fill();
    ctx.stroke();
    ctx.textAlign = "left";
    ctx.font = "10px -apple-system,system-ui,sans-serif";
    ctx.fillStyle = "rgba(226,232,240,0.55)";
    ctx.fillText(tDate, tx + 8, ty + 11);
    ctx.font = "bold 11px -apple-system,system-ui,sans-serif";
    ctx.fillStyle = line;
    ctx.fillText(tPrice, tx + 8, ty + 24);
  }
}

function bindChartPointer(canvas) {
  const scrub = (e) => {
    if (!_chartData || !_chartGeom) return;
    const rect = canvas.getBoundingClientRect();
    const { padL, plotW, n } = _chartGeom;
    let idx = Math.round((e.clientX - rect.left - padL) / plotW * (n - 1));
    idx = Math.max(0, Math.min(n - 1, idx));
    _chartHover = idx;
    if (_chartAnimId) { cancelAnimationFrame(_chartAnimId); _chartAnimId = null; }
    renderChart(canvas, 1, idx);
  };
  const clear = () => {
    _chartHover = null;
    if (_chartData && !_chartAnimId) renderChart(canvas, 1, null);
  };
  canvas.onpointerdown = scrub;
  canvas.onpointermove = (e) => { if (e.pointerType === "mouse" || e.pressure > 0) scrub(e); };
  canvas.onpointerup = clear;
  canvas.onpointercancel = clear;
  canvas.onpointerleave = clear;
}

function setChartPeriod(period) {
  _chartPeriod = period;
  document.querySelectorAll(".scp-btn").forEach(b => b.classList.toggle("active", b.textContent === period));
  const sym = _stories[_storyIdx]?.symbol;
  if (sym) loadChart(sym, period);
}

window.addEventListener("resize", () => {
  const canvas = document.getElementById("story-chart-canvas");
  if (canvas && _chartData && !_chartAnimId) renderChart(canvas, 1, _chartHover);
});

function toggleChangePwd() {
  const form = document.getElementById("change-pwd-form");
  const btn = document.getElementById("toggle-pwd-btn");
  if (form.style.display === "none") {
    form.style.display = "block";
    btn.style.display = "none";
  } else {
    form.style.display = "none";
    btn.style.display = "block";
  }
}

