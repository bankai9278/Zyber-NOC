# AI handoff: Zyber NOC

Use this file when continuing the project in a new chat. Read it before changing code. `README.md` is the portfolio description. This file is the working context.

Owner: Yash Oza. Role: researcher and beginner. Explain decisions in plain language. Keep the app small enough to understand.

Project folder:

`C:\Users\yash3\Desktop\network-monitoring-dashboard`

## What this project is

A local Windows portfolio app for junior network technician and IT support roles. It stores devices the user chooses, pings only those saved addresses with Windows `ping`, saves each result in SQLite, and shows the latest status on a dashboard.

It is a learning prototype on this PC. It is not a production monitor.

## Rules that must stay in place

- Local Windows only. Bind to `127.0.0.1`. Do not add login, cloud hosting, Docker, or extra infrastructure unless a concrete defect requires it. The one exception, approved by the user on Nov 2, 2026, is the read-only demo (item 27): a public copy may be hosted only with `ZYBER_DEMO_MODE` on. Never host normal mode.
- Do not scan subnets, discover hosts, accept hostnames, or contact arbitrary systems. Ping, TCP-check, or SNMP-poll only devices already saved in the inventory. TCP ports are only 22, 53, 80, 443, and 3389. SNMP is read-only GetNext on the configured SNMP port (161 by default).
- Use parameterized SQL (`?` placeholders). Never build SQL by string concatenation.
- Keep CSRF checks on state-changing forms. Do not add Flask-WTF.
- Never call `subprocess` with `shell=True`. The ping command must be a list of arguments.
- Validate the IP before building the ping command. Block broadcast, multicast, unspecified, and reserved addresses. Allow loopback (`127.0.0.1` and `::1`).
- Do not add a JavaScript framework or new dependencies unless the user asks. `requirements.txt` is only `Flask==3.1.3` and `pytest==9.1.1`.
- Do not invent statuses, counts, performance numbers, screenshots, or test results. A device with no saved check is Unknown.
- Do not weaken a test to make it pass. Do not claim tests passed unless they were run in that session.
- Do not commit, push, or publish unless the user asks.

## Stack

| Piece | Choice |
|---|---|
| Language | Python. This PC has Python 3.15.0. The project asks for 3.11 or newer. |
| Web | Flask 3.1.3, app factory `create_app()` |
| Database | SQLite through the standard library. File: `instance/monitor.db` |
| UI | Server-rendered HTML. Styles load `style.css`, then `theme-terminal.css`, then `premium.css`, then `effects.css`. Scripts are `dashboard.js`, `forms.js`, `premium.js`, `effects.js`, and, in demo mode only, `tour.js` |
| Tests | pytest 9.1.1 |
| Virtual environment | `.venv` in the project folder. Use `.\.venv\Scripts\python.exe`. Do not install packages globally. |

## How to run and stop

From PowerShell, in the project folder:

```powershell
cd C:\Users\yash3\Desktop\network-monitoring-dashboard
.\.venv\Scripts\python.exe run.py
```

Leave that window open. Open `http://127.0.0.1:5000/`. That is the landing page. The device dashboard is `http://127.0.0.1:5000/devices`.

`ERR_CONNECTION_REFUSED` on port 5000 means the Flask process is not running. Start it with the command above. Debug mode is off. Stop the server with Ctrl+C in that window.

Health check: `http://127.0.0.1:5000/health` returns JSON `status: ok` and `application: network-monitoring-dashboard`.

Tests do not need the server, and they must not send real pings:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The last full run, after SNMP polling (Nov 3, 2026), was 321 passed and 0 failed (pytest 9.1.1, Python 3.15.0). Re-run pytest before claiming a newer result.

## What is already built

