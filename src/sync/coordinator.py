"""
Sync Coordinator - Runs as separate service in Docker
Handles file synchronization coordination
"""
import os
import logging
from pathlib import Path
from sync_manager import SyncManager
from models import db
from flask import Flask

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create minimal Flask app for database access
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///data/devices.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

def main():
    logger.info("Starting Sync Coordinator...")
    
    with app.app_context():
        # Initialize sync manager with app context
        from flask_socketio import SocketIO
        socketio = SocketIO(message_queue='redis://redis:6379' if os.getenv('USE_REDIS') else None)
        
        sync_manager = SyncManager(app, socketio)
        
        logger.info("Sync Coordinator running")
        
        # Keep alive
        import time
        try:
            while True:
                time.sleep(10)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            sync_manager.stop()

if __name__ == '__main__':
    main()
