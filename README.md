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

I finished the Computer Systems Technician – Networking program at Mohawk College in 2025. In college I designed networks on paper, like a 7-floor office network for my team's Skyline Paralegal project, but I never got to see how a network is actually watched day to day. I wanted to understand what a NOC tech looks at, so I built a small version for my own home network.

## What I learned

- Ping output is messier than I expected. Timeouts, "destination host unreachable" and partial replies all mean different things, and the exit code alone can't be trusted.
- Root cause matters. If a switch goes down, every device behind it looks down too. Adding parent devices taught me why tools like LibreNMS group alerts this way.
- "Unknown" and "offline" have to be different. A device I haven't checked yet isn't down.
- A hosted website can't reach devices on a home network, which is why the home agent sends results out instead.
- Basic web security (input validation, CSRF, CSP) matters even on a small tool.
- How to work with AI coding tools: writing clear requirements, reviewing what they produce, and testing it instead of trusting it.

## What was hard

- Ping readings that didn't make sense. Every device on my home network came back with almost the same response time, no matter if it was the router, a switch or another PC. It took me a while to figure out why: on a small local network everything is only one or two hops away, so the times are tiny and close together, and ping alone can't show which device is "slower." I also realised the live checks only work from my own PC, because those are private local IPs that the hosted site can't reach. That's why I split it into a home agent that runs the pings locally and a hosted site that only shows the results.
- Getting my home PC to send live results to the hosted site without exposing my network or IPs.
- A test that passed on my PC but failed on GitHub Actions because of a Python version difference. Tracking that down took longer than writing the feature.
- A deploy where one secret got split across two lines in the WSGI config, which took the whole site down until I found the broken quote.
- Knowing when to stop. I added too many visual effects at one point and had to cut them back so it looks like a real ops tool.

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