1. Flask entry point, config, requirements, gitignore, README, and tests.
2. SQLite inventory and monitoring history, with validation and safe database errors.
3. Pages to list, add, view, and delete devices. Delete asks for confirmation and removes that device and its history. If the deleted device is a parent, its children's `parent_id` is set to null. Children are not deleted.
4. Dashboard with real counts: total, online, offline, unknown, and error. The error card exists because a saved status can be `error`, and the counts must add up to the total.
5. Windows ping for one authorized device, with careful parsing of Windows `ping` output.
6. Check now for one device, and Check all with a batch limit, a concurrency limit, a cooldown, and a process-wide lock.
7. Security pass: blocked special-use addresses, CSRF, a local session secret, safe 500 page, security headers including `Content-Security-Policy: default-src 'self'`, and extra tests. If `instance/secret_key` cannot be written, the app uses `secrets.token_hex(32)` in memory.
8. Portfolio README. The home page shows three static images of the dashboard, device page, and topology. They are illustrations, not a live view of the database.
9. Uptime percentage and average response time, calculated only from saved results. Unknown when a device has no results.
10. Status-change rows when a new result's status differs from the previous result. The dashboard shows the 10 newest.
11. Optional location (100 characters) and VLAN (1–4094). The dashboard can filter the table by location, VLAN, or both. Summary counts stay global.
12. TCP port check for a saved device on ports 22, 53, 80, 443, or 3389, using `socket.create_connection` with a 2 second timeout. Results use the same status, response-time, and error rules as ping.
13. Optional scheduled Check all. Default off. Minimum interval 1 minute. It reuses the batch limit, cooldown, and lock, and waits one interval before the first run.
14. Inline SVG latency chart on the device page from the last 20 saved checks. The line is the median. A shaded band is drawn from min to max where both were saved. Each point is coloured from that check's packet loss: 0% is `#6e9fff`, 1–20% is `#ff9830`, over 20% is `#f2495c`. A null loss uses `#8e8e9a` and is not treated as 0. A row with only `response_time_ms` still plots, with no band.
15. CSV download of one device's history. Timestamps in the file stay UTC. Cells that start with `=`, `+`, `-`, `@`, or a tab or carriage return get a leading quote.
16. GitHub Actions workflow `.github/workflows/tests.yml` on `windows-latest`. The README badge points at `bankai9278/Zyber-NOC`.
17. Recent incidents on the dashboard, built only from saved status changes whose new status is offline or error. The latest 10 are shown. Each row has the device name, the change such as `online -> offline`, the America/Toronto time, and the outage duration until the next saved change back to online. If that recovery is not saved, the duration says `ongoing`. The same list is included in `GET /api/dashboard` as `incidents`.
18. Group by on the devices page. The GET query `group` accepts `location` or `vlan`. Any other value, including an empty value, leaves the flat table. Each group is a `<details>` section. The header counts only the devices in that group. Devices with no location or VLAN are in `Unassigned`, listed last. Location groups sort alphabetically, ignoring letter case. VLAN groups sort numerically. Location and VLAN filters still apply first, and summary counts stay global.
19. Edit device at `GET/POST /devices/<id>/edit`. The form uses the same validation as add, including the IP and VLAN rules, and the same CSRF check. A successful save redirects to the device page with the flash message `Device updated.` Invalid input is shown again with the entered values. A missing device returns 404. Changing the IP, parent, or any other field updates only the device row. Monitoring results and status changes stay as they were.
20. Parent device. `devices.parent_id` is a nullable foreign key to `devices.id`, with `ON DELETE SET NULL`. Add and edit forms have a Parent device dropdown. Blank means none. The edit list does not offer the device itself. Saving rejects a self-parent with `A device cannot be its own parent.` and a loop of any length with `That parent would create a loop.` A missing parent is `Parent device does not exist.` When a device's latest saved status is offline and its parent's latest saved status is also offline, the badge says `Unreachable via <parent name>` in the unknown colour. That is a display label. The stored status stays offline, so summary counts still count it as offline. In recent incidents, a child incident says `caused by parent outage` when the parent's latest monitoring result at or before that incident time is offline.
21. Topology map at `GET /topology`, linked from the main navigation. It is a server-rendered inline SVG tree from `parent_id`. Devices with no parent, or a missing parent, are roots on the top row. Children sit below their parent with straight lines. Each node shows a short type label, name, and IP, and links to `/devices/<id>`. Fill and border use the latest saved status colour. No saved check uses the unknown colour `#5a5a5a`. The legend shows the status colours. With no devices the page says `Add devices and set parent devices to build the map.`
22. Ping sends 5 echo requests. Each saved ping can store `min_ms`, `median_ms`, `max_ms`, `jitter_ms`, and `packet_loss_pct`. `response_time_ms` is the median. Jitter is the mean absolute difference between consecutive replies, in reply order, rounded half up. It is null when fewer than two replies were saved. No replies store null latency fields and packet loss 100. An error stores null loss and does not invent a percentage. The device page has Jitter and Packet loss cards from the latest saved ping row: Unknown when that device has no results, Not measured when the value is null. CSV adds those five columns after `error_details`.
23. Status history. The device page shows 90 blocks, one America/Toronto day, oldest on the left. The devices list shows a compact 30-day bar on each row, including after Refresh. Colour is the worst saved status that day: offline, then error, then online. A day with no checks is `#2a2d33`. The title is like `Nov 2, 2026 - Online (17 checks)` or `Nov 2, 2026 - Offline 2 times, first at 7:12 PM`. Under the 90-day bar: `90 days ago`, the window uptime, and `Today`. That uptime counts only checks inside the 90 days. It says `No data` when there are none. It is not the all-time uptime card. One grouped SQL query loads the page: results in the UTC window are grouped by device, status, and timestamp second, with `COUNT(*)` and `MIN(recorded_at)`. Python then places those groups on Toronto days. SQLite has no America/Toronto zone, so the query is not one query per day and it does not group by a UTC date.
24. Cyber terminal theme in `app/static/css/theme-terminal.css`. `base.html` loads it immediately after `style.css`. It does not replace `style.css`. The visible name is Zyber NOC. In the header and footer, `ZYBER` uses the heading colour and `NOC` uses the mint accent `#3ef0a5`. Both are in the mono font. The landing page shows this tagline under the brand: `Network operations centre, built from ping to topology.` Do not change that name unless the user asks. The project folder, Python package, routes, database, and file names stay `network-monitoring-dashboard`. Colours are mint accent `#3ef0a5`, online `#3ef08a`, offline `#ff4d6a`, unknown `#5e6b67`, and error `#ffa53d` on the dark page. The topology SVG sets `width` and `height` from the layout so one device is not stretched, and connector lines use the `topology-edge` class so the theme can colour them. No inline styles were added. The content security policy stays `default-src 'self'`.
25. Public site pages in the `site` blueprint, `app/routes/site.py`. `GET /` is the landing page. `GET /reports` is a 30-day reliability report. `GET /about` explains the project. These routes only read saved rows through the existing database and presentation helpers. They do not ping, write, or invent a count. With no saved checks the pages say so. `GITHUB_URL` in `site.py` is `https://github.com/bankai9278/Zyber-NOC`. `LINKEDIN_URL` is `https://www.linkedin.com/in/yash-oza-it/`. Both are injected into every template. Templates are `app/templates/site/home.html`, `reports.html`, `about.html`, `_icons.html`, and `_network.html`. Styles and motion are `app/static/css/premium.css` and `app/static/js/premium.js`, loaded after the theme. The home page also shows three static images: `app/static/img/shot-dashboard.png`, `shot-detail.png`, and `shot-topology.png`, plus `favicon.svg`. Those images are illustrations, not live data. `premium.js` sets CSS variables from script. It does not use `innerHTML` or inline style attributes. Cursor spotlight, card glow, scroll reveal, the progress bar, and counters run only when the browser does not request reduced motion. When `prefers-reduced-motion: reduce` matches, including Windows "Show animations" off, the page shows the final numbers immediately and does not animate. Navigation is Home, Dashboard, Topology, Reports, About, and Add device.
26. About page rewrite and initials logo. `app/templates/site/about.html` is written in first person as Yash Oza, a networking graduate from Mohawk College in Hamilton, Ontario. Sections: hero with heading `About Zyber NOC`, three "Why I built it" cards, "Where it started" (the Mohawk team project), "How it helped me", the existing architecture diagram (`One request, end to end.`), grouped skill chips, "What's next", and a contact card. The old guardrails and "Built in layers" sections were removed from that page; their CSS (`.timeline`) is still in `premium.css`. Facts about the team project are only these, supplied by Yash: NETTRIO - Network Design Proposal for Skyline Paralegal, a 5-person team, Yash's role design specialist; a new 7-floor office for 473 employees across 11 departments; Cisco Catalyst 9500F core on floor 7, Catalyst 9200L distribution on each floor, Catalyst 2960L access, Ubiquiti UniFi U6 Pro APs, FortiGate 100F firewall, Dell PowerEdge R750 and R550 servers; Cat6a horizontal and OM3 multimode fibre risers following TIA/EIA-568; VLANs by department; left and right trunks 29,671 Mb/s and 31,739 Mb/s; $174,171.28 total acquisition. Do not add dates, grades, certifications, employers, or numbers beyond those. Certifications such as the CCNA are goals, not held. The hierarchy figure is a self-drawn inline SVG that reuses the `arch-*` classes, with mono labels from `.hier-svg`. The stat strip uses `stat-row stat-row-4`; 7, 473, and 11 use `data-counter`, so they count up only when motion is allowed. The logo is `app/static/img/logo-yo.svg`: a hand-written `YO` monogram, mint `#3ef0a5` strokes on transparent in a rounded square, with title `Yash Oza logo`. `base.html` uses it as the favicon, at 24px in the header link before ZYBER NOC (`.brand-logo`), and at 24px in the footer next to `Built by Yash Oza` (`.footer-built`). The About hero shows it at 96px (`.about-logo`, 72px under 40rem) with a mint drop-shadow on hover. Every `<img>` of it has `alt="Yash Oza logo"`. The old `favicon.svg` file is still on disk but is no longer linked. `GITHUB_URL` is `https://github.com/bankai9278/Zyber-NOC`.
27. Read-only demo mode for a public copy. `Config.DEMO_MODE` is off by default and turns on only when the environment variable `ZYBER_DEMO_MODE` is `1`, `true`, `yes`, or `on` (any case, spaces trimmed). `TestConfig` forces it off so tests turn it on themselves. When it is on, `create_app` calls `seed_demo_database` in `app/demo.py`, which rebuilds `DEMO_DATABASE_PATH` (`instance/demo.db`) through a temporary file and `os.replace`, and the app reads only that file; `instance/monitor.db` is not opened. The sample has 8 devices named `Sample ...` with the description `Sample data for the demo. Not a real device.`, on documentation ranges `192.0.2.0/24`, `198.51.100.0/24`, and `203.0.113.0/24`, and 90 days of ping rows (6 a day) from a fixed `random.Random(2026)` seed, with status-change rows for each change. Latest states: floor 2 switch offline, its access point offline (so it shows Unreachable via), the printer error, the lab workstation never checked (Unknown), the rest online. Dates follow the start time. A `before_request` hook, registered before the CSRF check, returns a 403 `Read-only demo` page for any method other than GET, HEAD, or OPTIONS, and for the endpoints in `DEMO_BLOCKED_ENDPOINTS` in `app/__init__.py` (add form, create, edit, delete confirm and delete, check, check port, check all). `scheduled_interval_seconds` returns None and `run_scheduled_checks` returns `"demo"` without checking. Templates get `demo_mode`: `base.html` shows a banner on every page (`Every device, status, and number here is sample data, not a live reading.`), hides the Add device link, and changes the footer note. The dashboard, device page, and home page hide Check now, Check all, Check port, Edit, Delete, and Add device; the dashboard row shows View instead. `GET /api/dashboard` adds `sample_data: true` only in demo mode. History CSV still downloads. Banner style is `.demo-banner` at the end of `premium.css`. Tests are in `tests/test_demo.py`; they replace `subprocess.run`, `subprocess.Popen`, and `socket.create_connection` with functions that fail the test. README has hosting notes: PythonAnywhere through its WSGI file with no new dependency, and Render, which would need `gunicorn` added to `requirements.txt` (not added). `.claude/launch.json` has a `zyber-noc-demo-5051` preview entry that starts the demo on port 5051.
28. README top section (Nov 3, 2026). The README opens with the Tests badge, the live demo link `https://zybernoc.pythonanywhere.com` (read-only, sample data), a short pitch, and a 2x2 table of four real screenshots in `docs/screenshots/` (`dashboard.png`, `device.png`, `topology.png`, `home.png`). They were captured at 1440x1000 with headless Edge from the app running locally in demo mode (`zyber-noc-demo-5051`), so every value in them is sample data. Recapture them the same way after a visible change; never edit or mock them. `tests/test_readme.py` checks the link, that each referenced file exists and is a PNG, and that the sample-data note is there.
29. "How it works" tour, demo mode only (Nov 3, 2026). `base.html` includes `app/templates/_tour.html` and loads `app/static/js/tour.js` only when `demo_mode` is on. The tour is a floating card (`role="dialog"`, not modal) in the bottom-right with three steps: sample data, how one check is saved, and where to look. It is `hidden` in the HTML, so it never appears without its script. `tour.js` opens it once per browser (localStorage key `zyber-tour-seen`, wrapped in try/catch, so a blocked store just shows it again), and a `How it works` button in the demo banner reopens it. Close, Got it, and Escape close it and remember that. Auto-open leaves focus alone; opening from the button moves focus to the title and returns it on close. The script toggles `hidden` and classes only (no `innerHTML`, no inline style). The slide-in animation (`.tour-animate` in `premium.css`) is skipped when `prefers-reduced-motion: reduce` matches; the tour itself still shows, because it is information, not motion. The step text avoids the words `Check now`, which `tests/test_demo.py` requires to be absent in demo mode. Tests: `tests/test_tour.py`.
30. Outage alerts (Nov 3, 2026). `app/alerts.py`. Off by default: `Config.ALERTS_ENABLED` reads `ZYBER_ALERTS` with the same on/off rule as demo mode, and `alerts_enabled` is always False when `DEMO_MODE` is on. An alert is a saved result whose status differs from the previous result and is `offline` or `error` (same rule as an incident). The first saved result and a recovery to online never alert. `save_monitoring_result` now also returns `previous_status` (None for a first result). `_store_check` in `app/routes/devices.py` calls `_alert_on_outage` after a successful save; any exception there is swallowed so a check never fails because of an alert. Each alert appends one line to `ALERT_LOG_PATH` (`instance/alerts.log`, git-ignored with `instance/`), such as `<UTC time> ALERT Zyber NOC: Core switch (10.0.0.2) is offline`. Email is optional, through stdlib `smtplib` (no new dependency), only when `ZYBER_SMTP_HOST`, `ZYBER_ALERT_FROM`, and `ZYBER_ALERT_TO` are set; port `ZYBER_SMTP_PORT` (default 587), STARTTLS on unless `ZYBER_SMTP_STARTTLS` is 0/false/no/off, optional login from `ZYBER_SMTP_USERNAME` and `ZYBER_SMTP_PASSWORD`, 10 second timeout. Email is sent on a daemon thread. A failure logs `EMAIL FAILED <error type>` and never the password or server reply. Why this default: the log file works with no account or network, and email is the common next step that still needs nothing outside the standard library. `TestConfig` forces alerts off and blanks every SMTP setting. Tests: `tests/test_alerts.py` replaces `smtplib.SMTP` with a recorder or a function that fails the test, and runs the background send inline. The About page still lists "Add alerting when a status changes." under What's next; that is Yash's own text and was left for him to update.
31. Phone layout (Nov 3, 2026). One section at the end of `app/static/css/premium.css`, headed `Phone layout`, inside `@media (max-width: 42rem)`. It was checked in the running app at 360, 375, and 430px wide, in demo mode and normal mode, on Home, Dashboard (flat and grouped, before and after Refresh), device page, Topology, Reports, About, add/edit/delete forms, the demo banner, and the tour. What it does: the header is not sticky on phones and the nav links wrap instead of running off the right edge; page gutters are 1rem; form fields are 16px so iOS does not zoom on focus; summary cards are a 2-column grid with Total across the top; the status-change strip stacks; filters are a 2-column grid; every table (dashboard and device history) becomes one card per row with the label on the left and the value on the right; the device page's details grid is 2 columns with Description full width, and the 90-day bar uses 1px gaps; the tour is a bottom sheet across the screen. Wide drawings keep a readable size and scroll sideways in their own box instead of shrinking: the topology SVG keeps its drawn width inside `.topology-wrap`, and the two About diagrams are 52rem wide inside `.arch-figure`. Each has a `.scroll-hint` line (`Swipe sideways to see the whole map.` or `...whole diagram.`) that is hidden above 42rem; the empty topology has no hint. The section adds no animation or transition, so reduced motion is unchanged, and no inline styles or scripts. Two bugs fixed on the way: `.table-wrap` is now `position: relative`, because the absolute visually hidden labels in table cells escaped its scroll box and gave the page a sideways scrollbar between phone and desktop widths (about 1024px); and `dashboard.js` now reads `sample_data` from `/api/dashboard`, so in demo mode Refresh rebuilds rows with a View link instead of bringing back Check now, Edit, and Delete. Tests: `tests/test_mobile.py`.
32. Design effects pass (Nov 3, 2026). From the design ideas Jay approved. Front end only, plus two display keys in `topology_map`: each node now has `status` (unknown when the saved status is not one of the four) and `parent_id`, and each edge has `parent_id`, `child_id`, and the child's `status`. Files: `app/static/css/effects.css` (loaded after `premium.css`), `app/static/js/effects.js` (loaded after `premium.js`), and `app/static/img/grain.svg` (an SVG noise tile, because the CSP blocks `data:` URLs). `base.html` adds `.fx-texture` and `.fx-cursor` divs, an `overlay` block before `<main>`, and a hidden `Interface sound: off` button in the footer. What each piece does: page transitions are CSS `@view-transition` only, with the header kept still; a fixed texture layer adds faint scanlines and grain with `pointer-events: none`; the topology draws moving dots (`.topology-flow`, a dash animation) only on links whose child's latest saved status is online, dashes offline and error links in their colour, and pulses a halo (`.topo-halo`) around offline nodes; hovering or focusing a node lights its path to the root and dims the rest. Edge lines keep the exact class `topology-edge` (a test checks it) and carry `data-status` instead. The home page has a boot intro (`#boot`, in the `overlay` block so it covers the header): hidden in the HTML, shown by `effects.js` once per browser session (`sessionStorage` key `zyber-boot-seen`; blocked storage skips it), about 2 seconds, closed early by Skip intro, any click, or any key. Its lines come from saved totals; in demo mode one says `read-only demo: no checks will run`. While it runs `html.is-booting` holds the hero reveal and `premium.js` waits for the `zyber:booted` event before typing. Every `main h1` scrambles through random characters for under a second, then settles; the real text stays in the DOM and in a temporary `aria-label`. The four home steps are a scroll story: a rail on the left fills and a packet dot moves as you scroll, and each step's dot lights when you pass it; without script or with reduced motion the rail is full. The home hero has a canvas field of drifting nodes that link up near the mouse; it pauses when the hero is off screen or the tab is hidden, uses at most 70 points, and caps the pixel ratio at 2. A cursor ring follows the mouse only under `(hover: hover) and (pointer: fine)`, keeps the normal cursor, and grows over links and buttons. The hero ghost buttons are magnetic too. Dashboard summary numbers count up from 0 to the saved value on load and stop if Refresh writes a newer number. App-page panels that start below the fold reveal on scroll; panels already in view are never hidden first. Interface sound is off by default: the footer button turns it on (localStorage `zyber-sound`), and clicks then play a short Web Audio tone with no audio files. Reduced motion: `effects.js` returns before the field, story, count-up, panel reveal, and cursor code, and skips the boot intro and the headline scramble; `effects.css` ends with a block that turns off view transitions, topology dots and the pulse, the boot intro, the field, the cursor ring, and the packet dot. The topology hover path and the sound toggle still work, because they are not motion. Skipped from the ideas list: the WebGL/Three.js 3D globe and the GSAP scroll engine, which both need a library and the user's OK. Checked in the running app with headless Edge at 1440x900 and at 375x812 with touch, in demo and normal mode, with motion on and with reduced motion, on Home, Dashboard (flat and grouped), device pages, Topology, Reports, About, and the add, edit and delete forms: no page scrolled sideways and there were no console errors. Tests: `tests/test_effects.py`.

