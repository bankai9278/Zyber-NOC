# Set up, run, and use it on Windows

## Windows setup

Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/windows/). During setup, select **Add python.exe to PATH**.

Open PowerShell in this project folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Activate the environment when you want `python` and `pip` to point at it:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script, skip activation and call `.\.venv\Scripts\python.exe` directly. Do not install these packages into the global Python installation.

The first run creates these local files. Git ignores them:

- `instance/monitor.db`, the SQLite database
- `instance/secret_key`, the key that signs the local session cookie

## Run the application

From the project folder:

```powershell
.\.venv\Scripts\python.exe run.py
```

Open the home page at `http://127.0.0.1:5000/`. The device dashboard is `http://127.0.0.1:5000/devices`. Reports are `http://127.0.0.1:5000/reports` and the project note is `http://127.0.0.1:5000/about`.

The server listens on `127.0.0.1` port `5000`, so only this computer can open it. Debug mode is off. Stop the server with Ctrl+C in that PowerShell window.

Confirm the process is running:

```powershell
.\.venv\Scripts\python.exe -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:5000/health').read().decode())"
```

The health check returns:

```json
{"application": "zyber-noc", "status": "ok"}
```

## Run the tests

The tests do not need the web server to be running. From the project folder:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Ping tests replace the Windows command with saved examples of online, offline, timeout, and failed output. TCP tests replace the socket connection. They do not contact the network.

