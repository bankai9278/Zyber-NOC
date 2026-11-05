# Hosting: read-only demo and hosted live mode

## Read-only demo for hosting

The app can run as a public, read-only demo. Demo mode is off by default. Turn it on with the environment variable `ZYBER_DEMO_MODE=1` (`true`, `yes`, or `on` also work; anything else leaves it off).

When demo mode is on:

- The app never runs `ping` and never opens a TCP connection.
- Adding, editing, deleting, Check now, Check port, and Check all return a `403` page that says the demo is read-only. Any `POST`, `PUT`, `PATCH`, or `DELETE` is refused the same way. The scheduler never starts.
- The app does not open `instance/monitor.db`. On each start it rebuilds `instance/demo.db` from `app/demo.py`: eight made-up devices named `Sample ...` on documentation addresses (`192.0.2.x`, `198.51.100.x`, `203.0.113.x`) with 90 days of made-up checks. The dates follow the time the app started, so reloading the web app refreshes them.
- Every page shows a banner saying the data is sample data, not a live reading. `GET /api/dashboard` adds `"sample_data": true`.
- A short three-step "How it works" card opens the first time a browser visits. It can be closed, and the **How it works** button in the banner opens it again. Its slide-in animation is off when the system asks for reduced motion. Normal mode does not load it.

To try it on this PC:

```powershell
$env:ZYBER_DEMO_MODE = "1"
.\.venv\Scripts\python.exe run.py
```

Close that PowerShell window, or run `Remove-Item Env:ZYBER_DEMO_MODE`, to go back to normal mode.

### PythonAnywhere (no new dependencies)

1. Push the project to GitHub. On a free PythonAnywhere account, open a **Bash console** and run `git clone https://github.com/<you>/<repository>.git network-monitoring-dashboard`.
2. Make a virtual environment and install the existing requirements: `python3.11 -m venv ~/zyber-venv`, then `~/zyber-venv/bin/pip install -r ~/network-monitoring-dashboard/requirements.txt`.
3. On the **Web** tab, add a new web app with **Manual configuration** and Python 3.11 or newer. Set **Virtualenv** to `/home/<you>/zyber-venv`.
4. Open the WSGI configuration file from the Web tab and replace its contents with:

   ```python
   import os
   import sys

   path = "/home/<you>/network-monitoring-dashboard"
   if path not in sys.path:
       sys.path.insert(0, path)
   os.environ["ZYBER_DEMO_MODE"] = "1"
   from run import app as application
   ```

5. Set a static files mapping from `/static/` to `/home/<you>/network-monitoring-dashboard/app/static`, then choose **Reload**.

### Render

Render runs a web service with a start command, and a Flask app there normally uses `gunicorn`. That would be one new dependency (`gunicorn`), and it is not in `requirements.txt` yet. If you choose Render, add `gunicorn` to `requirements.txt`, then create a **Web Service** from the GitHub repository with build command `pip install -r requirements.txt`, start command `gunicorn run:app`, and environment variable `ZYBER_DEMO_MODE=1`. Render's free disk is temporary, which is fine because the demo database is rebuilt on every start.

Never host the app in plain normal mode. Without hosted mode it would let the server ping whatever a signed-in admin saves, and without a password hash nobody could sign in. Host either demo mode or hosted mode (next section).

## Hosted live mode with a home agent (optional)

The demo above shows sample data. Hosted mode shows **your real devices** on a public website, without the website ever reaching into your home network:

```text
home PC (agent/agent.py, every 5 minutes)              website (hosted mode)
  1. GET  /api/agent/devices   ---- agent key ---->   list of saved devices and queued checks
  2. ping / TCP-check each one on the home network
  3. POST /api/agent/results   ---- agent key ---->   saved, status changes, incidents
```

- `ZYBER_HOSTED_MODE=1` turns it on. The website then never runs `ping`, never opens a TCP connection, never polls SNMP, and never starts scheduled checks. Demo mode wins if both are set.
- The agent API is on only when `ZYBER_AGENT_KEY` is set to at least 32 characters. Every request must send the same value in the `X-Zyber-Agent-Key` header; the site compares it with `hmac.compare_digest`. These two routes are the only ones without a CSRF token, because they are not browser forms.
- `GET /api/agent/devices` returns each saved device's id, IP address, and checks (`ping`), plus queued `requests`, at most 200.
- `POST /api/agent/results` takes `{"results": [...], "completed_requests": [...]}`. At most 200 rows and 128 KB. Every row is checked with the same rules as a local check, plus the shapes a real check produces (no response time on a failed check, no packet loss on an error, no ping statistics on a TCP row, median equals response time). One bad row refuses the whole batch with `400`. A row for a device that was deleted while the agent ran is skipped and listed in `rejected`; the rest are saved. Status changes and outage alerts work as they do for local checks. After each post, results and status changes older than 90 days are deleted.
- The dashboard shows **Last result from the home agent** with the time of the newest saved result.

### Sign-in

Hosted mode has one admin user. Sign-in is also on for the local app when `ZYBER_ADMIN_PASSWORD_HASH` is set. Without either, the local app works as before, with no password.

