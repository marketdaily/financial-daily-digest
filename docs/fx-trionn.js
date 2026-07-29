/* fx.js — Trionn-class effect layer, zero dependencies.
 * Ported from a frame/bundle teardown of trionn.com (2026-07-29):
 * char blur reveal, letter-roll hover, marquee w/ drag, count-up,
 * line-draw, fbm fog WebGL shader (their "FooterFog"), welding sparks,
 * slot-digit preloader. All rAF loops share one ticker that pauses on
 * tab-hide and when the element leaves the viewport (their CanvasManager). */
(function () {
  "use strict";
  var REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
  var FINE = matchMedia("(hover:hover) and (pointer:fine)").matches;

  /* ---------- shared ticker (Trionn CanvasManager pattern) ---------- */
  var jobs = new Map(), jid = 0, running = false, hidden = document.hidden;
  function tick(now) {
    if (!running) return;
    var any = false;
    jobs.forEach(function (j) { if (j.active && !hidden) { any = true; j.fn(now); } });
    if (any) requestAnimationFrame(tick); else running = false;
  }
  function addJob(fn) {
    var id = ++jid; jobs.set(id, { fn: fn, active: true });
    if (!running) { running = true; requestAnimationFrame(tick); }
    return id;
  }
  function setJob(id, active) {
    var j = jobs.get(id); if (!j) return;
    j.active = active;
    if (active && !running) { running = true; requestAnimationFrame(tick); }
  }
  document.addEventListener("visibilitychange", function () {
    hidden = document.hidden;
    if (!hidden && jobs.size && !running) { running = true; requestAnimationFrame(tick); }
  });

  /* ---------- 1. char split + blur reveal ---------- */
  var seg = window.Intl && Intl.Segmenter
    ? new Intl.Segmenter(undefined, { granularity: "grapheme" }) : null;
  function graphemes(s) {
    if (seg) { var out = []; for (var g of seg.segment(s)) out.push(g.segment); return out; }
    return Array.from(s);
  }
  function splitChars(el) {
    if (el.querySelector(".fx-char")) return el.querySelectorAll(".fx-char");
    var walker = [], n;
    (function walk(node) {
      for (var c = node.firstChild; c; c = c.nextSibling) {
        if (c.nodeType === 3 && c.nodeValue.trim()) walker.push(c);
        else if (c.nodeType === 1 && c.tagName !== "BR") {
          /* atomic: animate as one unit (e.g. background-clip:text gradients) */
          if (c.hasAttribute && c.hasAttribute("data-fx-atomic")) c.classList.add("fx-char");
          else walk(c);
        }
      }
    })(el);
    walker.forEach(function (t) {
      var frag = document.createDocumentFragment(), word = null;
      function charSpan(ch) {
        var s = document.createElement("span");
        s.className = "fx-char"; s.textContent = ch;
        return s;
      }
      graphemes(t.nodeValue).forEach(function (ch) {
        if (/[A-Za-z0-9À-ɏ'’.,%+\-]/.test(ch)) {
          /* latin run: group in a nowrap word so lines never break mid-word */
          if (!word) {
            word = document.createElement("span");
            word.className = "fx-word";
            frag.appendChild(word);
          }
          word.appendChild(charSpan(ch));
        } else {
          word = null;
          if (/\s/.test(ch)) frag.appendChild(document.createTextNode(ch));
          else frag.appendChild(charSpan(ch)); /* CJK: per-char, breakable */
        }
      });
      t.parentNode.replaceChild(frag, t);
    });
    return el.querySelectorAll(".fx-char");
  }
  var revealIO = new IntersectionObserver(function (es) {
    es.forEach(function (e) {
      if (!e.isIntersecting) return;
      revealIO.unobserve(e.target);
      e.target.classList.add("fx-in");
    });
  }, { threshold: 0.25 });
  function blurReveal(el) {
    if (REDUCED || el.__fx) return; el.__fx = 1;
    var chars = splitChars(el);
    var order = [];
    chars.forEach(function (c, i) { order.push(i); });
    /* Trionn stagger: {each, from:"random"} */
    for (var i = order.length - 1; i > 0; i--) {
      var k = (Math.random() * (i + 1)) | 0, t = order[i]; order[i] = order[k]; order[k] = t;
    }
    var each = Math.min(38, 700 / Math.max(chars.length, 1));
    order.forEach(function (idx, rank) {
      chars[idx].style.setProperty("--fxd", Math.round(rank * each) + "ms");
    });
    el.classList.add("fx-splitting");
    revealIO.observe(el);
  }

  /* ---------- 2. letter-roll hover ---------- */
  function letterRoll(el) {
    if (REDUCED || !FINE || el.__fxr) return; el.__fxr = 1;
    if (el.querySelector(".fxr")) return;
    var text = el.textContent;
    if (!text.trim() || el.children.length) return; /* only plain-text links */
    el.textContent = "";
    el.classList.add("fx-roll");
    graphemes(text).forEach(function (ch, i) {
      var w = document.createElement("span"); w.className = "fxr";
      var a = document.createElement("span"); a.textContent = ch;
      var b = document.createElement("span"); b.className = "fxb";
      b.textContent = ch; b.setAttribute("aria-hidden", "true");
      a.style.setProperty("--i", i); b.style.setProperty("--i", i);
      w.appendChild(a); w.appendChild(b); el.appendChild(w);
    });
  }

  /* ---------- 3. count-up ---------- */
  function countUp(el) {
    if (el.__fxc) return; el.__fxc = 1;
    var raw = el.textContent.trim();
    var m = raw.match(/^([^\d]*)([\d,.]+)(.*)$/);
    if (!m) return;
    var target = parseFloat(m[2].replace(/,/g, "")), dec = (m[2].split(".")[1] || "").length;
    var sep = m[2].indexOf(",") !== -1; /* only re-add separators if source had them */
    if (REDUCED || !isFinite(target)) return;
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return; io.unobserve(el);
        var t0 = performance.now(), dur = 1400;
        var id = addJob(function (now) {
          var p = Math.min(1, (now - t0) / dur);
          var v = target * (1 - Math.pow(1 - p, 4)); /* out-quart */
          var s = v.toFixed(dec);
          if (sep) s = s.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
          el.textContent = m[1] + s + m[3];
          if (p >= 1) setJob(id, false);
        });
      });
    }, { threshold: 0.5 });
    io.observe(el);
  }

  /* ---------- 4. marquee with drag ---------- */
  function marquee(el, speed) {
    if (el.__fxm) return; el.__fxm = 1;
    speed = speed || 0.5;
    var track = document.createElement("div");
    track.className = "fx-mq-track";
    while (el.firstChild) track.appendChild(el.firstChild);
    el.appendChild(track); el.classList.add("fx-marquee");
    var base = track.scrollWidth;
    if (!base) return;
    var copies = Math.max(2, Math.ceil((el.clientWidth * 2) / base));
    var orig = Array.prototype.slice.call(track.children);
    for (var k = 0; k < copies; k++)
      orig.forEach(function (c) {
        var d = c.cloneNode(true); d.setAttribute("aria-hidden", "true");
        track.appendChild(d);
      });
    var x = 0, vel = 0, dragging = false, lastX = 0, inView = true;
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { inView = e.isIntersecting; setJob(id, inView); });
    });
    io.observe(el);
    var id = addJob(function () {
      if (!dragging) { x -= REDUCED ? 0 : speed + vel; vel *= 0.94; }
      if (x <= -base) x += base;
      if (x > 0) x -= base;
      track.style.transform = "translateX(" + x.toFixed(2) + "px)";
    });
    if (FINE) {
      el.addEventListener("pointerdown", function (e) {
        dragging = true; lastX = e.clientX; el.setPointerCapture(e.pointerId);
      });
      el.addEventListener("pointermove", function (e) {
        if (!dragging) return;
        var dx = e.clientX - lastX; lastX = e.clientX; x += dx; vel = -dx * 0.4;
      });
      ["pointerup", "pointercancel"].forEach(function (ev) {
        el.addEventListener(ev, function () { dragging = false; });
      });
    }
  }

  /* ---------- 5. line draw ---------- */
  var lineIO = new IntersectionObserver(function (es) {
    es.forEach(function (e) {
      if (e.isIntersecting) { e.target.classList.add("fx-in"); lineIO.unobserve(e.target); }
    });
  }, { threshold: 0.3 });
  function lineDraw(el) { el.classList.add("fx-line"); lineIO.observe(el); }

  /* ---------- 6. fog shader (port of Trionn "FooterFog") ---------- */
  var FOG_FRAG =
    "precision highp float;uniform float T;uniform float M;uniform float H;" +
    "uniform vec2 R;uniform vec3 C1;uniform vec3 C2;uniform vec3 C3;" +
    "float hash(vec2 p){if(R.x<768.0){p=fract(p*vec2(.3183099,.3678794));" +
    "return fract(sin(p.x*12.9898+p.y*78.233)*43.75854);}else{" +
    "p=fract(p*vec2(127.34,311.7));p+=dot(p,p+19.19);return fract(p.x*p.y);}}" +
    "float vnoise(vec2 p){vec2 i=floor(p),f=fract(p),u=f*f*(3.-2.*f);" +
    "if(R.x<768.0){i=mod(i,100.0);}" +
    "return mix(mix(hash(i),hash(i+vec2(1,0)),u.x)," +
    "mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),u.x),u.y);}" +
    "float fbm(vec2 p){float v=0.,a=.5;for(int i=0;i<3;i++){v+=a*vnoise(p);" +
    "p=p*2.1+vec2(3.7,8.3);a*=.5;}return v;}" +
    "void main(){vec2 uv=gl_FragCoord.xy/R;float y=uv.y;float aspect=R.x/R.y;" +
    "float vMask=1.0-smoothstep(0.0,1.0,y);vMask=pow(vMask,0.22);" +
    "vMask*=1.0-smoothstep(0.95,1.0,y);" +
    "if(vMask<0.002){gl_FragColor=vec4(0.);return;}" +
    "float rise=T*0.07;float LOOP=32.0;float mA=mod(M,LOOP);" +
    "float mB=mod(M+LOOP*0.5,LOOP);float blend=abs(mod(M,LOOP)/LOOP-0.5)*2.0;" +
    "vec2 q,q2;if(R.x<768.0){float qY=(R.y-gl_FragCoord.y)/88.88;" +
    "q=vec2(gl_FragCoord.x/133.33,qY+rise);" +
    "q2=vec2(gl_FragCoord.x/153.84,qY*0.8444+rise*0.6);}else{" +
    "q=vec2(uv.x*aspect*3.0,(1.0-y)*4.5+rise);" +
    "q2=vec2(uv.x*aspect*2.6,(1.0-y)*3.8+rise*0.6);}" +
    "vec2 w1a=vec2(fbm(q2+vec2(0.0,mA*0.15)),fbm(q2+vec2(4.3,2.7+mA*0.10)));" +
    "float fA=fbm(q+1.4*w1a+vec2(0.0,mA*0.06));" +
    "vec2 w1b=vec2(fbm(q2+vec2(7.3,mB*0.15)),fbm(q2+vec2(1.8,5.4+mB*0.10)));" +
    "float fB=fbm(q+1.4*w1b+vec2(3.7,mB*0.06));" +
    "float f=mix(fA,fB,blend);f=max(0.0,f-0.36);f=smoothstep(0.0,0.36,f);" +
    "f=pow(f,0.85);float hoverGlow=H*0.42;f=clamp(f+H*0.14,0.0,1.0);" +
    "float baseFog=smoothstep(0.35,0.0,y)*0.14+smoothstep(0.18,0.0,y)*0.11;" +
    "float alpha=(f+baseFog+hoverGlow*vMask)*vMask*0.94;" +
    "alpha=clamp(alpha,0.0,0.82);" +
    "vec3 col=mix(C1,C2,pow(f,1.0));col=mix(col,C3,pow(f,2.2));" +
    "col=mix(col,C3*1.25,H*0.55*f);" +
    "gl_FragColor=vec4(col*alpha,alpha);}";
  function hex3(h) {
    var n = parseInt(h.slice(1), 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  }
  function fog(host, palette) {
    if (REDUCED || host.__fxf) return; host.__fxf = 1;
    palette = palette || {};
    var cv = document.createElement("canvas");
    cv.className = "fx-fog"; cv.setAttribute("aria-hidden", "true");
    host.classList.add("fx-fog-host");
    host.insertBefore(cv, host.firstChild);
    var gl = cv.getContext("webgl", { alpha: true, antialias: false, premultipliedAlpha: true });
    if (!gl) { cv.remove(); return; }
    function sh(type, src) {
      var s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) { return null; }
      return s;
    }
    var vs = sh(gl.VERTEX_SHADER, "attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}");
    var fs = sh(gl.FRAGMENT_SHADER, FOG_FRAG);
    if (!vs || !fs) { cv.remove(); return; }
    var pr = gl.createProgram();
    gl.attachShader(pr, vs); gl.attachShader(pr, fs); gl.linkProgram(pr);
    if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) { cv.remove(); return; }
    var buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]), gl.STATIC_DRAW);
    var loc = gl.getAttribLocation(pr, "p");
    gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    gl.useProgram(pr);
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    var uT = gl.getUniformLocation(pr, "T"), uR = gl.getUniformLocation(pr, "R"),
        uM = gl.getUniformLocation(pr, "M"), uH = gl.getUniformLocation(pr, "H");
    gl.uniform3fv(gl.getUniformLocation(pr, "C1"), hex3(palette.c1 || "#05070d"));
    gl.uniform3fv(gl.getUniformLocation(pr, "C2"), hex3(palette.c2 || "#1f2430"));
    gl.uniform3fv(gl.getUniformLocation(pr, "C3"), hex3(palette.c3 || "#47505f"));
    var dpr = Math.min(devicePixelRatio || 1, 1.5);
    function size() {
      var w = Math.max(1, host.clientWidth), h = Math.max(1, host.clientHeight);
      cv.width = w * dpr; cv.height = h * dpr;
      gl.viewport(0, 0, cv.width, cv.height);
    }
    size();
    new ResizeObserver(size).observe(host);
    var M = 0, Mt = 0, H = 0, Ht = 0, t0 = performance.now(), inView = true;
    if (FINE) {
      addEventListener("pointermove", function (e) { Mt = (e.clientX / innerWidth) * 8; }, { passive: true });
      host.addEventListener("pointerenter", function () { Ht = 1; });
      host.addEventListener("pointerleave", function () { Ht = 0; });
    }
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { inView = e.isIntersecting; setJob(id, inView); });
    });
    io.observe(host);
    var id = addJob(function (now) {
      M += (Mt - M) * 0.02 + 0.004; H += (Ht - H) * 0.06;
      gl.uniform1f(uT, (now - t0) / 1000);
      gl.uniform1f(uM, M); gl.uniform1f(uH, H);
      gl.uniform2f(uR, cv.width, cv.height);
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    });
  }

  /* ---------- 7. welding sparks (2D canvas, Trionn "touch the lines") ---------- */
  function sparks(host, color) {
    if (REDUCED || !FINE || host.__fxs) return; host.__fxs = 1;
    color = color || "#ffcf7d";
    var cv = document.createElement("canvas");
    cv.className = "fx-sparks"; cv.setAttribute("aria-hidden", "true");
    if (getComputedStyle(host).position === "static") host.style.position = "relative";
    host.appendChild(cv);
    var ctx = cv.getContext("2d");
    var dpr = Math.min(devicePixelRatio || 1, 2);
    function size() {
      cv.width = host.clientWidth * dpr; cv.height = host.clientHeight * dpr;
    }
    size(); new ResizeObserver(size).observe(host);
    var parts = [], cooldown = 0, px = -1, py = -1, moving = 0;
    host.addEventListener("pointermove", function (e) {
      var r = host.getBoundingClientRect();
      px = (e.clientX - r.left) * dpr; py = (e.clientY - r.top) * dpr; moving = 1;
      setJob(id, true);
    }, { passive: true });
    host.addEventListener("pointerleave", function () { px = py = -1; });
    function burst() {
      /* Trionn: 5-7 sparks per burst, weldCooldown 40-100ms */
      var n = 5 + ((Math.random() * 3) | 0);
      for (var i = 0; i < n; i++) {
        var a = -Math.PI / 2 + (Math.random() - 0.5) * 2.2;
        var sp = (2 + Math.random() * 5) * dpr;
        parts.push({ x: px, y: py, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp,
          life: 0, max: 24 + Math.random() * 26, seg: [] });
      }
    }
    var id = addJob(function () {
      ctx.clearRect(0, 0, cv.width, cv.height);
      cooldown--;
      if (moving && px >= 0 && cooldown <= 0) { burst(); cooldown = 3 + Math.random() * 4; }
      moving = 0;
      var alive = false;
      for (var i = parts.length - 1; i >= 0; i--) {
        var p = parts[i];
        p.life++;
        if (p.life > p.max) { parts.splice(i, 1); continue; }
        alive = true;
        p.vy += 0.18 * dpr; /* gravity */
        p.x += p.vx + (Math.random() - 0.5) * 1.6 * dpr; /* jitter = electric */
        p.y += p.vy;
        p.seg.push([p.x, p.y]);
        if (p.seg.length > 6) p.seg.shift();
        var t = 1 - p.life / p.max;
        ctx.strokeStyle = color;
        ctx.globalAlpha = t * 0.9;
        ctx.lineWidth = Math.max(1, 1.4 * dpr * t);
        ctx.beginPath();
        p.seg.forEach(function (s, k) { k ? ctx.lineTo(s[0], s[1]) : ctx.moveTo(s[0], s[1]); });
        ctx.stroke();
        ctx.globalAlpha = t;
        ctx.fillStyle = "#fff";
        ctx.fillRect(p.x - dpr, p.y - dpr, 2 * dpr, 2 * dpr);
      }
      ctx.globalAlpha = 1;
      if (!alive && !moving) setJob(id, false);
    });
    setJob(id, false);
  }

  /* ---------- 8. first-visit preloader (slot digits + border draw + corner plus) ---------- */
  function preloader(name) {
    if (REDUCED || sessionStorage.getItem("fx-pl-seen")) return;
    sessionStorage.setItem("fx-pl-seen", "1");
    var el = document.createElement("div");
    el.id = "fx-pl";
    el.innerHTML =
      '<div class="plbox">' +
      '<svg class="plborder" aria-hidden="true"><rect x="1" y="1" width="100%" height="100%" rx="3" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/></svg>' +
      ["tl","tr","bl","br"].map(function (c) {
        return '<svg class="plplus ' + c + '" viewBox="0 0 14 14" aria-hidden="true"><path d="M7 1v12M1 7h12" stroke="currentColor" stroke-width="1.5"/></svg>';
      }).join("") +
      '<div class="plname">' + name + '</div>' +
      '<div><span class="plslots"><span class="plcol">' +
      "0123456789".split("").map(function (d) { return "<div>" + d + "</div>"; }).join("") +
      '</span><span class="plcol">' +
      "0123456789".split("").map(function (d) { return "<div>" + d + "</div>"; }).join("") +
      '</span></span><span class="plpct">%</span></div></div>';
    document.body.appendChild(el);
    var rect = el.querySelector(".plborder rect");
    var cols = el.querySelectorAll(".plcol");
    var plus = el.querySelectorAll(".plplus");
    var t0 = performance.now(), dur = 1600;
    var id = addJob(function (now) {
      var p = Math.min(1, (now - t0) / dur);
      var e = 1 - Math.pow(1 - p, 3);
      var n = Math.round(e * 99);
      cols[0].style.transform = "translateY(" + (-Math.floor(n / 10) * 10) + "%)";
      cols[1].style.transform = "translateY(" + (-(n % 10) * 10) + "%)";
      rect.style.strokeDashoffset = String(1 - e);
      plus.forEach(function (pl) { pl.style.transform = "rotate(" + e * 360 + "deg)"; });
      if (p >= 1) {
        setJob(id, false);
        setTimeout(function () {
          el.classList.add("done");
          setTimeout(function () { el.remove(); }, 600);
        }, 150);
      }
    });
  }

  /* ---------- auto-wire via data attributes ---------- */
  function init(root) {
    root = root || document;
    root.querySelectorAll("[data-fx-reveal]").forEach(blurReveal);
    root.querySelectorAll("[data-fx-roll]").forEach(letterRoll);
    root.querySelectorAll("[data-fx-count]").forEach(countUp);
    root.querySelectorAll("[data-fx-marquee]").forEach(function (el) {
      marquee(el, parseFloat(el.getAttribute("data-fx-marquee")) || 0.5);
    });
    root.querySelectorAll("[data-fx-line]").forEach(lineDraw);
    root.querySelectorAll("[data-fx-fog]").forEach(function (el) {
      var p = (el.getAttribute("data-fx-fog") || "").split(",");
      fog(el, p.length === 3 ? { c1: p[0], c2: p[1], c3: p[2] } : null);
    });
    root.querySelectorAll("[data-fx-sparks]").forEach(function (el) {
      sparks(el, el.getAttribute("data-fx-sparks") || undefined);
    });
    root.querySelectorAll("[data-fx-ul]").forEach(function (el) { el.classList.add("fx-ul"); });
  }
  /* re-apply after i18n text swaps wiped split DOM (MarketDaily applyLang) */
  function refresh() {
    document.querySelectorAll("[data-fx-reveal]").forEach(function (el) {
      if (!el.querySelector(".fx-char")) {
        el.__fx = 0; el.classList.remove("fx-splitting", "fx-in");
        blurReveal(el);
      }
    });
    document.querySelectorAll("[data-fx-roll]").forEach(function (el) {
      if (!el.querySelector(".fxr")) {
        el.__fxr = 0; el.classList.remove("fx-roll");
        letterRoll(el);
      }
    });
  }
  window.FX = { init: init, refresh: refresh, blurReveal: blurReveal, letterRoll: letterRoll,
    countUp: countUp, marquee: marquee, fog: fog, sparks: sparks,
    lineDraw: lineDraw, preloader: preloader };
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", function () { init(); });
  else init();
})();