GitHub Actions runs the same tests on `windows-latest`. The workflow file is `.github/workflows/tests.yml`. The repository is [bankai9278/Zyber-NOC](https://github.com/bankai9278/Zyber-NOC). The badge at the top of this file shows the latest workflow run.

## Add a device and check it

1. Start the application and open `http://127.0.0.1:5000/`. Choose **Dashboard**, or open `http://127.0.0.1:5000/devices`.
2. Choose **Add device**.
3. Enter a device you are allowed to monitor. Use a real IP address from this PC or its local network, such as the IPv4 address shown by `ipconfig`. `127.0.0.1` is a safe loopback test.
4. Save the device. Its status is **Unknown**, and the response time and last checked time say **Not checked**.
5. Choose **Check now** on that row, or open the device and choose **Check now** there. The button says **Checking** while Windows ping sends five echo requests. **Check port** on the device page connects to the selected allowed port.
6. After the page reloads, the status is **Online**, **Offline**, or **Error**. Online includes the median response time in milliseconds. The device page lists the saved check and, when a response time was stored, draws the median and the min-to-max band. Jitter and packet loss appear when the ping stored them.
7. **Check all** checks every saved device that is not still inside the 15-second wait, up to 20 devices. **Refresh status** reloads stored results and does not ping again. Location and VLAN filters change the table only. **Group by** can be None, Location, or VLAN, and it works together with those filters. Each row has a 30-day status bar.
8. **Edit** on a device row or the device page opens a form with the saved values, including Parent device. Saving it returns to the device page. The saved checks stay in place, including after an IP or parent change. **Topology** draws the saved parent links.
9. **Download CSV** saves that device's history, including the ping statistics. **Delete** opens a confirmation page. The device is removed only after **Delete device** is submitted. A child device is kept, and its parent becomes none. The incidents panel lists saved changes to offline or error. It stays empty until one of those changes has been saved. The device page also shows the 90-day status bar.

Use a device you control. Do not add an address at work, school, or another network unless you are allowed to monitor it.

## SNMP interface polling

**Poll SNMP** on a device page sends SNMP v2c GetNext requests to that saved device on UDP port 161 and stores what it answers: each interface's name, whether it is up or down, and its in and out byte counters (64-bit when the device has them, 32-bit otherwise). It only reads. It never sends an SNMP set.

- The community string is `public` unless you set another one before starting the app: `$env:ZYBER_SNMP_COMMUNITY = "your-community"`. It works like a password, so keep it out of files you commit.
- Traffic rates need two answered polls. Poll again after at least 15 seconds and the page shows bits per second in and out for each interface. A 32-bit counter that rolls over is handled; a 64-bit counter that goes backwards means the device restarted, so that rate says Unknown.
- If the device does not answer, the poll is saved as **No reply** and the page keeps showing the interfaces from the last poll that answered.
- Demo mode never polls. It shows sample interfaces for a few sample devices.

### Try it without a switch

`tools/snmp_simulator.py` is a small SNMP agent with four made-up interfaces whose counters grow at a steady rate. It listens on `127.0.0.1` only.

```powershell
.\.venv\Scripts\python.exe tools\snmp_simulator.py
```

In a second PowerShell window:

```powershell
$env:ZYBER_SNMP_PORT = "1161"
.\.venv\Scripts\python.exe run.py
```

Add a device with IP `127.0.0.1`, open it, and press **Poll SNMP** twice, at least 15 seconds apart. Remove `ZYBER_SNMP_PORT` (or open a new window) before polling real equipment, which listens on 161.

## Monitor devices over Tailscale (optional)

[Tailscale](https://tailscale.com) puts your own devices on one private network, even when they are in different places. Each device gets an address from `100.64.0.0/10` (such as `100.101.102.103`) and an IPv6 address in `fd7a:115c:a1e0::/48`. Zyber NOC accepts both kinds like any other single address, so a laptop at home, a Raspberry Pi at a friend's place, or a cloud server can be pinged, port-checked, and polled over SNMP from this PC.

### Set it up on this PC

1. Install Tailscale from PowerShell (Windows asks for administrator approval):

   ```powershell
   winget install --id Tailscale.Tailscale -e
   ```

   Or download the Windows installer from <https://tailscale.com/download/windows>.
2. Open Tailscale from the Start menu and sign in. Every device you sign in with the same account joins your tailnet.
3. Install Tailscale on each device you want to monitor and sign in there too.
4. Find their addresses: `tailscale status` lists every device and its `100.x` address, or open the admin console at <https://login.tailscale.com/admin/machines>.

### Add a tailnet device to Zyber NOC

Add it like any other device, using its `100.x` address (hostnames such as MagicDNS names are not accepted, on purpose). Then:

- **Check now** works when the device allows ping. Windows blocks ping by default; allow "File and Printer Sharing (Echo Request - ICMPv4-In)" on a Windows device you want to ping.
- **Check port** works for 22, 53, 80, 443, or 3389 when that service runs on the device.
- **Poll SNMP** works when the device runs an SNMP agent that allows v2c from your tailnet address.
- Tailscale access controls (ACLs) can block traffic between your devices. The default policy allows it.

### Open the dashboard from your other devices with `tailscale serve`

The app itself still listens only on `127.0.0.1`. `tailscale serve` is a proxy on this PC that makes it reachable from your own tailnet devices over HTTPS, and from nowhere else.

```powershell
tailscale serve --bg 5000
tailscale serve status
```

It prints an address like `https://your-pc.your-tailnet.ts.net`. Open that from your phone or laptop while both are signed in to Tailscale. Turn it off with:

```powershell
tailscale serve --https=443 off
```

Read this before using it:

- Normal mode has **no login**. Anyone on your tailnet can add, edit, and delete devices and start checks. Only serve it when your tailnet holds just your own devices, and remove people from the tailnet you no longer trust. Setting `ZYBER_ADMIN_PASSWORD_HASH` before you start the app adds an admin sign-in (see [Sign-in](hosting.md#sign-in)).
- To show someone the project safely, serve the read-only demo instead: start the app with `$env:ZYBER_DEMO_MODE = "1"`, then serve that port.
- **Never use `tailscale funnel`.** Funnel publishes the app to the whole internet, and this app's normal mode must never be public.

## Outage alerts (optional)

Alerts are off by default. An alert is raised when a saved check changes a device's status to **offline** or **error**, the same rule the incidents panel uses. A device's first check is not a change, so it never alerts, and a return to online does not alert either.

When alerts are on, each one is added as a line to `instance/alerts.log` on this PC. That file is the default because it needs no account, no password, and no network. Email is an extra you can add: the app sends it with Python's built-in `smtplib`, so there is no new dependency. The email goes out on a background thread, so a slow mail server does not hold up Check all. A failed email is written to the log by error type only; the password is never written.

Settings come from environment variables, so nothing secret is saved in the code:

| Variable | Meaning |
|---|---|
| `ZYBER_ALERTS` | `1` turns alerts on. Anything else leaves them off |
| `ZYBER_SMTP_HOST` | Mail server, such as `smtp.gmail.com`. Email is skipped when this is empty |
| `ZYBER_SMTP_PORT` | Default `587` |
| `ZYBER_SMTP_USERNAME`, `ZYBER_SMTP_PASSWORD` | Mail login. For Gmail or Outlook use an app password, not your normal password |
| `ZYBER_SMTP_STARTTLS` | Default on. Set `0` only for a server that does not use STARTTLS |
| `ZYBER_ALERT_FROM` | Sender address |
| `ZYBER_ALERT_TO` | One recipient, or several separated by commas |

Example for one PowerShell window:

```powershell
$env:ZYBER_ALERTS = "1"
$env:ZYBER_SMTP_HOST = "smtp.gmail.com"
$env:ZYBER_SMTP_USERNAME = "you@gmail.com"
$env:ZYBER_SMTP_PASSWORD = "your-app-password"
$env:ZYBER_ALERT_FROM = "you@gmail.com"
$env:ZYBER_ALERT_TO = "you@gmail.com"
.\.venv\Scripts\python.exe run.py
```

Leave out the `ZYBER_SMTP_*` lines to get the log file only. Alerts only happen when a check runs, so they pair well with scheduled checks.
