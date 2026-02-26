"""Script Library — reusable saved scripts with categories."""
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from models import ScriptLibrary
from database import get_db

router = APIRouter()

# Built-in script library — Action1-equivalent coverage
BUILTIN_SCRIPTS = [

  # ── SYSTEM INFORMATION ────────────────────────────────────
  {"name":"System Overview","category":"System Info","platform":"windows","script_type":"powershell","description":"Full system snapshot: OS, CPU, RAM, uptime, serial number","script_body":"""$os = Get-WmiObject Win32_OperatingSystem
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
"""},
  {"name":"Installed RAM Details","category":"System Info","platform":"windows","script_type":"powershell","description":"Show each RAM stick: size, speed, slot, manufacturer","script_body":"""Get-WmiObject Win32_PhysicalMemory | Select-Object `
  @{N='Slot';E={$_.DeviceLocator}},
  @{N='Size_GB';E={[math]::Round($_.Capacity/1GB,0)}},
  @{N='Speed_MHz';E={$_.Speed}},
  @{N='Manufacturer';E={$_.Manufacturer}},
  @{N='PartNumber';E={$_.PartNumber.Trim()}} | Format-Table -AutoSize
"""},
  {"name":"CPU Info","category":"System Info","platform":"windows","script_type":"powershell","description":"CPU name, cores, threads, speed, load","script_body":"""$cpu = Get-WmiObject Win32_Processor
Write-Output "Name    : $($cpu.Name)"
Write-Output "Cores   : $($cpu.NumberOfCores)"
Write-Output "Threads : $($cpu.NumberOfLogicalProcessors)"
Write-Output "Speed   : $($cpu.MaxClockSpeed) MHz"
Write-Output "Load    : $($cpu.LoadPercentage)%"
Write-Output "Socket  : $($cpu.SocketDesignation)"
"""},
  {"name":"Disk Inventory","category":"System Info","platform":"windows","script_type":"powershell","description":"All drives: size, free space, filesystem, health","script_body":"""Get-WmiObject Win32_LogicalDisk | Where-Object {$_.DriveType -eq 3} | Select-Object `
  DeviceID,
  @{N='Size_GB';E={[math]::Round($_.Size/1GB,1)}},
  @{N='Free_GB';E={[math]::Round($_.FreeSpace/1GB,1)}},
  @{N='Used_Pct';E={[math]::Round(($_.Size-$_.FreeSpace)/$_.Size*100,1)}},
  FileSystem,
  VolumeName | Format-Table -AutoSize
"""},
  {"name":"GPU Info","category":"System Info","platform":"windows","script_type":"powershell","description":"Graphics card name, VRAM, driver version","script_body":"""Get-WmiObject Win32_VideoController | Select-Object Name,
  @{N='VRAM_MB';E={[math]::Round($_.AdapterRAM/1MB,0)}},
  DriverVersion,CurrentRefreshRate,VideoModeDescription | Format-List
"""},
  {"name":"Motherboard Info","category":"System Info","platform":"windows","script_type":"powershell","description":"Motherboard make, model, BIOS version","script_body":"""$mb = Get-WmiObject Win32_BaseBoard
$bios = Get-WmiObject Win32_BIOS
Write-Output "Manufacturer : $($mb.Manufacturer)"
Write-Output "Product      : $($mb.Product)"
Write-Output "Serial       : $($mb.SerialNumber)"
Write-Output "BIOS Version : $($bios.SMBIOSBIOSVersion)"
Write-Output "BIOS Date    : $($bios.ReleaseDate)"
"""},
  {"name":"Network Adapters","category":"System Info","platform":"windows","script_type":"powershell","description":"All NICs: name, IP, MAC, status","script_body":"""Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | ForEach-Object {
  $ip = (Get-NetIPAddress -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress
  Write-Output "$($_.Name) | MAC: $($_.MacAddress) | IP: $ip | Speed: $($_.LinkSpeed)"
}
"""},
  {"name":"Startup Programs","category":"System Info","platform":"windows","script_type":"powershell","description":"List all programs set to run at startup","script_body":"""$paths = @(
  'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run',
  'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
)
foreach ($p in $paths) {
  Write-Output "`n=== $p ==="
  Get-ItemProperty -Path $p -ErrorAction SilentlyContinue | Select-Object -Property * -ExcludeProperty PS*
}
Get-CimInstance Win32_StartupCommand | Select-Object Name,Command,Location,User | Format-Table -AutoSize
"""},
  {"name":"Environment Variables","category":"System Info","platform":"windows","script_type":"powershell","description":"List all system environment variables","script_body":"[System.Environment]::GetEnvironmentVariables('Machine') | Format-Table -AutoSize"},
  {"name":"Windows License Key","category":"System Info","platform":"windows","script_type":"powershell","description":"Retrieve the installed Windows product key","script_body":"""$key = (Get-WmiObject -query 'select * from SoftwareLicensingService').OA3xOriginalProductKey
if ($key) { Write-Output "Product Key: $key" }
else {
  $regKey = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\SoftwareProtectionPlatform' -Name BackupProductKeyDefault -ErrorAction SilentlyContinue).BackupProductKeyDefault
  Write-Output "Product Key: $regKey"
}
"""},

  # ── MAINTENANCE ───────────────────────────────────────────
  {"name":"Disk Cleanup — Temp Files","category":"Maintenance","platform":"windows","script_type":"powershell","description":"Delete temp files, Windows.old, CBS logs, prefetch","script_body":"""$before = (Get-WmiObject Win32_LogicalDisk -Filter "DeviceID='C:'").FreeSpace
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
"""},
  {"name":"Clear Event Logs","category":"Maintenance","platform":"windows","script_type":"powershell","description":"Clear Application, System, and Security event logs","script_body":"""$logs = @('Application','System','Security','Setup')
foreach ($log in $logs) {
  try { Clear-EventLog -LogName $log -ErrorAction Stop; Write-Output "Cleared: $log" }
  catch { Write-Output "Skipped: $log ($($_.Exception.Message))" }
}
"""},
  {"name":"Flush DNS Cache","category":"Maintenance","platform":"windows","script_type":"powershell","description":"Flush and display the DNS resolver cache","script_body":"""Clear-DnsClientCache
Write-Output "DNS cache flushed."
ipconfig /displaydns | Select-Object -First 10
"""},
  {"name":"Reset Network Stack","category":"Maintenance","platform":"windows","script_type":"powershell","description":"Reset Winsock, TCP/IP, and DNS — fixes many network issues","script_body":"""Write-Output "Resetting Winsock..."
netsh winsock reset
Write-Output "Resetting TCP/IP..."
netsh int ip reset
Write-Output "Flushing DNS..."
ipconfig /flushdns
Write-Output "Done. A restart is recommended."
"""},
  {"name":"Repair Windows System Files (SFC)","category":"Maintenance","platform":"windows","script_type":"powershell","description":"Run sfc /scannow to repair corrupted system files","script_body":"sfc /scannow"},
  {"name":"DISM Repair","category":"Maintenance","platform":"windows","script_type":"powershell","description":"Run DISM to repair the Windows image","script_body":"DISM /Online /Cleanup-Image /RestoreHealth"},
  {"name":"Defrag C Drive","category":"Maintenance","platform":"windows","script_type":"powershell","description":"Optimize (defrag) the C: drive — SSDs will do TRIM instead","script_body":"Optimize-Volume -DriveLetter C -Verbose"},
  {"name":"Check Disk (CHKDSK)","category":"Maintenance","platform":"windows","script_type":"powershell","description":"Schedule a CHKDSK on next reboot","script_body":"""chkdsk C: /f /r /x
Write-Output "CHKDSK scheduled for next boot."
"""},
  {"name":"Windows Update — Install All","category":"Maintenance","platform":"windows","script_type":"powershell","description":"Install all pending Windows Updates silently","script_body":"""if (!(Get-Module -Name PSWindowsUpdate -ListAvailable)) {
  Install-Module PSWindowsUpdate -Force -Scope AllUsers -ErrorAction Stop
}
Import-Module PSWindowsUpdate
Get-WindowsUpdate -Install -AcceptAll -AutoReboot:$false
"""},
  {"name":"Windows Update — List Pending","category":"Maintenance","platform":"windows","script_type":"powershell","description":"List available Windows Updates without installing","script_body":"""if (!(Get-Module -Name PSWindowsUpdate -ListAvailable)) {
  Install-Module PSWindowsUpdate -Force -Scope AllUsers -ErrorAction Stop
}
Import-Module PSWindowsUpdate
Get-WindowsUpdate | Select-Object KB,Title,Size,IsDownloaded | Format-Table -AutoSize
"""},
  {"name":"Disable Hibernate","category":"Maintenance","platform":"windows","script_type":"powershell","description":"Disable hibernation and delete hiberfil.sys","script_body":"powercfg /hibernate off; Write-Output 'Hibernate disabled'"},
  {"name":"Restart Explorer","category":"Maintenance","platform":"windows","script_type":"powershell","description":"Restart Windows Explorer shell","script_body":"Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue; Start-Process explorer; Write-Output 'Explorer restarted'"},
  {"name":"Rebuild Icon Cache","category":"Maintenance","platform":"windows","script_type":"powershell","description":"Clear and rebuild the Windows icon cache","script_body":"""Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
Remove-Item "$env:LOCALAPPDATA\IconCache.db" -Force -ErrorAction SilentlyContinue
Remove-Item "$env:LOCALAPPDATA\Microsoft\Windows\Explorer\iconcache_*" -Force -ErrorAction SilentlyContinue
Start-Process explorer
Write-Output "Icon cache rebuilt"
"""},

  # ── SECURITY ──────────────────────────────────────────────
  {"name":"Antivirus Status","category":"Security","platform":"windows","script_type":"powershell","description":"Check Windows Defender status and last scan time","script_body":"""$def = Get-MpComputerStatus
Write-Output "Enabled          : $($def.AntivirusEnabled)"
Write-Output "Real-time Protect: $($def.RealTimeProtectionEnabled)"
Write-Output "Definitions Date : $($def.AntivirusSignatureLastUpdated)"
Write-Output "Last Scan        : $($def.LastScanTime)"
Write-Output "Threats Found    : $($def.ThreatCount)"
"""},
  {"name":"Run Defender Quick Scan","category":"Security","platform":"windows","script_type":"powershell","description":"Start a Windows Defender quick scan","script_body":"Start-MpScan -ScanType QuickScan; Write-Output 'Quick scan started'"},
  {"name":"Update Defender Definitions","category":"Security","platform":"windows","script_type":"powershell","description":"Force-update Windows Defender definitions","script_body":"Update-MpSignature; Write-Output 'Definitions updated'"},
  {"name":"Check Local Admins","category":"Security","platform":"windows","script_type":"powershell","description":"List all local administrator accounts","script_body":"Get-LocalGroupMember -Group 'Administrators' | Select-Object Name,ObjectClass,PrincipalSource | Format-Table -AutoSize"},
  {"name":"List Open Network Ports","category":"Security","platform":"windows","script_type":"powershell","description":"Show all open TCP/UDP ports and associated processes","script_body":"""Get-NetTCPConnection -State Listen | Select-Object LocalAddress,LocalPort,
  @{N='Process';E={(Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName}} |
  Sort-Object LocalPort | Format-Table -AutoSize
"""},
  {"name":"Check Firewall Status","category":"Security","platform":"windows","script_type":"powershell","description":"Show Windows Firewall status for all profiles","script_body":"Get-NetFirewallProfile | Select-Object Name,Enabled,DefaultInboundAction,DefaultOutboundAction | Format-Table -AutoSize"},
  {"name":"Enable Firewall All Profiles","category":"Security","platform":"windows","script_type":"powershell","description":"Turn on Windows Firewall for Domain, Private, and Public profiles","script_body":"Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled True; Write-Output 'Firewall enabled on all profiles'"},
  {"name":"List Failed Logons (Last 24h)","category":"Security","platform":"windows","script_type":"powershell","description":"Show failed login attempts from the Security event log","script_body":"""$since = (Get-Date).AddHours(-24)
Get-WinEvent -FilterHashtable @{LogName='Security';Id=4625;StartTime=$since} -ErrorAction SilentlyContinue |
  Select-Object TimeCreated,
    @{N='User';E={$_.Properties[5].Value}},
    @{N='IP';E={$_.Properties[19].Value}} |
  Format-Table -AutoSize | Select-Object -First 50
"""},
  {"name":"Check BitLocker Status","category":"Security","platform":"windows","script_type":"powershell","description":"Show BitLocker encryption status on all drives","script_body":"Get-BitLockerVolume | Select-Object MountPoint,EncryptionMethod,ProtectionStatus,VolumeStatus | Format-Table -AutoSize"},
  {"name":"Disable USB Storage","category":"Security","platform":"windows","script_type":"powershell","description":"Disable USB mass storage devices","script_body":"""Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\USBSTOR' -Name 'Start' -Value 4
Write-Output "USB storage disabled. Re-enable by setting Start value back to 3."
"""},
  {"name":"Enable USB Storage","category":"Security","platform":"windows","script_type":"powershell","description":"Re-enable USB mass storage devices","script_body":"""Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\USBSTOR' -Name 'Start' -Value 3
Write-Output "USB storage enabled."
"""},

  # ── USER MANAGEMENT ───────────────────────────────────────
  {"name":"List Local Users","category":"User Management","platform":"windows","script_type":"powershell","description":"All local user accounts with status and last logon","script_body":"""Get-LocalUser | Select-Object Name,Enabled,LastLogon,PasswordExpires,
  @{N='PasswordAge';E={(Get-Date)-$_.PasswordLastSet}} | Format-Table -AutoSize
"""},
  {"name":"List Logged-In Users","category":"User Management","platform":"windows","script_type":"powershell","description":"Show who is currently logged on","script_body":"query user 2>&1"},
  {"name":"Create Local User","category":"User Management","platform":"windows","script_type":"powershell","description":"Create a new local user (edit username/password in script before running)","script_body":"""$username = "newuser"
$password = ConvertTo-SecureString "TempPass123!" -AsPlainText -Force
New-LocalUser -Name $username -Password $password -FullName "New User" -Description "Created by RMM"
Add-LocalGroupMember -Group "Users" -Member $username
Write-Output "User '$username' created"
"""},
  {"name":"Disable Local User","category":"User Management","platform":"windows","script_type":"powershell","description":"Disable a local user account (edit username before running)","script_body":"""$username = "targetuser"
Disable-LocalUser -Name $username
Write-Output "User '$username' disabled"
"""},
  {"name":"Reset Local Password","category":"User Management","platform":"windows","script_type":"powershell","description":"Reset a local user password (edit username/password before running)","script_body":"""$username = "targetuser"
$password = ConvertTo-SecureString "NewTemp123!" -AsPlainText -Force
Set-LocalUser -Name $username -Password $password
Write-Output "Password reset for '$username'"
"""},
  {"name":"List Active Sessions","category":"User Management","platform":"windows","script_type":"powershell","description":"Show all active RDP and console sessions","script_body":"qwinsta"},

  # ── NETWORK ───────────────────────────────────────────────
  {"name":"Ping Test (8.8.8.8)","category":"Network","platform":"windows","script_type":"powershell","description":"Test internet connectivity with ping","script_body":"Test-Connection 8.8.8.8 -Count 4 | Select-Object Address,ResponseTime,StatusCode"},
  {"name":"Traceroute","category":"Network","platform":"windows","script_type":"powershell","description":"Trace route to 8.8.8.8 to diagnose network path","script_body":"Test-NetConnection 8.8.8.8 -TraceRoute"},
  {"name":"Get Public IP","category":"Network","platform":"windows","script_type":"powershell","description":"Retrieve the device's current public IP address","script_body":"(Invoke-RestMethod -Uri 'https://api.ipify.org?format=json').ip"},
  {"name":"Network Speed Test","category":"Network","platform":"windows","script_type":"powershell","description":"Rough download speed test using PowerShell","script_body":"""$url = "http://speedtest.tele2.net/10MB.zip"
$tmp = "$env:TEMP\speedtest.bin"
$start = Get-Date
(New-Object System.Net.WebClient).DownloadFile($url,$tmp)
$elapsed = ((Get-Date) - $start).TotalSeconds
$size = (Get-Item $tmp).Length / 1MB
Remove-Item $tmp -Force
Write-Output "Download: $([math]::Round($size/$elapsed,2)) MB/s ($([math]::Round($size,1)) MB in $([math]::Round($elapsed,1))s)"
"""},
  {"name":"WiFi Signal Strength","category":"Network","platform":"windows","script_type":"powershell","description":"Show current WiFi SSID and signal strength","script_body":"netsh wlan show interfaces | Select-String 'SSID|Signal|Profile|Radio'"},
  {"name":"ARP Cache","category":"Network","platform":"windows","script_type":"powershell","description":"Show ARP table (local network device map)","script_body":"arp -a"},
  {"name":"DNS Resolution Test","category":"Network","platform":"windows","script_type":"powershell","description":"Test DNS resolution for common domains","script_body":"""@('google.com','microsoft.com','github.com') | ForEach-Object {
  try { $r = Resolve-DnsName $_ -QuickTimeout -ErrorAction Stop; Write-Output "$_ → $($r[0].IPAddress)" }
  catch { Write-Output "$_ → FAILED: $($_.Exception.Message)" }
}
"""},
  {"name":"Shared Folders","category":"Network","platform":"windows","script_type":"powershell","description":"List all shared folders on this device","script_body":"Get-SmbShare | Select-Object Name,Path,Description,CurrentUsers | Format-Table -AutoSize"},

  # ── PERFORMANCE ───────────────────────────────────────────
  {"name":"Top CPU Processes","category":"Performance","platform":"windows","script_type":"powershell","description":"Top 15 processes by CPU usage","script_body":"Get-Process | Sort-Object CPU -Descending | Select-Object -First 15 Name,Id,CPU,@{N='RAM_MB';E={[math]::Round($_.WorkingSet64/1MB,1)}} | Format-Table -AutoSize"},
  {"name":"Top RAM Processes","category":"Performance","platform":"windows","script_type":"powershell","description":"Top 15 processes by RAM consumption","script_body":"Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 15 Name,Id,@{N='RAM_MB';E={[math]::Round($_.WorkingSet64/1MB,1)}},CPU | Format-Table -AutoSize"},
  {"name":"CPU Load (30s sample)","category":"Performance","platform":"windows","script_type":"powershell","description":"Sample CPU usage every 5 seconds for 30 seconds","script_body":"""1..6 | ForEach-Object {
  $load = (Get-WmiObject Win32_Processor).LoadPercentage
  Write-Output "$(Get-Date -f 'HH:mm:ss') CPU: $load%"
  Start-Sleep 5
}
"""},
  {"name":"Memory Usage Summary","category":"Performance","platform":"windows","script_type":"powershell","description":"Total, used, and available RAM","script_body":"""$os = Get-WmiObject Win32_OperatingSystem
$total = [math]::Round($os.TotalVisibleMemorySize/1MB,2)
$free  = [math]::Round($os.FreePhysicalMemory/1MB,2)
$used  = [math]::Round($total - $free, 2)
Write-Output "Total : $total GB"
Write-Output "Used  : $used GB ($([math]::Round($used/$total*100,1))%)"
Write-Output "Free  : $free GB"
"""},
  {"name":"Page File Info","category":"Performance","platform":"windows","script_type":"powershell","description":"Check page file size and current usage","script_body":"Get-WmiObject Win32_PageFileUsage | Select-Object Name,AllocatedBaseSize,CurrentUsage,PeakUsage | Format-Table"},
  {"name":"Uptime","category":"Performance","platform":"windows","script_type":"powershell","description":"How long the device has been running since last boot","script_body":"""$boot = (Get-WmiObject Win32_OperatingSystem).ConvertToDateTime((Get-WmiObject Win32_OperatingSystem).LastBootUpTime)
$uptime = (Get-Date) - $boot
Write-Output "Last Boot : $boot"
Write-Output "Uptime    : $($uptime.Days)d $($uptime.Hours)h $($uptime.Minutes)m"
"""},

  # ── SOFTWARE MANAGEMENT ──────────────────────────────────
  {"name":"List Installed Software","category":"Software","platform":"windows","script_type":"powershell","description":"Full list of installed applications with version and publisher","script_body":"""Get-ItemProperty HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*,
  HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\* -ErrorAction SilentlyContinue |
  Where-Object {$_.DisplayName} |
  Select-Object DisplayName,DisplayVersion,Publisher,InstallDate |
  Sort-Object DisplayName | Format-Table -AutoSize
"""},
  {"name":"Uninstall Software","category":"Software","platform":"windows","script_type":"powershell","description":"Silently uninstall a program by name (edit AppName before running)","script_body":"""$AppName = "AppNameHere"
$app = Get-WmiObject -Class Win32_Product | Where-Object { $_.Name -like "*$AppName*" }
if ($app) { $app.Uninstall(); Write-Output "Uninstalled: $($app.Name)" }
else { Write-Output "Not found: $AppName" }
"""},
  {"name":"Install Chocolatey","category":"Software","platform":"windows","script_type":"powershell","description":"Install Chocolatey package manager","script_body":"""Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))
Write-Output "Chocolatey installed"
"""},
  {"name":"Install App via Winget","category":"Software","platform":"windows","script_type":"powershell","description":"Install any app via winget (edit PackageId before running)","script_body":"""$PackageId = "7zip.7zip"
winget install --id $PackageId --silent --accept-package-agreements --accept-source-agreements
"""},

  # ── POWER MANAGEMENT ──────────────────────────────────────
  {"name":"Power Plan Status","category":"Power","platform":"windows","script_type":"powershell","description":"Show active power plan and available plans","script_body":"powercfg /list; Write-Output '---'; powercfg /getactivescheme"},
  {"name":"Set High Performance Plan","category":"Power","platform":"windows","script_type":"powershell","description":"Switch to High Performance power plan","script_body":"powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c; Write-Output 'High Performance plan activated'"},
  {"name":"Set Balanced Power Plan","category":"Power","platform":"windows","script_type":"powershell","description":"Switch to Balanced power plan","script_body":"powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e; Write-Output 'Balanced plan activated'"},
  {"name":"Battery Health Report","category":"Power","platform":"windows","script_type":"powershell","description":"Generate a battery health report and display key stats","script_body":"""$report = "$env:TEMP\battery_report.html"
powercfg /batteryreport /output $report /duration 7
if (Test-Path $report) {
  $content = Get-Content $report -Raw
  $design = [regex]::Match($content, 'DESIGN CAPACITY.*?(\d[\d,]+) mWh').Groups[1].Value
  $full   = [regex]::Match($content, 'FULL CHARGE CAPACITY.*?(\d[\d,]+) mWh').Groups[1].Value
  Write-Output "Design Capacity : $design mWh"
  Write-Output "Full Charge     : $full mWh"
  if ($design -and $full) {
    $health = [math]::Round(($full -replace ',','' -as [int]) / ($design -replace ',','' -as [int]) * 100, 1)
    Write-Output "Battery Health  : $health%"
  }
  Remove-Item $report -Force
}
"""},

  # ── REMOTE CONTROL ────────────────────────────────────────
  {"name":"Enable RDP","category":"Remote Access","platform":"windows","script_type":"powershell","description":"Enable Remote Desktop and open firewall rule","script_body":"""Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name 'fDenyTSConnections' -Value 0
Enable-NetFirewallRule -DisplayGroup "Remote Desktop"
Write-Output "RDP enabled"
"""},
  {"name":"Disable RDP","category":"Remote Access","platform":"windows","script_type":"powershell","description":"Disable Remote Desktop","script_body":"""Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name 'fDenyTSConnections' -Value 1
Disable-NetFirewallRule -DisplayGroup "Remote Desktop"
Write-Output "RDP disabled"
"""},
  {"name":"Enable WinRM (PowerShell Remoting)","category":"Remote Access","platform":"windows","script_type":"powershell","description":"Enable PS Remoting for remote management","script_body":"Enable-PSRemoting -Force; Write-Output 'WinRM enabled'"},

  # ── REGISTRY ──────────────────────────────────────────────
  {"name":"Disable Autorun","category":"Registry","platform":"windows","script_type":"powershell","description":"Disable AutoRun on all drives via registry","script_body":"""Set-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer' -Name 'NoDriveTypeAutoRun' -Value 255
Write-Output "AutoRun disabled for all drive types"
"""},
  {"name":"Show File Extensions","category":"Registry","platform":"windows","script_type":"powershell","description":"Force Explorer to show file extensions for all users","script_body":"""Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced' -Name 'HideFileExt' -Value 0
Write-Output "File extensions now visible"
"""},
  {"name":"Disable Fast Startup","category":"Registry","platform":"windows","script_type":"powershell","description":"Disable Windows Fast Startup (hybrid shutdown)","script_body":"""Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -Name 'HiberbootEnabled' -Value 0
Write-Output "Fast Startup disabled"
"""},

  # ── LINUX SCRIPTS ─────────────────────────────────────────
  {"name":"System Overview","category":"System Info","platform":"linux","script_type":"bash","description":"Full system info: OS, CPU, RAM, disk, uptime","script_body":"""echo "=== SYSTEM OVERVIEW ==="
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
"""},
  {"name":"Update All Packages (Debian/Ubuntu)","category":"Maintenance","platform":"linux","script_type":"bash","description":"Full apt update, upgrade, and autoremove","script_body":"apt-get update -y && apt-get upgrade -y && apt-get autoremove -y && apt-get autoclean -y && echo 'Done'"},
  {"name":"Update All Packages (RHEL/CentOS)","category":"Maintenance","platform":"linux","script_type":"bash","description":"Full yum/dnf update","script_body":"dnf update -y 2>/dev/null || yum update -y && echo 'Done'"},
  {"name":"List Failed Services","category":"Monitoring","platform":"linux","script_type":"bash","description":"Show all systemd services that have failed","script_body":"systemctl --failed --no-pager"},
  {"name":"Top Processes by CPU","category":"Performance","platform":"linux","script_type":"bash","description":"Top 15 CPU-consuming processes","script_body":"ps aux --sort=-%cpu | head -16"},
  {"name":"Top Processes by RAM","category":"Performance","platform":"linux","script_type":"bash","description":"Top 15 RAM-consuming processes","script_body":"ps aux --sort=-%mem | head -16"},
  {"name":"Check Disk Health (smartctl)","category":"Monitoring","platform":"linux","script_type":"bash","description":"Run SMART health check on all disks","script_body":"""for disk in /dev/sd? /dev/nvme?; do
  [ -e "$disk" ] || continue
  echo "=== $disk ==="
  smartctl -H "$disk" 2>/dev/null || echo "  smartmontools not installed or no access"
done
"""},
  {"name":"Large Files (>100MB)","category":"Maintenance","platform":"linux","script_type":"bash","description":"Find files larger than 100MB","script_body":"find / -xdev -type f -size +100M 2>/dev/null | xargs ls -lh | sort -k5 -rh | head -20"},
  {"name":"Last 50 Auth Failures","category":"Security","platform":"linux","script_type":"bash","description":"Show recent SSH/auth failure attempts","script_body":"grep -i 'failed\|invalid\|refused' /var/log/auth.log 2>/dev/null | tail -50 || journalctl -u ssh --since '24 hours ago' | grep -i failed | tail -50"},
  {"name":"Open Ports","category":"Security","platform":"linux","script_type":"bash","description":"List all listening ports and processes","script_body":"ss -tulnp"},
  {"name":"Firewall Rules (iptables)","category":"Security","platform":"linux","script_type":"bash","description":"Show current iptables/nftables firewall rules","script_body":"iptables -L -n -v 2>/dev/null || nft list ruleset 2>/dev/null || ufw status verbose 2>/dev/null"},
  {"name":"Reboot","category":"Power","platform":"linux","script_type":"bash","description":"Schedule a reboot in 1 minute","script_body":"shutdown -r +1 'RMM-initiated reboot in 1 minute' && echo 'Reboot scheduled'"},
  {"name":"Shutdown","category":"Power","platform":"linux","script_type":"bash","description":"Shutdown in 1 minute","script_body":"shutdown -h +1 'RMM-initiated shutdown' && echo 'Shutdown scheduled'"},
  {"name":"Clear Old Logs","category":"Maintenance","platform":"linux","script_type":"bash","description":"Rotate and clear old journal logs older than 7 days","script_body":"journalctl --vacuum-time=7d && journalctl --vacuum-size=500M && echo 'Done'"},
  {"name":"Check Network Interfaces","category":"Network","platform":"linux","script_type":"bash","description":"Show all interfaces, IPs, and link status","script_body":"ip addr show && echo '---' && ip route"},

  # ── ANDROID ───────────────────────────────────────────────
  {"name":"Battery Status","category":"Monitoring","platform":"android","script_type":"bash","description":"Check battery level and charging state","script_body":"""echo "Battery: $(cat /sys/class/power_supply/battery/capacity)%"
echo "Status : $(cat /sys/class/power_supply/battery/status)"
echo "Temp   : $(echo "scale=1; $(cat /sys/class/power_supply/battery/temp)/10" | bc)°C"
"""},
  {"name":"Storage Info","category":"Monitoring","platform":"android","script_type":"bash","description":"Show storage usage breakdown","script_body":"df -h && echo '---' && du -sh /sdcard/* 2>/dev/null | sort -rh | head -10"},
  {"name":"Network Info","category":"Network","platform":"android","script_type":"bash","description":"Show WiFi and mobile data interface info","script_body":"ip addr && echo '---' && cat /proc/net/wireless 2>/dev/null"},
  {"name":"Running Packages","category":"System Info","platform":"android","script_type":"bash","description":"List running application processes","script_body":"ps -A 2>/dev/null || ps"},
]
]


