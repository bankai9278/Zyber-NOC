# Features and networking concepts

## Features

**Inventory**

- Save a device with a name, an IPv4 or IPv6 address, a type, and optionally a description, location, VLAN, and parent device.
- Bad input is refused: missing fields, invalid or duplicate addresses, and broadcast, multicast, or unspecified addresses.
- Edit a device at any time, including its parent. Its history stays with it, even after an IP change. A device can't be its own parent, and a parent link that would make a loop is refused.
- Delete only after a confirmation page. The device and its history go; any children stay, with no parent.

**Checks**

- **Check now** pings one device (five echo requests). **Check all** pings up to 20, two at a time.
- **Check port** tries TCP 22, 53, 80, 443, or 3389 on a saved device. No other port is ever opened.
- **Poll SNMP** reads each interface's name, up/down status, and traffic counters over SNMP v2c. It's read-only and uses only the standard library. Two polls turn the counters into traffic rates. A poll never changes ping status, uptime, or incidents.
- Every finished check is saved, including errors. A device stays **Unknown** until a check is saved; the app never invents a status.
- Scheduled checks are off by default. When turned on in config, a background thread runs Check all every so many minutes (1 at the least).

**Dashboard and history**

- Counts for total, online, offline, unknown, and error, plus the latest response time and check time for each device.
- Filter the table by location or VLAN, or group it by either. Summary counts always cover every device.
- Uptime and average response time from saved results only.
- The 10 most recent status changes, and the 10 most recent incidents (changes to offline or error), with how long each lasted or `ongoing`.
- When a device and its parent are both offline, the badge says **Unreachable via** the parent. A child's incident is marked as caused by the parent outage when the parent was already down.
- Device page: the last 20 checks, a response-time chart (median line, min-to-max band, points coloured by packet loss), jitter and packet loss from the latest ping, and a 90-day status bar. Each dashboard row has a 30-day bar.
- The dashboard and the topology map keep themselves current. While the page is open and visible, they check the saved results every 45 seconds (the same public JSON, so no addresses when signed out). When a newer result has arrived, counts, rows, colours, and links update in place and each device sends out a short sonar ring in its status colour; with reduced motion they just update. Demo mode does not poll.
- A light next to ZYBER NOC says **live** (green, with how long ago) when the newest saved result is under 10 minutes old, and **agent offline** (grey) when it isn't; the demo says **demo**. Pages that keep themselves live update it as they go.
- On phones, the top menu is replaced by a bottom tab bar (Home, Dashboard, Map, Reports, More) with thumb-sized buttons; More opens About, Try it, and Sign in or out. It works without JavaScript, leaves room for the phone's home bar in the installed app, and computers keep the normal top menu.
- **Refresh status** reloads saved results without pinging again. **Download CSV** exports a device's full history in UTC.
- Times show in America/Toronto; the database stores UTC. `/health` returns a small JSON health check.

**Topology**

- `/topology` draws the parent and child tree as inline SVG, with each device linking to its page.

**Hosting, sign-in, and phone**

- Hosted live mode: the website never pings. A home agent (`agent/agent.py`) checks the saved devices every 5 minutes and posts the results with a shared key. One admin sign-in. Signed-out visitors see names and statuses but not addresses or descriptions. The dashboard shows when the last result arrived.
- A **Try it** sandbox at `/try`: visitors can add, edit, delete, and pretend-check up to 8 made-up devices. They live only in that visitor's session cookie, never in the database, reset after an hour, and are never pinged or contacted. Their history is random and labelled as made up.
- Installs as an app on Android. A web app manifest is at `/manifest.webmanifest`, the icons are drawn by `tools/make_icons.py` with the standard library, and a service worker is at `/service-worker.js`. The worker stores only files under `/static/` and an offline page. Pages, `/api/` JSON, sign-in, and CSV downloads always come from the network, so a phone never shows an old status as live. In Chrome on Android, open the site and choose **Add to Home screen** or **Install app**.
- Optional outage alerts, off by default. When on, a check that changes a device to offline or error is written to `instance/alerts.log` and can also be emailed through your own mail server. Demo mode never alerts.

**Look and feel**

- A dark terminal theme with mint accents. Headings use Space Grotesk, served from this site.
- **Follow a ping** on the home page walks one ping from this PC through the router to a device and back, and ends with the newest real check.
- My `YO` initials logo is the favicon and sits next to ZYBER NOC in the header.
- Animations turn off when the system asks for reduced motion; a footer switch turns them back on.

## Networking concepts

These are the network support ideas I practised while building it. On my home network every device came back with almost the same tiny response time, which is what made me look at hops and latency properly.

- **Authorized inventory.** A technician monitors devices they are allowed to check. The app pings only addresses that were added to the inventory. It does not scan an IP range or accept a hostname.
- **ICMP echo.** **Check now** uses Windows `ping`, which sends five ICMP echo requests and waits for echo replies. A reply makes the device **Online**. No reply before the timeout makes it **Offline**.
- **Response time, jitter, and loss.** Windows reports each round trip in milliseconds, such as `time=12ms`. A reply faster than 1 millisecond is stored as 0 ms. The saved response time is the median of the replies. Jitter is the average change between consecutive replies. Packet loss is the share of the five requests that got no reply. If none come back, loss is 100 and no latency number is invented.
- **Upstream dependency.** A parent device is the path used to reach a child. If both are offline in the saved results, the child is shown as unreachable through that parent. The map on `/topology` draws those links.
- **Unknown is not the same as offline.** Unknown means no check has been saved yet. Offline means a check ran and the device did not reply.
- **Ping is not proof that every service is up.** A firewall or host policy can block ICMP while the device is still reachable on another protocol. The TCP check only tries to connect to one of five ports: 22, 53, 80, 443, or 3389. It does not test websites or name resolution.
- **One address, one device.** Broadcast and multicast addresses can represent many hosts, so they are rejected. Each saved address must be unique.
- **Check limits.** The default check sends 5 echo requests and waits 1000 milliseconds for each reply. A repeated check is skipped for 15 seconds, and a second check is rejected while one is already running. These limits avoid sending a burst of traffic from a mis-click.
