"""Script Library — built-in scripts + CRUD endpoints."""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import ScriptLibrary
from database import get_db

router = APIRouter()

# ── BUILTIN SCRIPTS ──────────────────────────────────────────
# All registry paths use raw strings (r"...") to avoid backslash escape issues

def _s(name, cat, plat, stype, desc, body):
    return {"name": name, "category": cat, "platform": plat,
            "script_type": stype, "description": desc, "script_body": body}

BUILTIN_SCRIPTS = [

  # ════════════════════════════════════════════════════════════
  # SYSTEM INFO — WINDOWS
  # ════════════════════════════════════════════════════════════
  _s("System Overview", "System Info", "windows", "powershell",
     "Full system snapshot: OS, CPU, RAM, uptime, serial number",
     r"""$os = Get-WmiObject Win32_OperatingSystem
$cs = Get-WmiObject Win32_ComputerSystem
$bios = Get-WmiObject Win32_BIOS
Write-Output "=== SYSTEM OVERVIEW ==="
Write-Output "Hostname     : $env:COMPUTERNAME"
Write-Output "OS           : $($os.Caption) $($os.Version)"
Write-Output "Build        : $($os.BuildNumber)"
Write-Output "Uptime       : $((Get-Date) - $os.ConvertToDateTime($os.LastBootUpTime))"
Write-Output "Manufacturer : $($cs.Manufacturer)"
Write-Output "Model        : $($cs.Model)"
Write-Output "Serial       : $($bios.SerialNumber)"
Write-Output "CPU          : $((Get-WmiObject Win32_Processor).Name)"
Write-Output "RAM (GB)     : $([math]::Round($cs.TotalPhysicalMemory/1GB,2))"
Write-Output "Logged In    : $($cs.UserName)"
"""),

  _s("Installed RAM Details", "System Info", "windows", "powershell",
     "Show each RAM stick: size, speed, slot, manufacturer",
     r"""Get-WmiObject Win32_PhysicalMemory | Select-Object `
  @{N='Slot';E={$_.DeviceLocator}},
  @{N='Size_GB';E={[math]::Round($_.Capacity/1GB,0)}},
  @{N='Speed_MHz';E={$_.Speed}},
  @{N='Manufacturer';E={$_.Manufacturer}},
  @{N='PartNumber';E={$_.PartNumber.Trim()}} | Format-Table -AutoSize
"""),

  _s("CPU Info", "System Info", "windows", "powershell",
     "CPU name, cores, threads, speed, load",
     r"""$cpu = Get-WmiObject Win32_Processor
Write-Output "Name    : $($cpu.Name)"
Write-Output "Cores   : $($cpu.NumberOfCores)"
Write-Output "Threads : $($cpu.NumberOfLogicalProcessors)"
Write-Output "Speed   : $($cpu.MaxClockSpeed) MHz"
Write-Output "Load    : $($cpu.LoadPercentage)%"
Write-Output "Socket  : $($cpu.SocketDesignation)"
"""),

  _s("Disk Inventory", "System Info", "windows", "powershell",
     "All drives: size, free space, filesystem",
     r"""Get-WmiObject Win32_LogicalDisk | Where-Object {$_.DriveType -eq 3} | Select-Object `
  DeviceID,
  @{N='Size_GB';E={[math]::Round($_.Size/1GB,1)}},
  @{N='Free_GB';E={[math]::Round($_.FreeSpace/1GB,1)}},
  @{N='Used_Pct';E={[math]::Round(($_.Size-$_.FreeSpace)/$_.Size*100,1)}},
  FileSystem,VolumeName | Format-Table -AutoSize
"""),

  _s("GPU Info", "System Info", "windows", "powershell",
     "Graphics card name, VRAM, driver version",
     r"""Get-WmiObject Win32_VideoController | Select-Object Name,
  @{N='VRAM_MB';E={[math]::Round($_.AdapterRAM/1MB,0)}},
  DriverVersion,CurrentRefreshRate | Format-List
"""),

  _s("Motherboard Info", "System Info", "windows", "powershell",
     "Motherboard make, model, BIOS version",
     r"""$mb = Get-WmiObject Win32_BaseBoard
$bios = Get-WmiObject Win32_BIOS
Write-Output "Manufacturer : $($mb.Manufacturer)"
Write-Output "Product      : $($mb.Product)"
Write-Output "Serial       : $($mb.SerialNumber)"
Write-Output "BIOS Version : $($bios.SMBIOSBIOSVersion)"
Write-Output "BIOS Date    : $($bios.ReleaseDate)"
"""),

  _s("Network Adapters", "System Info", "windows", "powershell",
     "All NICs: name, IP, MAC, speed",
     r"""Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | ForEach-Object {
  $ip = (Get-NetIPAddress -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress
  Write-Output "$($_.Name) | MAC: $($_.MacAddress) | IP: $ip | Speed: $($_.LinkSpeed)"
}
"""),

  _s("Startup Programs", "System Info", "windows", "powershell",
     "List all programs set to run at startup",
     r"""$paths = @(
  'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run',
  'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
)
foreach ($p in $paths) {
  Write-Output "`n=== $p ==="
  Get-ItemProperty -Path $p -ErrorAction SilentlyContinue |
    Select-Object -Property * -ExcludeProperty PS*
}
Get-CimInstance Win32_StartupCommand |
  Select-Object Name,Command,Location,User | Format-Table -AutoSize
"""),

  _s("Windows License Key", "System Info", "windows", "powershell",
     "Retrieve the installed Windows product key",
     r"""$key = (Get-WmiObject -query 'select * from SoftwareLicensingService').OA3xOriginalProductKey
if ($key) { Write-Output "Product Key: $key" }
else {
  $path = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\SoftwareProtectionPlatform'
  $regKey = (Get-ItemProperty $path -Name BackupProductKeyDefault -ErrorAction SilentlyContinue).BackupProductKeyDefault
  Write-Output "Product Key: $regKey"
}
"""),

  _s("Environment Variables", "System Info", "windows", "powershell",
     "List all system environment variables",
     "[System.Environment]::GetEnvironmentVariables('Machine') | Format-Table -AutoSize"),

  # ════════════════════════════════════════════════════════════
  # MAINTENANCE — WINDOWS
  # ════════════════════════════════════════════════════════════
  _s("Disk Cleanup — Temp Files", "Maintenance", "windows", "powershell",
     "Delete temp files, prefetch, SoftwareDistribution cache",
     r"""$before = (Get-WmiObject Win32_LogicalDisk -Filter "DeviceID='C:'").FreeSpace
$paths = @("$env:TEMP","$env:WINDIR\Temp","$env:WINDIR\Prefetch","$env:WINDIR\SoftwareDistribution\Download")
foreach ($p in $paths) {
  if (Test-Path $p) {
    Remove-Item "$p\*" -Recurse -Force -ErrorAction SilentlyContinue
    Write-Output "Cleaned: $p"
  }
}
Clear-RecycleBin -Force -ErrorAction SilentlyContinue
$after = (Get-WmiObject Win32_LogicalDisk -Filter "DeviceID='C:'").FreeSpace
Write-Output "Freed: $([math]::Round(($after-$before)/1MB,1)) MB"
"""),

  _s("Clear Event Logs", "Maintenance", "windows", "powershell",
     "Clear Application, System, Security, and Setup event logs",
     r"""$logs = @('Application','System','Security','Setup')
foreach ($log in $logs) {
  try { Clear-EventLog -LogName $log -ErrorAction Stop; Write-Output "Cleared: $log" }
  catch { Write-Output "Skipped: $log ($($_.Exception.Message))" }
}
"""),

  _s("Flush DNS Cache", "Maintenance", "windows", "powershell",
     "Flush and display the DNS resolver cache",
     "Clear-DnsClientCache\r\nWrite-Output 'DNS cache flushed.'\r\nipconfig /displaydns | Select-Object -First 10"),

  _s("Reset Network Stack", "Maintenance", "windows", "powershell",
     "Reset Winsock, TCP/IP, DNS — fixes many network issues",
     "Write-Output 'Resetting Winsock...'\r\nnetsh winsock reset\r\nWrite-Output 'Resetting TCP/IP...'\r\nnetsh int ip reset\r\nWrite-Output 'Flushing DNS...'\r\nipconfig /flushdns\r\nWrite-Output 'Done. Restart recommended.'"),

  _s("Repair System Files (SFC)", "Maintenance", "windows", "powershell",
     "Run sfc /scannow to repair corrupted system files",
     "sfc /scannow"),

  _s("DISM Repair", "Maintenance", "windows", "powershell",
     "Run DISM to repair the Windows image",
     "DISM /Online /Cleanup-Image /RestoreHealth"),

  _s("Defrag C Drive", "Maintenance", "windows", "powershell",
     "Optimize C: drive (SSDs will trim instead of defrag)",
     "Optimize-Volume -DriveLetter C -Verbose"),

  _s("Check Disk (CHKDSK)", "Maintenance", "windows", "powershell",
     "Schedule a CHKDSK on next reboot",
     "chkdsk C: /f /r /x\r\nWrite-Output 'CHKDSK scheduled for next boot.'"),

  _s("Windows Update — List Pending", "Maintenance", "windows", "powershell",
     "List available Windows Updates without installing",
     r"""if (!(Get-Module -Name PSWindowsUpdate -ListAvailable)) {
  Install-Module PSWindowsUpdate -Force -Scope AllUsers -ErrorAction Stop
}
Import-Module PSWindowsUpdate
Get-WindowsUpdate | Select-Object KB,Title,Size,IsDownloaded | Format-Table -AutoSize
"""),

  _s("Windows Update — Install All", "Maintenance", "windows", "powershell",
     "Install all pending Windows Updates silently",
     r"""if (!(Get-Module -Name PSWindowsUpdate -ListAvailable)) {
  Install-Module PSWindowsUpdate -Force -Scope AllUsers -ErrorAction Stop
}
Import-Module PSWindowsUpdate
Get-WindowsUpdate -Install -AcceptAll -AutoReboot:$false
"""),

  _s("Disable Hibernate", "Maintenance", "windows", "powershell",
     "Disable hibernation and delete hiberfil.sys",
     "powercfg /hibernate off; Write-Output 'Hibernate disabled'"),

  _s("Restart Explorer", "Maintenance", "windows", "powershell",
     "Restart Windows Explorer shell",
     "Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue; Start-Process explorer; Write-Output 'Explorer restarted'"),

  _s("Rebuild Icon Cache", "Maintenance", "windows", "powershell",
     "Clear and rebuild the Windows icon cache",
     r"""Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
Remove-Item "$env:LOCALAPPDATA\IconCache.db" -Force -ErrorAction SilentlyContinue
Remove-Item "$env:LOCALAPPDATA\Microsoft\Windows\Explorer\iconcache_*" -Force -ErrorAction SilentlyContinue
Start-Process explorer
Write-Output "Icon cache rebuilt"
"""),

  # ════════════════════════════════════════════════════════════
  # SECURITY — WINDOWS
  # ════════════════════════════════════════════════════════════
  _s("Antivirus Status", "Security", "windows", "powershell",
     "Check Windows Defender status and last scan time",
     r"""$def = Get-MpComputerStatus
Write-Output "Enabled           : $($def.AntivirusEnabled)"
Write-Output "Real-time Protect : $($def.RealTimeProtectionEnabled)"
Write-Output "Definitions Date  : $($def.AntivirusSignatureLastUpdated)"
Write-Output "Last Scan         : $($def.LastScanTime)"
Write-Output "Threats Found     : $($def.ThreatCount)"
"""),

  _s("Run Defender Quick Scan", "Security", "windows", "powershell",
     "Start a Windows Defender quick scan",
     "Start-MpScan -ScanType QuickScan; Write-Output 'Quick scan started'"),

  _s("Update Defender Definitions", "Security", "windows", "powershell",
     "Force-update Windows Defender virus definitions",
     "Update-MpSignature; Write-Output 'Definitions updated'"),

  _s("Check Local Admins", "Security", "windows", "powershell",
     "List all local administrator accounts",
     "Get-LocalGroupMember -Group 'Administrators' | Select-Object Name,ObjectClass,PrincipalSource | Format-Table -AutoSize"),

  _s("List Open Network Ports", "Security", "windows", "powershell",
     "Show all listening TCP ports and associated processes",
     r"""Get-NetTCPConnection -State Listen | Select-Object LocalAddress,LocalPort,
  @{N='Process';E={(Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName}} |
  Sort-Object LocalPort | Format-Table -AutoSize
"""),

  _s("Check Firewall Status", "Security", "windows", "powershell",
     "Show Windows Firewall status for all profiles",
     "Get-NetFirewallProfile | Select-Object Name,Enabled,DefaultInboundAction,DefaultOutboundAction | Format-Table -AutoSize"),

  _s("Enable Firewall All Profiles", "Security", "windows", "powershell",
     "Turn on Windows Firewall for Domain, Private, and Public",
     "Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled True; Write-Output 'Firewall enabled on all profiles'"),

  _s("List Failed Logons (Last 24h)", "Security", "windows", "powershell",
     "Show failed login attempts from the Security event log",
     r"""$since = (Get-Date).AddHours(-24)
Get-WinEvent -FilterHashtable @{LogName='Security';Id=4625;StartTime=$since} -ErrorAction SilentlyContinue |
  Select-Object TimeCreated,
    @{N='User';E={$_.Properties[5].Value}},
    @{N='IP';E={$_.Properties[19].Value}} |
  Format-Table -AutoSize | Select-Object -First 50
"""),

  _s("Check BitLocker Status", "Security", "windows", "powershell",
     "Show BitLocker encryption status on all drives",
     "Get-BitLockerVolume | Select-Object MountPoint,EncryptionMethod,ProtectionStatus,VolumeStatus | Format-Table -AutoSize"),

  _s("Disable USB Storage", "Security", "windows", "powershell",
     "Block USB mass storage devices via registry",
     r"""Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\USBSTOR' -Name 'Start' -Value 4
Write-Output "USB storage disabled. Set Start=3 to re-enable."
"""),

  _s("Enable USB Storage", "Security", "windows", "powershell",
     "Re-enable USB mass storage devices",
     r"""Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\USBSTOR' -Name 'Start' -Value 3
Write-Output "USB storage enabled."
"""),

  # ════════════════════════════════════════════════════════════
  # USER MANAGEMENT — WINDOWS
  # ════════════════════════════════════════════════════════════
  _s("List Local Users", "User Management", "windows", "powershell",
     "All local user accounts with status and last logon",
     r"""Get-LocalUser | Select-Object Name,Enabled,LastLogon,PasswordExpires,
  @{N='PasswordAge';E={(Get-Date)-$_.PasswordLastSet}} | Format-Table -AutoSize
"""),

  _s("List Logged-In Users", "User Management", "windows", "powershell",
     "Show who is currently logged on",
     "query user 2>&1"),

  _s("Create Local User", "User Management", "windows", "powershell",
     "Create a new local user (edit username/password before running)",
     r"""$username = "newuser"
$password = ConvertTo-SecureString "TempPass123!" -AsPlainText -Force
New-LocalUser -Name $username -Password $password -FullName "New User" -Description "Created by RMM"
Add-LocalGroupMember -Group "Users" -Member $username
Write-Output "User '$username' created"
"""),

  _s("Disable Local User", "User Management", "windows", "powershell",
     "Disable a local user account (edit username before running)",
     'Disable-LocalUser -Name "targetuser"; Write-Output "User disabled"'),

  _s("Reset Local Password", "User Management", "windows", "powershell",
     "Reset a local user password (edit username/password before running)",
     r"""$password = ConvertTo-SecureString "NewTemp123!" -AsPlainText -Force
Set-LocalUser -Name "targetuser" -Password $password
Write-Output "Password reset"
"""),

  _s("List Active Sessions", "User Management", "windows", "powershell",
     "Show all active RDP and console sessions",
     "qwinsta"),

  # ════════════════════════════════════════════════════════════
  # NETWORK — WINDOWS
  # ════════════════════════════════════════════════════════════
  _s("Ping Test (8.8.8.8)", "Network", "windows", "powershell",
     "Test internet connectivity with ping",
     "Test-Connection 8.8.8.8 -Count 4 | Select-Object Address,ResponseTime,StatusCode"),

  _s("Traceroute", "Network", "windows", "powershell",
     "Trace network path to 8.8.8.8",
     "Test-NetConnection 8.8.8.8 -TraceRoute"),

  _s("Get Public IP", "Network", "windows", "powershell",
     "Retrieve the device's current public IP address",
     "(Invoke-RestMethod -Uri 'https://api.ipify.org?format=json').ip"),

  _s("Network Speed Test", "Network", "windows", "powershell",
     "Rough download speed test",
     r"""$url = "http://speedtest.tele2.net/10MB.zip"
$tmp = "$env:TEMP\speedtest.bin"
$start = Get-Date
(New-Object System.Net.WebClient).DownloadFile($url,$tmp)
$elapsed = ((Get-Date) - $start).TotalSeconds
$size = (Get-Item $tmp).Length / 1MB
Remove-Item $tmp -Force
Write-Output "Download: $([math]::Round($size/$elapsed,2)) MB/s"
"""),

  _s("WiFi Signal Strength", "Network", "windows", "powershell",
     "Show current WiFi SSID and signal strength",
     "netsh wlan show interfaces | Select-String 'SSID|Signal|Profile|Radio'"),

  _s("ARP Cache", "Network", "windows", "powershell",
     "Show ARP table (local network device map)",
     "arp -a"),

  _s("DNS Resolution Test", "Network", "windows", "powershell",
     "Test DNS resolution for common domains",
     r"""@('google.com','microsoft.com','github.com') | ForEach-Object {
  try { $r = Resolve-DnsName $_ -QuickTimeout -ErrorAction Stop; Write-Output "$_ -> $($r[0].IPAddress)" }
  catch { Write-Output "$_ -> FAILED: $($_.Exception.Message)" }
}
"""),

  _s("Shared Folders", "Network", "windows", "powershell",
     "List all shared folders on this device",
     "Get-SmbShare | Select-Object Name,Path,Description,CurrentUsers | Format-Table -AutoSize"),

  # ════════════════════════════════════════════════════════════
  # PERFORMANCE — WINDOWS
  # ════════════════════════════════════════════════════════════
  _s("Top CPU Processes", "Performance", "windows", "powershell",
     "Top 15 processes by CPU usage",
     r"""Get-Process | Sort-Object CPU -Descending | Select-Object -First 15 `
  Name,Id,CPU,@{N='RAM_MB';E={[math]::Round($_.WorkingSet64/1MB,1)}} | Format-Table -AutoSize
"""),

  _s("Top RAM Processes", "Performance", "windows", "powershell",
     "Top 15 processes by RAM consumption",
     r"""Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 15 `
  Name,Id,@{N='RAM_MB';E={[math]::Round($_.WorkingSet64/1MB,1)}},CPU | Format-Table -AutoSize
"""),

  _s("CPU Load (30s sample)", "Performance", "windows", "powershell",
     "Sample CPU usage every 5 seconds for 30 seconds",
     r"""1..6 | ForEach-Object {
  $load = (Get-WmiObject Win32_Processor).LoadPercentage
  Write-Output "$(Get-Date -f 'HH:mm:ss') CPU: $load%"
  Start-Sleep 5
}
"""),

  _s("Memory Usage Summary", "Performance", "windows", "powershell",
     "Total, used, and available RAM",
     r"""$os = Get-WmiObject Win32_OperatingSystem
$total = [math]::Round($os.TotalVisibleMemorySize/1MB,2)
$free  = [math]::Round($os.FreePhysicalMemory/1MB,2)
$used  = [math]::Round($total - $free, 2)
Write-Output "Total : $total GB"
Write-Output "Used  : $used GB ($([math]::Round($used/$total*100,1))%)"
Write-Output "Free  : $free GB"
"""),

  _s("Uptime", "Performance", "windows", "powershell",
     "How long the device has been running since last boot",
     r"""$boot = (Get-WmiObject Win32_OperatingSystem).ConvertToDateTime(
  (Get-WmiObject Win32_OperatingSystem).LastBootUpTime)
$uptime = (Get-Date) - $boot
Write-Output "Last Boot : $boot"
Write-Output "Uptime    : $($uptime.Days)d $($uptime.Hours)h $($uptime.Minutes)m"
"""),

  # ════════════════════════════════════════════════════════════
  # SOFTWARE — WINDOWS
  # ════════════════════════════════════════════════════════════
  _s("List Installed Software", "Software", "windows", "powershell",
     "Full list of installed applications with version and publisher",
     r"""Get-ItemProperty `
  'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' `
  -ErrorAction SilentlyContinue |
  Where-Object {$_.DisplayName} |
  Select-Object DisplayName,DisplayVersion,Publisher,InstallDate |
  Sort-Object DisplayName | Format-Table -AutoSize
"""),

  _s("Uninstall Software", "Software", "windows", "powershell",
     "Silently uninstall a program by name (edit AppName before running)",
     r"""$AppName = "AppNameHere"
$app = Get-WmiObject -Class Win32_Product | Where-Object { $_.Name -like "*$AppName*" }
if ($app) { $app.Uninstall(); Write-Output "Uninstalled: $($app.Name)" }
else { Write-Output "Not found: $AppName" }
"""),

  _s("Install Chocolatey", "Software", "windows", "powershell",
     "Install Chocolatey package manager",
     r"""Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))
Write-Output "Chocolatey installed"
"""),

  _s("Install App via Winget", "Software", "windows", "powershell",
     "Install any app via winget (edit PackageId before running)",
     'winget install --id "7zip.7zip" --silent --accept-package-agreements --accept-source-agreements'),

  # ════════════════════════════════════════════════════════════
  # POWER — WINDOWS
  # ════════════════════════════════════════════════════════════
  _s("Power Plan Status", "Power", "windows", "powershell",
     "Show active power plan and available plans",
     "powercfg /list; Write-Output '---'; powercfg /getactivescheme"),

  _s("Set High Performance Plan", "Power", "windows", "powershell",
     "Switch to High Performance power plan",
     "powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c; Write-Output 'High Performance activated'"),

  _s("Set Balanced Power Plan", "Power", "windows", "powershell",
     "Switch to Balanced power plan",
     "powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e; Write-Output 'Balanced plan activated'"),

  _s("Battery Health Report", "Power", "windows", "powershell",
     "Generate and parse a battery health report",
     r"""$report = "$env:TEMP\battery_report.html"
powercfg /batteryreport /output $report /duration 7
if (Test-Path $report) {
  $c = Get-Content $report -Raw
  $design = [regex]::Match($c,'DESIGN CAPACITY.*?(\d[\d,]+) mWh').Groups[1].Value
  $full   = [regex]::Match($c,'FULL CHARGE CAPACITY.*?(\d[\d,]+) mWh').Groups[1].Value
  Write-Output "Design Capacity : $design mWh"
  Write-Output "Full Charge     : $full mWh"
  if ($design -and $full) {
    $health = [math]::Round(($full -replace ',','' -as [int]) / ($design -replace ',','' -as [int]) * 100, 1)
    Write-Output "Battery Health  : $health%"
  }
  Remove-Item $report -Force
}
"""),

  # ════════════════════════════════════════════════════════════
  # REMOTE ACCESS — WINDOWS
  # ════════════════════════════════════════════════════════════
  _s("Enable RDP", "Remote Access", "windows", "powershell",
     "Enable Remote Desktop and open firewall rule",
     r"""Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name 'fDenyTSConnections' -Value 0
Enable-NetFirewallRule -DisplayGroup "Remote Desktop"
Write-Output "RDP enabled"
"""),

  _s("Disable RDP", "Remote Access", "windows", "powershell",
     "Disable Remote Desktop",
     r"""Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name 'fDenyTSConnections' -Value 1
Disable-NetFirewallRule -DisplayGroup "Remote Desktop"
Write-Output "RDP disabled"
"""),

  _s("Enable WinRM (PS Remoting)", "Remote Access", "windows", "powershell",
     "Enable PowerShell Remoting for remote management",
     "Enable-PSRemoting -Force; Write-Output 'WinRM enabled'"),

  # ════════════════════════════════════════════════════════════
  # REGISTRY — WINDOWS
  # ════════════════════════════════════════════════════════════
  _s("Disable Autorun", "Registry", "windows", "powershell",
     "Disable AutoRun on all drives via registry",
     r"""Set-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer' -Name 'NoDriveTypeAutoRun' -Value 255
Write-Output "AutoRun disabled for all drive types"
"""),

  _s("Show File Extensions", "Registry", "windows", "powershell",
     "Force Explorer to show file extensions",
     r"""Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced' -Name 'HideFileExt' -Value 0
Write-Output "File extensions now visible"
"""),

  _s("Disable Fast Startup", "Registry", "windows", "powershell",
     "Disable Windows Fast Startup (hybrid shutdown)",
     r"""Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -Name 'HiberbootEnabled' -Value 0
Write-Output "Fast Startup disabled"
"""),

  # ════════════════════════════════════════════════════════════
  # LINUX
  # ════════════════════════════════════════════════════════════
  _s("System Overview", "System Info", "linux", "bash",
     "Full system info: OS, CPU, RAM, disk, uptime",
     r"""echo "=== SYSTEM OVERVIEW ==="
echo "Hostname  : $(hostname)"
echo "OS        : $(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '"')"
echo "Kernel    : $(uname -r)"
echo "Uptime    : $(uptime -p)"
echo "CPU       : $(grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2 | xargs)"
echo "CPU Cores : $(nproc)"
echo "RAM Total : $(free -h | awk '/Mem:/{print $2}')"
echo "RAM Used  : $(free -h | awk '/Mem:/{print $3}')"
echo "Disk:"
df -h --output=target,size,used,avail,pcent | grep -v tmpfs
"""),

  _s("Update All Packages (Debian/Ubuntu)", "Maintenance", "linux", "bash",
     "Full apt update, upgrade, and autoremove",
     "apt-get update -y && apt-get upgrade -y && apt-get autoremove -y && apt-get autoclean -y && echo 'Done'"),

  _s("Update All Packages (RHEL/CentOS)", "Maintenance", "linux", "bash",
     "Full yum/dnf update",
     "dnf update -y 2>/dev/null || yum update -y && echo 'Done'"),

  _s("List Failed Services", "Monitoring", "linux", "bash",
     "Show all systemd services that have failed",
     "systemctl --failed --no-pager"),

  _s("Top Processes by CPU", "Performance", "linux", "bash",
     "Top 15 CPU-consuming processes",
     "ps aux --sort=-%cpu | head -16"),

  _s("Top Processes by RAM", "Performance", "linux", "bash",
     "Top 15 RAM-consuming processes",
     "ps aux --sort=-%mem | head -16"),

  _s("Check Disk Health (smartctl)", "Monitoring", "linux", "bash",
     "Run SMART health check on all disks",
     r"""for disk in /dev/sd? /dev/nvme?; do
  [ -e "$disk" ] || continue
  echo "=== $disk ==="
  smartctl -H "$disk" 2>/dev/null || echo "  smartmontools not installed"
done
"""),

  _s("Large Files (>100MB)", "Maintenance", "linux", "bash",
     "Find files larger than 100MB",
     "find / -xdev -type f -size +100M 2>/dev/null | xargs ls -lh 2>/dev/null | sort -k5 -rh | head -20"),

  _s("Last 50 Auth Failures", "Security", "linux", "bash",
     "Show recent SSH/auth failure attempts",
     "grep -i 'failed\\|invalid\\|refused' /var/log/auth.log 2>/dev/null | tail -50 || journalctl -u ssh --since '24 hours ago' | grep -i failed | tail -50"),

  _s("Open Ports", "Security", "linux", "bash",
     "List all listening ports and processes",
     "ss -tulnp"),

  _s("Firewall Rules", "Security", "linux", "bash",
     "Show current iptables/nftables/ufw firewall rules",
     "iptables -L -n -v 2>/dev/null || nft list ruleset 2>/dev/null || ufw status verbose 2>/dev/null"),

  _s("Reboot (1 min)", "Power", "linux", "bash",
     "Schedule a reboot in 1 minute",
     "shutdown -r +1 'RMM-initiated reboot' && echo 'Reboot scheduled'"),

  _s("Shutdown (1 min)", "Power", "linux", "bash",
     "Shutdown in 1 minute",
     "shutdown -h +1 'RMM-initiated shutdown' && echo 'Shutdown scheduled'"),

  _s("Clear Old Journal Logs", "Maintenance", "linux", "bash",
     "Rotate and clear journal logs older than 7 days",
     "journalctl --vacuum-time=7d && journalctl --vacuum-size=500M && echo 'Done'"),

  _s("Network Interfaces", "Network", "linux", "bash",
     "Show all interfaces, IPs, and routes",
     "ip addr show && echo '---' && ip route"),

  # ════════════════════════════════════════════════════════════
  # ANDROID
  # ════════════════════════════════════════════════════════════
  _s("Battery Status", "Monitoring", "android", "bash",
     "Check battery level and charging state",
     r"""echo "Battery: $(cat /sys/class/power_supply/battery/capacity)%"
echo "Status : $(cat /sys/class/power_supply/battery/status)"
"""),

  _s("Storage Info", "Monitoring", "android", "bash",
     "Show storage usage breakdown",
     "df -h && echo '---' && du -sh /sdcard/* 2>/dev/null | sort -rh | head -10"),

  _s("Network Info", "Network", "android", "bash",
     "Show WiFi and network interface info",
     "ip addr && echo '---' && cat /proc/net/wireless 2>/dev/null"),

  _s("Running Processes", "System Info", "android", "bash",
     "List running application processes",
     "ps -A 2>/dev/null || ps"),
]


