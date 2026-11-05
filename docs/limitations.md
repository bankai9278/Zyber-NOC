# Limitations and later work

## Current limitations

- This is a local prototype. It is bound to `127.0.0.1` and is not a production monitoring system.
- The hosted demo shows sample data only. It cannot check real devices or save changes.
- Outage alerts are off by default, cover only changes to offline or error, and are only as fast as the checks. Without scheduled checks, nothing alerts until someone runs a check.
- The local app has no login unless `ZYBER_ADMIN_PASSWORD_HASH` is set. Anyone who can use this Windows session can open the dashboard. Hosted mode has one admin user only, and its failed sign-in counter is per web process.
- In hosted mode, results are only as fresh as the agent's last run (every 5 minutes), queued checks wait for that run, the agent runs only while the home PC is on and signed in, and SNMP is not available.
- Connectivity checks use ICMP through Windows `ping` only. They use 5 attempts and a 1000 millisecond wait for each reply.
- A host or firewall that blocks ICMP can appear Offline even though it answers other traffic.
- Windows can also block `ping` when the command is not permitted. The app then saves an error instead of a response time.
- TCP checks connect only to ports 22, 53, 80, 443, and 3389, with a 2 second timeout. The app does not test other ports, DNS names, websites, or wireless signal strength.
- SNMP polling is v2c only (no v3 authentication or encryption), reads only the interface table, runs only when someone presses Poll SNMP, and reads at most 48 interfaces per device.
- Uptime is the percentage of saved results marked online. It is not a measure of elapsed time. Average response time uses only saved response times.
- The chart plots medians from the latest 20 saved checks and shades min to max only where both were saved. It does not draw a point when a check has no response time. The 90-day bar is status by day, not a longer response-time chart.
- Displayed times use America/Toronto. CSV export and the database keep UTC.
- Scheduled checks are off. Set `SCHEDULED_CHECKS_ENABLED` to `True` and `SCHEDULED_CHECK_MINUTES` to 1 or more before starting the app. The thread waits that many minutes, then uses the same Check all limits.
- Check all handles at most 20 devices, two at the same time, and gives up on the batch after 30 seconds.
- The same device is not checked again until 15 seconds after its last saved result. Another check is also rejected while one check is already running in this app process.
- The device page displays the 20 most recent checks. Older checks remain stored.
- Recent incidents lists at most 10 saved changes to offline or error. A device that is offline on its first saved check has no incident until a later check changes status. An incident that has not returned online says ongoing; the page does not invent an elapsed time for it.
- The web server is Flask's local development server with debug mode off.

## Possible later work

These items are not built:

- SNMP v3, scheduled SNMP polls, interface error counters, and a traffic chart over time.
- Separate logins for each technician. Hosted mode has one admin user.
- Alert channels beyond the log file and email, such as a Windows notification or a chat webhook, and a recovery alert when a device comes back online.
- A response-time chart longer than the latest 20 saved checks. The status bar already covers 90 days, but it does not plot latency.
- TCP checks for ports other than 22, 53, 80, 443, and 3389.