33. Animations switch (Nov 3, 2026). When the system asks for reduced motion (Windows "Animation effects" off), the footer shows `Animations: off (system setting)`. Clicking it stores `zyber-motion=on` in localStorage and reloads; `premium.js` then adds `html.motion-on`, and every rule inside a `prefers-reduced-motion: reduce` block in the four stylesheets is scoped to `html:not(.motion-on)` (a test walks every such block). `premium.js`, `effects.js`, and `tour.js` treat motion as allowed when that class is set. Page transitions under reduced motion are skipped from `premium.js` on `pageswap` and `pagereveal`, because an `@view-transition` rule cannot check a class. With no reduced-motion request the switch stays hidden.
34. Speed pass (Nov 3, 2026). Measured with headless Edge, CPU throttled 6x at 375x812 with touch and 4x at 1440x900. Scrolling frames per second before and after: phone home 11 to 30, dashboard 5 to 60, About 16 to 56, topology 32 to 62; desktop home 15 to 33, dashboard 24 to 56, About 23 to 58. Causes and fixes: `premium.js` set `--progress` and `--mx`/`--my` on `<html>`, which restyled the whole page on every scroll and mouse frame; they now go on the progress bar, spotlight, and cursor ring only, and `is-scrolled` changes only when it flips (a test forbids `root.style.setProperty`). The card glow now updates only the hovered card instead of every card near the mouse. `html.fx-lite` (coarse pointer, data saver, 4 or fewer cores, or 4 GB or less memory) drops the `drop-shadow` glows on the hero illustration and topology, stops the node halo, and keeps only the scanlines of the texture. Loops in the hero, CTA band, topology, and About diagrams pause while off screen (`.fx-paused`). The hero field skips data saver, starts smaller on slow devices, caps the pixel ratio at 1.5 on touch, ignores phone resize events from the address bar, and drops points (or stops) if frames keep taking over 30 ms. The topology dots lost their drop-shadow filter.

