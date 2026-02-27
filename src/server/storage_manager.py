"""
Storage Manager - Handles external drive detection and tracking
"""
import os
import logging
from datetime import datetime
from pathlib import Path

try:
    import win32api
    import win32file
    import win32con
    import wmi
    WINDOWS_AVAILABLE = True
except ImportError:
    WINDOWS_AVAILABLE = False

from models import db, Storage, Device

logger = logging.getLogger(__name__)


class StorageManager:
    """Manages storage device detection and tracking"""
    
    def __init__(self, app, socketio):
        self.app = app
        self.socketio = socketio
        self.wmi_client = wmi.WMI() if WINDOWS_AVAILABLE else None
        
    def get_drive_serial(self, drive_letter):
        """
        Get persistent volume serial number
        This survives drive letter changes
        """
        if not WINDOWS_AVAILABLE:
            logger.warning("Windows API not available")
            return None
            
        try:
            volume_info = win32api.GetVolumeInformation(f"{drive_letter}:\\")
            return str(volume_info[1])  # Serial number
        except Exception as e:
            logger.error(f"Failed to get serial for {drive_letter}: {e}")
            return None
    
    def get_disk_info(self, drive_letter):
        """
        Get detailed disk information including signature
        """
        if not self.wmi_client:
            return {}
        
        try:
            # Get disk drive info
            for disk in self.wmi_client.Win32_DiskDrive():
                for partition in disk.associators("Win32_DiskDriveToDiskPartition"):
                    for logical_disk in partition.associators("Win32_LogicalDiskToPartition"):
                        if logical_disk.DeviceID.upper() == drive_letter.upper() + ":":
                            return {
                                'signature': disk.Signature,
                                'serial_number': disk.SerialNumber,
                                'model': disk.Model,
                                'size': int(disk.Size) if disk.Size else 0,
                                'interface_type': disk.InterfaceType,
                                'media_type': disk.MediaType
                            }
        except Exception as e:
            logger.error(f"Failed to get disk info for {drive_letter}: {e}")
        
        return {}
    
    def determine_storage_type(self, media_type, interface_type, model):
        """Determine if drive is HDD, SSD, or USB"""
        model_lower = model.lower() if model else ""
        
        # Check for USB
        if interface_type and 'USB' in interface_type.upper():
            return 'usb'
        
        # Check for SSD indicators
        if any(keyword in model_lower for keyword in ['ssd', 'solid state', 'nvme']):
            return 'ssd'
        
        # Check media type
        if media_type:
            if 'Fixed hard disk' in media_type:
                # Additional heuristics needed
                return 'hdd'  # Default to HDD
            elif 'Removable Media' in media_type:
                return 'usb'
        
        return 'hdd'  # Default
    
    def scan_folder_tree(self, drive_letter, max_depth=3):
        """
        Quickly scan folder structure without reading file contents
        Only gets folder names, not file contents
        """
        tree = {}
        root = Path(f"{drive_letter}:\\")
        
        try:
            def scan_dir(path, current_depth=0):
                if current_depth >= max_depth:
                    return
                
                try:
                    for item in path.iterdir():
                        if item.is_dir():
                            relative_path = str(item.relative_to(root))
                            tree[relative_path] = {
                                'depth': current_depth,
                                'parent': str(item.parent.relative_to(root)) if item.parent != root else None
                            }
                            scan_dir(item, current_depth + 1)
                except PermissionError:
                    pass  # Skip directories we can't access
                except Exception as e:
                    logger.debug(f"Error scanning {path}: {e}")
            
            scan_dir(root)
            
        except Exception as e:
            logger.error(f"Failed to scan folder tree for {drive_letter}: {e}")
        
        return tree
    
    def scan_drive(self, drive_letter, device_id=None):
        """
        Scan a drive and register/update it in the database
        """
        if not WINDOWS_AVAILABLE:
            return {'error': 'Windows API not available'}
        
        drive_letter = drive_letter.upper().rstrip(':')
        
        # Get serial number (primary identifier)
        serial_number = self.get_drive_serial(drive_letter)
        if not serial_number:
            return {'error': 'Could not get drive serial number'}
        
        # Get detailed disk info
        disk_info = self.get_disk_info(drive_letter)
        
        # Get volume info
        try:
            volume_info = win32api.GetVolumeInformation(f"{drive_letter}:\\")
            label = volume_info[0] or "Unnamed"
        except:
            label = "Unnamed"
        
        # Get size info
        try:
            _, total, free = win32api.GetDiskFreeSpaceEx(f"{drive_letter}:\\")
            used = total - free
        except:
            total = 0
            used = 0
        
        # Determine storage type
        storage_type = self.determine_storage_type(
            disk_info.get('media_type'),
            disk_info.get('interface_type'),
            disk_info.get('model')
        )
        
        # Scan folder tree
        logger.info(f"Scanning folder tree for {drive_letter}...")
        folder_tree = self.scan_folder_tree(drive_letter)
        
        # Check if storage already exists
        storage = Storage.query.filter_by(serial_number=serial_number).first()
        
        if storage:
            # Update existing storage
            storage.drive_letter = drive_letter
            storage.label = label
            storage.total_size = total
            storage.used_size = used
            storage.folder_tree = folder_tree
            storage.connected = True
            storage.last_seen = datetime.utcnow()
            storage.updated_at = datetime.utcnow()
            
            if device_id:
                storage.device_id = device_id
            
            logger.info(f"Updated existing storage: {serial_number}")
        else:
            # Generate asset tag
            asset_tag = self.generate_asset_tag(storage_type)
            
            # Create new storage entry
            storage = Storage(
                serial_number=serial_number,
                disk_signature=disk_info.get('signature'),
                model=disk_info.get('model'),
                drive_letter=drive_letter,
                label=label,
                total_size=total,
                used_size=used,
                storage_type=storage_type,
                folder_tree=folder_tree,
                connected=True,
                last_seen=datetime.utcnow(),
                asset_tag=asset_tag,
                device_id=device_id
            )
            db.session.add(storage)
            logger.info(f"Registered new storage: {serial_number}")
        
        db.session.commit()
        
        # Emit WebSocket event
        self.socketio.emit('storage_updated', storage.to_dict())
        
        return storage.to_dict()
    
    def generate_asset_tag(self, storage_type):
        """Generate unique asset tag for storage device"""
        from datetime import datetime
        import random
        
        prefix = {
            'hdd': 'HD',
            'ssd': 'SS',
            'usb': 'USB'
        }.get(storage_type, 'STR')
        
        # Generate tag: PREFIX-YYMM-XXXX
        date_part = datetime.now().strftime('%y%m')
        random_part = f"{random.randint(0, 9999):04d}"
        
        tag = f"{prefix}-{date_part}-{random_part}"
        
        # Ensure uniqueness
        while Storage.query.filter_by(asset_tag=tag).first():
            random_part = f"{random.randint(0, 9999):04d}"
            tag = f"{prefix}-{date_part}-{random_part}"
        
        return tag
    
    def monitor_usb_insertion(self):
        """
        Monitor for USB drive insertion events
        This should run in a separate thread
        """
        if not WINDOWS_AVAILABLE:
            logger.warning("USB monitoring not available on non-Windows platforms")
            return
        
        import pythoncom
        from win32com.client import Dispatch
        
        pythoncom.CoInitialize()
        
        try:
            wmi = Dispatch("WbemScripting.SWbemLocator")
            service = wmi.ConnectServer(".", "root\\cimv2")
            
            # Watch for volume creation events
            watcher = service.ExecNotificationQuery(
                "SELECT * FROM __InstanceCreationEvent WITHIN 2 "
                "WHERE TargetInstance ISA 'Win32_LogicalDisk' "
                "AND TargetInstance.DriveType = 2"  # Removable disk
            )
            
            logger.info("USB monitoring started")
            
            while True:
                event = watcher.NextEvent()
                drive = event.Properties_('TargetInstance').Value
                drive_letter = drive.Properties_('DeviceID').Value.rstrip(':')
                
                logger.info(f"USB drive detected: {drive_letter}")
                
                # Scan the drive
                with self.app.app_context():
                    self.scan_drive(drive_letter)
                
        except Exception as e:
            logger.error(f"USB monitoring error: {e}")
        finally:
            pythoncom.CoUninitialize()
    
    def mark_disconnected(self, serial_number):
        """Mark storage as disconnected"""
        storage = Storage.query.filter_by(serial_number=serial_number).first()
        if storage:
            storage.connected = False
            storage.drive_letter = None
            db.session.commit()
            
            self.socketio.emit('storage_disconnected', storage.to_dict())
