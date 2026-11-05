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
```
 I finished the Computer Systems Technician – Networking program at Mohawk College in 2025. In school I designed networks on paper, like a 7-floor office network for my team's Skyline Paralegal project, but I never got to see how a network is actually watched day to day. I wanted to understand what a NOC tech looks at, so I built a small version for my own home network.

## What I learned
- Ping output is messier than I expected. Timeouts, "destination host unreachable" and partial replies all mean different things, and I had to handle each one.
- Root cause matters. If a switch goes down, every device behind it looks down too. Adding parent devices taught me why tools like LibreNMS group alerts this way.
- Uptime and latency numbers are only as good as the data behind them, so I only show what was actually saved.
- Basic web security (input validation, CSRF, CSP) matters even on a small tool.
- How to work with AI coding tools: writing clear requirements, reviewing what they produce, and testing it instead of trusting it.

## What was hard
- Getting my home PC to send live results to the hosted site without exposing my network or IPs.
- A test that passed on my PC but failed on GitHub Actions because of a Python version difference. Tracking that down took longer than writing the feature.
- Knowing when to stop. I added too many visual effects at one point and had to cut them back so it looks like a real ops tool.
- Ping readings that didn't make sense. Every device on my home network came back with almost the same response time, no matter if it was the router, a switch or another PC. It was frustrating and took me a while to figure out why: on a small local network everything is only one or two hops away, so the times are tiny and close together, and ping alone can't show which device is "slower." I also realised the live checks only work from my own PC, because those are private local IPs that the hosted site can't reach. That's why I split it into a home agent that runs the pings locally and a hosted site that only shows the results.
```

**About page intro:**

```
I'm Yash Oza, a 2025 graduate of the Computer Systems Technician – Networking program at Mohawk College in Hamilton, Ontario.

I like figuring out why something on a network isn't working. [One real sentence about how you got into networking, e.g. "I got into IT fixing my family's Wi-Fi and computers back home in Vadodara."]

Zyber NOC started as a way to get more hands-on practice after school. I used AI coding tools to help build it, but I planned the features, tested them on my own network, and can explain how each part works. It ties back to my team's Skyline Paralegal network design project, where I was a design specialist. That project was on paper. This one actually runs.

Right now I'm studying for CompTIA Network+ (December 2026) and looking for IT support, help desk and junior networking roles in Hamilton, the GTA or remote.
```

Fill in the two square-bracket lines with something true about you. A small real detail beats anything I could write. Then paste these in, replace the drafts, and delete the `<!-- Yash: edit -->` comments.

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
