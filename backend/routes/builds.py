"""Agent Builder — Windows MSI, Linux .sh, Android .zip."""
import os, shutil, subprocess, sys, textwrap, uuid, zipfile, hashlib
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


def bake(template: Path, local_ip, vpn_ip, port, token) -> str:
    src = template.read_text()
    return (src
        .replace('"RMM_LOCAL_IP"', f'"{local_ip}"')
        .replace('"RMM_VPN_IP"',   f'"{vpn_ip}"')
        .replace('"RMM_PORT"',     f'"{port}"')
        .replace('"RMM_TOKEN"',    f'"{token}"'))


def build_msi(local_ip: str, vpn_ip: str, port: str, token: str) -> Path:
    """
    Build a Windows MSI using wixl (msitools).
    Installs to C:\\ProgramData\\SovereignRMM which avoids UAC issues
    and is accessible to SYSTEM account for the scheduled task.
    """
    build_id  = str(uuid.uuid4())[:8]
    work_dir  = BUILD_DIR / f"msi-{build_id}"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # ── 1. Bake agent script ────────────────────────────────
        agent_py = work_dir / "sovereign_agent.py"
        agent_py.write_text(bake(WIN_TEMPLATE, local_ip, vpn_ip, port, token))

        # ── 2. VBS silent launcher (no console window) ─────────
        # Writes to INSTALLDIR at install time via CustomAction
        launcher_vbs = work_dir / "run.vbs"
        launcher_vbs.write_text(
            'Set sh = CreateObject("WScript.Shell")\r\n'
            'sh.Run "pythonw.exe ""C:\\ProgramData\\SovereignRMM\\agent.py""", 0, False\r\n'
        )

        # ── 3. PowerShell post-install script ───────────────────
        # Registers scheduled task + installs pip deps + starts agent now
        post_install = work_dir / "post_install.ps1"
        # This script runs as SYSTEM during MSI install.
        # It does everything: pip deps, task registration, immediate start,
        # and a user-facing toast notification.
        post_install.write_text("\r\n".join([
            '$inst = "C:\\ProgramData\\SovereignRMM"',
            '$log  = "$inst\\install.log"',
            '"=== Sovereign RMM Post-Install ===" | Out-File $log -Append',
            '"Started: $(Get-Date)" | Out-File $log -Append',
            '',
            '# ── 1. Install Python dependencies ──────────────────────────',
            '"[1/4] Installing Python dependencies..." | Out-File $log -Append',
            'try {',
            '    $pip = python.exe -m pip install --quiet psutil requests websockets 2>&1',
            '    $pip | Out-File $log -Append',
            '    "[1/4] Done" | Out-File $log -Append',
            '} catch {',
            '    "[1/4] pip failed: $_" | Out-File $log -Append',
            '}',
            '',
            '# ── 2. Register scheduled task (SYSTEM, boot, auto-restart) ─',
            '"[2/4] Registering scheduled task..." | Out-File $log -Append',
            'try {',
            '    Unregister-ScheduledTask -TaskName "SovereignRMM" -Confirm:$false -ErrorAction SilentlyContinue',
            '    $action    = New-ScheduledTaskAction -Execute "wscript.exe" -Argument ("\\"" + $inst + "\\run.vbs\\"")',
            '    $trigger   = New-ScheduledTaskTrigger -AtStartup',
            '    $settings  = New-ScheduledTaskSettingsSet `',
            '                   -AllowStartIfOnBatteries `',
            '                   -DontStopIfGoingOnBatteries `',
            '                   -StartWhenAvailable `',
            '                   -RestartCount 9999 `',
            '                   -RestartInterval (New-TimeSpan -Minutes 1)',
            '    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest',
            '    Register-ScheduledTask -TaskName "SovereignRMM" `',
            '        -Action $action -Trigger $trigger `',
            '        -Settings $settings -Principal $principal -Force | Out-Null',
            '    "[2/4] Task registered" | Out-File $log -Append',
            '} catch {',
            '    "[2/4] Task failed: $_" | Out-File $log -Append',
            '    # Fallback: registry Run key',
            '    Set-ItemProperty -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run" `',
            '        -Name "SovereignRMM" -Value ("wscript.exe \\"" + $inst + "\\run.vbs\\"") -Force',
            '    "[2/4] Registry Run key set as fallback" | Out-File $log -Append',
            '}',
            '',
            '# ── 3. Start the agent RIGHT NOW ─────────────────────────────',
            '"[3/4] Starting agent..." | Out-File $log -Append',
            'try {',
            '    Start-ScheduledTask -TaskName "SovereignRMM" -ErrorAction Stop',
            '    "[3/4] Agent started via Task Scheduler" | Out-File $log -Append',
            '} catch {',
            '    # Task Scheduler start failed — launch directly',
            '    Start-Process "wscript.exe" -ArgumentList ("\\"" + $inst + "\\run.vbs\\"") -WindowStyle Hidden',
            '    "[3/4] Agent started directly" | Out-File $log -Append',
            '}',
            '',
            '# ── 4. Toast notification to ALL logged-in users ─────────────',
            '"[4/4] Sending install notification to users..." | Out-File $log -Append',
            '$notifyScript = @\'',
            '[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null',
            '[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] | Out-Null',
            '$xml = [Windows.Data.Xml.Dom.XmlDocument]::new()',
            '$xml.LoadXml(@"',
            '<toast>',
            '  <visual>',
            '    <binding template="ToastGeneric">',
            '      <text>Sovereign RMM Agent</text>',
            '      <text>Device management agent installed and running.</text>',
            '    </binding>',
            '  </visual>',
            '</toast>',
            '"@)',
            '$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)',
            '$app = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"',
            '[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show($toast)',
            '\'@',
            '# Run the notification in the context of each logged-in user',
            '$sessions = query session 2>$null | Select-String "Active" | ForEach-Object {',
            '    ($_ -split "\s+")[2]',
            '}',
            'foreach ($sid in $sessions) {',
            '    try {',
            '        $task = Register-ScheduledTask -TaskName "SovNotify_$sid" `',
            '            -Action (New-ScheduledTaskAction -Execute "powershell.exe" `',
            '                -Argument "-WindowStyle Hidden -EncodedCommand $([Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($notifyScript)))") `',
            '            -Principal (New-ScheduledTaskPrincipal -LogonType Interactive -RunLevel Limited -UserId $sid) `',
            '            -Force 2>$null',
            '        Start-ScheduledTask -TaskName "SovNotify_$sid" 2>$null',
            '        Start-Sleep 3',
            '        Unregister-ScheduledTask -TaskName "SovNotify_$sid" -Confirm:$false 2>$null',
            '    } catch {}',
            '}',
            '"[4/4] Done" | Out-File $log -Append',
            '"=== Install complete: $(Get-Date) ===" | Out-File $log -Append',
        ]))

        # Pre-uninstall: stop task before files are removed
        pre_uninstall = work_dir / "pre_uninstall.ps1"
        pre_uninstall.write_text(
            'Stop-ScheduledTask  -TaskName "SovereignRMM" -ErrorAction SilentlyContinue\r\n'
            'Unregister-ScheduledTask -TaskName "SovereignRMM" -Confirm:$false -ErrorAction SilentlyContinue\r\n'
        )

        # ── 4. Stable GUIDs (reproducible per token) ───────────
        product_guid  = str(uuid.UUID(hashlib.md5(token.encode()).hexdigest()))
        upgrade_code  = str(uuid.UUID(hashlib.md5(b"sovereign-rmm-upgrade").hexdigest()))
        comp_files    = str(uuid.UUID(hashlib.md5(b"sovereign-files-comp").hexdigest()))
        comp_reg      = str(uuid.UUID(hashlib.md5(b"sovereign-reg-comp").hexdigest()))

        # ── 5. WXS — minimal, wixl-compatible ──────────────────
        # Key rules for wixl:
        #  - No UIRef, no WixVariable, no WixUI_* 
        #  - RegistryValue must be in its own Component with KeyPath="yes"
        #  - CustomAction with cmd.exe works reliably
        #  - Use CommonAppDataFolder (= C:\ProgramData) not ProgramFilesFolder
        wxs = work_dir / "sovereign.wxs"
        wxs.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="{product_guid}"
           Name="Sovereign RMM Agent"
           Language="1033"
           Version="4.0.0"
           Manufacturer="Sovereign RMM"
           UpgradeCode="{upgrade_code}">

    <Package InstallerVersion="200" Compressed="yes" InstallScope="perMachine" Platform="x64"/>
    <MajorUpgrade DowngradeErrorMessage="A newer version is already installed."/>
    <MediaTemplate EmbedCab="yes"/>

    <!-- Install to C:\\ProgramData\\SovereignRMM (no UAC, SYSTEM-accessible) -->
    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="CommonAppDataFolder">
        <Directory Id="INSTALLDIR" Name="SovereignRMM"/>
      </Directory>
    </Directory>

    <!-- Agent files component -->
    <Component Id="AgentFiles" Directory="INSTALLDIR" Guid="{comp_files}">
      <File Id="AgentPy"      Source="{agent_py}"      Name="agent.py"      KeyPath="yes"/>
      <File Id="RunVbs"       Source="{launcher_vbs}"  Name="run.vbs"/>
      <File Id="PostInstPs1"  Source="{post_install}"  Name="post_install.ps1"/>
      <File Id="PreUninstPs1" Source="{pre_uninstall}" Name="pre_uninstall.ps1"/>
    </Component>

    <!-- Registry autostart fallback (separate component, own KeyPath) -->
    <Component Id="AgentReg" Directory="INSTALLDIR" Guid="{comp_reg}">
      <RegistryValue Root="HKLM"
        Key="SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run"
        Name="SovereignRMM"
        Type="string"
        Value="wscript.exe &quot;[INSTALLDIR]run.vbs&quot;"
        KeyPath="yes"/>
    </Component>

    <Feature Id="Main" Title="Sovereign RMM Agent" Level="1">
      <ComponentRef Id="AgentFiles"/>
      <ComponentRef Id="AgentReg"/>
    </Feature>

    <!-- Post-install: register task, install pip deps, start agent -->
    <CustomAction Id="PostInstall"
                  Directory="INSTALLDIR"
                  ExeCommand="cmd.exe /c powershell.exe -ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File &quot;[INSTALLDIR]post_install.ps1&quot; &gt;&gt; &quot;[CommonAppDataFolder]SovereignRMM\\install.log&quot; 2&gt;&amp;1"
                  Execute="deferred"
                  Impersonate="no"
                  Return="ignore"/>

    <!-- Pre-uninstall: stop and remove scheduled task -->
    <CustomAction Id="PreUninstall"
                  Directory="INSTALLDIR"
                  ExeCommand="cmd.exe /c powershell.exe -ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File &quot;[INSTALLDIR]pre_uninstall.ps1&quot;"
                  Execute="deferred"
                  Impersonate="no"
                  Return="ignore"/>

    <InstallExecuteSequence>
      <Custom Action="PostInstall"   After="InstallFiles">NOT Installed</Custom>
      <Custom Action="PreUninstall"  Before="RemoveFiles">Installed AND NOT UPGRADINGPRODUCTCODE</Custom>
    </InstallExecuteSequence>

  </Product>
