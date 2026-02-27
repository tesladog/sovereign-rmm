"""
Sync Manager - Handles file synchronization between devices
Similar to Syncthing functionality
"""
import os
import logging
import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from threading import Thread
import time

from models import db, SyncJob, Device

logger = logging.getLogger(__name__)


class SyncManager:
    """Manages file synchronization across devices"""
    
    def __init__(self, app, socketio):
        self.app = app
        self.socketio = socketio
        self.sync_storage = Path('sync-storage')
        self.sync_storage.mkdir(exist_ok=True)
        
        # Start sync worker thread
        self.running = True
        self.worker_thread = Thread(target=self._sync_worker, daemon=True)
        self.worker_thread.start()
    
    def create_job(self, name, source_path, destinations, mode='push'):
        """
        Create a new sync job
        
        Args:
            name: Job name
            source_path: Source file/folder path
            destinations: List of {device_id, path} dicts
            mode: 'push', 'sync', or 'pull'
        """
        job = SyncJob(
            name=name,
            source_path=source_path,
            destinations=destinations,
            mode=mode,
            status='pending'
        )
        db.session.add(job)
        db.session.commit()
        
        logger.info(f"Created sync job: {name} (mode: {mode})")
        self.socketio.emit('sync_job_created', job.to_dict())
        
        return job
    
    def upload_and_distribute(self, file, targets):
        """
        Upload file to server and distribute to target devices
        
        Args:
            file: FileStorage object from Flask
            targets: List of device IDs to distribute to
        """
        # Save file to sync storage
        file_hash = hashlib.sha256()
        filename = file.filename
        
        upload_path = self.sync_storage / filename
        file.save(str(upload_path))
        
        # Calculate hash
        with open(upload_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                file_hash.update(chunk)
        
        file_checksum = file_hash.hexdigest()
        
        # Create distribution job
        destinations = [{'device_id': device_id, 'path': None} for device_id in targets]
        
        job = SyncJob(
            name=f"Push {filename}",
            source_path=str(upload_path),
            destinations=destinations,
            mode='push',
            status='pending'
        )
        db.session.add(job)
        db.session.commit()
        
        logger.info(f"File uploaded: {filename} ({file_checksum[:8]})")
        
        # Notify agents to pull file
        for device_id in targets:
            self.socketio.emit('file_push', {
                'job_id': job.id,
                'filename': filename,
                'checksum': file_checksum,
                'size': upload_path.stat().st_size
            }, room=device_id)
        
        return {
            'job_id': job.id,
            'filename': filename,
            'checksum': file_checksum,
            'size': upload_path.stat().st_size,
            'targets': len(targets)
        }
    
    def sync_file(self, source_device_id, source_path, target_devices):
        """
        Set up bidirectional sync between devices
        Similar to Syncthing's folder sharing
        """
        destinations = [
            {'device_id': device_id, 'path': source_path}
            for device_id in target_devices
        ]
        
        job = SyncJob(
            name=f"Sync {Path(source_path).name}",
            source_path=source_path,
            source_device_id=source_device_id,
            destinations=destinations,
            mode='sync',
            status='pending'
        )
        db.session.add(job)
        db.session.commit()
        
        logger.info(f"Created sync job for {source_path}")
        
        return job
    
    def _sync_worker(self):
        """Background worker that processes sync jobs"""
        logger.info("Sync worker started")
        
        while self.running:
            try:
                with self.app.app_context():
                    # Get pending jobs
                    jobs = SyncJob.query.filter_by(
                        status='pending',
                        enabled=True
                    ).limit(5).all()
                    
                    for job in jobs:
                        self._process_sync_job(job)
                
                time.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                logger.error(f"Sync worker error: {e}")
                time.sleep(10)
    
    def _process_sync_job(self, job):
        """Process a single sync job"""
        try:
            job.status = 'running'
            db.session.commit()
            
            if job.mode == 'push':
                self._process_push(job)
            elif job.mode == 'sync':
                self._process_sync(job)
            elif job.mode == 'pull':
                self._process_pull(job)
            
            job.status = 'completed'
            job.last_sync = datetime.utcnow()
            
        except Exception as e:
            logger.error(f"Job {job.id} failed: {e}")
            job.status = 'failed'
        
        finally:
            db.session.commit()
            self.socketio.emit('sync_job_updated', job.to_dict())
    
    def _process_push(self, job):
        """
        Push mode: One-way from source to destinations
        Server has the file, agents pull it
        """
        source_path = Path(job.source_path)
        
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")
        
        # Calculate file hash
        file_hash = self._calculate_hash(source_path)
        
        # Notify each destination device
        for dest in job.destinations:
            device_id = dest['device_id']
            target_path = dest.get('path') or source_path.name
            
            # Check if device is online
            device = Device.query.get(device_id)
            if not device or device.status != 'online':
                logger.warning(f"Device {device_id} is offline, skipping")
                continue
            
            # Send push notification to agent
            self.socketio.emit('sync_push', {
                'job_id': job.id,
                'source_file': source_path.name,
                'target_path': target_path,
                'checksum': file_hash,
                'size': source_path.stat().st_size
            }, room=device_id)
            
            logger.info(f"Pushed {source_path.name} to device {device_id}")
    
    def _process_sync(self, job):
        """
        Sync mode: Bidirectional sync between all devices
        Uses conflict resolution (last modified wins)
        """
        # Get file metadata from all devices
        devices = [job.source_device_id] + [d['device_id'] for d in job.destinations]
        
        # Request file info from all devices
        for device_id in devices:
            self.socketio.emit('sync_request_info', {
                'job_id': job.id,
                'path': job.source_path
            }, room=device_id)
        
        # Wait for responses and determine newest version
        # (This would need a more sophisticated implementation with callbacks)
        
        logger.info(f"Sync job {job.id} - requested info from {len(devices)} devices")
    
    def _process_pull(self, job):
        """
        Pull mode: Destinations pull from source
        """
        # Similar to push but initiated by destinations
        pass
    
    def _calculate_hash(self, filepath):
        """Calculate SHA256 hash of file"""
        sha256_hash = hashlib.sha256()
        
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                sha256_hash.update(chunk)
        
        return sha256_hash.hexdigest()
    
    def handle_file_request(self, device_id, job_id, filename):
        """Handle file download request from agent"""
        job = SyncJob.query.get(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return None
        
        source_path = Path(job.source_path)
        if not source_path.exists():
            logger.error(f"Source file not found: {source_path}")
            return None
        
        logger.info(f"Device {device_id} downloading {filename}")
        return source_path
    
    def stop(self):
        """Stop the sync worker"""
        self.running = False
        if self.worker_thread.is_alive():
            self.worker_thread.join(timeout=5)
