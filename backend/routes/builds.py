"""Agent Builder — Windows MSI, Linux .deb/.sh, Android zip."""
import os, shutil, subprocess, sys, textwrap, uuid, zipfile, urllib.request, json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")
BUILD_DIR   = Path("/app/agent-builds")
BUILD_DIR.mkdir(parents=True, exist_ok=True)

WIN_TEMPLATE     = Path("/app/agent/windows_agent.py")
LINUX_TEMPLATE   = Path("/app/agent-linux/linux_agent.py")
ANDROID_TEMPLATE = Path("/app/agent-android/android_agent.py")

PYTHON_EMBED_URL = "https://www.python.org/ftp/python/3.12.4/python-3.12.4-embed-amd64.zip"
PYTHON_EMBED_CACHE = Path("/app/agent-builds/.python-embed-cache.zip")


def bake(template: Path, local_ip, vpn_ip, port, token) -> str:
    src = template.read_text()
    return (src
        .replace('"RMM_LOCAL_IP"', f'"{local_ip}"')
        .replace('"RMM_VPN_IP"',   f'"{vpn_ip}"')
        .replace('"RMM_PORT"',     f'"{port}"')
        .replace('"RMM_TOKEN"',    f'"{token}"'))


def get_python_embed() -> Path:
    """Download and cache the Python embeddable package."""
    if PYTHON_EMBED_CACHE.exists():
        return PYTHON_EMBED_CACHE
    print("[MSI] Downloading Python embeddable package...")
    urllib.request.urlretrieve(PYTHON_EMBED_URL, PYTHON_EMBED_CACHE)
    print("[MSI] Download complete.")
    return PYTHON_EMBED_CACHE


