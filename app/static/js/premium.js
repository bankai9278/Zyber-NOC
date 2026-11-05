/* premium.js - cursor, scroll and reveal effects. No dependencies.
   Every effect is skipped when the user prefers reduced motion. */
(function () {
  "use strict";
  var root = document.documentElement;
  var systemReduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  /* A visitor whose system asks for reduced motion can turn motion back on
     with the footer switch. The choice is kept in this browser only. */
  var motionOn = false;
  try { motionOn = localStorage.getItem("zyber-motion") === "on"; } catch (err) { motionOn = false; }
  if (systemReduce && motionOn) root.classList.add("motion-on");
  var reduce = { matches: systemReduce && !motionOn };
  root.classList.add("fx-js");
  /* Lite mode for phones, tablets, slow PCs and data saver: the same effects,
     minus the costly glows (see "Lite mode" in effects.css). */
  var conn = navigator.connection || {};
  if (window.matchMedia("(pointer: coarse)").matches || conn.saveData ||
      (navigator.hardwareConcurrency || 8) <= 4 || (navigator.deviceMemory || 8) <= 4) {
    root.classList.add("fx-lite");
  }

  /* ---- Footer switch: shown only when the system asks for reduced motion ---- */
  var motionToggle = document.querySelector("[data-motion-toggle]");
  if (motionToggle && systemReduce) {
    motionToggle.setAttribute("aria-pressed", motionOn ? "true" : "false");
    motionToggle.textContent = motionOn ? "Animations: on" : "Animations: off (system setting)";
    motionToggle.hidden = false;
    motionToggle.addEventListener("click", function () {
      try {
        localStorage.setItem("zyber-motion", motionOn ? "off" : "on");
        window.location.reload();
      } catch (err) {
        motionToggle.textContent = "Animations: this browser blocks saving the choice";
      }
    });
  }

  /* ---- Page transitions: skip them when motion is reduced ---- */
  function skipTransition(e) { if (reduce.matches && e.viewTransition) e.viewTransition.skipTransition(); }
  window.addEventListener("pageswap", skipTransition);
  window.addEventListener("pagereveal", skipTransition);

  /* ---- Scroll: progress bar + shrinking header ----
     Variables are set on the element that uses them, never on <html>: a custom
     property on the root makes the browser restyle the whole page each frame. */
  var ticking = false;
  var progressBar = document.querySelector(".fx-progress span");
  var scrolled = null;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () {
      var max = root.scrollHeight - window.innerHeight;
      var p = max > 0 ? Math.min(1, window.scrollY / max) : 0;
      if (progressBar) progressBar.style.setProperty("--progress", p.toFixed(4));
      var now = window.scrollY > 24;
      if (now !== scrolled) { scrolled = now; root.classList.toggle("is-scrolled", now); }
      ticking = false;
    });
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---- Reveal on scroll with a small stagger per group ---- */
  var revealItems = Array.prototype.slice.call(document.querySelectorAll("[data-reveal]"));
  if (reduce.matches || !("IntersectionObserver" in window)) {
    revealItems.forEach(function (el) { el.classList.add("is-visible"); });
  } else {
    revealItems.forEach(function (el) {
      var siblings = el.parentElement ? el.parentElement.querySelectorAll(":scope > [data-reveal]") : [];
      var index = Array.prototype.indexOf.call(siblings, el);
      if (index > 0) el.style.setProperty("--reveal-delay", Math.min(index, 6) * 90 + "ms");
    });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          io.unobserve(entry.target);
        }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.12 });
    revealItems.forEach(function (el) { io.observe(el); });
  }

  /* ---- Animated counters (final value is already in the HTML) ---- */
  var counters = document.querySelectorAll("[data-counter]");
  function runCounter(el) {
    var target = parseInt(el.getAttribute("data-counter"), 10);
    if (isNaN(target) || target <= 0) return;
    var start = performance.now();
    var duration = Math.min(1600, 600 + target * 20);
    function frame(now) {
      var t = Math.min(1, (now - start) / duration);
      var eased = 1 - Math.pow(1 - t, 3);
      el.textContent = String(Math.round(target * eased));
      if (t < 1) requestAnimationFrame(frame);
      else el.textContent = String(target);
    }
    el.textContent = "0";
    requestAnimationFrame(frame);
  }
  if (!reduce.matches && "IntersectionObserver" in window && counters.length) {
    var cio = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) { runCounter(entry.target); cio.unobserve(entry.target); }
      });
    }, { threshold: 0.6 });
    Array.prototype.forEach.call(counters, function (el) { cio.observe(el); });
  }

  /* ---- Donut sweep on the reports page ---- */
  var donut = document.querySelector(".donut-ok");
  if (donut && !reduce.matches) {
    var dash = parseFloat(donut.getAttribute("stroke-dasharray")) || 0;
    donut.style.setProperty("stroke-dashoffset", String(dash));
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { donut.style.setProperty("stroke-dashoffset", "0"); });
    });
  }

  /* ---- Typing effect for the hero command ---- */
  var typed = document.querySelector("[data-type]");
  if (typed && !reduce.matches) {
    var text = typed.getAttribute("data-type");
    var i = 0;
    typed.textContent = "";
    var out = typed.closest(".hero-terminal") ? typed.closest(".hero-terminal").querySelector(".term-out") : null;
    if (out) out.style.setProperty("visibility", "hidden");
    setTimeout(function step() {
      i += 1;
      typed.textContent = text.slice(0, i);
      if (i < text.length) setTimeout(step, 45 + Math.random() * 55);
      else if (out) setTimeout(function () { out.style.removeProperty("visibility"); }, 260);
    }, 700);
  }

  if (reduce.matches) return;
  function isMouse(e) { return e.pointerType === "mouse" || e.pointerType === "pen"; }

  /* ---- Cursor: page spotlight + card border glow ----
     The glow only shows on the hovered card, so only that card gets new
     values. Setting them on every card restyled whole tables on each move. */
  var glowSelector = ".glow-card, .panel, .summary li";
  var mouse = { x: 0, y: 0 }, pending = false, hovered = null;
  var followers = document.querySelectorAll(".fx-spotlight");
  function paint() {
    pending = false;
    for (var f = 0; f < followers.length; f++) {
      followers[f].style.setProperty("--mx", mouse.x + "px");
      followers[f].style.setProperty("--my", mouse.y + "px");
    }
    if (hovered) {
      var r = hovered.getBoundingClientRect();
      hovered.style.setProperty("--gx", (mouse.x - r.left) + "px");
      hovered.style.setProperty("--gy", (mouse.y - r.top) + "px");
    }
  }
  window.addEventListener("pointermove", function (e) {
    if (!isMouse(e)) return;
    mouse.x = e.clientX; mouse.y = e.clientY;
    hovered = e.target.closest ? e.target.closest(glowSelector) : null;
    root.classList.add("fx-pointer");
    if (!pending) { pending = true; requestAnimationFrame(paint); }
  }, { passive: true });
  document.addEventListener("pointerleave", function () { root.classList.remove("fx-pointer"); });

})();