35. SNMP interface polling (Nov 3, 2026). Jay asked for it with a simulator, because there are no test switches. `app/snmp.py` encodes and decodes SNMP v2c by hand (BER over UDP, standard library only, no new dependency) and only sends GetNext. `poll_interfaces` walks the IF-MIB columns ifDescr, ifOperStatus, and ifHCInOctets/ifHCOutOctets (falling back to ifInOctets/ifOutOctets, stored as `counter_bits` 32), at most 48 interfaces, 2 second reply timeout with one retry, 15 second total limit. Replies are matched on sender IP, request id, and community. A Windows connection reset on a closed port counts as no reply. Settings: `SNMP_COMMUNITY` from `ZYBER_SNMP_COMMUNITY` (default `public`), `SNMP_PORT` from `ZYBER_SNMP_PORT` (default 161; only for the simulator). Tables `snmp_polls` (status `ok`, `no_reply`, or `error`) and `snmp_interfaces` (one row per interface per poll); deleting a device deletes both. `save_snmp_poll` validates every row and refuses interfaces on a failed poll; `get_snmp_view` returns the latest poll, the latest answered poll, and the answered poll before it. `present_snmp` computes rates only between those two answered polls (`traffic_rate_bps`: a 32-bit counter that went backwards is one wrap, a 64-bit one is a restart, so Unknown). SNMP never changes ping status, uptime, incidents, or alerts. Route `POST /devices/<id>/snmp` (`devices.poll_device_snmp`) uses CSRF, the shared check lock, and the 15 second cooldown against the latest poll, and is in `DEMO_BLOCKED_ENDPOINTS`. The device page has a Poll SNMP button (hidden in demo mode) and an `Interfaces (SNMP)` panel between the 90-day bar and the chart. Demo mode seeds sample interfaces for the firewall, core switch, floor 2 switch (latest poll No reply, interfaces from the day before), and floor 3 switch, from `random.Random(161)`. `tools/snmp_simulator.py` is a local agent on 127.0.0.1 (default port 1161) with four interfaces and steady counters; tests start it on a free port. `.claude/launch.json` has `zyber-noc-snmp-sim-5052`, which runs the simulator and the app against a throwaway database in the temp folder. Tests: `tests/test_snmp.py`.