</Wix>
""")

        # ── 6. Compile with wixl ────────────────────────────────
        out_msi = BUILD_DIR / f"SovereignRMM-Agent-{build_id}.msi"
        result  = subprocess.run(
            ["wixl", "-o", str(out_msi), str(wxs)],
            capture_output=True, text=True, cwd=str(work_dir)
        )
        if result.returncode != 0:
            raise RuntimeError(f"wixl failed: {result.stderr[:1000]}")

        return out_msi

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ── ENDPOINTS ─────────────────────────────────────────────────────────────────

@router.post("/build/windows")
async def build_windows_msi(data: dict):
    local_ip = data.get("local_ip", os.getenv("SERVER_IP", "192.168.5.199"))
    vpn_ip   = data.get("vpn_ip",   "100.125.120.81")
    port     = data.get("port",     os.getenv("BACKEND_PORT", "8000"))
    token    = data.get("token",    AGENT_TOKEN)

    if not WIN_TEMPLATE.exists():
        raise HTTPException(404, "Windows agent template not found")
    try:
        msi_path = build_msi(local_ip, vpn_ip, port, token)
        return FileResponse(str(msi_path), media_type="application/x-msi", filename=msi_path.name)
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

    content  = bake(LINUX_TEMPLATE, local_ip, vpn_ip, port, token)
    build_id = str(uuid.uuid4())[:8]

    installer = (
        "#!/bin/bash\n"
        "# Sovereign RMM Linux Agent Installer\n"
        "set -e\n"
        'echo "Installing Sovereign RMM Agent..."\n'
        'INSTALL_DIR="/opt/sovereign-rmm"\n'
        'mkdir -p "$INSTALL_DIR"\n'
        "\n"
        "cat > \"$INSTALL_DIR/agent.py\" << 'AGENTEOF'\n"
        + content +
        "\nAGENTEOF\n"
        "\n"
        "pip3 install --quiet psutil requests websockets 2>/dev/null || pip install --quiet psutil requests websockets\n"
        "\n"
        "cat > /etc/systemd/system/sovereign-rmm.service << 'SVCEOF'\n"
        "[Unit]\n"
        "Description=Sovereign RMM Agent\n"
        "After=network.target\n"
        "StartLimitIntervalSec=0\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        "Restart=always\n"
        "RestartSec=30\n"
        "ExecStart=/usr/bin/python3 /opt/sovereign-rmm/agent.py\n"
        "StandardOutput=journal\n"
        "StandardError=journal\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
        "SVCEOF\n"
        "\n"
        "systemctl daemon-reload\n"
        "systemctl enable sovereign-rmm\n"
        "systemctl start sovereign-rmm\n"
        'echo ""\n'
        'echo "============================================"\n'
        'echo "  Sovereign RMM Agent installed!"\n'
        'echo "  Log: /var/log/sovereign-rmm.log"\n'
        'echo "  Live tail: tail -f /var/log/sovereign-rmm.log"\n'
        'echo "  Status: systemctl status sovereign-rmm"\n'
        'echo "============================================"\n'
        "systemctl status sovereign-rmm --no-pager\n"
    )

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

    content  = bake(ANDROID_TEMPLATE, local_ip, vpn_ip, port, token)
    build_id = str(uuid.uuid4())[:8]

    setup = (
        "#!/data/data/com.termux/files/usr/bin/bash\n"
        "# Sovereign RMM Android Agent Setup\n"
        "pkg update -y && pkg install -y python\n"
        "pip install psutil requests websockets\n"
        'mkdir -p ~/.sovereign-rmm\n'
        "cat > ~/.sovereign-rmm/agent.py << 'AGENTEOF'\n"
        + content +
        "\nAGENTEOF\n"
        'mkdir -p ~/.termux/boot\n'
        'echo "python ~/.sovereign-rmm/agent.py &" > ~/.termux/boot/sovereign-rmm.sh\n'
        'chmod +x ~/.termux/boot/sovereign-rmm.sh\n'
        'echo "Agent installed. Log: ~/.sovereign-rmm/agent.log"\n'
        'echo "Enable Termux:Boot from F-Droid for auto-start."\n'
        "python ~/.sovereign-rmm/agent.py &\n"
    )

    zip_path = BUILD_DIR / f"sovereign-rmm-android-{build_id}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("sovereign_agent.py", content)
        zf.writestr("setup.sh", setup)
        zf.writestr("README.txt",
            "1. Open Termux\n"
            "2. Run: bash setup.sh\n"
            "3. Install Termux:Boot from F-Droid for auto-start\n"
            "4. Log file: ~/.sovereign-rmm/agent.log\n"
        )
    return FileResponse(str(zip_path), media_type="application/zip", filename=zip_path.name)


@router.get("/list")
async def list_builds():
    files = []
    for f in BUILD_DIR.iterdir():
        if f.is_file() and not f.name.startswith('.'):
            files.append({"name": f.name, "size_kb": round(f.stat().st_size/1024, 1), "modified": f.stat().st_mtime})
    return sorted(files, key=lambda x: x["modified"], reverse=True)


@router.delete("/clean")
async def clean_builds():
    count = 0
    for f in BUILD_DIR.iterdir():
        if f.is_file() and not f.name.startswith('.'):
            f.unlink(); count += 1
    return {"deleted": count}
