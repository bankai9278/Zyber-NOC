/* effects.js - scroll story, hero network field, living topology hover,
   app-page reveals, dashboard count-up, and optional interface sounds. No dependencies. Text changes use textContent and nodeValue only.
   Every moving effect is skipped when the user prefers reduced motion. */
(function () {
  "use strict";
  var root = document.documentElement;
  /* site.js adds motion-on when the visitor overrides reduced motion. */
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches && !root.classList.contains("motion-on");
  var each = function (list, fn) { Array.prototype.forEach.call(list, fn); };

  /* ---- Living topology: hover or focus a device to light its path to the root ---- */
  var topo = document.querySelector(".topology-svg");
  if (topo) {
    var nodesById = {};
    each(topo.querySelectorAll(".topo-node"), function (node) { nodesById[node.getAttribute("data-node")] = node; });
    var clearPath = function () {
      topo.classList.remove("has-path");
      each(topo.querySelectorAll(".is-path"), function (el) { el.classList.remove("is-path"); });
    };
    var showPath = function (node) {
      clearPath();
      var guard = 0;
      while (node && guard < 200) {
        node.classList.add("is-path");
        var id = node.getAttribute("data-node");
        var edge = topo.querySelector('.topology-edge[data-edge-child="' + id + '"]');
        if (edge) edge.classList.add("is-path");
        node = nodesById[node.getAttribute("data-parent")];
        guard += 1;
      }
      topo.classList.add("has-path");
    };
    each(topo.querySelectorAll(".topo-node"), function (node) {
      node.addEventListener("pointerenter", function () { showPath(node); });
      node.addEventListener("pointerleave", clearPath);
    });
    topo.addEventListener("focusin", function (e) {
      var node = e.target.closest && e.target.closest(".topo-node");
      if (node) showPath(node);
    });
    topo.addEventListener("focusout", clearPath);
  }

  /* ---- Optional interface sounds: off by default, remembered per browser ---- */
  var toggle = document.querySelector("[data-sound-toggle]");
  var soundOn = false;
  var audio = null;
  function blip(freq, length) {
    if (!soundOn) return;
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      var osc = audio.createOscillator();
      var gain = audio.createGain();
      var now = audio.currentTime;
      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, now);
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(0.035, now + 0.005);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + length);
      osc.connect(gain).connect(audio.destination);
      osc.start(now);
      osc.stop(now + length + 0.02);
    } catch (err) { /* No Web Audio: stay silent. */ }
  }
  if (toggle && (window.AudioContext || window.webkitAudioContext)) {
    try { soundOn = localStorage.getItem("zyber-sound") === "on"; } catch (err) { soundOn = false; }
    var paintToggle = function () {
      toggle.setAttribute("aria-pressed", soundOn ? "true" : "false");
      toggle.textContent = "Interface sound: " + (soundOn ? "on" : "off");
    };
    paintToggle();
    toggle.hidden = false;
    toggle.addEventListener("click", function () {
      soundOn = !soundOn;
      try { localStorage.setItem("zyber-sound", soundOn ? "on" : "off"); } catch (err) { /* not remembered */ }
      paintToggle();
      blip(880, 0.12);
    });
    document.addEventListener("pointerdown", function (e) {
      if (e.target === toggle || !e.target.closest) return;
      if (e.target.closest("a, button, summary, select")) blip(1320, 0.05);
    });
  }

  if (reduce) return;

  /* ---- Reveal app-page panels that start below the fold (no flicker above it) ---- */
  if ("IntersectionObserver" in window && document.body.classList.contains("page-app")) {
    var below = [];
    each(document.querySelectorAll("main .panel, main .legend"), function (el) {
      if (el.hasAttribute("data-reveal") || el.closest("[data-reveal]")) return;
      if (el.getBoundingClientRect().top > window.innerHeight) below.push(el);
    });
    var rio = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) { entry.target.classList.add("is-visible"); rio.unobserve(entry.target); }
      });
    }, { rootMargin: "0px 0px -6% 0px", threshold: 0.08 });
    below.forEach(function (el) { el.setAttribute("data-reveal", ""); rio.observe(el); });
  }

  /* ---- Dashboard count-up: animates only to the saved number already shown ---- */
  each(document.querySelectorAll(".summary-value[data-count]"), function (el) {
    var target = parseInt(el.textContent, 10);
    if (isNaN(target) || target <= 0 || String(target) !== el.textContent.trim()) return;
    var start = performance.now();
    var duration = Math.min(1200, 500 + target * 25);
    var last = "0";
    el.textContent = last;
    function frame(now) {
      if (el.textContent !== last) return; /* Refresh wrote a newer value: stop. */
      var t = Math.min(1, (now - start) / duration);
      last = String(t < 1 ? Math.round(target * (1 - Math.pow(1 - t, 3))) : target);
      el.textContent = last;
      if (t < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  });

  /* ---- Scroll story: the rail fills and each step lights up as you pass it ---- */
  var story = document.querySelector("[data-story]");
  if (story) {
    root.classList.add("fx-story");
    var rail = story.querySelector(".story-rail");
    var steps = story.querySelectorAll(".story-step");
    /* The path figure: the packet goes PC -> router -> device and back, and the
       readout names what is happening at the step you are reading. */
    var pingPath = story.querySelector(".ping-path");
    var pingPacket = pingPath && pingPath.querySelector(".ping-packet");
    var pingReadout = pingPath && pingPath.querySelector(".ping-readout");
    var latency = pingPath && pingPath.getAttribute("data-latency");
    /* Out to the device by step 3, back during the reply, faded while lost, home to be saved. */
    var pingKeys = [[0, 70], [0.17, 280], [0.33, 530], [0.5, 300], [0.67, 300], [0.83, 70], [1, 70]];
    var pingLabels = {
      request: "echo request \u00b7 TTL 128",
      router: "forwarded by the router \u00b7 TTL 127",
      reply: latency ? "echo reply \u00b7 " + latency + " ms" : "echo reply \u00b7 latency measured",
      timeout: "no reply in 1000 ms = packet loss",
      store: "result saved to SQLite",
      live: "shown on the dashboard"
    };
    var pingX = function (p) {
      for (var i = 1; i < pingKeys.length; i++) {
        if (p <= pingKeys[i][0]) {
          var a = pingKeys[i - 1], b = pingKeys[i];
          return a[1] + (b[1] - a[1]) * ((p - a[0]) / (b[0] - a[0]));
        }
      }
      return pingKeys[pingKeys.length - 1][1];
    };
    var queued = false;
    var paintStory = function () {
      queued = false;
      var r = story.getBoundingClientRect();
      var focus = window.innerHeight * 0.6;
      var p = Math.max(0, Math.min(1, (focus - r.top) / Math.max(1, r.height)));
      story.style.setProperty("--story", p.toFixed(4));
      story.style.setProperty("--story-px", (p * rail.offsetHeight).toFixed(1) + "px");
      var phase = "request";
      each(steps, function (step) {
        var active = step.getBoundingClientRect().top < focus;
        step.classList.toggle("is-active", active);
        if (active && step.getAttribute("data-phase")) phase = step.getAttribute("data-phase");
      });
      if (pingPacket) {
        pingPacket.setAttribute("cx", pingX(p).toFixed(1));
        pingPacket.classList.toggle("is-reply", phase === "reply" || phase === "store" || phase === "live");
        pingPath.classList.toggle("is-lost", phase === "timeout");
        var label = pingLabels[phase] || pingLabels.request;
        if (pingReadout.textContent !== label) pingReadout.textContent = label;
      }
    };
    var queueStory = function () { if (!queued) { queued = true; requestAnimationFrame(paintStory); } };
    window.addEventListener("scroll", queueStory, { passive: true });
    window.addEventListener("resize", queueStory);
    paintStory();
  }

  /* ---- Hero network field: drifting nodes that link up near the mouse ---- */
  var canvas = document.querySelector(".hero-field");
  var conn = navigator.connection || {};
  /* Data saver: skip the field. Few cores or little memory: start smaller. */
  var lowEnd = (navigator.hardwareConcurrency || 8) <= 4 || (navigator.deviceMemory || 8) <= 4;
  var ctx = canvas && canvas.getContext && !conn.saveData ? canvas.getContext("2d") : null;
  if (ctx) {
    root.classList.add("fx-field");
    var hero = canvas.parentElement;
    var points = [];
    var size = { w: 0, h: 0 };
    var pointer = { x: -9999, y: -9999 };
    var running = false;
    var inView = true;
    var LINK = 120;
    var coarse = window.matchMedia("(pointer: coarse)").matches;
    var cap = 70;
    var frames = 0, slow = 0, lastFrame = 0;
    var resize = function () {
      var ratio = Math.min(window.devicePixelRatio || 1, lowEnd || coarse ? 1.5 : 2);
      size.w = hero.clientWidth;
      size.h = hero.clientHeight;
      canvas.width = Math.round(size.w * ratio);
      canvas.height = Math.round(size.h * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      var want = Math.max(12, Math.min(lowEnd ? 35 : 70, Math.round(size.w * size.h / (lowEnd ? 40000 : 20000))));
      want = Math.min(want, cap);
      while (points.length < want) {
        points.push({ x: Math.random() * size.w, y: Math.random() * size.h, vx: (Math.random() - 0.5) * 0.25, vy: (Math.random() - 0.5) * 0.25 });
      }
      points.length = want;
    };
    /* If frames keep taking over 30 ms, draw fewer points; below 12, stop. */
    var adapt = function (now) {
      if (lastFrame) {
        frames += 1;
        if (now - lastFrame > 30) slow += 1;
        if (frames === 60) {
          if (slow > 30) {
            cap = Math.floor(points.length * 0.6);
            if (cap < 12) { running = false; root.classList.remove("fx-field"); return false; }
            points.length = cap;
          }
          frames = 0; slow = 0;
        }
      }
      lastFrame = now;
      return true;
    };
    var draw = function (now) {
      if (!running || !adapt(now)) return;
      ctx.clearRect(0, 0, size.w, size.h);
      for (var i = 0; i < points.length; i++) {
        var a = points[i];
        a.x += a.vx; a.y += a.vy;
        if (a.x < 0 || a.x > size.w) a.vx *= -1;
        if (a.y < 0 || a.y > size.h) a.vy *= -1;
        for (var j = i + 1; j < points.length; j++) {
          var b = points[j];
          var d = Math.hypot(a.x - b.x, a.y - b.y);
          if (d < LINK) {
            ctx.strokeStyle = "rgba(62, 240, 165, " + (0.16 * (1 - d / LINK)).toFixed(3) + ")";
            ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
        }
        var m = Math.hypot(a.x - pointer.x, a.y - pointer.y);
        if (m < LINK * 1.5) {
          ctx.strokeStyle = "rgba(107, 247, 189, " + (0.45 * (1 - m / (LINK * 1.5))).toFixed(3) + ")";
          ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(pointer.x, pointer.y); ctx.stroke();
        }
        ctx.fillStyle = m < LINK * 1.5 ? "rgba(107, 247, 189, .9)" : "rgba(62, 240, 165, .45)";
        ctx.beginPath(); ctx.arc(a.x, a.y, 1.6, 0, Math.PI * 2); ctx.fill();
      }
      requestAnimationFrame(draw);
    };
    var update = function () {
      var should = inView && !document.hidden;
      if (should && !running && root.classList.contains("fx-field")) { running = true; lastFrame = 0; requestAnimationFrame(draw); }
      if (!should) running = false;
    };
    resize();
    /* Phones fire resize while the address bar slides; only redo a real change. */
    window.addEventListener("resize", function () {
      if (hero.clientWidth !== size.w || Math.abs(hero.clientHeight - size.h) > 80) resize();
    });
    hero.addEventListener("pointermove", function (e) {
      if (e.pointerType !== "mouse" && e.pointerType !== "pen") return;
      var r = hero.getBoundingClientRect();
      pointer.x = e.clientX - r.left; pointer.y = e.clientY - r.top;
    }, { passive: true });
    hero.addEventListener("pointerleave", function () { pointer.x = -9999; pointer.y = -9999; });
    document.addEventListener("visibilitychange", update);
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) { inView = entries[0].isIntersecting; update(); }).observe(hero);
    }
    update();
  }

  /* ---- GSAP scroll scenes on the home page (desktop, full motion only) ----
     gsap.min.js and ScrollTrigger.min.js are vendored in static/vendor and
     are fetched only here, so other pages and phones never download them. */
  var vendor = (document.currentScript || document.querySelector('script[src*="js/effects.js"]')).src.replace(/js\/effects\.js.*$/, "vendor/");
  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var tag = document.createElement("script");
      tag.src = src;
      tag.onload = resolve;
      tag.onerror = reject;
      document.body.appendChild(tag);
    });
  }
  if (document.body.classList.contains("page-home") && !root.classList.contains("fx-lite")) {
    loadScript(vendor + "gsap.min.js").then(function () {
      return loadScript(vendor + "ScrollTrigger.min.js");
    }).then(function () {
      var gsap = window.gsap;
      gsap.registerPlugin(window.ScrollTrigger);
      root.classList.add("fx-gsap");
      var hero = document.querySelector(".hero");
      gsap.to(".hero-grid", { yPercent: -12, opacity: 0.35, ease: "none", scrollTrigger: { trigger: hero, start: "top top", end: "bottom top", scrub: true } });
      gsap.to(".hero-field", { yPercent: 18, ease: "none", scrollTrigger: { trigger: hero, start: "top top", end: "bottom top", scrub: true } });
      document.querySelectorAll(".feature-figure img").forEach(function (img) {
        gsap.fromTo(img, { scale: 1.12 }, { scale: 1, ease: "none", scrollTrigger: { trigger: img.parentElement, start: "top bottom", end: "center center", scrub: true } });
      });
      document.querySelectorAll(".feature-copy h3").forEach(function (title) {
        gsap.fromTo(title, { xPercent: -6, letterSpacing: "0.08em" }, { xPercent: 0, letterSpacing: "-0.02em", ease: "none", scrollTrigger: { trigger: title, start: "top bottom", end: "top 55%", scrub: true } });
      });
      gsap.fromTo(".cta-inner", { scale: 0.92 }, { scale: 1, ease: "none", scrollTrigger: { trigger: ".cta-band", start: "top bottom", end: "center center", scrub: true } });
      gsap.to(".stack-grid", { yPercent: -4, ease: "none", scrollTrigger: { trigger: ".stack", start: "top bottom", end: "bottom top", scrub: true } });
    }).catch(function () { /* Without GSAP the page keeps its CSS reveals. */ });
  }

  /* ---- Pause CSS loops while their section is off screen ---- */
  if ("IntersectionObserver" in window) {
    var pio = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) { entry.target.classList.toggle("fx-paused", !entry.isIntersecting); });
    });
    each(document.querySelectorAll(".hero, .cta-band, .topology-wrap, .arch-figure"), function (el) { pio.observe(el); });
  }
})();