## Routes

| Method and path | Behavior |
|---|---|
| `GET /` | Landing page from saved device and check totals. Does not ping |
| `GET /reports` | 30-day report from saved results and incidents. Does not ping |
| `GET /about` | Yash Oza's first-person project story, Skyline Paralegal design project, architecture, skills. No live counts |
| `GET /health` | JSON health check |
| `GET /devices` | Dashboard. Optional query `location` and `vlan` filter the table only. Optional query `group` is `location`, `vlan`, or omitted. Each row includes a 30-day status bar |
| `GET /api/dashboard` | JSON for the Refresh button. Uses the same filters and grouping. Includes `incidents` and each device's `history_bar`. Does not ping |
| `GET /topology` | Parent and child map for saved devices |
| `GET /devices/new` | Add-device form |
| `POST /devices` | Save a device |
| `GET/POST /devices/<id>/edit` | Edit form. Success redirects to the device page. Invalid input returns 400. Missing device returns 404 |
| `GET /devices/<id>` | Device details, jitter and loss, 90-day status bar, chart, and recent history |
| `GET /devices/<id>/history.csv` | CSV download of that device's saved history |
| `POST /devices/<id>/check` | Check now. Redirects back to the dashboard when `next=dashboard`, otherwise to the device page |
| `POST /devices/<id>/check-port` | TCP check of one allowed port |
| `POST /devices/check` | Check all |
| `POST /devices/<id>/snmp` | Poll SNMP: read the device's interfaces and save the poll. Blocked in demo mode |
| `GET/POST /devices/<id>/delete` | Delete confirmation, then delete |