@router.get("/")
async def list_scripts(category: str = None, platform: str = None, db: AsyncSession = Depends(get_db)):
    query = select(ScriptLibrary).order_by(ScriptLibrary.category, ScriptLibrary.name)
    if category:
        query = query.where(ScriptLibrary.category == category)
    if platform and platform != "all":
        query = query.where((ScriptLibrary.platform == platform) | (ScriptLibrary.platform == "all"))
    result = await db.execute(query)
    scripts = result.scalars().all()
    return [
        {"id": s.id, "name": s.name, "description": s.description,
         "category": s.category, "platform": s.platform,
         "script_type": s.script_type, "script_body": s.script_body,
         "tags": s.tags or [], "run_count": s.run_count,
         "created_at": s.created_at.isoformat()}
        for s in scripts
    ]


@router.post("/seed")
async def seed_builtin_scripts(db: AsyncSession = Depends(get_db)):
    """Seed the built-in starter scripts — call once from UI."""
    count = 0
    for s in BUILTIN_SCRIPTS:
        existing = await db.execute(select(ScriptLibrary).where(ScriptLibrary.name == s["name"]))
        if not existing.scalar_one_or_none():
            db.add(ScriptLibrary(id=str(uuid.uuid4()), **s, tags=[]))
            count += 1
    await db.commit()
    return {"seeded": count}


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ScriptLibrary.category).distinct())
    return sorted(set(row[0] for row in result.all() if row[0]))


@router.post("/")
async def create_script(data: dict, db: AsyncSession = Depends(get_db)):
    script = ScriptLibrary(
        id=str(uuid.uuid4()),
        name=data.get("name", "Unnamed Script"),
        description=data.get("description", ""),
        category=data.get("category", "Custom"),
        platform=data.get("platform", "all"),
        script_type=data.get("script_type", "powershell"),
        script_body=data.get("script_body", ""),
        tags=data.get("tags", []),
    )
    db.add(script)
    await db.commit()
    return {"id": script.id}


@router.put("/{script_id}")
async def update_script(script_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ScriptLibrary).where(ScriptLibrary.id == script_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Not found")
    for field in ("name", "description", "category", "platform", "script_type", "script_body", "tags"):
        if field in data:
            setattr(s, field, data[field])
    s.updated_at = datetime.utcnow()
    await db.commit()
    return {"status": "updated"}


@router.delete("/{script_id}")
async def delete_script(script_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ScriptLibrary).where(ScriptLibrary.id == script_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(s)
    await db.commit()
    return {"status": "deleted"}
