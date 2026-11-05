/* live.js - keep the dashboard and topology current without a reload.
   Every 45 seconds, while the tab is visible, it asks /api/dashboard for
   the saved results (the same public JSON the Refresh button uses: no
   addresses when signed out). When a newer result has arrived, it updates
   the page in place and sends a sonar ring out from each device in its
   status colour. Reduced motion: the page still updates, with no ring.
   No HTML is injected; elements are built with createElementNS. */
(function () {
  var root = document.documentElement;
  var light = document.querySelector("[data-live-light]");
  var source = document.querySelector("[data-live-url]");
  if (!source || !window.fetch) return;

  var POLL_MS = 45000;
  var RING_MS = 1700;
  var SVG = "http://www.w3.org/2000/svg";
  var COLORS = { online: "#73bf69", offline: "#f2495c", unknown: "#5a5a5a", error: "#ff9830" };
  var url = source.getAttribute("data-live-url");
  var latest = source.getAttribute("data-live-latest") || "";
  var timer = null;
  var busy = false;

  function motionAllowed() {
    var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    return !reduced || root.classList.contains("motion-on");
  }

  function each(list, fn) { Array.prototype.forEach.call(list, fn); }

  /* The header light: live while the newest result is inside the window. */
  function paintLight() {
    if (!light || light.classList.contains("live-demo") || !latest) return;
    var seconds = Math.max(0, (Date.now() - Date.parse(latest)) / 1000);
    var windowMinutes = Number(light.getAttribute("data-window")) || 10;
    var isLive = seconds <= windowMinutes * 60;
    var minutes = Math.floor(seconds / 60);
    var age = seconds < 60 ? "just now" : minutes + (minutes === 1 ? " minute ago" : " minutes ago");
    light.classList.toggle("live-live", isLive);
    light.classList.toggle("live-offline", !isLive);
    var label = light.querySelector("[data-live-label]");
    var text = isLive ? "live \u00b7 " + age : light.getAttribute("data-offline-label");
    if (label && label.textContent !== text) label.textContent = text;
  }

  function schedule() {
    paintLight();
    clearTimeout(timer);
    if (!document.hidden) timer = setTimeout(poll, POLL_MS);
  }

  function poll() {
    if (busy || document.hidden) return;
    busy = true;
    fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        if (data && typeof data.last_updated_at === "string" && data.last_updated_at > latest) {
          latest = data.last_updated_at;
          apply(data);
        }
      })
      .catch(function () { /* Try again on the next tick. */ })
      .then(function () { busy = false; schedule(); });
  }

  function apply(data) {
    // The dashboard script redraws its own table and counts from this event.
    document.dispatchEvent(new CustomEvent("zyber:live-data", { detail: data }));
    var devices = data.devices || [];
    var topo = document.querySelector(".topology-svg");
    if (topo) updateTopology(topo, devices);
    var stamp = document.getElementById("last-updated");
    if (stamp && typeof data.last_updated === "string") stamp.textContent = data.last_updated;
    if (motionAllowed()) {
      if (topo) ringTopology(topo, devices);
      ringDashboard();
    }
  }

  /* ---- Topology: recolour changed nodes, links, halos, and flows ---- */
  function updateTopology(svg, devices) {
    devices.forEach(function (device) {
      var status = COLORS[device.status] ? device.status : "unknown";
      var node = svg.querySelector('.topo-node[data-node="' + device.id + '"]');
      if (!node || node.classList.contains("topo-" + status)) return;
      ["online", "offline", "error", "unknown"].forEach(function (name) { node.classList.remove("topo-" + name); });
      node.classList.add("topo-" + status);
      var box = node.querySelector("rect:not(.topo-halo):not(.live-ring)");
      if (!box) return;
      box.setAttribute("fill", COLORS[status]);
      box.setAttribute("stroke", COLORS[status]);
      each(node.querySelectorAll("text"), function (text) {
        text.setAttribute("fill", status === "unknown" ? "#ffffff" : "#111217");
      });
      var halo = node.querySelector(".topo-halo");
      if (status === "offline" && !halo) {
        halo = document.createElementNS(SVG, "rect");
        halo.setAttribute("class", "topo-halo");
        halo.setAttribute("aria-hidden", "true");
        halo.setAttribute("x", Number(box.getAttribute("x")) - 5);
        halo.setAttribute("y", Number(box.getAttribute("y")) - 5);
        halo.setAttribute("width", Number(box.getAttribute("width")) + 10);
        halo.setAttribute("height", Number(box.getAttribute("height")) + 10);
        halo.setAttribute("rx", "8");
        halo.setAttribute("fill", "none");
        node.insertBefore(halo, box);
      } else if (status !== "offline" && halo) {
        halo.remove();
      }
      var edge = svg.querySelector('.topology-edge[data-edge-child="' + device.id + '"]');
      if (!edge) return;
      edge.setAttribute("data-status", status);
      var flow = svg.querySelector('.topology-flow[data-flow-child="' + device.id + '"]');
      if (status === "online" && !flow) {
        flow = document.createElementNS(SVG, "line");
        flow.setAttribute("class", "topology-flow");
        flow.setAttribute("aria-hidden", "true");
        flow.setAttribute("data-flow-child", device.id);
        ["x1", "y1", "x2", "y2"].forEach(function (name) { flow.setAttribute(name, edge.getAttribute(name)); });
        flow.setAttribute("stroke-width", "3");
        edge.parentNode.insertBefore(flow, edge.nextSibling);
      } else if (status !== "online" && flow) {
        flow.remove();
      }
    });
  }

  /* ---- Sonar rings ---- */
  function ringTopology(svg, devices) {
    devices.forEach(function (device) {
      var node = svg.querySelector('.topo-node[data-node="' + device.id + '"]');
      var box = node && node.querySelector("rect:not(.topo-halo):not(.live-ring)");
      if (!box) return;
      var ring = document.createElementNS(SVG, "rect");
      ["x", "y", "width", "height"].forEach(function (name) { ring.setAttribute(name, box.getAttribute(name)); });
      ring.setAttribute("rx", "6");
      ring.setAttribute("fill", "none");
      ring.setAttribute("aria-hidden", "true");
      ring.setAttribute("class", "live-ring live-" + (COLORS[device.status] ? device.status : "unknown"));
      node.appendChild(ring);
      setTimeout(function () { ring.remove(); }, RING_MS);
    });
  }

  function ringDashboard() {
    each(document.querySelectorAll("[data-dashboard] .status"), function (badge) {
      badge.classList.remove("live-ping");
      void badge.offsetWidth; /* Restart the animation if it is still running. */
      badge.classList.add("live-ping");
      setTimeout(function () { badge.classList.remove("live-ping"); }, RING_MS);
    });
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) clearTimeout(timer);
    else poll();
  });
  schedule();
})();
