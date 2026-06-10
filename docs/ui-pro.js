/**
 * ui-pro.js — MarketDaily Shared UI Enhancement Layer
 * Techniques: noise grain · scroll progress bar · page transitions ·
 *             magnetic buttons · click ripple · scene reveal observer
 */
(function () {
  'use strict';

  /* ── 1. NOISE / GRAIN OVERLAY ── */
  const grain = document.createElement('div');
  grain.setAttribute('aria-hidden', 'true');
  grain.style.cssText =
    'position:fixed;inset:0;z-index:9990;pointer-events:none;' +
    'background-image:url("data:image/svg+xml,%3Csvg viewBox=\'0 0 256 256\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cfilter id=\'n\'%3E%3CfeTurbulence type=\'fractalNoise\' baseFrequency=\'0.88\' numOctaves=\'4\' stitchTiles=\'stitch\'/%3E%3C/filter%3E%3Crect width=\'100%25\' height=\'100%25\' filter=\'url(%23n)\'/%3E%3C/svg%3E");' +
    'background-size:190px 190px;opacity:0.028;';
  document.body.appendChild(grain);

  /* ── 2. SCROLL PROGRESS BAR ── */
  const progressBar = document.createElement('div');
  progressBar.setAttribute('aria-hidden', 'true');
  progressBar.style.cssText =
    'position:fixed;top:0;left:0;height:2px;width:0%;z-index:10001;pointer-events:none;' +
    'background:linear-gradient(90deg,#6366f1 0%,#8b5cf6 50%,#38bdf8 100%);' +
    'transition:width 0.08s linear;';
  document.body.appendChild(progressBar);
  window.addEventListener('scroll', function () {
    var pct = window.scrollY / Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    progressBar.style.width = (pct * 100) + '%';
  }, { passive: true });

  /* ── 4. PAGE TRANSITION WIPE ── */
  var ptEl = document.createElement('div');
  ptEl.id = 'pt-wipe';
  ptEl.setAttribute('aria-hidden', 'true');
  ptEl.style.cssText =
    'position:fixed;inset:0;background:#060611;z-index:10000;pointer-events:none;' +
    'transform:translateY(0%);transition:transform .65s cubic-bezier(.76,0,.24,1);';
  document.body.appendChild(ptEl);

  /* Reveal page on load */
  requestAnimationFrame(function () {
    requestAnimationFrame(function () {
      ptEl.style.transform = 'translateY(-105%)';
    });
  });

  /* Intercept internal link clicks */
  document.addEventListener('click', function (e) {
    var link = e.target.closest('a[href]');
    if (!link) return;
    var href = link.getAttribute('href');
    if (!href || href.startsWith('http') || href.startsWith('mailto') ||
        href.startsWith('tel') || href.startsWith('#') || link.target === '_blank') return;
    e.preventDefault();
    var dest = href;
    ptEl.style.transition = 'transform .5s cubic-bezier(.76,0,.24,1)';
    ptEl.style.transform = 'translateY(0%)';
    setTimeout(function () { location.href = dest; }, 520);
  }, true);

  /* ── 5. MAGNETIC BUTTONS ── */
  function initMagnetic() {
    document.querySelectorAll('.cta-btn,.pricing-btn.btn-pro,.subscribe-box button,.plan-mini-btn.paid,.wb-card a').forEach(function (btn) {
      if (btn.dataset.magnetic) return;
      btn.dataset.magnetic = '1';
      btn.addEventListener('mousemove', function (e) {
        var r = btn.getBoundingClientRect();
        var dx = (e.clientX - (r.left + r.width / 2)) * 0.28;
        var dy = (e.clientY - (r.top + r.height / 2)) * 0.28;
        btn.style.transform = 'translate(' + dx + 'px,' + dy + 'px)';
        btn.style.transition = 'transform .1s ease';
      });
      btn.addEventListener('mouseleave', function () {
        btn.style.transform = '';
        btn.style.transition = 'transform .6s cubic-bezier(.34,1.56,.64,1)';
      });
    });
  }
  initMagnetic();

  /* ── 6. CLICK RIPPLE ── */
  var rippleStyle = document.createElement('style');
  rippleStyle.textContent =
    '@keyframes md-ripple{to{transform:scale(32);opacity:0}}' +
    '.md-ripple-el{position:absolute;border-radius:50%;background:rgba(255,255,255,.16);' +
    'width:10px;height:10px;pointer-events:none;transform:scale(0);' +
    'animation:md-ripple .65s ease-out forwards;}';
  document.head.appendChild(rippleStyle);

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('button,.cta-btn,.pricing-btn,.plan-mini-btn,.slider-btn');
    if (!btn) return;
    var r = btn.getBoundingClientRect();
    var ripple = document.createElement('span');
    ripple.className = 'md-ripple-el';
    ripple.style.left = (e.clientX - r.left - 5) + 'px';
    ripple.style.top  = (e.clientY - r.top  - 5) + 'px';
    var prevPos = window.getComputedStyle(btn).position;
    if (prevPos === 'static') btn.style.position = 'relative';
    btn.style.overflow = 'hidden';
    btn.appendChild(ripple);
    setTimeout(function () { ripple.remove(); }, 700);
  });

  /* ── 7. SCENE REVEAL OBSERVER (shared fallback) ── */
  if (typeof IntersectionObserver !== 'undefined') {
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add('visible');
          obs.unobserve(e.target);
        }
      });
    }, { threshold: 0.05, rootMargin: '0px 0px 90px 0px' });
    document.querySelectorAll(
      '.reveal,.scene-reveal,.scene-from-left,.scene-from-right,.scene-zoom-in'
    ).forEach(function (el) { obs.observe(el); });
  }

})();