Unexpected exceptions render a safe page that says the request could not be completed. The page does not include the exception text.

## Data model

`devices`: id, name, ip_address, device_type, description, location, vlan, parent_id, created_at. IP is stored in canonical form. There is a unique index on `ip_address`. Location is optional text up to 100 characters. VLAN is optional and must be an integer from 1 to 4094. `parent_id` is null or another device's id. Existing databases gain the column through `ALTER TABLE`, and existing rows keep a null parent.

`monitoring_results`: id, device_id, status, response_time_ms, error_details, check_type, port, min_ms, median_ms, max_ms, jitter_ms, packet_loss_pct, recorded_at. Status is `online`, `offline`, or `error`. `check_type` is `ping` or `tcp`. Ping rows have no port. TCP rows use port 22, 53, 80, 443, or 3389. Response time is null when it was not measured, and must be 0 or greater when it is stored. For a ping with replies, `response_time_ms` and `median_ms` are the same median. The other latency fields are null when they were not measured. Packet loss is null, or an integer from 0 to 100. An online result cannot store error details. TCP rows store null for the five ping-only fields. Existing databases add the five columns with `ALTER TABLE` and leave old values null.

`status_changes`: id, device_id, previous_status, new_status, recorded_at. Written only when the new result's status differs from that device's previous result. The first result does not create a row. An incident is one of these rows whose new status is `offline` or `error`. Its recovery time is the next saved change for that device whose new status is `online`. Editing a device does not insert, change, or delete these rows.

