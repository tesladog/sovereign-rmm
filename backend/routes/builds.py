"""Agent Builder — Windows MSI (self-contained), Linux .sh, Android .zip."""
import os, shutil, subprocess, uuid, zipfile, hashlib, urllib.request
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

# Python 3.12 embeddable (amd64) — ~11 MB download, cached after first build
PY_EMBED_URL   = "https://www.python.org/ftp/python/3.12.4/python-3.12.4-embed-amd64.zip"
PY_EMBED_CACHE = BUILD_DIR / ".py312-embed-amd64.zip"

# get-pip bootstrap — lets us install packages into the embeddable runtime
GETPIP_URL     = "https://bootstrap.pypa.io/get-pip.py"
GETPIP_CACHE   = BUILD_DIR / ".get-pip.py"


def bake(template: Path, local_ip, vpn_ip, port, token) -> str:
    src = template.read_text()
    return (src
        .replace('"RMM_LOCAL_IP"', f'"{local_ip}"')
        .replace('"RMM_VPN_IP"',   f'"{vpn_ip}"')
        .replace('"RMM_PORT"',     f'"{port}"')
        .replace('"RMM_TOKEN"',    f'"{token}"'))


def fetch_cached(url: str, cache: Path) -> Path:
    if not cache.exists():
        print(f"[build] Downloading {url} ...")
        urllib.request.urlretrieve(url, cache)
        print(f"[build] Cached → {cache} ({cache.stat().st_size//1024} KB)")
    return cache


def build_python_bundle(work_dir: Path) -> Path:
    """
    Assemble a self-contained Windows Python runtime bundle zip.
    Contains:
      python-embed/          ← Python 3.12 embeddable unpacked
        pythonw.exe, python.exe, python312.dll, *.pyd, *.zip, *.pth ...
        Lib/site-packages/   ← psutil, requests, websockets + deps installed here
    Returns path to the bundle zip (to be embedded in the MSI and extracted on-device).
    """
    bundle_cache = BUILD_DIR / ".python-bundle.zip"
    if bundle_cache.exists():
        print("[build] Using cached Python bundle")
        return bundle_cache

    print("[build] Building Python bundle (first time — takes ~60s)...")
    bundle_dir = work_dir / "pybundle"
    py_dir     = bundle_dir / "python-embed"
    py_dir.mkdir(parents=True)

    # 1. Extract Python embeddable
    embed_zip = fetch_cached(PY_EMBED_URL, PY_EMBED_CACHE)
    with zipfile.ZipFile(embed_zip) as zf:
        zf.extractall(py_dir)
    print("[build] Python embeddable extracted")

    # 2. Enable site-packages by uncommenting `import site` in the .pth file
    pth_files = list(py_dir.glob("python3*._pth"))
    for pth in pth_files:
        content = pth.read_text()
        content = content.replace("#import site", "import site")
        pth.write_text(content)
    print(f"[build] Patched {len(pth_files)} .pth file(s) to enable site-packages")

    # 3. Bootstrap pip into the embeddable runtime
    getpip = fetch_cached(GETPIP_URL, GETPIP_CACHE)
    result = subprocess.run(
        [str(py_dir / "python.exe"), str(getpip), "--no-warn-script-location", "-q"],
        capture_output=True, text=True, cwd=str(py_dir)
    )
    # pip install will fail here because we're on Linux running Windows exe,
    # BUT we can use the host pip with --target to cross-install the packages
    # into the embed's site-packages directory
    site_pkgs = py_dir / "Lib" / "site-packages"
    site_pkgs.mkdir(parents=True, exist_ok=True)

    # 4. Download Windows wheels using host pip and install into embed site-packages
    packages = ["psutil", "requests", "websockets", "certifi",
                "charset-normalizer", "idna", "urllib3"]
    wheels_dir = work_dir / "wheels"
    wheels_dir.mkdir()

    print(f"[build] Downloading Windows wheels for: {', '.join(packages)}")
    result = subprocess.run(
        ["pip", "download",
         "--dest", str(wheels_dir),
         "--platform", "win_amd64",
         "--python-version", "312",
         "--implementation", "cp",
         "--only-binary=:all:",
         "--no-deps",
         ] + packages,
        capture_output=True, text=True
    )
    if result.returncode != 0:
        # Fallback: download pure-python wheels (no binary constraint)
        print("[build] Binary download failed, trying pure-python wheels...")
        subprocess.run(
            ["pip", "download", "--dest", str(wheels_dir),
             "--no-deps", "--prefer-binary"] + packages,
            capture_output=True, text=True
        )

    # Extract each wheel (wheels are just zips) into site-packages
    for whl in wheels_dir.glob("*.whl"):
        print(f"[build]   Installing wheel: {whl.name}")
        with zipfile.ZipFile(whl) as zf:
            zf.extractall(site_pkgs)
    # Also handle .tar.gz source dists if any slipped through
    for tgz in wheels_dir.glob("*.tar.gz"):
        print(f"[build]   Note: source dist skipped: {tgz.name}")

    print(f"[build] site-packages populated: "
          f"{sum(1 for _ in site_pkgs.rglob('*'))} files")

    # 5. Zip the whole bundle
    print("[build] Zipping Python bundle...")
    with zipfile.ZipFile(bundle_cache, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in bundle_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(bundle_dir))

    size_mb = bundle_cache.stat().st_size / 1024 / 1024
    print(f"[build] Python bundle ready: {size_mb:.1f} MB → {bundle_cache}")
    return bundle_cache


