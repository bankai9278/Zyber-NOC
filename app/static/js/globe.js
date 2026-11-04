/* globe.js - the topology as a 3D globe, drawn with Three.js (vendored in
   static/vendor, no CDN). Loaded only when someone presses "Show 3D globe".
   It reads the saved devices from the 2D map already on the page, so it
   shows exactly what the server drew: same devices, links and status colours.
   Depth in the tree becomes latitude (roots at the top), and the 2D map's
   left-to-right order becomes longitude. */
import * as THREE from "../vendor/three.module.min.js";

var COLORS = { online: 0x3ef08a, offline: 0xff4d6a, error: 0xffa53d, unknown: 0x8a9893 };

function readTopology(svg) {
  var width = parseFloat(svg.getAttribute("width")) || 1;
  var nodes = [];
  var byId = {};
  svg.querySelectorAll(".topo-node").forEach(function (link) {
    var rect = link.querySelector("rect:not(.topo-halo)");
    var status = (link.getAttribute("class").match(/topo-(online|offline|error|unknown)/) || [])[1] || "unknown";
    var title = link.querySelector("title");
    var node = {
      id: link.getAttribute("data-node"),
      parent: link.getAttribute("data-parent") || null,
      status: status,
      name: title ? title.textContent : "",
      href: link.getAttribute("href"),
      x: (parseFloat(rect.getAttribute("x")) + parseFloat(rect.getAttribute("width")) / 2) / width,
      y: parseFloat(rect.getAttribute("y")),
    };
    nodes.push(node);
    byId[node.id] = node;
  });
  var rows = Array.from(new Set(nodes.map(function (n) { return n.y; }))).sort(function (a, b) { return a - b; });
  nodes.forEach(function (n) { n.depth = rows.indexOf(n.y); });
  return { nodes: nodes, byId: byId, depths: rows.length };
}

function onSphere(lat, lon, radius) {
  return new THREE.Vector3(
    radius * Math.cos(lat) * Math.sin(lon),
    radius * Math.sin(lat),
    radius * Math.cos(lat) * Math.cos(lon)
  );
}