# ── ENDPOINTS ─────────────────────────────────────────────────

@router.get("/")
async def list_scripts(category: str = None, platform: str = None,
                       db: AsyncSession = Depends(get_db)):
    query = select(ScriptLibrary).order_by(ScriptLibrary.category, ScriptLibrary.name)
    if category:
        query = query.where(ScriptLibrary.category == category)
    if platform:
        query = query.where((ScriptLibrary.platform == platform) | (ScriptLibrary.platform == "all"))
    result = await db.execute(query)
    scripts = result.scalars().all()
    return [{"id": s.id, "name": s.name, "category": s.category, "platform": s.platform,
             "script_type": s.script_type, "description": s.description,
             "script_body": s.script_body, "tags": s.tags or []} for s in scripts]


@router.post("/seed")
async def seed_scripts(db: AsyncSession = Depends(get_db)):
    """Seed the built-in starter scripts — call once from UI."""
    added = 0
    for s in BUILTIN_SCRIPTS:
        existing = await db.execute(select(ScriptLibrary).where(ScriptLibrary.name == s["name"]))
        if not existing.scalar_one_or_none():
            db.add(ScriptLibrary(id=str(uuid.uuid4()), **s, tags=[]))
            added += 1
    await db.commit()
    return {"seeded": added, "total": len(BUILTIN_SCRIPTS)}


