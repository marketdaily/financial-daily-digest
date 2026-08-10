/* fx-motion.js — scroll/spring motion layer, zero dependencies.
 * Studied 2026-08-11 from the four animation libraries' signature techniques:
 *   GSAP ScrollTrigger  -> scroll-linked scrub progress + parallax
 *   Anime.js            -> grid/center stagger reveals
 *   Motion.dev          -> transform/opacity-only, hardware-accelerated
 *   React-Spring        -> damped-spring integrator (no fixed duration/curve)
 * Companions: fx-motion.css. Parallax writes the CSS `translate` property so it
 * composes with (never fights) inline `transform` set by other layers. */
(function () {
  "use strict";
  var REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- shared rAF ticker ---------- */
  var jobs = new Map(), jid = 0, running = false;
  function tick(now) {
    if (!running) return;
    var any = false;
    jobs.forEach(function (j) { if (j.active) { any = true; j.fn(now); } });
    if (any) requestAnimationFrame(tick); else running = false;
  }
  function addJob(fn) {
    var id = ++jid; jobs.set(id, { fn: fn, active: true });
    if (!running) { running = true; requestAnimationFrame(tick); }
    return id;
  }
  function setJob(id, active) {
    var j = jobs.get(id); if (!j || j.active === active) return;
    j.active = active;
    if (active && !running) { running = true; requestAnimationFrame(tick); }
  }

  /* ---------- 1. spring engine (react-spring: motion from physics, not curves) ----------
   * Damped harmonic oscillator, semi-implicit Euler. Returns a driver whose
   * .set(target) retargets mid-flight preserving velocity. */
  function spring(onFrame, opts) {
    opts = opts || {};
    var k = opts.stiffness || 170, c = opts.damping || 20, m = opts.mass || 1;
    var x = opts.from || 0, v = 0, target = x, last = 0, id = null;
    function step(now) {
      var dt = Math.min(0.048, (now - last) / 1000 || 0.016); last = now;
      var a = (-k * (x - target) - c * v) / m;
      v += a * dt; x += v * dt;
      if (Math.abs(x - target) < 0.0015 && Math.abs(v) < 0.0015) {
        x = target; v = 0; onFrame(x, true); setJob(id, false); return;
      }
      onFrame(x, false);
    }
    return {
      set: function (t) {
        target = t;
        if (id === null) { last = performance.now(); id = addJob(step); }
        else { last = performance.now(); setJob(id, true); }
      },
      get: function () { return x; }
    };
  }

  /* ---------- 2. scroll scrub (GSAP ScrollTrigger scrub) ----------
   * [data-fx-scrub]        progress 0->1 while element crosses the viewport
   * [data-fx-scrub="exit"] progress 0->1 only while element scrolls out the top
   * Smoothed progress lands in --fxp for CSS to map (opacity/scale/anything).
   * [data-fx-parallax="0.2"] additionally translates via the CSS `translate`
   * property: +speed drifts slower than scroll (depth), -speed faster. */
  var scrubEls = [];
  function scrubProgress(el, mode) {
    var r = el.getBoundingClientRect(), vh = innerHeight;
    var p = mode === "exit"
      ? -r.top / Math.max(1, r.height)
      : (vh - r.top) / (vh + r.height);
    return Math.max(0, Math.min(1, p));
  }
  function initScrub() {
    var els = document.querySelectorAll("[data-fx-scrub],[data-fx-parallax]");
    if (!els.length || REDUCED) return;
    els.forEach(function (el) {
      scrubEls.push({
        el: el,
        mode: el.getAttribute("data-fx-scrub") || "",
        speed: parseFloat(el.getAttribute("data-fx-parallax")) || 0,
        cur: -1, near: true
      });
    });
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        var s = scrubEls.find(function (x) { return x.el === e.target; });
        if (s) s.near = e.isIntersecting;
      });
      wake();
    }, { rootMargin: "25% 0px 25% 0px" });
    scrubEls.forEach(function (s) { io.observe(s.el); });

    var id = null;
    function frame() {
      var busy = false;
      scrubEls.forEach(function (s) {
        if (!s.near) return;
        var tp = scrubProgress(s.el, s.mode);
        if (s.cur < 0) s.cur = tp;
        s.cur += (tp - s.cur) * 0.14; /* scrub smoothing, GSAP scrub:~0.5 feel */
        if (Math.abs(tp - s.cur) > 0.001) busy = true; else s.cur = tp;
        s.el.style.setProperty("--fxp", s.cur.toFixed(4));
        if (s.speed) s.el.style.translate = "0 " + ((s.cur - 0.5) * s.speed * -120).toFixed(1) + "px";
      });
      if (!busy) setJob(id, false);
    }
    function wake() {
      if (id === null) id = addJob(frame); else setJob(id, true);
    }
    addEventListener("scroll", wake, { passive: true });
    addEventListener("resize", wake, { passive: true });
    wake();
  }

  /* ---------- 3. stagger reveal (anime.js stagger: {from:"center"|"first"}) ----------
   * [data-fx-stagger] / [data-fx-stagger="center"]: direct children fade+rise
   * with per-child delay by distance from origin. CSS does the tween. */
  function initStagger() {
    var els = document.querySelectorAll("[data-fx-stagger]");
    if (!els.length) return;
    if (REDUCED) { els.forEach(function (el) { el.classList.add("fx-in"); }); return; }
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return;
        io.unobserve(e.target);
        e.target.classList.add("fx-in");
      });
    }, { threshold: 0.15, rootMargin: "0px 0px 60px 0px" });
    els.forEach(function (el) {
      var kids = Array.prototype.filter.call(el.children, function (c) {
        return c.nodeType === 1;
      });
      var n = kids.length, from = el.getAttribute("data-fx-stagger") || "first";
      var each = Math.min(110, 480 / Math.max(1, n - 1) || 0);
      kids.forEach(function (c, i) {
        var d = from === "center" ? Math.abs(i - (n - 1) / 2) : i;
        c.style.setProperty("--fxd", Math.round(d * each) + "ms");
      });
      el.classList.add("fx-stagger-set");
      io.observe(el);
    });
  }

  /* ---------- boot ---------- */
  function init() { initScrub(); initStagger(); }
  window.FXM = { spring: spring, init: init };
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