export function mountGlobe(container, svg, options) {
  var reduce = options.reduce;
  var lite = options.lite;
  var data = readTopology(svg);
  var canvas = document.createElement("canvas");
  canvas.className = "globe-canvas";
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "3D globe of " + data.nodes.length + " saved devices. The 2D map below lists the same devices.");
  container.appendChild(canvas);
  var tip = document.createElement("p");
  tip.className = "globe-tip mono";
  tip.hidden = true;
  container.appendChild(tip);

  var renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: !lite, alpha: true, powerPreference: "low-power" });
  } catch (err) {
    canvas.remove();
    return null;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, lite ? 1 : 1.75));

  var scene = new THREE.Scene();
  var camera = new THREE.PerspectiveCamera(40, 1, 0.1, 50);
  camera.position.set(0, 0.3, 3.3);
  camera.lookAt(0, 0, 0);
  var world = new THREE.Group();
  scene.add(world);

  /* Wireframe globe: latitude and longitude lines every 20 degrees. */
  var gridPoints = [];
  var steps = lite ? 36 : 72;
  for (var latDeg = -60; latDeg <= 60; latDeg += 20) {
    for (var i = 0; i < steps; i++) {
      gridPoints.push(onSphere(latDeg * Math.PI / 180, i / steps * Math.PI * 2, 1));
      gridPoints.push(onSphere(latDeg * Math.PI / 180, (i + 1) / steps * Math.PI * 2, 1));
    }
  }
  for (var lonDeg = 0; lonDeg < 360; lonDeg += 20) {
    for (var j = 0; j < steps / 2; j++) {
      var a = -Math.PI / 2 + j / (steps / 2) * Math.PI;
      var b = -Math.PI / 2 + (j + 1) / (steps / 2) * Math.PI;
      gridPoints.push(onSphere(a, lonDeg * Math.PI / 180, 1));
      gridPoints.push(onSphere(b, lonDeg * Math.PI / 180, 1));
    }
  }
  world.add(new THREE.LineSegments(
    new THREE.BufferGeometry().setFromPoints(gridPoints),
    new THREE.LineBasicMaterial({ color: 0x3ef0a5, transparent: true, opacity: 0.12 })
  ));
  world.add(new THREE.Mesh(
    new THREE.SphereGeometry(0.985, 32, 16),
    new THREE.MeshBasicMaterial({ color: 0x07110e, transparent: true, opacity: 0.85 })
  ));

  /* Devices. */
  var nodeGeometry = new THREE.SphereGeometry(0.045, 16, 12);
  var meshes = [];
  data.nodes.forEach(function (n) {
    var lat = (70 - n.depth * (data.depths > 1 ? 120 / (data.depths - 1) : 0)) * Math.PI / 180;
    var lon = n.x * Math.PI * 2;
    n.position = onSphere(lat, lon, 1.02);
    var mesh = new THREE.Mesh(nodeGeometry, new THREE.MeshBasicMaterial({ color: COLORS[n.status] }));
    mesh.position.copy(n.position);
    mesh.userData = n;
    world.add(mesh);
    meshes.push(mesh);
    if (n.status === "offline") {
      var ring = new THREE.Mesh(
        new THREE.RingGeometry(0.06, 0.075, 24),
        new THREE.MeshBasicMaterial({ color: COLORS.offline, transparent: true, side: THREE.DoubleSide })
      );
      ring.position.copy(n.position);
      ring.lookAt(n.position.clone().multiplyScalar(2));
      ring.userData.pulse = true;
      world.add(ring);
      n.ring = ring;
    }
  });

  /* Links as arcs above the surface, with a packet on links to online devices. */
  var packets = [];
  data.nodes.forEach(function (child) {
    var parent = data.byId[child.parent];
    if (!parent) return;
    var mid = parent.position.clone().add(child.position).multiplyScalar(0.5);
    mid.setLength(1.02 + 0.25 * parent.position.distanceTo(child.position));
    var curve = new THREE.QuadraticBezierCurve3(parent.position, mid, child.position);
    var color = child.status === "online" ? 0x3ef0a5 : COLORS[child.status];
    world.add(new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(curve.getPoints(32)),
      new THREE.LineBasicMaterial({ color: color, transparent: true, opacity: child.status === "online" ? 0.55 : 0.35 })
    ));
    if (child.status === "online" && !reduce) {
      var dot = new THREE.Mesh(new THREE.SphereGeometry(0.018, 8, 6), new THREE.MeshBasicMaterial({ color: 0xb8ffe0 }));
      dot.userData = { curve: curve, offset: Math.random() };
      world.add(dot);
      packets.push(dot);
    }
  });

  world.rotation.x = 0.25;

  /* Drag to turn. Auto-turn only when motion is allowed. */
  var drag = null;
  var spin = reduce ? 0 : 0.0016;
  canvas.addEventListener("pointerdown", function (e) {
    drag = { x: e.clientX, y: e.clientY, rx: world.rotation.x, ry: world.rotation.y };
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointerup", function (e) {
    if (drag && Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) < 4) openHovered();
    drag = null;
  });
  canvas.addEventListener("pointercancel", function () { drag = null; });

  var raycaster = new THREE.Raycaster();
  var pointer = new THREE.Vector2();
  var hovered = null;
  canvas.addEventListener("pointermove", function (e) {
    var r = canvas.getBoundingClientRect();
    if (drag) {
      world.rotation.y = drag.ry + (e.clientX - drag.x) * 0.008;
      world.rotation.x = Math.max(-1.2, Math.min(1.2, drag.rx + (e.clientY - drag.y) * 0.006));
      requestRender();
      return;
    }
    pointer.x = (e.clientX - r.left) / r.width * 2 - 1;
    pointer.y = -(e.clientY - r.top) / r.height * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    var hit = raycaster.intersectObjects(meshes)[0];
    hovered = hit ? hit.object.userData : null;
    canvas.classList.toggle("is-hot", !!hovered);
    if (hovered) {
      tip.textContent = hovered.name + " - " + hovered.status;
      tip.hidden = false;
      tip.style.setProperty("transform", "translate(" + (e.clientX - r.left + 12) + "px," + (e.clientY - r.top + 12) + "px)");
    } else {
      tip.hidden = true;
    }
  });
  canvas.addEventListener("pointerleave", function () { tip.hidden = true; hovered = null; });
  function openHovered() { if (hovered && hovered.href) window.location.href = hovered.href; }

  function resize() {
    var w = container.clientWidth;
    var h = Math.round(Math.min(520, Math.max(300, w * 0.6)));
    renderer.setSize(w, h, false);
    canvas.style.setProperty("height", h + "px");
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    requestRender();
  }

  var visible = true;
  var looping = false;
  function frame(now) {
    looping = false;
    if (!drag) world.rotation.y += spin;
    var t = now / 1000;
    packets.forEach(function (dot) {
      dot.position.copy(dot.userData.curve.getPoint((t * 0.35 + dot.userData.offset) % 1));
    });
    data.nodes.forEach(function (n) {
      if (!n.ring) return;
      var p = reduce ? 0.5 : (t * 0.6) % 1;
      n.ring.scale.setScalar(1 + p * 1.2);
      n.ring.material.opacity = 0.9 * (1 - p);
    });
    renderer.render(scene, camera);
    if (!reduce && visible && !document.hidden) loop();
  }
  function loop() { if (!looping) { looping = true; requestAnimationFrame(frame); } }
  function requestRender() { loop(); }

  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) { visible = entries[0].isIntersecting; if (visible) loop(); }).observe(canvas);
  }
  document.addEventListener("visibilitychange", function () { if (!document.hidden) loop(); });
  window.addEventListener("resize", resize);
  resize();
  return { destroy: function () { renderer.dispose(); canvas.remove(); tip.remove(); } };
}