def build_msi(local_ip: str, vpn_ip: str, port: str, token: str) -> Path:
    """Build a Windows MSI installer using wixl."""
    build_id = str(uuid.uuid4())[:8]
    work_dir = BUILD_DIR / f"msi-{build_id}"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Bake agent script
        agent_content = bake(WIN_TEMPLATE, local_ip, vpn_ip, port, token)
        agent_py = work_dir / "sovereign_agent.py"
        agent_py.write_text(agent_content)

        # 2. Extract Python embeddable
        embed_zip = get_python_embed()
        py_dir = work_dir / "python"
        py_dir.mkdir()
        with zipfile.ZipFile(embed_zip) as zf:
            zf.extractall(py_dir)

        # 3. Copy pip and requests into embed
        # Create a launcher script
        launcher = work_dir / "sovereign_launcher.bat"
        launcher.write_text(
            '@echo off\r\n'
            'cd /d "%~dp0"\r\n'
            'start /b "" pythonw.exe sovereign_agent.py\r\n'
        )

        # Silent launcher (no console window at startup)
        silent_launcher = work_dir / "sovereign_start.vbs"
        silent_launcher.write_text(
            'Set oShell = CreateObject("WScript.Shell")\r\n'
            'sFile = """" & WScript.ScriptFullName & """"\r\n'
            'sDir = Left(sFile, InStrRev(sFile, "\\"))\r\n'
            'oShell.Run "cmd /c cd /d " & sDir & " & pythonw.exe sovereign_agent.py", 0, False\r\n'
        )

        # Uninstall script (cleanup scheduled task)
        uninstall_ps = work_dir / "uninstall.ps1"
        uninstall_ps.write_text(
            'Unregister-ScheduledTask -TaskName "SovereignRMM" -Confirm:$false -ErrorAction SilentlyContinue\r\n'
            'Remove-ItemProperty -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run" -Name "SovereignRMM" -ErrorAction SilentlyContinue\r\n'
        )

        # Install script (creates scheduled task that survives login)
        install_ps = work_dir / "install.ps1"
        install_ps.write_text(
            '$installDir = $env:ProgramFiles + "\\SovereignRMM"\r\n'
            '$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument """$installDir\\sovereign_start.vbs"""\r\n'
            '$trigger = New-ScheduledTaskTrigger -AtLogOn\r\n'
            '$trigger2 = New-ScheduledTaskTrigger -AtStartup\r\n'
            '$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RunOnlyIfNetworkAvailable:$false\r\n'
            '$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest\r\n'
            'Register-ScheduledTask -TaskName "SovereignRMM" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force\r\n'
            '# Also start immediately\r\n'
            'Start-Process "wscript.exe" -ArgumentList """$installDir\\sovereign_start.vbs""" -WindowStyle Hidden\r\n'
        )

        # 4. Generate a stable product GUID based on the token (reproducible)
        import hashlib
        product_guid = str(uuid.UUID(hashlib.md5(token.encode()).hexdigest()))
        component_guid = str(uuid.uuid4())

        # Collect all Python embed files for WiX
        py_files = list(py_dir.rglob("*"))
        py_components = ""
        component_ids = []
        for i, f in enumerate(py_files):
            if f.is_file():
                rel = f.relative_to(py_dir)
                cid = f"PyFile{i}"
                component_ids.append(cid)
                py_components += f"""
          <Component Id="{cid}" Guid="*">
            <File Id="{cid}File" Source="{f}" Name="{f.name}" KeyPath="yes"/>
          </Component>"""

        component_refs = "\n".join(f'        <ComponentRef Id="{cid}"/>' for cid in component_ids)

        # 5. Write WiX source
        wxs = work_dir / "sovereign.wxs"
        wxs.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="{product_guid}"
           Name="Sovereign RMM Agent"
           Language="1033"
           Version="4.0.0"
           Manufacturer="Sovereign RMM"
           UpgradeCode="12345678-1234-1234-1234-{hashlib.md5(b'sovereign-rmm').hexdigest()[:12]}">

    <Package InstallerVersion="200" Compressed="yes" InstallScope="perMachine"/>
    <MajorUpgrade DowngradeErrorMessage="A newer version is already installed."/>
    <MediaTemplate EmbedCab="yes"/>

    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="ProgramFilesFolder">
        <Directory Id="INSTALLDIR" Name="SovereignRMM">

          <!-- Main agent files -->
          <Component Id="AgentScript" Guid="{component_guid}">
            <File Id="AgentPy"       Source="{agent_py}"        Name="sovereign_agent.py"  KeyPath="yes"/>
            <File Id="LauncherBat"   Source="{launcher}"         Name="sovereign_launcher.bat"/>
            <File Id="LauncherVbs"   Source="{silent_launcher}"  Name="sovereign_start.vbs"/>
            <File Id="InstallPs1"    Source="{install_ps}"       Name="install.ps1"/>
            <File Id="UninstallPs1"  Source="{uninstall_ps}"     Name="uninstall.ps1"/>
          </Component>
          <!-- Registry autostart — separate component so KeyPath is unambiguous -->
          <Component Id="AgentRegKey" Guid="*">
            <RegistryValue Root="HKLM"
              Key="SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run"
              Name="SovereignRMM"
              Type="string"
              Value="wscript.exe &quot;[INSTALLDIR]sovereign_start.vbs&quot;"
              KeyPath="yes"/>
          </Component>

          <!-- Python embeddable runtime -->
          {py_components}

        </Directory>
      </Directory>
    </Directory>

    <Feature Id="ProductFeature" Title="Sovereign RMM Agent" Level="1">
      <ComponentRef Id="AgentScript"/>
      <ComponentRef Id="AgentRegKey"/>
      {component_refs}
    </Feature>

    <!-- Run install.ps1 after install to register scheduled task -->
    <CustomAction Id="RegisterScheduledTask"
                  Directory="INSTALLDIR"
                  ExeCommand="powershell.exe -ExecutionPolicy Bypass -NonInteractive -File &quot;[INSTALLDIR]install.ps1&quot;"
                  Execute="deferred"
                  Impersonate="no"
                  Return="ignore"/>

    <!-- Run uninstall.ps1 before uninstall -->
    <CustomAction Id="UnregisterScheduledTask"
                  Directory="INSTALLDIR"
                  ExeCommand="powershell.exe -ExecutionPolicy Bypass -NonInteractive -File &quot;[INSTALLDIR]uninstall.ps1&quot;"
                  Execute="deferred"
                  Impersonate="no"
                  Return="ignore"/>

    <InstallExecuteSequence>
      <Custom Action="RegisterScheduledTask"   After="InstallFiles">NOT Installed</Custom>
      <Custom Action="UnregisterScheduledTask" Before="RemoveFiles">Installed AND NOT UPGRADINGPRODUCTCODE</Custom>
    </InstallExecuteSequence>

  </Product>