Limits: name 100, device type 50, description 500, location 100, error details 500.

Latest status is the newest monitoring row for that device (`recorded_at DESC`, then `id DESC`). No row means Unknown. The UI shows at most 20 recent checks, oldest first inside that window. Older rows stay in the database.

Timestamps are stored as UTC ISO strings. The UI shows them in America/Toronto with an `ET` label. Windows Python has no IANA database installed, so `zoneinfo` loads `app/zoneinfo/America/Toronto` when `ZoneInfo("America/Toronto")` is unavailable. That file uses the current Toronto rule: UTC-5, daylight time from the second Sunday in March to the first Sunday in November.

Uptime is `online results / all saved results`, rounded half up to a percent. Average response time is the mean of stored response times, rounded half up. Both are Unknown when there are no saved results. Average is Not measured when results exist but none stored a response time.

## Ping behavior

Command shape, with `shell=False` and no console window:

`ping -4` or `ping -6`, then `-n`, attempts, `-w`, timeout milliseconds, then the IP.

Defaults: 5 attempts, 1000 ms wait. Attempts are clamped to 1–5. The per-reply timeout is clamped to 200–5000 ms. The subprocess timeout is at most 15 seconds.

Windows uses `-n` and `-w`. Linux and macOS use `-c` and `-W`. This app is written for Windows ping output.

Parsing:

- Each `time=Nms` is one reply time. `time<1ms` is 0.
- Min, median, and max come from the reply times that were parsed. For an even count, the median is the half-up average of the two middle values.
- Jitter uses reply order, not sorted order. One reply stores null jitter.
- The Windows `(N% loss)` line supplies packet loss. If no echo reply was parsed, loss is 100 even when that line says 0%.
- No replies: status offline, latency fields null, loss 100. Do not invent times.
- `Request timed out` for every request is offline with loss 100.
- `Destination host unreachable` is offline even if some packets were received.
- Transmit failure, an invalid address, or unexpected output is error, with null latency and null loss.
- Do not trust the exit code alone.
- Do not return raw ping output to the user.

Unknown device IDs are not pinged. A monitoring failure must be saved or shown as an error. It must not crash Flask.

## Check limits

From `app/config.py`:

- Check all: at most 20 devices, 2 at a time.
- The batch request gives up after 30 seconds. A ping already running may still finish after that, and unfinished work is stored as error.
- Scheduled checks are off unless `SCHEDULED_CHECKS_ENABLED` is true and `SCHEDULED_CHECK_MINUTES` is an integer of at least 1. Testing mode never starts the thread. The thread waits one interval, then calls the same Check all path.
- The same device is skipped for 15 seconds after its last saved result. Ping, TCP, Check all, and the scheduler share that cooldown and the same lock.
- A threading lock rejects a second check while one is running in the same process. Two separate `run.py` processes can still overlap.
- `True` must not be treated as a device id. In Python, `bool` is a subclass of `int`.

## Security details already implemented

- CSRF token in a signed session cookie and a hidden form field. A mismatch returns a safe 400 page.
- Session cookie is HTTP-only and SameSite Lax.
- When not testing, the app writes `instance/secret_key` if it can. If that file cannot be read or written, `create_app` sets `SECRET_KEY` to `secrets.token_hex(32)` in memory. `config.py` still contains the old string `local-development-session-key` as the class default, and that string is replaced before the app serves requests.
- Headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, `Content-Security-Policy: default-src 'self'`.
- Dashboard refresh builds table text with `textContent`. The 30-day bar is built with `createElement` and a status class (`history-online`, `history-offline`, `history-error`, or `history-empty`). Inline styles are not used, because the content security policy is `default-src 'self'`. The script does not inject HTML.

## Files

