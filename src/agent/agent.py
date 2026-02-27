"""
Device Management Agent - Windows Service
Runs on client machines to communicate with the server
"""
import os
import sys
import time
import logging
import socket
import platform
from datetime import datetime
from threading import Thread
import json

import socketio
import requests
import psutil

# Windows-specific imports
try:
    import win32api
    import win32service
    import win32serviceutil
    import win32event
    import servicemanager
    WINDOWS_SERVICE = True
except ImportError:
    WINDOWS_SERVICE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class DeviceAgent:
    """Main agent class"""
    
    def __init__(self, server_url, config_file='agent_config.json'):
        self.server_url = server_url
        self.config_file = config_file
        self.config = self.load_config()
        self.device_id = self.config.get('device_id')
        self.running = True
        
        # Initialize Socket.IO client
        self.sio = socketio.Client(reconnection=True, reconnection_attempts=0)
        self.setup_socketio_handlers()
        
        # Storage monitor thread
        self.storage_thread = None
        
    def load_config(self):
        """Load agent configuration"""
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                return json.load(f)
        return {}
    
    def save_config(self):
        """Save agent configuration"""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def register_device(self):
        """Register this device with the server"""
        hostname = socket.gethostname()
        
        # Get system info
        try:
            ip_address = socket.gethostbyname(hostname)
        except:
            ip_address = None
        
        # Get MAC address
        import uuid
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff)
                       for elements in range(0,2*6,2)][::-1])
        
        device_data = {
            'hostname': hostname,
            'device_type': self.detect_device_type(),
            'ip_address': ip_address,
            'mac_address': mac,
            'os_version': platform.platform()
        }
        
        try:
            response = requests.post(
                f"{self.server_url}/api/devices",
                json=device_data,
                timeout=10
            )
            
            if response.status_code == 201:
                device = response.json()
                self.device_id = device['id']
                self.config['device_id'] = self.device_id
                self.save_config()
                logger.info(f"Device registered: {self.device_id}")
                return True
            else:
                logger.error(f"Registration failed: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to register device: {e}")
            return False
    
    def detect_device_type(self):
        """Detect if this is a laptop, desktop, or server"""
        # Check if battery exists (laptop indicator)
        battery = psutil.sensors_battery()
        if battery is not None:
            return 'laptop'
        
        # Check Windows edition
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
            )
            edition, _ = winreg.QueryValueEx(key, "EditionID")
            winreg.CloseKey(key)
            
            if 'Server' in edition:
                return 'server'
        except:
            pass
        
        return 'desktop'
    
    def setup_socketio_handlers(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.on('connect')
        def on_connect():
            logger.info("Connected to server")
            # Join room for this device
            if self.device_id:
                self.sio.emit('join', {'device_id': self.device_id})
        
        @self.sio.on('disconnect')
        def on_disconnect():
            logger.info("Disconnected from server")
        
        @self.sio.on('run_gpupdate')
        def on_run_gpupdate(data):
            logger.info("Running gpupdate...")
            self.run_gpupdate(force=data.get('force', False))
        
        @self.sio.on('schedule_restart')
        def on_schedule_restart(data):
            delay = data.get('delay_minutes', 5)
            logger.info(f"Scheduling restart in {delay} minutes")
            self.schedule_restart(delay)
        
        @self.sio.on('sync_push')
        def on_sync_push(data):
            logger.info(f"Receiving sync push: {data['source_file']}")
            self.handle_sync_push(data)
        
        @self.sio.on('task_execute')
        def on_task_execute(data):
            logger.info(f"Executing task: {data.get('task_id')}")
            self.execute_task(data)
    
    def connect(self):
        """Connect to the server"""
        try:
            self.sio.connect(self.server_url)
            return True
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False
    
    def heartbeat_loop(self):
        """Send periodic heartbeat to server"""
        while self.running:
            try:
                if self.sio.connected:
                    # Get policy status
                    from policy_monitor import PolicyMonitor
                    pm = PolicyMonitor(None, None)
                    
                    last_gpupdate = pm.get_last_gpupdate()
                    pending_restart = pm.check_pending_restart()
                    
                    # Send heartbeat
                    self.sio.emit('agent_heartbeat', {
                        'device_id': self.device_id,
                        'timestamp': datetime.utcnow().isoformat(),
                        'last_gpupdate': last_gpupdate.isoformat() if last_gpupdate else None,
                        'pending_restart': pending_restart
                    })
                    
                time.sleep(30)  # Every 30 seconds
                
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                time.sleep(60)
    
    def storage_monitor_loop(self):
        """Monitor for USB drive insertion"""
        logger.info("Starting storage monitor")
        
        from storage_manager import StorageManager
        sm = StorageManager(None, None)
        
        # Monitor USB insertion
        sm.monitor_usb_insertion()
    
    def run_gpupdate(self, force=False):
        """Run gpupdate command"""
        import subprocess
        
        cmd = ['gpupdate']
        if force:
            cmd.append('/force')
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            logger.info(f"gpupdate completed: {result.returncode}")
            
            # Report back to server
            from policy_monitor import PolicyMonitor
            pm = PolicyMonitor(None, None)
            last_gpupdate = pm.get_last_gpupdate()
            
            requests.post(
                f"{self.server_url}/api/policy/update",
                json={
                    'device_id': self.device_id,
                    'last_gpupdate': last_gpupdate.isoformat() if last_gpupdate else None
                }
            )
            
        except Exception as e:
            logger.error(f"gpupdate failed: {e}")
    
    def schedule_restart(self, delay_minutes):
        """Schedule system restart"""
        import subprocess
        
        delay_seconds = delay_minutes * 60
        
        try:
            subprocess.run(
                ['shutdown', '/r', '/t', str(delay_seconds)],
                check=True
            )
            logger.info(f"Restart scheduled in {delay_minutes} minutes")
        except Exception as e:
            logger.error(f"Failed to schedule restart: {e}")
    
    def handle_sync_push(self, data):
        """Handle incoming file sync"""
        job_id = data['job_id']
        filename = data['source_file']
        target_path = data['target_path']
        checksum = data['checksum']
        
        # Download file from server
        try:
            response = requests.get(
                f"{self.server_url}/api/sync/download/{job_id}/{filename}",
                stream=True
            )
            
            if response.status_code == 200:
                # Save file
                with open(target_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                logger.info(f"Downloaded {filename} to {target_path}")
                
                # Verify checksum
                import hashlib
                sha256 = hashlib.sha256()
                with open(target_path, 'rb') as f:
                    for chunk in iter(lambda: f.read(4096), b''):
                        sha256.update(chunk)
                
                if sha256.hexdigest() == checksum:
                    logger.info("Checksum verified")
                else:
                    logger.error("Checksum mismatch!")
            
        except Exception as e:
            logger.error(f"Sync push failed: {e}")
    
    def execute_task(self, data):
        """Execute a scheduled task (script)"""
        task_id = data['task_id']
        script_content = data['script_content']
        script_type = data['script_type']
        
        import subprocess
        import tempfile
        
        try:
            # Create temporary script file
            suffix = {
                'powershell': '.ps1',
                'batch': '.bat',
                'python': '.py'
            }.get(script_type, '.txt')
            
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix=suffix,
                delete=False
            ) as f:
                f.write(script_content)
                script_path = f.name
            
            # Execute script
            if script_type == 'powershell':
                cmd = ['powershell', '-ExecutionPolicy', 'Bypass', '-File', script_path]
            elif script_type == 'python':
                cmd = ['python', script_path]
            else:
                cmd = [script_path]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            # Report result back to server
            requests.post(
                f"{self.server_url}/api/tasks/{task_id}/result",
                json={
                    'status': 'success' if result.returncode == 0 else 'failed',
                    'output': result.stdout,
                    'error': result.stderr
                }
            )
            
            logger.info(f"Task {task_id} completed: {result.returncode}")
            
        except Exception as e:
            logger.error(f"Task execution failed: {e}")
            
            requests.post(
                f"{self.server_url}/api/tasks/{task_id}/result",
                json={
                    'status': 'failed',
                    'error': str(e)
                }
            )
        finally:
            # Clean up temp file
            try:
                os.unlink(script_path)
            except:
                pass
    
    def run(self):
        """Main agent loop"""
        # Register device if needed
        if not self.device_id:
            if not self.register_device():
                logger.error("Failed to register device")
                return
        
        # Connect to server
        if not self.connect():
            logger.error("Failed to connect to server")
            return
        
        # Start heartbeat thread
        heartbeat_thread = Thread(target=self.heartbeat_loop, daemon=True)
        heartbeat_thread.start()
        
        # Start storage monitor
        self.storage_thread = Thread(target=self.storage_monitor_loop, daemon=True)
        self.storage_thread.start()
        
        logger.info("Agent running")
        
        # Keep alive
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            self.stop()
    
    def stop(self):
        """Stop the agent"""
        self.running = False
        if self.sio.connected:
            self.sio.disconnect()


# Windows Service wrapper
if WINDOWS_SERVICE:
    class DeviceAgentService(win32serviceutil.ServiceFramework):
        _svc_name_ = "DeviceManagementAgent"
        _svc_display_name_ = "Device Management Agent"
        _svc_description_ = "Agent for device and storage management"
        
        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.agent = None
        
        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)
            if self.agent:
                self.agent.stop()
        
        def SvcDoRun(self):
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, '')
            )
            
            # Get server URL from config
            server_url = os.getenv('SERVER_URL', 'http://localhost:5000')
            
            self.agent = DeviceAgent(server_url)
            self.agent.run()


def main():
    """Main entry point"""
    if len(sys.argv) > 1 and WINDOWS_SERVICE:
        # Running as Windows service
        win32serviceutil.HandleCommandLine(DeviceAgentService)
    else:
        # Running standalone
        server_url = os.getenv('SERVER_URL', 'http://localhost:5000')
        agent = DeviceAgent(server_url)
        agent.run()


if __name__ == '__main__':
    main()
