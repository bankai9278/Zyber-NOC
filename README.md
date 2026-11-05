# Zyber NOC

[![Tests](https://github.com/bankai9278/Zyber-NOC/actions/workflows/tests.yml/badge.svg)](https://github.com/bankai9278/Zyber-NOC/actions/workflows/tests.yml)

**Live site: [zybernoc.pythonanywhere.com](https://zybernoc.pythonanywhere.com)** shows the real status of devices on my home network, sent in by a small agent on my PC. Anyone can look; only I can sign in and make changes, and IP addresses stay hidden from the public. The **Try it** page has a sandbox with pretend devices.

Zyber NOC is a small network monitoring console for the devices you're allowed to watch. It pings them, keeps every result in SQLite, and turns the results into uptime, incidents, a 90-day status bar, and a topology map. Python, Flask, and plain HTML, CSS, and JavaScript.

Built with help from AI coding tools. I planned the features, tested them, and can explain how each part works.

| Dashboard | Device page |
|---|---|
| ![Dashboard with device counts, status changes, and recent incidents](docs/screenshots/dashboard.png) | ![Device page with jitter, packet loss, 90-day status, and response-time chart](docs/screenshots/device.png) |
| **Topology** | **Home** |
| ![Topology map drawn from saved parent links](docs/screenshots/topology.png) | ![Landing page](docs/screenshots/home.png) |

The screenshots come from demo mode, so every device and number in them is sample data on documentation addresses.

## Key features

- Checks only devices you've saved: Windows ping (5 echo requests, median, jitter, loss) and TCP ports 22, 53, 80, 443, 3389. No subnet scanning.
- Online, offline, error, and **unknown** (never checked) are kept separate. Status changes become incidents with durations.
- Parent devices: when a parent and its child are both offline, the child shows **Unreachable via** the parent, and the topology map draws the tree.
- Hosted mode: the website never pings. A home agent checks the devices every 5 minutes and posts results with a shared key.
- Security basics: CSRF tokens on every form, a `default-src 'self'` content security policy, no `shell=True`, strict IP validation, one admin sign-in.

## Why I built it
<!-- Yash: edit into your own words -->

In my Mohawk College team project I designed a network for Skyline Paralegal on paper. I wanted the next step: the tool a NOC team uses to watch a network like that, so I could see how a ping turns into a status, an uptime number, and an incident.

## What I learned
<!-- Yash: edit into your own words -->

- How Windows `ping` reports replies, timeouts, and unreachable hosts, and why the exit code alone can't be trusted.
- Why "unknown" and "offline" have to be different, and how a parent outage explains a child's outage.
- That a hosted website can't reach devices on a home network, which is why the home agent sends results out instead.
- Web security basics: CSRF tokens, a strict content security policy, and never building shell commands from input.

## What was hard
<!-- Yash: edit into your own words -->

- Turning messy ping output into the right status every time.
- Designing the agent so it doesn't trust the website: it re-checks every address before pinging it.
- Going live: one key pasted across two lines in the WSGI file took the whole site down until I read the error log.
- Hiding addresses from the public without making the pages useless.

## Run it on Windows

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

Open `http://127.0.0.1:5000`. Run the tests with `.\.venv\Scripts\python.exe -m pytest`.

## More documentation

- [Features and networking concepts](docs/features.md)
- [Architecture, data model, and technologies](docs/architecture.md)
- [Setup, using it, SNMP, Tailscale, and alerts](docs/setup.md)
- [Hosting: demo mode, hosted mode, sign-in, the home agent](docs/hosting.md)
- [Limitations and later work](docs/limitations.md)

## Credits

[Space Grotesk](https://github.com/floriankarsten/space-grotesk) (SIL Open Font License) and [GSAP](https://gsap.com) (standard no-charge license), both served from this site with their licenses.