| Path | Role |
|---|---|
| `run.py` | Starts the server from config |
| `app/__init__.py` | App factory, secret, database init, blueprints, CSRF, headers, error handlers |
| `app/config.py` | Host, port, paths, ping and check limits |
| `app/database.py` | Schema, validation, queries |
| `app/monitoring.py` | Ping command, TCP connect, parsers, batch runner |
| `app/demo.py` | Builds the sample SQLite file for demo mode. No network access |
| `app/snmp.py` | SNMP v2c encoder, decoder, and read-only interface poll |
| `tools/snmp_simulator.py` | Local SNMP agent for trying Poll SNMP without a switch |
| `app/alerts.py` | Outage alerts: local log line and optional SMTP email. Off by default, never in demo mode |
| `app/presentation.py` | Status labels, Toronto timestamps, statistics labels, topology layout, latency chart, status bars |
| `app/zoneinfo/America/Toronto` | TZif data used when the system has no IANA zone |
| `app/csrf.py` | Token creation and comparison |
| `app/routes/devices.py` | Dashboard and device actions. It no longer serves `GET /` |
| `app/routes/site.py` | Landing page, reports, and about. Read-only. `GITHUB_URL` is the project repository |
| `app/routes/health.py` | Health JSON |
| `app/templates/` | Base, dashboard, form, detail, topology, delete confirmation, error |
| `app/templates/site/` | Home, reports, about, shared icons, and the network illustration |
| `app/static/css/style.css` | Layout, including a narrow-screen table |
| `app/static/css/theme-terminal.css` | Cyber terminal theme, loaded after `style.css` |
| `app/static/css/premium.css` | Landing, reports, and about layout, loaded after the theme. Ends with the phone layout section |
| `app/static/js/dashboard.js` | Refresh from saved JSON |
| `app/static/js/forms.js` | Loading label and disabled button while a form submits |
| `app/static/js/premium.js` | Spotlight, glow, reveal, progress bar, and counters. Skipped under reduced motion |
| `app/static/js/effects.js` | Boot intro, headline scramble, scroll story, hero field, topology path hover, panel reveal, dashboard count-up, cursor ring, optional sound |
| `app/static/css/effects.css` | Page transitions, texture, topology animation, boot intro, scroll story, cursor ring. Ends with its reduced-motion block |
| `app/static/js/tour.js` | Demo-only three-step tour. Loaded only when demo mode is on |
| `app/static/img/` | `logo-yo.svg` (initials logo, also the favicon), the older unused `favicon.svg`, `grain.svg` (texture tile for effects.css), and three static page images used on the home page |
| `tests/conftest.py` | Temporary database and test client |
| `tests/test_alerts.py` | Outage rule, off by default, demo never alerts, log line, email through a stand-in SMTP, failure logging, and the Check now path |
| `tests/test_snmp.py` | SNMP codec, polls against the simulator, storage, rates, the Poll SNMP route, and demo mode staying read-only |
| `tests/test_effects.py` | Effect assets, CSP safety, reduced motion, boot intro, scroll story, sound toggle, and topology status markup |
| `tests/test_tour.py` | Demo-only tour markup, script, CSP safety, and reduced motion |
| `tests/test_mobile.py` | Phone layout section, swipe hints, CSP safety, no added motion, and demo Refresh keeping View links |
| `tests/test_readme.py` | README demo link and screenshot files |
| `tests/test_demo.py` | Demo flag, sample data labels, blocked write routes, scheduler off, and no ping or socket calls |
| `tests/test_site.py` | Landing, reports, about content, logo file and header/footer/favicon links, and the no-inline-script check |
| `tests/test_*.py` | Health, database, devices, dashboard, monitoring, presentation, site |
| `.github/workflows/tests.yml` | GitHub Actions pytest job on windows-latest |

Git ignores `.venv/`, `__pycache__/`, `.pytest_cache/`, `instance/`, `*.db`, and `.claude/` (local preview settings).

## Git on this PC

Git 2.56.0 is installed at `C:\Program Files\Git\cmd\git.exe`. The system PATH includes that folder. A terminal opened before Git was installed will not see `git` until it is closed and reopened. For that old window only:

```powershell
$env:PATH += ";C:\Program Files\Git\cmd"
```

Repository state (Nov 2, 2026):

- Branch `master`
- `9781ea3` `Create project foundation` held the original 28 files. A second commit on Nov 2, 2026 added everything since, including the site pages, demo mode, and this handoff
- The GitHub repository is `https://github.com/bankai9278/Zyber-NOC`, created by the user. The user adds it as `origin` and pushes `master` from their own PowerShell, because Claude's permission settings block adding a remote and pushing. Check `git remote -v` and `git status` before assuming it is pushed
- Nothing has been deployed to a host yet

Commit or push again only when the user asks.

## Not built

Do not treat these as existing features:

- SNMP v3, scheduled SNMP polls, and authentication
- Alert channels other than the local log file and SMTP email, and recovery alerts
- A latency chart beyond the latest 20 saved checks. The 90-day bar shows status, not response time
- TCP ports other than 22, 53, 80, 443, and 3389
- A production server, login, or deployment setup for normal mode. Only the read-only demo has hosting notes, and nothing has been deployed

## How to continue with another AI

Open this same folder in the other tool. The first message should be: read `AI_HANDOFF.md` first and follow every project rule in it. The chat history does not need to be copied. The code, tests, and this file are the record.

## How to change the project

- Change the smallest area that does the job. Match the existing modules instead of adding a new framework.
- Add or update tests for the behavior you change. Run the full suite with the virtual-environment Python.
- If the change is visible in the browser, start the app and use the affected page. A screenshot of a static page is not enough.
- Tell the user what changed, how it was tested, and what remains limited.
- Keep README claims aligned with the code. Do not document a feature that is not implemented.