| Signed out (anyone) | Signed in (admin) |
|---|---|
| Every page is read-only. Device names, statuses, and numbers are shown | Add, edit, and delete devices |
| IP addresses and descriptions are hidden on every page and left out of `/api/dashboard` | Everything is shown |
| CSV downloads, forms, and checks redirect to **Sign in** | **Check now**, **Check port**, and **Check all** queue a request. The agent runs it on its next run (within about 5 minutes) and marks it done. Requests not picked up within 60 minutes are dropped |

- The username is `admin` (change it with `ZYBER_ADMIN_USERNAME`). The password is never stored: `ZYBER_ADMIN_PASSWORD_HASH` holds a `werkzeug.security` hash.
- Sign-in and sign-out forms use the CSRF token. Signing in starts a fresh session with a new token. Sessions last 12 hours. Changing the password hash signs out every old session. In hosted mode the session cookie is `Secure` (HTTPS only).
- Each wrong password waits 1 second. Five wrong attempts from one address within 15 minutes lock that address out for the rest of the 15 minutes. This is counted per web process, so it resets when the web app reloads.
- SNMP polling is not available in hosted mode, because the agent only pings and checks TCP ports.

### Make the two secrets

From the project folder on this PC:

```powershell
.\.venv\Scripts\python.exe -m tools.zyber_secrets agent-key
.\.venv\Scripts\python.exe -m tools.zyber_secrets password-hash
```

`agent-key` prints a random 64-character key. `password-hash` asks for a password twice (at least 12 characters, not shown on screen) and prints a hash that starts with `scrypt:`. Keep both somewhere private, such as a password manager. Never commit them.

### Publish on PythonAnywhere

These steps change the existing demo site into the live site. To keep the demo instead, skip this section.

1. **Push the code** from this PC (PowerShell, in the project folder):

   ```powershell
   git push origin master
   ```

2. **Pull it on PythonAnywhere.** Open a **Bash console** there and run:

   ```bash
   cd ~/network-monitoring-dashboard
   git pull
   ```

3. **Edit the WSGI file** (Web tab, the link next to *WSGI configuration file*). Replace the `ZYBER_DEMO_MODE` line so the file reads like this, with your own key and hash pasted between the quotes:

   ```python
   import os
   import sys

   path = "/home/<you>/network-monitoring-dashboard"
   if path not in sys.path:
       sys.path.insert(0, path)
   os.environ["ZYBER_HOSTED_MODE"] = "1"
   os.environ["ZYBER_AGENT_KEY"] = "paste the agent key here"
   os.environ["ZYBER_ADMIN_PASSWORD_HASH"] = "paste the scrypt:... hash here"
   from run import app as application
   ```

   Remove the `ZYBER_DEMO_MODE` line completely; if it stays, the site keeps showing sample data. The WSGI file is private to your PythonAnywhere account and is not in git.

4. **Reload** the web app (the green button on the Web tab). Open the site, choose **Sign in**, and sign in as `admin`. The live site starts with an empty inventory (`instance/monitor.db` on PythonAnywhere). Add your devices there.

### Set up the agent on this PC

1. Copy the example config and fill it in:

   ```powershell
   Copy-Item agent\config.example.json agent\config.json
   notepad agent\config.json
   ```

   Set `site_url` to `https://zybernoc.pythonanywhere.com` (or your own address) and `agent_key` to the same key you put in the WSGI file. `concurrency` (1 to 4, default 2) is how many checks run at once. `agent/config.json` is in `.gitignore`.

2. Test the connection, then do one real run:

   ```powershell
   .\.venv\Scripts\python.exe agent\agent.py --check-connection
   .\.venv\Scripts\python.exe agent\agent.py
   ```

   The second command prints a line such as `Checked 3, saved 3, rejected 0, skipped 0.` Each run is also added to `agent/agent.log` (git-ignored; it is renamed to `agent.log.old` above 512 KB).

3. Schedule it every 5 minutes with Windows Task Scheduler. In PowerShell (no administrator needed):

   ```powershell
   schtasks /Create /TN "Zyber NOC agent" /SC MINUTE /MO 5 /F /TR "\"C:\Users\yash3\Desktop\network-monitoring-dashboard\.venv\Scripts\pythonw.exe\" \"C:\Users\yash3\Desktop\network-monitoring-dashboard\agent\agent.py\""
   ```

   `pythonw.exe` runs it without opening a window. The task runs while you are signed in to Windows. To run it now: `schtasks /Run /TN "Zyber NOC agent"`. To check it: `schtasks /Query /TN "Zyber NOC agent"`. To remove it: `schtasks /Delete /TN "Zyber NOC agent" /F`.

What the agent does not trust: it validates every address from the website again with the inventory's own rules (no hostnames, broadcast, multicast, unspecified, or reserved addresses), only tries TCP ports 22, 53, 80, 443, and 3389, checks at most 200 devices per run, requires `https://` (plain `http://` is allowed only for `127.0.0.1` while testing), and does not follow redirects, so the key is only ever sent to `site_url`. It uses only the Python standard library plus this project's own `app/monitoring.py`, so run it with the project's `.venv` Python. It does not use `subprocess` itself; ping runs through the same `shell=False` code as the local app.
