"""
Unit tests for Storage Manager
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from src.server.storage_manager import StorageManager


class TestStorageManager:
    """Test suite for StorageManager"""
    
    @pytest.fixture
    def storage_manager(self):
        """Create a StorageManager instance for testing"""
        app = Mock()
        socketio = Mock()
        return StorageManager(app, socketio)
    
    def test_get_drive_serial(self, storage_manager):
        """Test getting drive serial number"""
        with patch('src.server.storage_manager.win32api.GetVolumeInformation') as mock_vol:
            mock_vol.return_value = ('TestDrive', 12345678, None, None, 'NTFS')
            
            serial = storage_manager.get_drive_serial('C')
            
            assert serial == '12345678'
            mock_vol.assert_called_once_with('C:\\')
    
    def test_determine_storage_type_ssd(self, storage_manager):
        """Test SSD detection"""
        storage_type = storage_manager.determine_storage_type(
            'Fixed hard disk',
            'SATA',
            'Samsung SSD 870 EVO'
        )
        
        assert storage_type == 'ssd'
    
    def test_determine_storage_type_usb(self, storage_manager):
        """Test USB detection"""
        storage_type = storage_manager.determine_storage_type(
            'Removable Media',
            'USB',
            'Kingston DataTraveler'
        )
        
        assert storage_type == 'usb'
    
    def test_scan_folder_tree(self, storage_manager):
        """Test folder tree scanning"""
        with patch('pathlib.Path.iterdir') as mock_iterdir:
            # Mock folder structure
            mock_folder = Mock()
            mock_folder.is_dir.return_value = True
            mock_folder.relative_to.return_value = 'TestFolder'
            mock_folder.parent = Mock()
            
            mock_iterdir.return_value = [mock_folder]
            
            tree = storage_manager.scan_folder_tree('C', max_depth=1)
            
            assert isinstance(tree, dict)
    
    def test_generate_asset_tag(self, storage_manager):
        """Test asset tag generation"""
        with patch('src.server.storage_manager.Storage') as mock_storage:
            mock_storage.query.filter_by.return_value.first.return_value = None
            
            tag = storage_manager.generate_asset_tag('ssd')
            
            assert tag.startswith('SS-')
            assert len(tag.split('-')) == 3


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