</Wix>
""")

        # 6. Run wixl to compile MSI
        out_msi = BUILD_DIR / f"SovereignRMM-Agent-{build_id}.msi"
        result = subprocess.run(
            ["wixl", "-v", "-o", str(out_msi), str(wxs), "-D", "SourceDir=" + str(work_dir)],
            capture_output=True, text=True, cwd=str(work_dir)
        )
        if result.returncode != 0:
            print(f"[wixl stderr] {result.stderr}")
            raise RuntimeError(f"wixl failed: {result.stderr[:800]}")

        return out_msi

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ── ENDPOINTS ─────────────────────────────────────────────────

@router.post("/build/windows")
async def build_windows_msi(data: dict):
    """Build Windows MSI installer."""
    local_ip = data.get("local_ip", os.getenv("SERVER_IP", "192.168.5.199"))
    vpn_ip   = data.get("vpn_ip",   "100.125.120.81")
    port     = data.get("port",     os.getenv("BACKEND_PORT", "8000"))
    token    = data.get("token",    AGENT_TOKEN)

    if not WIN_TEMPLATE.exists():
        raise HTTPException(404, "Windows agent template not found")

    try:
        msi_path = build_msi(local_ip, vpn_ip, port, token)
        return FileResponse(
            str(msi_path),
            media_type="application/x-msi",
            filename=msi_path.name
        )
    except Exception as e:
        raise HTTPException(500, f"MSI build failed: {e}")


@router.post("/build/linux")
async def build_linux(data: dict):
    local_ip = data.get("local_ip", os.getenv("SERVER_IP", "192.168.5.199"))
    vpn_ip   = data.get("vpn_ip",   "100.125.120.81")
    port     = data.get("port",     os.getenv("BACKEND_PORT", "8000"))
    token    = data.get("token",    AGENT_TOKEN)

    if not LINUX_TEMPLATE.exists():
        raise HTTPException(404, "Linux agent template not found")

    content = bake(LINUX_TEMPLATE, local_ip, vpn_ip, port, token)
    build_id = str(uuid.uuid4())[:8]

    installer = f"""#!/bin/bash
# Sovereign RMM Linux Agent Installer
set -e
echo "Installing Sovereign RMM Agent..."
INSTALL_DIR="/opt/sovereign-rmm"
mkdir -p "$INSTALL_DIR"

cat > "$INSTALL_DIR/agent.py" << 'AGENTEOF'
{content}
AGENTEOF

pip3 install --quiet psutil requests websockets 2>/dev/null || pip install --quiet psutil requests websockets

cat > /etc/systemd/system/sovereign-rmm.service << 'SVCEOF'
[Unit]
Description=Sovereign RMM Agent
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
Restart=always
RestartSec=30
ExecStart=/usr/bin/python3 /opt/sovereign-rmm/agent.py
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable sovereign-rmm
systemctl start sovereign-rmm
echo ""
echo "============================================"
echo "  Sovereign RMM Agent installed!"
echo "  Log file: /var/log/sovereign-rmm.log"
echo "  View live: tail -f /var/log/sovereign-rmm.log"
echo "  Service:   systemctl status sovereign-rmm"
echo "============================================"
echo ""
systemctl status sovereign-rmm --no-pager
"""

    out = BUILD_DIR / f"sovereign-rmm-linux-{build_id}.sh"
    out.write_text(installer)

    return FileResponse(str(out), media_type="application/x-sh", filename=out.name)


@router.post("/build/android")
async def build_android(data: dict):
    local_ip = data.get("local_ip", os.getenv("SERVER_IP", "192.168.5.199"))
    vpn_ip   = data.get("vpn_ip",   "100.125.120.81")
    port     = data.get("port",     os.getenv("BACKEND_PORT", "8000"))
    token    = data.get("token",    AGENT_TOKEN)

    if not ANDROID_TEMPLATE.exists():
        raise HTTPException(404, "Android agent template not found")

    content = bake(ANDROID_TEMPLATE, local_ip, vpn_ip, port, token)
    build_id = str(uuid.uuid4())[:8]

    setup = textwrap.dedent(f"""\
        #!/data/data/com.termux/files/usr/bin/bash
        # Sovereign RMM Android Agent Setup
        pkg update -y && pkg install -y python
        pip install psutil requests websockets
        mkdir -p ~/.sovereign-rmm
        cat > ~/.sovereign-rmm/agent.py << 'AGENTEOF'
{content}
AGENTEOF
        mkdir -p ~/.termux/boot
        echo "python ~/.sovereign-rmm/agent.py &" > ~/.termux/boot/sovereign-rmm.sh
        chmod +x ~/.termux/boot/sovereign-rmm.sh
        echo "Agent installed. Enable Termux:Boot for auto-start."
        python ~/.sovereign-rmm/agent.py &
    """)

    zip_path = BUILD_DIR / f"sovereign-rmm-android-{build_id}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("sovereign_agent.py", content)
        zf.writestr("setup.sh", setup)
        zf.writestr("README.txt",
            "1. Open Termux\n"
            "2. Run: bash setup.sh\n"
            "3. Install Termux:Boot from F-Droid for auto-start\n"
        )

    return FileResponse(str(zip_path), media_type="application/zip", filename=zip_path.name)


@router.get("/list")
async def list_builds():
    files = []
    for f in BUILD_DIR.iterdir():
        if f.is_file() and not f.name.startswith('.'):
            files.append({
                "name": f.name,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "modified": f.stat().st_mtime,
            })
    return sorted(files, key=lambda x: x["modified"], reverse=True)


@router.delete("/clean")
async def clean_builds():
    count = 0
    for f in BUILD_DIR.iterdir():
        if f.is_file() and not f.name.startswith('.'):
            f.unlink()
            count += 1
    return {"deleted": count}
