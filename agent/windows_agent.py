"""
SOVEREIGN RMM v2 — Windows Agent
- All task trigger types: now / once / interval / cron / event
- Local JSON task cache (survives server outages)
- 5-min pre-run server check to confirm task not cancelled
- Live stdout streaming to dashboard
- Smart IP selection: local → VPN fallback, weekly retest
- Self-update: checks server version on checkin
- Weekly disk scan
- Runs as startup registry entry (silent)
"""

import asyncio, json, logging, os, platform, re, socket, subprocess, sys, uuid, winreg
from datetime import datetime, timedelta
from pathlib import Path

import psutil, requests, websockets

# ── CONFIG (baked in at build time) ─────────────────────────
SERVER_IP_LOCAL = "RMM_LOCAL_IP"
SERVER_IP_VPN   = "RMM_VPN_IP"
SERVER_PORT     = "RMM_PORT"
AGENT_TOKEN     = "RMM_TOKEN"
AGENT_VERSION   = "2.0.0"

# ── PATHS ────────────────────────────────────────────────────
# ProgramData is always C:\ProgramData regardless of which user/SYSTEM runs the agent
APP_DIR     = Path(os.getenv("PROGRAMDATA", "C:/ProgramData")) / "SovereignRMM"
TASKS_FILE  = APP_DIR / "scheduled_tasks.json"
STATE_FILE  = APP_DIR / "state.json"
LOG_FILE    = APP_DIR / "agent.log"
APP_DIR.mkdir(parents=True, exist_ok=True)

# ── LOGGING ──────────────────────────────────────────────────
# Rotating log: max 5 MB per file, keep 3 backups = max 20 MB total
from logging.handlers import RotatingFileHandler
_log_handler = RotatingFileHandler(
    str(LOG_FILE), maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
)
_log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-8s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
_con_handler = logging.StreamHandler(sys.stdout)
_con_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-8s] %(message)s", datefmt="%H:%M:%S"))
logging.basicConfig(level=logging.INFO, handlers=[_log_handler, _con_handler])
log = logging.getLogger("SovAgent")

