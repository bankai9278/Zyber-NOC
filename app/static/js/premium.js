/* premium.js - cursor, scroll and reveal effects. No dependencies.
   Every effect is skipped when the user prefers reduced motion. */
(function () {
  "use strict";
  var root = document.documentElement;
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  root.classList.add("fx-js");

  /* ---- Scroll: progress bar + shrinking header ---- */
  var ticking = false;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () {
      var max = root.scrollHeight - window.innerHeight;
      var p = max > 0 ? Math.min(1, window.scrollY / max) : 0;
      root.style.setProperty("--progress", p.toFixed(4));
      root.classList.toggle("is-scrolled", window.scrollY > 24);
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
      /* Wait for the boot intro (effects.js) to finish before typing. */
      if (root.classList.contains("is-booting")) {
        document.addEventListener("zyber:booted", function () { setTimeout(step, 400); }, { once: true });
        return;
      }
      i += 1;
      typed.textContent = text.slice(0, i);
      if (i < text.length) setTimeout(step, 45 + Math.random() * 55);
      else if (out) setTimeout(function () { out.style.removeProperty("visibility"); }, 260);
    }, 700);
  }

  if (reduce.matches) return;
  function isMouse(e) { return e.pointerType === "mouse" || e.pointerType === "pen"; }

  /* ---- Cursor: page spotlight + card border glow ---- */
  var glowCards = document.querySelectorAll(".glow-card, .panel, .summary li");
  var mouse = { x: 0, y: 0 }, pending = false;
  function paint() {
    pending = false;
    root.style.setProperty("--mx", mouse.x + "px");
    root.style.setProperty("--my", mouse.y + "px");
    for (var k = 0; k < glowCards.length; k++) {
      var r = glowCards[k].getBoundingClientRect();
      if (mouse.y < r.top - 300 || mouse.y > r.bottom + 300) continue;
      glowCards[k].style.setProperty("--gx", (mouse.x - r.left) + "px");
      glowCards[k].style.setProperty("--gy", (mouse.y - r.top) + "px");
    }
  }
  window.addEventListener("pointermove", function (e) {
    if (!isMouse(e)) return;
    mouse.x = e.clientX; mouse.y = e.clientY;
    root.classList.add("fx-pointer");
    if (!pending) { pending = true; requestAnimationFrame(paint); }
  }, { passive: true });
  document.addEventListener("pointerleave", function () { root.classList.remove("fx-pointer"); });

  /* ---- Magnetic primary buttons ---- */
  document.querySelectorAll("[data-magnetic], .page-heading .button.primary").forEach(function (btn) {
    btn.addEventListener("pointermove", function (e) {
      if (!isMouse(e)) return;
      var r = btn.getBoundingClientRect();
      var dx = e.clientX - (r.left + r.width / 2);
      var dy = e.clientY - (r.top + r.height / 2);
      btn.style.setProperty("transform", "translate(" + (dx * 0.25).toFixed(1) + "px," + (dy * 0.35).toFixed(1) + "px)");
    });
    btn.addEventListener("pointerleave", function () { btn.style.removeProperty("transform"); });
  });

  /* ---- 3D tilt on feature figures ---- */
  document.querySelectorAll("[data-tilt]").forEach(function (card) {
    card.addEventListener("pointermove", function (e) {
      if (!isMouse(e)) return;
      var r = card.getBoundingClientRect();
      var px = (e.clientX - r.left) / r.width - 0.5;
      var py = (e.clientY - r.top) / r.height - 0.5;
      card.style.setProperty("--ry", (px * 7).toFixed(2) + "deg");
      card.style.setProperty("--rx", (-py * 6).toFixed(2) + "deg");
    });
    card.addEventListener("pointerleave", function () {
      card.style.setProperty("--ry", "0deg");
      card.style.setProperty("--rx", "0deg");
    });
  });
})();
