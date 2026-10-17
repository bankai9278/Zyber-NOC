(function () {
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || form.tagName !== "FORM") {
      return;
    }
    var button = form.querySelector("[type='submit']");
    if (!button || button.disabled) {
      return;
    }
    var label = button.getAttribute("data-loading-label");
    if (label) {
      button.textContent = label;
    }
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    form.setAttribute("aria-busy", "true");
  });
})();
