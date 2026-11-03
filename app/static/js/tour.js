/* tour.js - three-step "How it works" card for the read-only demo.
   Loaded only in demo mode. It opens once per browser, and the banner
   button reopens it. Uses the hidden attribute and classes only, so it
   needs no inline style. Motion is skipped under reduced motion. */
(function () {
  "use strict";
  var tour = document.getElementById("tour");
  if (!tour) return;
  var STORAGE_KEY = "zyber-tour-seen";
  var steps = tour.querySelectorAll(".tour-step");
  var count = document.getElementById("tour-count");
  var title = document.getElementById("tour-title");
  var back = tour.querySelector('[data-tour="back"]');
  var next = tour.querySelector('[data-tour="next"]');
  var done = tour.querySelector('[data-tour="done"]');
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  var current = 0;
  var opener = null;

  // Storage can be blocked (private window, cleared site data). The tour then just shows again.
  function seen() {
    try { return window.localStorage.getItem(STORAGE_KEY) === "1"; } catch (e) { return false; }
  }
  function remember() {
    try { window.localStorage.setItem(STORAGE_KEY, "1"); } catch (e) { /* ignore */ }
  }

  function show(index) {
    current = index;
    for (var i = 0; i < steps.length; i++) steps[i].hidden = i !== index;
    count.textContent = String(index + 1);
    back.disabled = index === 0;
    next.hidden = index === steps.length - 1;
    done.hidden = index !== steps.length - 1;
  }

  function open(focus) {
    show(0);
    tour.classList.toggle("tour-animate", !reduce.matches);
    tour.hidden = false;
    // Opened by the visitor: move focus in. Opened on page load: leave focus where it is.
    if (focus) title.focus();
  }

  function close() {
    tour.hidden = true;
    remember();
    if (opener) opener.focus();
  }

  back.addEventListener("click", function () { if (current > 0) show(current - 1); });
  next.addEventListener("click", function () { if (current < steps.length - 1) show(current + 1); });
  done.addEventListener("click", close);
  tour.querySelector('[data-tour="close"]').addEventListener("click", close);
  tour.addEventListener("keydown", function (event) {
    if (event.key === "Escape") close();
  });

  var buttons = document.querySelectorAll('[data-tour="open"]');
  for (var i = 0; i < buttons.length; i++) {
    buttons[i].hidden = false;
    buttons[i].addEventListener("click", function (event) {
      opener = event.currentTarget;
      open(true);
    });
  }

  if (!seen()) open(false);
})();
