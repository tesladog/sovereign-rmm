"""
Policy Monitor - Tracks Group Policy updates and pending restarts
"""
import subprocess
import logging
from datetime import datetime
import re

try:
    import winreg
    WINDOWS_AVAILABLE = True
except ImportError:
    WINDOWS_AVAILABLE = False

from models import db, Device

logger = logging.getLogger(__name__)


class PolicyMonitor:
    """Monitors Group Policy status and system restart requirements"""
    
    def __init__(self, app, socketio):
        self.app = app
        self.socketio = socketio
    
    def get_last_gpupdate(self):
        """
        Get the last time Group Policy was applied
        Parses gpresult output
        """
        if not WINDOWS_AVAILABLE:
            return None
        
        try:
            result = subprocess.run(
                ['gpresult', '/r'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"gpresult failed: {result.stderr}")
                return None
            
            # Parse output for last GP update time
            output = result.stdout
            
            # Look for "Last time Group Policy was applied"
            pattern = r"Last time Group Policy was applied:\s*(.+)"
            match = re.search(pattern, output)
            
            if match:
                date_str = match.group(1).strip()
                try:
                    # Parse date string (format varies by locale)
                    # Example: "12/15/2024 at 3:45:23 PM"
                    dt = self._parse_gpresult_date(date_str)
                    return dt
                except Exception as e:
                    logger.error(f"Failed to parse GP date '{date_str}': {e}")
            
            return None
            
        except subprocess.TimeoutExpired:
            logger.error("gpresult timed out")
            return None
        except Exception as e:
            logger.error(f"Error getting gpupdate time: {e}")
            return None
    
    def _parse_gpresult_date(self, date_str):
        """Parse gpresult date string to datetime"""
        # Try common formats
        formats = [
            "%m/%d/%Y at %I:%M:%S %p",  # US format
            "%d/%m/%Y at %H:%M:%S",      # International format
            "%Y-%m-%d %H:%M:%S",         # ISO-ish format
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        # If all formats fail, return None
        logger.warning(f"Could not parse date: {date_str}")
        return None
    
    def check_pending_restart(self):
        """
        Check if the system has a pending restart
        Checks multiple registry locations
        """
        if not WINDOWS_AVAILABLE:
            return False
        
        keys_to_check = [
            # Component Based Servicing
            (winreg.HKEY_LOCAL_MACHINE, 
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"),
            
            # Windows Update
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"),
            
            # Session Manager
            (winreg.HKEY_LOCAL_MACHINE,
             r"SYSTEM\CurrentControlSet\Control\Session Manager"),
            
            # File Rename Operations
            (winreg.HKEY_LOCAL_MACHINE,
             r"SYSTEM\CurrentControlSet\Control\Session Manager"),
        ]
        
        # Check standard reboot pending keys
        for hive, key_path in keys_to_check[:2]:
            try:
                key = winreg.OpenKey(hive, key_path)
                winreg.CloseKey(key)
                logger.info(f"Found reboot pending key: {key_path}")
                return True
            except FileNotFoundError:
                continue
            except Exception as e:
                logger.debug(f"Error checking {key_path}: {e}")
        
        # Check for PendingFileRenameOperations
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager"
            )
            try:
                value, _ = winreg.QueryValueEx(key, "PendingFileRenameOperations")
                winreg.CloseKey(key)
                if value:
                    logger.info("Found PendingFileRenameOperations")
                    return True
            except FileNotFoundError:
                pass
            finally:
                try:
                    winreg.CloseKey(key)
                except:
                    pass
        except Exception as e:
            logger.debug(f"Error checking PendingFileRenameOperations: {e}")
        
        # Check CCM Client (SCCM/ConfigMgr)
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\SMS\Mobile Client\Reboot Management\RebootData"
            )
            winreg.CloseKey(key)
            logger.info("Found SCCM reboot pending")
            return True
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.debug(f"Error checking SCCM: {e}")
        
        return False
    
    def check_pending_windows_updates(self):
        """Check if Windows Updates are pending"""
        if not WINDOWS_AVAILABLE:
            return False
        
        try:
            result = subprocess.run(
                ['powershell', '-Command', 
                 'Get-WindowsUpdate -MicrosoftUpdate | Select-Object -ExpandProperty Title'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.stdout.strip():
                return True
        except:
            pass
        
        return False
    
    def get_status(self, device_id):
        """
        Get complete policy status for a device
        This runs on the server when the device reports in
        """
        device = Device.query.get(device_id)
        if not device:
            return {'error': 'Device not found'}
        
        return {
            'device_id': device_id,
            'hostname': device.hostname,
            'last_gpupdate': device.last_gpupdate.isoformat() if device.last_gpupdate else None,
            'pending_restart': device.pending_restart,
            'status': device.status
        }
    
    def update_device_status(self, device_id, gpupdate_time=None, pending_restart=None):
        """
        Update device policy status
        Called by agent when it reports status
        """
        device = Device.query.get(device_id)
        if not device:
            logger.error(f"Device {device_id} not found")
            return False
        
        if gpupdate_time is not None:
            device.last_gpupdate = gpupdate_time
            
        if pending_restart is not None:
            device.pending_restart = pending_restart
        
        device.updated_at = datetime.utcnow()
        db.session.commit()
        
        # Emit update to connected clients
        self.socketio.emit('policy_status_updated', {
            'device_id': device_id,
            'last_gpupdate': device.last_gpupdate.isoformat() if device.last_gpupdate else None,
            'pending_restart': device.pending_restart
        })
        
        logger.info(f"Updated policy status for {device.hostname}")
        return True
    
    def force_gpupdate(self, device_id):
        """
        Trigger gpupdate on a remote device
        Sends command to agent
        """
        device = Device.query.get(device_id)
        if not device or device.status != 'online':
            return {'error': 'Device offline or not found'}
        
        # Send command to agent via WebSocket
        self.socketio.emit('run_gpupdate', {
            'force': True
        }, room=device_id)
        
        logger.info(f"Triggered gpupdate on {device.hostname}")
        return {'status': 'Command sent'}
    
    def schedule_restart(self, device_id, delay_minutes=5):
        """
        Schedule a restart on a remote device
        """
        device = Device.query.get(device_id)
        if not device or device.status != 'online':
            return {'error': 'Device offline or not found'}
        
        self.socketio.emit('schedule_restart', {
            'delay_minutes': delay_minutes
        }, room=device_id)
        
        logger.info(f"Scheduled restart on {device.hostname} in {delay_minutes} minutes")
        return {'status': 'Restart scheduled', 'delay_minutes': delay_minutes}
