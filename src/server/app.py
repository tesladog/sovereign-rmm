"""
Device Management System - Main Server Application
"""
import os
import logging
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from datetime import datetime

from models import db, Device, Storage, SyncJob, Script, Task
from storage_manager import StorageManager
from sync_manager import SyncManager
from policy_monitor import PolicyMonitor

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///data/devices.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max upload

# Initialize extensions
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")
db.init_app(app)

# Initialize managers
storage_manager = StorageManager(app, socketio)
sync_manager = SyncManager(app, socketio)
policy_monitor = PolicyMonitor(app, socketio)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# Health check
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat()
    })


# Device endpoints
@app.route('/api/devices', methods=['GET'])
def get_devices():
    """Get all devices"""
    devices = Device.query.all()
    return jsonify([d.to_dict() for d in devices])


@app.route('/api/devices/<device_id>', methods=['GET'])
def get_device(device_id):
    """Get specific device"""
    device = Device.query.get_or_404(device_id)
    return jsonify(device.to_dict())


@app.route('/api/devices', methods=['POST'])
def register_device():
    """Register new device"""
    data = request.json
    device = Device(
        hostname=data['hostname'],
        device_type=data.get('device_type', 'laptop'),
        ip_address=data.get('ip_address'),
        mac_address=data.get('mac_address'),
        os_version=data.get('os_version')
    )
    db.session.add(device)
    db.session.commit()
    
    logger.info(f"Device registered: {device.hostname}")
    socketio.emit('device_registered', device.to_dict())
    
    return jsonify(device.to_dict()), 201


# Storage endpoints
@app.route('/api/storage', methods=['GET'])
def get_storage():
    """Get all storage devices"""
    storage_devices = Storage.query.all()
    return jsonify([s.to_dict() for s in storage_devices])


@app.route('/api/storage/<storage_id>', methods=['GET'])
def get_storage_device(storage_id):
    """Get specific storage device"""
    storage = Storage.query.get_or_404(storage_id)
    return jsonify(storage.to_dict())


@app.route('/api/storage/scan', methods=['POST'])
def scan_storage():
    """Scan and register storage device"""
    data = request.json
    result = storage_manager.scan_drive(
        drive_letter=data['drive_letter'],
        device_id=data.get('device_id')
    )
    return jsonify(result)


# Sync endpoints
@app.route('/api/sync/jobs', methods=['GET'])
def get_sync_jobs():
    """Get all sync jobs"""
    jobs = SyncJob.query.all()
    return jsonify([j.to_dict() for j in jobs])


@app.route('/api/sync/jobs', methods=['POST'])
def create_sync_job():
    """Create new sync job"""
    data = request.json
    job = sync_manager.create_job(
        name=data['name'],
        source_path=data['source_path'],
        destinations=data['destinations'],
        mode=data.get('mode', 'push')
    )
    return jsonify(job.to_dict()), 201


@app.route('/api/sync/upload', methods=['POST'])
def upload_file():
    """Upload file to server for distribution"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    targets = request.form.getlist('targets')
    
    result = sync_manager.upload_and_distribute(file, targets)
    return jsonify(result)


# Policy monitoring endpoints
@app.route('/api/policy/status/<device_id>', methods=['GET'])
def get_policy_status(device_id):
    """Get group policy status for device"""
    status = policy_monitor.get_status(device_id)
    return jsonify(status)


# Script and task endpoints
@app.route('/api/scripts', methods=['GET'])
def get_scripts():
    """Get all scripts"""
    scripts = Script.query.all()
    return jsonify([s.to_dict() for s in scripts])


@app.route('/api/scripts', methods=['POST'])
def create_script():
    """Create new script"""
    data = request.json
    script = Script(
        name=data['name'],
        content=data['content'],
        script_type=data.get('script_type', 'powershell')
    )
    db.session.add(script)
    db.session.commit()
    
    logger.info(f"Script created: {script.name}")
    return jsonify(script.to_dict()), 201


@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """Get all tasks"""
    tasks = Task.query.all()
    return jsonify([t.to_dict() for t in tasks])


@app.route('/api/tasks', methods=['POST'])
def create_task():
    """Create new task"""
    data = request.json
    
    # Validate device exists
    device = Device.query.get(data['device_id'])
    if not device:
        return jsonify({'error': 'Device not found'}), 404
    
    # Validate script exists
    script = Script.query.get(data['script_id'])
    if not script:
        return jsonify({'error': 'Script not found'}), 404
    
    task = Task(
        device_id=data['device_id'],
        script_id=data['script_id'],
        schedule=data.get('schedule'),
        enabled=data.get('enabled', True)
    )
    db.session.add(task)
    db.session.commit()
    
    logger.info(f"Task created for device {device.hostname}")
    socketio.emit('task_created', task.to_dict())
    
    return jsonify(task.to_dict()), 201


# WebSocket events
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info(f"Client connected: {request.sid}")
    emit('connected', {'message': 'Connected to server'})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info(f"Client disconnected: {request.sid}")


@socketio.on('agent_heartbeat')
def handle_agent_heartbeat(data):
    """Handle agent heartbeat"""
    device_id = data.get('device_id')
    device = Device.query.get(device_id)
    
    if device:
        device.last_seen = datetime.utcnow()
        device.status = 'online'
        db.session.commit()
        
        # Emit to all connected clients
        emit('device_status_update', device.to_dict(), broadcast=True)


# Initialize database
with app.app_context():
    db.create_all()
    logger.info("Database initialized")


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
