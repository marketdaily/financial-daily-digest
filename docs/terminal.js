/* Phosphor Terminal — 氛圍注入(開機掃描 + 左下角即時狀態 HUD)
   純附加,fixed/pointer-events:none,不碰既有 DOM 與功能 */
(function () {
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // 開機掃描 sweep(只一次)
  if (!reduce) {
    var boot = document.createElement('div');
    boot.id = 'md-boot';
    document.body.appendChild(boot);
    setTimeout(function () { boot.remove(); }, 1400);
  }

  // 左下角即時狀態 HUD + 台北時鐘
  var hud = document.createElement('div');
  hud.id = 'md-term-hud';
  hud.setAttribute('aria-hidden', 'true');
  hud.innerHTML = '<span class="dot"></span>SYSTEM ONLINE · <span class="amb">TPE</span> <span id="md-clock">--:--:--</span>';
  document.body.appendChild(hud);

  var clk = hud.querySelector('#md-clock');
  function tick() {
    try {
      var s = new Date().toLocaleTimeString('en-GB', { timeZone: 'Asia/Taipei', hour12: false });
      if (clk) clk.textContent = s;
    } catch (e) {
      var d = new Date(); clk.textContent = d.toTimeString().slice(0, 8);
    }
  }
  tick();
  setInterval(tick, 1000);
})();