@router.get("/categories")
async def get_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ScriptLibrary.category).distinct())
    return sorted([r[0] for r in result.fetchall() if r[0]])


@router.post("/")
async def create_script(data: dict, db: AsyncSession = Depends(get_db)):
    script = ScriptLibrary(
        id=str(uuid.uuid4()), name=data["name"], category=data.get("category", "Custom"),
        platform=data.get("platform", "windows"), script_type=data.get("script_type", "powershell"),
        description=data.get("description", ""), script_body=data.get("script_body", ""),
        tags=data.get("tags", []),
    )
    db.add(script)
    await db.commit()
    return {"id": script.id}


@router.put("/{script_id}")
async def update_script(script_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ScriptLibrary).where(ScriptLibrary.id == script_id))
    script = result.scalar_one_or_none()
    if not script:
        raise HTTPException(404, "Script not found")
    for field in ("name", "category", "platform", "script_type", "description", "script_body", "tags"):
        if field in data:
            setattr(script, field, data[field])
    await db.commit()
    return {"status": "updated"}


@router.delete("/{script_id}")
async def delete_script(script_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ScriptLibrary).where(ScriptLibrary.id == script_id))
    script = result.scalar_one_or_none()
    if not script:
        raise HTTPException(404, "Script not found")
    await db.delete(script)
    await db.commit()
    return {"status": "deleted"}


@router.post("/{script_id}/run")
async def run_script(script_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    """Dispatch a script to a device immediately."""
    result = await db.execute(select(ScriptLibrary).where(ScriptLibrary.id == script_id))
    script = result.scalar_one_or_none()
    if not script:
        raise HTTPException(404, "Script not found")
    from routes.tasks import create_task
    task_data = {
        "name": f"Run: {script.name}",
        "script_type": script.script_type,
        "script_body": script.script_body,
        "target_type": data.get("target_type", "all"),
        "target_id": data.get("target_id"),
        "trigger_type": "now",
    }
    return await create_task(task_data, db)