def build_msi(local_ip: str, vpn_ip: str, port: str, token: str) -> Path:
    """
    Build a self-contained Windows MSI (~25 MB).
    Bundles Python 3.12 embeddable + all required packages.
    Zero dependencies on the target machine — works on any Windows 10/11.
    """
    build_id = str(uuid.uuid4())[:8]
    work_dir  = BUILD_DIR / f"msi-{build_id}"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # ── 1. Bake agent ────────────────────────────────────────
        agent_py = work_dir / "agent.py"
        agent_py.write_text(bake(WIN_TEMPLATE, local_ip, vpn_ip, port, token))

        # ── 2. Python bundle (cached after first build) ──────────
        bundle_zip = build_python_bundle(work_dir)
        bundle_dest = work_dir / "python-bundle.zip"
        shutil.copy2(bundle_zip, bundle_dest)

        # ── 3. VBS silent launcher — uses bundled Python ─────────
        launcher_vbs = work_dir / "run.vbs"
        launcher_vbs.write_text(
            'Set sh = CreateObject("WScript.Shell")\r\n'
            'sh.Run """C:\\ProgramData\\SovereignRMM\\python-embed\\pythonw.exe"""'
            ' & " ""C:\\ProgramData\\SovereignRMM\\agent.py""", 0, False\r\n'
        )

        # ── 4. Post-install PowerShell ───────────────────────────
        post_install = work_dir / "post_install.ps1"
        post_install.write_text("\r\n".join([
            '$inst = "C:\\ProgramData\\SovereignRMM"',
            '$log  = "$inst\\install.log"',
            '"=== Sovereign RMM Post-Install $(Get-Date) ===" | Out-File $log -Append',
            '',
            '# ── 1. Extract Python bundle ─────────────────────────────────────',
            '"[1/5] Extracting Python runtime..." | Out-File $log -Append',
            'try {',
            '    $bundle = "$inst\\python-bundle.zip"',
            '    $pyDest = "$inst"',
            '    Expand-Archive -Path $bundle -DestinationPath $pyDest -Force',
            '    Remove-Item $bundle -Force -ErrorAction SilentlyContinue',
            '    "[1/5] Python extracted to $inst\\python-embed" | Out-File $log -Append',
            '} catch {',
            '    "[1/5] Extract failed: $_" | Out-File $log -Append',
            '}',
            '',
            '# ── 2. Verify Python works ───────────────────────────────────────',
            '"[2/5] Verifying Python..." | Out-File $log -Append',
            '$py = "$inst\\python-embed\\python.exe"',
            'if (Test-Path $py) {',
            '    $ver = & $py --version 2>&1',
            '    "[2/5] Python OK: $ver" | Out-File $log -Append',
            '} else {',
            '    "[2/5] ERROR: python.exe not found at $py" | Out-File $log -Append',
            '}',
            '',
            '# ── 3. Register scheduled task (SYSTEM, at boot, auto-restart) ──',
            '"[3/5] Registering scheduled task..." | Out-File $log -Append',
            'try {',
            '    Unregister-ScheduledTask -TaskName "SovereignRMM" -Confirm:$false -ErrorAction SilentlyContinue',
            '    $vbs     = "$inst\\run.vbs"',
            '    $action  = New-ScheduledTaskAction -Execute "wscript.exe" -Argument """$vbs"""',
            '    $trigger = New-ScheduledTaskTrigger -AtStartup',
            '    $settings = New-ScheduledTaskSettingsSet `',
            '        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `',
            '        -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 0) `',
            '        -RestartCount 9999 -RestartInterval (New-TimeSpan -Minutes 1)',
            '    $principal = New-ScheduledTaskPrincipal `',
            '        -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest',
            '    Register-ScheduledTask -TaskName "SovereignRMM" `',
            '        -Action $action -Trigger $trigger `',
            '        -Settings $settings -Principal $principal -Force | Out-Null',
            '    "[3/5] Task registered" | Out-File $log -Append',
            '} catch {',
            '    "[3/5] Task failed: $_ — using registry fallback" | Out-File $log -Append',
            '    $vbsQ = "wscript.exe """"$inst\\run.vbs""""',
            '    Set-ItemProperty "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run" `',
            '        -Name "SovereignRMM" -Value $vbsQ -Force',
            '}',
            '',
            '# ── 4. Start agent immediately ───────────────────────────────────',
            '"[4/5] Starting agent now..." | Out-File $log -Append',
            'try {',
            '    Start-ScheduledTask -TaskName "SovereignRMM" -ErrorAction Stop',
            '    "[4/5] Started via Task Scheduler" | Out-File $log -Append',
            '} catch {',
            '    Start-Process "wscript.exe" -ArgumentList """$inst\\run.vbs""" -WindowStyle Hidden',
            '    "[4/5] Started directly" | Out-File $log -Append',
            '}',
            '',
            '# ── 5. Toast notification to logged-in users ─────────────────────',
            '"[5/5] Sending install notification..." | Out-File $log -Append',
            '$toastXml = @"',
            '<toast><visual><binding template="ToastGeneric">',
            '  <text>Sovereign RMM Agent</text>',
            '  <text>Device management agent installed and running.</text>',
            '</binding></visual></toast>',
            '"@',
            '$encodedToast = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes(',
            '    "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;" +',
            '    "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]|Out-Null;" +',
            '    "\\$x=[Windows.Data.Xml.Dom.XmlDocument]::new();" +',
            '    "\\$x.LoadXml(\'$($toastXml -replace \"\\`n\",\" \")\');" +',
            '    "\\$t=[Windows.UI.Notifications.ToastNotification]::new(\\$x);" +',
            '    "\\$a=\'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe\';" +',
            '    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier(\\$a).Show(\\$t)"',
            '))',
            'Get-WmiObject -Class Win32_Process -Filter "Name=\'explorer.exe\'" | ForEach-Object {',
            '    $owner = $_.GetOwner()',
            '    if ($owner.ReturnValue -eq 0) {',
            '        try {',
            '            $sid = (New-Object System.Security.Principal.NTAccount($owner.Domain,$owner.User)).Translate([System.Security.Principal.SecurityIdentifier]).Value',
            '            $task2 = Register-ScheduledTask -TaskName "SovNotify_tmp" `',
            '                -Action (New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-WindowStyle Hidden -EncodedCommand $encodedToast") `',
            '                -Principal (New-ScheduledTaskPrincipal -LogonType Interactive -RunLevel Limited -UserId $sid) `',
            '                -Force 2>$null',
            '            Start-ScheduledTask -TaskName "SovNotify_tmp" 2>$null',
            '            Start-Sleep -Seconds 4',
            '            Unregister-ScheduledTask -TaskName "SovNotify_tmp" -Confirm:$false 2>$null',
            '        } catch {}',
            '    }',
            '}',
            '"[5/5] Done" | Out-File $log -Append',
            '"=== Install complete: $(Get-Date) ===" | Out-File $log -Append',
        ]))

        # Pre-uninstall script
        pre_uninstall = work_dir / "pre_uninstall.ps1"
        pre_uninstall.write_text("\r\n".join([
            'Stop-ScheduledTask  -TaskName "SovereignRMM" -Confirm:$false -ErrorAction SilentlyContinue',
            'Unregister-ScheduledTask -TaskName "SovereignRMM" -Confirm:$false -ErrorAction SilentlyContinue',
        ]))

        # ── 5. GUIDs ─────────────────────────────────────────────
        product_guid = str(uuid.UUID(hashlib.md5(token.encode()).hexdigest()))
        upgrade_code = str(uuid.UUID(hashlib.md5(b"sovereign-rmm-upgrade").hexdigest()))
        comp_files   = str(uuid.UUID(hashlib.md5(b"sovereign-files-v2").hexdigest()))
        comp_bundle  = str(uuid.UUID(hashlib.md5(b"sovereign-bundle-v2").hexdigest()))
        comp_reg     = str(uuid.UUID(hashlib.md5(b"sovereign-reg-v2").hexdigest()))

        # ── 6. WXS ───────────────────────────────────────────────
        wxs = work_dir / "sovereign.wxs"
        wxs.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="{product_guid}"
           Name="Sovereign RMM Agent"
           Language="1033"
           Version="4.0.0"
           Manufacturer="Sovereign RMM"
           UpgradeCode="{upgrade_code}">

    <Package InstallerVersion="200" Compressed="yes" InstallScope="perMachine"/>
    <MajorUpgrade DowngradeErrorMessage="A newer version is already installed."/>
    <MediaTemplate EmbedCab="yes"/>

    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="CommonAppDataFolder">
        <Directory Id="INSTALLDIR" Name="SovereignRMM">

          <!-- Core agent files -->
          <Component Id="AgentFiles" Guid="{comp_files}">
            <File Id="AgentPy"      Source="{agent_py}"      Name="agent.py"           KeyPath="yes"/>
            <File Id="RunVbs"       Source="{launcher_vbs}"  Name="run.vbs"/>
            <File Id="PostInstPs1"  Source="{post_install}"  Name="post_install.ps1"/>
            <File Id="PreUninstPs1" Source="{pre_uninstall}" Name="pre_uninstall.ps1"/>
          </Component>

          <!-- Python bundle zip (extracted post-install) -->
          <Component Id="PythonBundle" Guid="{comp_bundle}">
            <File Id="PyBundleZip" Source="{bundle_dest}" Name="python-bundle.zip" KeyPath="yes"/>
          </Component>

          <!-- Registry autostart fallback -->
          <Component Id="AgentReg" Guid="{comp_reg}">
            <RegistryValue Root="HKLM"
              Key="SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run"
              Name="SovereignRMM"
              Type="string"
              Value="wscript.exe &quot;[INSTALLDIR]run.vbs&quot;"
              KeyPath="yes"/>
          </Component>

        </Directory>
      </Directory>
    </Directory>

    <Feature Id="Main" Title="Sovereign RMM Agent" Level="1">
      <ComponentRef Id="AgentFiles"/>
      <ComponentRef Id="PythonBundle"/>
      <ComponentRef Id="AgentReg"/>
    </Feature>

    <!-- Extract Python bundle, register task, start agent -->
    <CustomAction Id="PostInstall"
                  Directory="INSTALLDIR"
                  ExeCommand="cmd.exe /c start /min &quot;&quot; powershell.exe -ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File &quot;[INSTALLDIR]post_install.ps1&quot;"
                  Execute="deferred"
                  Impersonate="no"
                  Return="ignore"/>

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

        # ── 7. Compile ───────────────────────────────────────────
        out_msi = BUILD_DIR / f"SovereignRMM-Agent-{build_id}.msi"
        result  = subprocess.run(
            ["wixl", "-o", str(out_msi), str(wxs)],
            capture_output=True, text=True, cwd=str(work_dir)
        )
        if result.returncode != 0:
            raise RuntimeError(f"wixl failed: {result.stderr[:1000]}")

        size_mb = out_msi.stat().st_size / 1024 / 1024
        print(f"[build] MSI ready: {out_msi.name} ({size_mb:.1f} MB)")
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
        "#!/bin/bash\n# Sovereign RMM Linux Agent Installer\nset -e\n"
        'INST="/opt/sovereign-rmm"\nmkdir -p "$INST"\n'
        "cat > \"$INST/agent.py\" << 'AGENTEOF'\n" + content + "\nAGENTEOF\n"
        "pip3 install --quiet psutil requests websockets 2>/dev/null || "
        "pip install --quiet psutil requests websockets\n"
        "cat > /etc/systemd/system/sovereign-rmm.service << 'SVCEOF'\n"
        "[Unit]\nDescription=Sovereign RMM Agent\nAfter=network.target\n\n"
        "[Service]\nType=simple\nRestart=always\nRestartSec=30\n"
        "ExecStart=/usr/bin/python3 /opt/sovereign-rmm/agent.py\n\n"
        "[Install]\nWantedBy=multi-user.target\nSVCEOF\n"
        "systemctl daemon-reload && systemctl enable sovereign-rmm && systemctl start sovereign-rmm\n"
        'echo "Log: /var/log/sovereign-rmm.log"\n'
        'echo "Tail: tail -f /var/log/sovereign-rmm.log"\n'
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
        "pkg update -y && pkg install -y python\n"
        "pip install psutil requests websockets\n"
        'mkdir -p ~/.sovereign-rmm\n'
        "cat > ~/.sovereign-rmm/agent.py << 'AGENTEOF'\n" + content + "\nAGENTEOF\n"
        'mkdir -p ~/.termux/boot\n'
        'echo "python ~/.sovereign-rmm/agent.py &" > ~/.termux/boot/sovereign-rmm.sh\n'
        'chmod +x ~/.termux/boot/sovereign-rmm.sh\n'
        'echo "Log: ~/.sovereign-rmm/agent.log"\n'
        "python ~/.sovereign-rmm/agent.py &\n"
    )
    zip_path = BUILD_DIR / f"sovereign-rmm-android-{build_id}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("sovereign_agent.py", content)
        zf.writestr("setup.sh", setup)
        zf.writestr("README.txt",
            "1. Open Termux\n2. Run: bash setup.sh\n"
            "3. Install Termux:Boot from F-Droid for auto-start\n"
            "4. Log: ~/.sovereign-rmm/agent.log\n")
    return FileResponse(str(zip_path), media_type="application/zip", filename=zip_path.name)


@router.get("/list")
async def list_builds():
    files = []
    for f in BUILD_DIR.iterdir():
        if f.is_file() and not f.name.startswith('.'):
            files.append({"name": f.name,
                          "size_kb": round(f.stat().st_size / 1024, 1),
                          "modified": f.stat().st_mtime})
    return sorted(files, key=lambda x: x["modified"], reverse=True)


@router.delete("/clean")
async def clean_builds():
    count = 0
    for f in BUILD_DIR.iterdir():
        if f.is_file() and not f.name.startswith('.'):
            f.unlink(); count += 1
    return {"deleted": count}