# ── NOTIFICATIONS ────────────────────────────────────────────
def notify(title: str, message: str, icon: str = "info"):
    """
    Send a Windows 10/11 toast notification to the logged-in user.
    icon: "info" | "warning" | "error"
    Runs silently in background via powershell — never blocks the agent.
    Fails silently if no user is logged in (e.g. locked server).
    """
    # Toast XML — simple two-line notification
    xml = (
        f'<toast scenario="default">'
        f'<visual><binding template="ToastGeneric">'
        f'<text>{title}</text>'
        f'<text>{message}</text>'
        f'</binding></visual>'
        f'</toast>'
    )
    # PowerShell one-liner: load WinRT, show toast
    # Uses powershell.exe AppId so it works without an app registration
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]|Out-Null;"
        "$x=[Windows.Data.Xml.Dom.XmlDocument]::new();"
        f"$x.LoadXml('{xml}');"
        "$t=[Windows.UI.Notifications.ToastNotification]::new($x);"
        "$a='{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($a).Show($t)"
    )
    try:
        subprocess.Popen(
            ["powershell.exe", "-WindowStyle", "Hidden", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", ps],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x08000000  # CREATE_NO_WINDOW
        )
    except Exception as e:
        log.debug(f"Notify failed (no user logged in?): {e}")


# ── STATE ────────────────────────────────────────────────────
def state_load():
    try: return json.loads(STATE_FILE.read_text())
    except: return {}
def state_save(d): STATE_FILE.write_text(json.dumps(d, indent=2))
def state_get(k, default=""):
    return state_load().get(k, default)
def state_set(k, v):
    s = state_load(); s[k] = v; state_save(s)

def get_device_id():
    d = state_get("device_id")
    if not d:
        d = str(uuid.uuid4()); state_set("device_id", d)
    return d

# ── IP SELECTION ─────────────────────────────────────────────
WEEK = 7*24*3600

def ping_ip(ip):
    try:
        s = socket.socket(); s.settimeout(3)
        ok = s.connect_ex((ip, int(SERVER_PORT))) == 0
        s.close(); return ok
    except: return False

def should_retest():
    t = state_get("last_ip_test","")
    if not t: return True
    try: return (datetime.utcnow()-datetime.fromisoformat(t)).total_seconds() > WEEK
    except: return True

def get_network_info():
    local_ip = "unknown"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8",80)); local_ip = s.getsockname()[0]; s.close()
    except: pass
    ssid = "unknown"
    try:
        r = subprocess.run(["netsh","wlan","show","interfaces"],capture_output=True,text=True,timeout=5)
        for line in r.stdout.splitlines():
            if "SSID" in line and "BSSID" not in line:
                ssid = line.split(":",1)[-1].strip(); break
    except: pass
    return {"local_ip": local_ip, "ssid": ssid}

def select_server_ip(force=False):
    cached = state_get("active_ip","")
    if cached and not force and not should_retest():
        return cached
    log.info("Testing server IPs...")
    net = get_network_info()
    log.info(f"Network: {net}")
    if ping_ip(SERVER_IP_LOCAL):
        ip = SERVER_IP_LOCAL; log.info(f"✓ Local IP: {ip}")
    elif ping_ip(SERVER_IP_VPN):
        ip = SERVER_IP_VPN; log.info(f"✓ VPN IP: {ip}")
    else:
        ip = cached or SERVER_IP_LOCAL
        log.warning(f"Neither reachable, using: {ip}")
        return ip
    s = state_load()
    s["active_ip"] = ip; s["last_ip_test"] = datetime.utcnow().isoformat()
    s["last_network"] = net; state_save(s)
    return ip

# ── TASK STORAGE ─────────────────────────────────────────────
def load_tasks():
    try: return json.loads(TASKS_FILE.read_text())
    except: return []

def save_tasks(tasks):
    TASKS_FILE.write_text(json.dumps(tasks, indent=2, default=str))

def add_or_update_task(task):
    tasks = load_tasks()
    tasks = [t for t in tasks if t.get("task_id") != task.get("task_id")]
    tasks.append(task)
    save_tasks(tasks)

def remove_task(task_id):
    tasks = [t for t in load_tasks() if t.get("task_id") != task_id]
    save_tasks(tasks)

def cancel_task_local(task_id):
    tasks = load_tasks()
    for t in tasks:
        if t.get("task_id") == task_id:
            t["cancelled"] = True
    save_tasks(tasks)

# ── POLICY ───────────────────────────────────────────────────
policy = {
    "checkin_plugged_seconds": 30,
    "checkin_battery_100_80_seconds": 60,
    "checkin_battery_79_50_seconds": 180,
    "checkin_battery_49_20_seconds": 300,
    "checkin_battery_19_10_seconds": 600,
    "checkin_battery_9_0_seconds": 900,
    "disk_scan_interval_hours": 168,
}

def get_battery():
    try:
        b = psutil.sensors_battery()
        return (round(b.percent,1), b.power_plugged) if b else (None, False)
    except: return (None, False)

def get_checkin_interval():
    lvl, charging = get_battery()
    if charging or lvl is None: return policy["checkin_plugged_seconds"]
    if lvl >= 80: return policy["checkin_battery_100_80_seconds"]
    if lvl >= 50: return policy["checkin_battery_79_50_seconds"]
    if lvl >= 20: return policy["checkin_battery_49_20_seconds"]
    if lvl >= 10: return policy["checkin_battery_19_10_seconds"]
    return policy["checkin_battery_9_0_seconds"]

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8",80)); ip = s.getsockname()[0]; s.close(); return ip
    except: return "unknown"

def get_system_info():
    lvl, charging = get_battery()
    info = {"hostname": socket.gethostname(), "ip_address": get_local_ip(),
            "os_info": f"{platform.system()} {platform.release()}",
            "battery_level": lvl, "battery_charging": charging,
            "agent_version": AGENT_VERSION}
    try:
        info["cpu_percent"] = psutil.cpu_percent(interval=0.3)
        m = psutil.virtual_memory()
        info["ram_percent"] = m.percent
        d = psutil.disk_usage("/")
        info["disk_percent"] = d.percent
    except: pass
    return info

# ── DISK SCAN ────────────────────────────────────────────────
async def do_disk_scan(ws, device_id):
    log.info("Running disk scan...")
    details = []
    try:
        for part in psutil.disk_partitions():
            try:
                u = psutil.disk_usage(part.mountpoint)
                details.append({"path": part.mountpoint, "size": f"{u.used/1e9:.1f}GB",
                                 "total": f"{u.total/1e9:.1f}GB", "pct": round(u.percent)})
            except: pass
        # Top folders on C:
        try:
            result = subprocess.run(
                ["powershell","-Command",
                 "Get-ChildItem C:\\ -ErrorAction SilentlyContinue | ForEach-Object { $s=(Get-ChildItem $_.FullName -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum; if($s -gt 100MB){[pscustomobject]@{path=$_.FullName;bytes=$s}} } | Sort-Object bytes -Descending | Select-Object -First 10 | ConvertTo-Json"],
                capture_output=True, text=True, timeout=60)
            if result.returncode == 0 and result.stdout.strip():
                folders = json.loads(result.stdout)
                if isinstance(folders, dict): folders = [folders]
                for f in folders:
                    details.append({"path": f.get("path",""), "size": f"{f.get('bytes',0)/1e9:.1f}GB",
                                    "pct": 0, "type": "folder"})
        except: pass
    except Exception as e:
        log.warning(f"Disk scan error: {e}")
    if ws:
        await ws.send(json.dumps({"type":"disk_scan","data":{"details":details}}))
    return details

# ── TASK EXECUTION ────────────────────────────────────────────
async def execute_task(task_data, ws, device_id):
    task_id     = task_data.get("task_id","?")
    script_type = task_data.get("script_type","powershell")
    script_body = task_data.get("script_body","")
    started_at  = datetime.utcnow().isoformat()
    log.info(f"Running task {task_id} ({script_type})")

    if script_type == "powershell":
        cmd = ["powershell","-NonInteractive","-NoProfile","-Command",script_body]
    elif script_type == "cmd":
        cmd = ["cmd","/c",script_body]
    elif script_type == "python":
        cmd = [sys.executable,"-c",script_body]
    elif script_type == "bash":
        cmd = ["wsl","bash","-c",script_body]
    else:
        cmd = ["powershell","-Command",script_body]

    stdout_buf, stderr_buf = [], []
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

        async def stream_stdout():
            while True:
                line = await proc.stdout.readline()
                if not line: break
                text = line.decode("utf-8","replace")
                stdout_buf.append(text)
                if ws:
                    try:
                        await ws.send(json.dumps({"type":"task_output","task_id":task_id,
                                                   "output":text,"progress":50}))
                    except: pass

        async def stream_stderr():
            while True:
                line = await proc.stderr.readline()
                if not line: break
                stderr_buf.append(line.decode("utf-8","replace"))

        await asyncio.gather(stream_stdout(), stream_stderr(),
                             asyncio.wait_for(proc.wait(), timeout=300))
        exit_code = proc.returncode
    except asyncio.TimeoutError:
        proc.kill(); exit_code = -1; stderr_buf.append("Task timed out after 300s")
    except Exception as e:
        exit_code = -1; stderr_buf.append(str(e))

    result = {"task_id":task_id,"exit_code":exit_code,
              "stdout":"".join(stdout_buf)[:65535],
              "stderr":"".join(stderr_buf)[:16383],
              "started_at":started_at}
    # Toast notification — success or failure
    task_name = task_data.get("name", f"Task {task_id[:8]}")
    if exit_code == 0:
        notify("RMM Task Complete ✓", f"{task_name} finished successfully.")
    else:
        err_preview = "".join(stderr_buf)[:80].strip() or f"Exit code {exit_code}"
        notify("RMM Task Failed ✗", f"{task_name}: {err_preview}", "error")
    if ws:
        try:
            await ws.send(json.dumps({"type":"task_result","data":result}))
            await ws.send(json.dumps({"type":"task_output","task_id":task_id,"output":"","progress":100}))
        except: pass
    return result

# ── CRON HELPER ───────────────────────────────────────────────
def cron_next_run(expr):
    """Very basic cron: 'minute hour * * weekday'"""
    try:
        parts = expr.strip().split()
        if len(parts) < 5: return None
        minute, hour = int(parts[0]), int(parts[1])
        now = datetime.utcnow()
        candidate = now.replace(minute=minute, hour=hour, second=0, microsecond=0)
        if candidate <= now: candidate += timedelta(days=1)
        if parts[4] != "*":
            target_wd = int(parts[4])
            while candidate.weekday() != target_wd:
                candidate += timedelta(days=1)
        return candidate
    except: return None

def task_is_due(task):
    trigger = task.get("trigger_type","now")
    if trigger == "now": return True
    if trigger == "once":
        t = task.get("scheduled_at")
        if not t: return False
        return datetime.utcnow() >= datetime.fromisoformat(t)
    if trigger == "interval":
        interval = task.get("interval_seconds", 3600)
        last = task.get("last_run")
        if not last: return True
        return (datetime.utcnow()-datetime.fromisoformat(last)).total_seconds() >= interval
    if trigger == "cron":
        expr = task.get("cron_expression","")
        next_run = cron_next_run(expr)
        if not next_run: return False
        last = task.get("last_run")
        if not last: return datetime.utcnow() >= next_run
        return datetime.utcnow() >= next_run and datetime.fromisoformat(last) < next_run
    if trigger == "event":
        # Event tasks are triggered by the event loop, not here
        return False
    return False

# ── PRE-RUN SERVER CHECK ──────────────────────────────────────
def check_task_still_active(task_id, server_ip):
    """5 min before run: confirm server hasn't cancelled the task."""
    try:
        r = requests.get(
            f"http://{server_ip}:{SERVER_PORT}/api/dashboard/tasks/{task_id}",
            headers={"X-Agent-Token": AGENT_TOKEN}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return not data.get("cancelled", False)
        return True  # Can't reach server — run anyway
    except:
        return True  # Server offline — run anyway

# ── CHECKIN ───────────────────────────────────────────────────
def do_checkin(device_id, server_ip):
    info = get_system_info()
    payload = {"device_id":device_id,"agent_version":AGENT_VERSION,"platform":"windows",**info}
    try:
        r = requests.post(f"http://{server_ip}:{SERVER_PORT}/api/agent/checkin",
            json=payload, headers={"X-Agent-Token":AGENT_TOKEN}, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"Checkin failed: {e}"); return None

# ── SELF UPDATE ───────────────────────────────────────────────
def check_for_update(server_ip, device_id):
    try:
        data = do_checkin(device_id, server_ip)
        if data and data.get("update_available") and data.get("auto_update"):
            log.info(f"Update available: {data['update_available']} — downloading...")
            ver = data["update_available"]
            url = f"http://{server_ip}:{SERVER_PORT}/api/builds/download/SovereignRMM-Windows-{ver}.exe"
            r = requests.get(url, headers={"X-Agent-Token":AGENT_TOKEN}, timeout=120, stream=True)
            if r.status_code == 200:
                new_exe = APP_DIR / f"SovereignRMM-{ver}.exe"
                with open(new_exe,"wb") as f:
                    for chunk in r.iter_content(8192): f.write(chunk)
                log.info(f"Downloaded {new_exe}. Installing...")
                subprocess.Popen([str(new_exe),"--update"], shell=True)
    except Exception as e:
        log.warning(f"Update check failed: {e}")

# ── SCHEDULED TASK RUNNER ─────────────────────────────────────
async def local_task_runner(ws_ref, device_id):
    """Runs scheduled tasks from local cache. Works even when server is offline."""
    while True:
        try:
            tasks = [t for t in load_tasks() if not t.get("cancelled")]
            for task in tasks:
                if not task_is_due(task): continue
                task_id = task.get("task_id","?")
                trigger = task.get("trigger_type","now")
                # 5-min pre-check for once/cron/interval tasks
                if trigger in ("once","cron","interval"):
                    server_ip = state_get("active_ip", SERVER_IP_LOCAL)
                    if not check_task_still_active(task_id, server_ip):
                        log.info(f"Task {task_id} cancelled on server — skipping")
                        cancel_task_local(task_id); continue
                log.info(f"Running scheduled task: {task.get('name','?')} [{trigger}]")
                notify("Sovereign RMM", f"Running task: {task.get('name','?')}")
                await execute_task(task, ws_ref[0], device_id)
                # Update last_run or remove if 'once'
                if trigger == "once":
                    remove_task(task_id)
                else:
                    tasks2 = load_tasks()
                    for t in tasks2:
                        if t.get("task_id") == task_id:
                            t["last_run"] = datetime.utcnow().isoformat()
                    save_tasks(tasks2)
        except Exception as e:
            log.error(f"Task runner error: {e}")
        await asyncio.sleep(30)

# ── EVENT TASK WATCHER ────────────────────────────────────────
async def event_task_watcher(ws_ref, device_id):
    """Watches for system events and runs event-triggered tasks."""
    last_network = get_network_info()
    while True:
        try:
            tasks = [t for t in load_tasks()
                     if t.get("trigger_type") == "event" and not t.get("cancelled")]
            current_network = get_network_info()
            network_changed = current_network.get("ssid") != last_network.get("ssid")
            if network_changed:
                last_network = current_network
                log.info(f"Network change detected: {current_network['ssid']}")
                state_set("active_ip","")  # Force IP retest after network change
            for task in tasks:
                event = task.get("event_trigger","")
                if event == "network_change" and network_changed:
                    await execute_task(task, ws_ref[0], device_id)
        except Exception as e:
            log.error(f"Event watcher error: {e}")
        await asyncio.sleep(15)

# ── WEEKLY IP RETEST ──────────────────────────────────────────
async def weekly_ip_retest():
    while True:
        last = state_get("last_ip_test","")
        wait = WEEK
        if last:
            try:
                elapsed = (datetime.utcnow()-datetime.fromisoformat(last)).total_seconds()
                wait = max(WEEK - elapsed, 3600)
            except: pass
        await asyncio.sleep(wait)
        log.info("Weekly IP retest...")
        select_server_ip(force=True)

# ── WEBSOCKET LOOP ────────────────────────────────────────────
async def ws_loop(device_id, ws_ref):
    global policy
    while True:
        server_ip = select_server_ip()
        url = f"ws://{server_ip}:{SERVER_PORT}/ws/agent/{device_id}?token={AGENT_TOKEN}"
        try:
            log.info(f"Connecting: {url}")
            async with websockets.connect(url, ping_interval=30, ping_timeout=15) as ws:
                ws_ref[0] = ws
                log.info("Connected!")
                log.debug("WebSocket connected — sending reconnect toast if was offline")
                if state_load().get("was_offline"):
                    notify("Sovereign RMM", "Connection to management server restored.")
                    state_save({**state_load(), "was_offline": False})
                async def heartbeat():
                    while True:
                        info = get_system_info()
                        await ws.send(json.dumps({"type":"heartbeat","data":info}))
                        await asyncio.sleep(get_checkin_interval())
                async def receive():
                    global policy
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            t = msg.get("type")
                            if t == "run_task":
                                asyncio.create_task(execute_task(msg.get("data",{}), ws, device_id))
                            elif t == "schedule_task":
                                add_or_update_task(msg.get("data",{}))
                                log.info(f"Scheduled task received: {msg['data'].get('name')}")
                            elif t == "cancel_task":
                                cancel_task_local(msg.get("task_id",""))
                            elif t == "update_policy":
                                policy.update(msg.get("data",{}))
                            elif t == "disk_scan_request":
                                asyncio.create_task(do_disk_scan(ws, device_id))
                        except Exception as e:
                            log.error(f"Message error: {e}")
                await asyncio.gather(heartbeat(), receive())
        except Exception as e:
            ws_ref[0] = None
            log.warning(f"Disconnected: {e} — retry in 30s")
            state_set("last_ip_test","")
            await asyncio.sleep(30)

# ── MAIN ─────────────────────────────────────────────────────
async def main():
    device_id = get_device_id()
    log.info("=" * 60)
    log.info(f"  Sovereign RMM Agent v{AGENT_VERSION} starting")
    log.info(f"  Device ID  : {device_id}")
    log.info(f"  Hostname   : {socket.gethostname()}")
    log.info(f"  Log file   : {LOG_FILE}")
    log.info(f"  Server     : {SERVER_IP_LOCAL} (local) / {SERVER_IP_VPN} (vpn)")
    log.info("=" * 60)
    server_ip = select_server_ip()

    # Initial checkin — retry up to 10 times, 30s apart
    checked_in = False
    for attempt in range(1, 11):
        resp = do_checkin(device_id, server_ip)
        if resp:
            if "policy" in resp: policy.update(resp["policy"])
            for task in resp.get("scheduled_tasks", []):
                add_or_update_task(task)
            tasks_n = len(resp.get("scheduled_tasks", []))
            log.info(f"✓ Checked in to {server_ip}:{SERVER_PORT} — {tasks_n} scheduled task(s) loaded")
            checked_in = True
            break
        log.warning(f"Checkin attempt {attempt}/10 failed — retrying in 30s (server: {server_ip}:{SERVER_PORT})")
        await asyncio.sleep(30)
        server_ip = select_server_ip()

    if not checked_in:
        log.error("Could not reach server after 10 attempts — running in offline mode")
        notify("Sovereign RMM — Warning", "Cannot reach management server. Running in offline mode.", "warning")
        log.error(f"  Check that the server is reachable at {SERVER_IP_LOCAL} or {SERVER_IP_VPN} port {SERVER_PORT}")

    ws_ref = [None]  # mutable ref so loops can update it
    await asyncio.gather(
        ws_loop(device_id, ws_ref),
        local_task_runner(ws_ref, device_id),
        event_task_watcher(ws_ref, device_id),
        weekly_ip_retest(),
    )

if __name__ == "__main__":
    _run()

# ── HARDWARE SCAN (appended to agent) ───────────────────────

def get_mac_address():
    try:
        import uuid as _uuid
        mac = _uuid.UUID(int=_uuid.getnode()).hex[-12:]
        return ':'.join(mac[i:i+2] for i in range(0,12,2)).upper()
    except: return None

def collect_hardware_info():
    hw = {}
    try:
        # CPU
        result = subprocess.run(
            ['powershell','-Command',
             'Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed | ConvertTo-Json'],
            capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            cpu_data = json.loads(result.stdout)
            if isinstance(cpu_data, list): cpu_data = cpu_data[0]
            hw['cpu'] = {
                'name': cpu_data.get('Name','').strip(),
                'cores': cpu_data.get('NumberOfCores'),
                'threads': cpu_data.get('NumberOfLogicalProcessors'),
                'speed': round(cpu_data.get('MaxClockSpeed',0)/1000, 2),
            }
    except: pass
    try:
        # RAM
        result = subprocess.run(
            ['powershell','-Command',
             'Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,MemoryType,SMBIOSMemoryType | ConvertTo-Json'],
            capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            sticks = json.loads(result.stdout)
            if isinstance(sticks, dict): sticks = [sticks]
            total = sum(int(s.get('Capacity',0)) for s in sticks)
            hw['ram'] = {
                'total_gb': round(total/1073741824, 1),
                'slots': [{'size': round(int(s.get('Capacity',0))/1073741824), 'speed': s.get('Speed'), 'type': 'DDR'} for s in sticks]
            }
    except: pass
    try:
        # GPU
        result = subprocess.run(
            ['powershell','-Command','Get-CimInstance Win32_VideoController | Select-Object Name | ConvertTo-Json'],
            capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            gpu_data = json.loads(result.stdout)
            if isinstance(gpu_data, dict): gpu_data = [gpu_data]
            hw['gpu'] = {'name': ', '.join(g.get('Name','') for g in gpu_data)}
    except: pass
    try:
        # Disks
        result = subprocess.run(
            ['powershell','-Command',
             'Get-PhysicalDisk | Select-Object FriendlyName,MediaType,Size,SerialNumber | ConvertTo-Json'],
            capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            disks = json.loads(result.stdout)
            if isinstance(disks, dict): disks = [disks]
            hw['disks'] = [{'model': d.get('FriendlyName'), 'size': f"{round(int(d.get('Size',0))/1e9)}GB",
                            'serial': d.get('SerialNumber','').strip(), 'type': d.get('MediaType')} for d in disks]
    except: pass
    try:
        # Motherboard
        result = subprocess.run(
            ['powershell','-Command','Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer,Product | ConvertTo-Json'],
            capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            mb = json.loads(result.stdout)
            hw['motherboard'] = {'manufacturer': mb.get('Manufacturer','').strip(), 'model': mb.get('Product','').strip()}
    except: pass
    hw['mac'] = get_mac_address()
    return hw

async def hw_scan_loop(ws_ref, device_id, server_ip):
    """Run hardware scan on startup and periodically."""
    await asyncio.sleep(60)  # Wait for connection first
    while True:
        try:
            log.info("Running hardware scan...")
            hw = collect_hardware_info()
            # Report to server
            requests.post(
                f"http://{server_ip}:{SERVER_PORT}/api/hardware/{device_id}/report",
                json=hw, headers={"X-Agent-Token": AGENT_TOKEN}, timeout=30)
            # Also report MAC via checkin
            if hw.get('mac'):
                state_set("mac_address", hw['mac'])
        except Exception as e:
            log.warning(f"HW scan error: {e}")
        await asyncio.sleep(30*24*3600)  # Monthly

# ══════════════════════════════════════════════════════════════
# SOFTWARE INVENTORY
# ══════════════════════════════════════════════════════════════

def collect_software():
    apps = []
    try:
        result = subprocess.run([
            'powershell','-Command',
            'Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*,'
            'HKLM:\\Software\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* '
            '| Select-Object DisplayName,DisplayVersion,Publisher,InstallDate '
            '| Where-Object {$_.DisplayName} | ConvertTo-Json -Depth 2'
        ], capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            items = json.loads(result.stdout)
            if isinstance(items, dict): items = [items]
            for item in items:
                name = (item.get('DisplayName') or '').strip()
                if name:
                    apps.append({
                        'name': name,
                        'version': (item.get('DisplayVersion') or '').strip(),
                        'publisher': (item.get('Publisher') or '').strip(),
                        'install_date': (item.get('InstallDate') or '').strip(),
                    })
    except Exception as e:
        log.warning(f"Software scan error: {e}")
    return apps


async def software_scan_loop(server_ip, device_id):
    await asyncio.sleep(120)
    while True:
        try:
            log.info("Running software inventory scan...")
            apps = collect_software()
            requests.post(
                f"http://{server_ip}:{SERVER_PORT}/api/software/{device_id}/report",
                json={"apps": apps},
                headers={"X-Agent-Token": AGENT_TOKEN},
                timeout=60
            )
            log.info(f"Software scan: {len(apps)} apps reported")
        except Exception as e:
            log.warning(f"Software scan upload error: {e}")
        await asyncio.sleep(7 * 24 * 3600)  # Weekly


# ══════════════════════════════════════════════════════════════
# PROCESS LIST
# ══════════════════════════════════════════════════════════════

def get_process_list():
    procs = []
    try:
        result = subprocess.run([
            'powershell','-Command',
            'Get-Process | Select-Object Id,Name,CPU,WorkingSet,Path | Sort-Object CPU -Descending | Select-Object -First 60 | ConvertTo-Json'
        ], capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            items = json.loads(result.stdout)
            if isinstance(items, dict): items = [items]
            for p in items:
                procs.append({
                    'pid': p.get('Id'), 'name': p.get('Name',''),
                    'cpu': round(p.get('CPU') or 0, 1),
                    'mem_mb': round((p.get('WorkingSet') or 0) / 1048576, 1),
                    'path': p.get('Path',''),
                })
    except Exception as e:
        log.warning(f"Process list error: {e}")
    return procs


def kill_process_by_pid(pid):
    try:
        subprocess.run(['powershell','-Command', f'Stop-Process -Id {pid} -Force'],
                       capture_output=True, timeout=10)
        return True
    except:
        return False


# ══════════════════════════════════════════════════════════════
# QUICK ACTIONS
# ══════════════════════════════════════════════════════════════

def do_quick_action(action):
    cmds = {
        'shutdown': ['shutdown', '/s', '/t', '30'],
        'restart':  ['shutdown', '/r', '/t', '30'],
        'lock':     ['rundll32.exe', 'user32.dll,LockWorkStation'],
        'sleep':    ['rundll32.exe', 'powrprof.dll,SetSuspendState', '0', '1', '0'],
    }
    cmd = cmds.get(action)
    if cmd:
        subprocess.Popen(cmd)
        return True
    return False


# ══════════════════════════════════════════════════════════════
# PATCH WEBSOCKET HANDLER to handle new message types
# ══════════════════════════════════════════════════════════════

_orig_handle_ws_message = handle_ws_message if 'handle_ws_message' in dir() else None

async def handle_ws_message_v2(msg, ws, device_id, server_ip):
    """Extended WS message handler for v2 features."""
    t = msg.get("type")
    if t == "get_processes":
        procs = get_process_list()
        await ws.send(json.dumps({"type": "process_list", "data": procs}))
    elif t == "kill_process":
        pid = msg.get("data", {}).get("pid")
        if pid:
            success = kill_process_by_pid(int(pid))
            await ws.send(json.dumps({"type": "kill_result", "data": {"pid": pid, "success": success}}))
    elif t == "quick_action":
        action = msg.get("data", {}).get("action")
        if action:
            do_quick_action(action)
    elif t == "software_scan":
        apps = collect_software()
        requests.post(
            f"http://{server_ip}:{SERVER_PORT}/api/software/{device_id}/report",
            json={"apps": apps},
            headers={"X-Agent-Token": AGENT_TOKEN},
            timeout=60
        )
    elif t == "hw_scan_request":
        hw = collect_hardware_info()
        requests.post(
            f"http://{server_ip}:{SERVER_PORT}/api/hardware/{device_id}/report",
            json=hw, headers={"X-Agent-Token": AGENT_TOKEN}, timeout=30
        )


# ══════════════════════════════════════════════════════════════
# STARTUP INSTALLER — Task Scheduler + Registry fallback
# ══════════════════════════════════════════════════════════════

TASK_NAME = "SovereignRMMAgent"
INSTALL_DIR = r"C:\ProgramData\SovereignRMM"
AGENT_EXE_NAME = "sovereign-agent.exe"

def is_admin():
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def get_install_path():
    return os.path.join(INSTALL_DIR, AGENT_EXE_NAME)

def install_agent():
    """Install agent to ProgramData and register as Task Scheduler task (runs at boot as SYSTEM)."""
    import shutil, ctypes

    exe_path = sys.executable  # When compiled with PyInstaller this is the .exe
    install_path = get_install_path()

    print(f"[Install] Installing Sovereign RMM Agent...")

    # 1. Create install directory
    os.makedirs(INSTALL_DIR, exist_ok=True)

    # 2. Copy exe to install directory (skip if already running from there)
    if os.path.abspath(exe_path).lower() != os.path.abspath(install_path).lower():
        print(f"[Install] Copying to {install_path}")
        shutil.copy2(exe_path, install_path)
    else:
        print(f"[Install] Already running from install location")

    # 3. Register Task Scheduler task (runs at system startup, no login required)
    task_xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Sovereign RMM Monitoring Agent</Description>
    <Author>Sovereign RMM</Author>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger>
      <Enabled>true</Enabled>
      <Delay>PT10S</Delay>
    </BootTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-18</UserId>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>false</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions>
    <Exec>
      <Command>{install_path}</Command>
      <WorkingDirectory>{INSTALL_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""

    xml_path = os.path.join(INSTALL_DIR, "task.xml")
    with open(xml_path, "w", encoding="utf-16") as f:
        f.write(task_xml)

    result = subprocess.run(
        ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", xml_path, "/F"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"[Install] Task Scheduler task '{TASK_NAME}' registered ✓")
    else:
        print(f"[Install] Task Scheduler failed: {result.stderr.strip()}")
        print(f"[Install] Falling back to registry Run key...")
        _install_registry_fallback(install_path)

    # 4. Also add HKLM registry Run key as belt-and-suspenders backup
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "SovereignRMMAgent", 0, winreg.REG_SZ, f'"{install_path}"')
        winreg.CloseKey(key)
        print(f"[Install] Registry Run key added ✓")
    except Exception as e:
        print(f"[Install] Registry key skipped (may need admin): {e}")

    # 5. Clean up temp xml
    try: os.remove(xml_path)
    except: pass

    print(f"\n✓ Sovereign RMM Agent installed successfully")
    print(f"  Location : {install_path}")
    print(f"  Task     : {TASK_NAME} (starts at boot, restarts on failure)")
    print(f"\nThe agent will start automatically on next boot.")
    print(f"To start it now, run: schtasks /Run /TN {TASK_NAME}")


def _install_registry_fallback(install_path):
    """HKCU fallback — starts on user login instead of boot."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "SovereignRMMAgent", 0, winreg.REG_SZ, f'"{install_path}"')
        winreg.CloseKey(key)
        print(f"[Install] HKCU Registry Run key set ✓ (starts on login)")
    except Exception as e:
        print(f"[Install] Registry fallback also failed: {e}")


def uninstall_agent():
    """Remove task scheduler task and registry keys."""
    print("[Uninstall] Removing Sovereign RMM Agent...")

    # Remove Task Scheduler task
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("[Uninstall] Task Scheduler task removed ✓")
    else:
        print(f"[Uninstall] Task not found or already removed")

    # Remove HKLM registry key
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, "SovereignRMMAgent")
        winreg.CloseKey(key)
        print("[Uninstall] HKLM registry key removed ✓")
    except: pass

    # Remove HKCU registry key
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, "SovereignRMMAgent")
        winreg.CloseKey(key)
        print("[Uninstall] HKCU registry key removed ✓")
    except: pass

    print("\n✓ Agent uninstalled. Files remain at:")
    print(f"  {INSTALL_DIR}")
    print("  Delete that folder manually if you want a clean removal.")


def check_already_running():
    """Return True if another instance is already running."""
    try:
        import psutil
        this_pid = os.getpid()
        this_name = os.path.basename(sys.executable).lower()
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            if proc.pid == this_pid:
                continue
            try:
                exe = (proc.info.get('exe') or '').lower()
                if AGENT_EXE_NAME.lower() in exe or (
                    proc.info.get('name','').lower() == this_name and
                    proc.pid != this_pid
                ):
                    return True
            except: pass
    except: pass
    return False


def hide_console():
    """Hide the console window — agent runs silently in background."""
    try:
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except: pass


# ══════════════════════════════════════════════════════════════
# PATCHED ENTRY POINT
# ══════════════════════════════════════════════════════════════

def _run():
    args = sys.argv[1:]

    if "--install" in args:
        if not is_admin():
            # Re-launch with admin rights
            try:
                import ctypes
                ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", sys.executable,
                    " ".join(sys.argv), None, 1
                )
            except Exception as e:
                print(f"[Install] Could not elevate: {e}")
                print("Please run as Administrator.")
            return

        install_agent()
        input("\nPress Enter to close...")
        return

    if "--uninstall" in args:
        uninstall_agent()
        input("\nPress Enter to close...")
        return

    if "--status" in args:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(result.stdout)
        else:
            print(f"Task '{TASK_NAME}' not found — agent may not be installed.")
        return

    # Normal run: check for duplicate instance, hide console, start agent
    if "--foreground" not in args:
        if check_already_running():
            sys.exit(0)  # Already running, exit silently
        hide_console()

    try: import psutil, websockets, requests
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "psutil", "websockets", "requests"])
        import psutil, websockets, requests

    asyncio.run(main())
