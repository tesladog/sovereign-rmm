"""
MSI Builder - Creates Windows installer with interactive UI
Includes fix for permission denied errors
"""
import os
import sys
import shutil
import stat
from pathlib import Path
import subprocess
import tempfile

# cx_Freeze for creating executable
from cx_Freeze import setup, Executable


class MSIBuilder:
    """Builds MSI installer for Windows"""
    
    def __init__(self):
        self.build_dir = Path("build")
        self.dist_dir = Path("dist")
        self.msi_dir = Path("msi-build")
        
    def ensure_permissions(self, path):
        """
        Ensure files have proper permissions
        Fixes the permission denied error
        """
        if not os.path.exists(path):
            return
        
        # Make file readable, writable, executable by owner
        # Readable and executable by group and others
        os.chmod(
            path,
            stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
        )
        
        print(f"Fixed permissions for: {path}")
    
    def fix_python_embed_permissions(self, embed_dir):
        """
        Fix permissions for Python embedded distribution
        This is the main fix for the build error
        """
        embed_path = Path(embed_dir)
        
        if not embed_path.exists():
            print(f"Warning: Python embed directory not found: {embed_dir}")
            return
        
        print(f"Fixing permissions in: {embed_dir}")
        
        # Fix permissions for all files in the embed directory
        for root, dirs, files in os.walk(embed_path):
            # Fix directory permissions
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                try:
                    os.chmod(dir_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
                except Exception as e:
                    print(f"Warning: Could not fix permissions for {dir_path}: {e}")
            
            # Fix file permissions
            for file_name in files:
                file_path = os.path.join(root, file_name)
                try:
                    # Special handling for .exe and .dll files
                    if file_name.endswith(('.exe', '.dll', '.pyd')):
                        os.chmod(file_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
                    else:
                        os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
                    
                    print(f"  Fixed: {file_name}")
                except Exception as e:
                    print(f"  Warning: Could not fix {file_name}: {e}")
    
    def clean_build(self):
        """Clean previous build artifacts"""
        for directory in [self.build_dir, self.dist_dir, self.msi_dir]:
            if directory.exists():
                print(f"Cleaning {directory}...")
                shutil.rmtree(directory)
    
    def create_installer_config(self):
        """Create WiX installer configuration"""
        
        wix_template = """<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi"
     xmlns:util="http://schemas.microsoft.com/wix/UtilExtension">
  
  <Product Id="*" 
           Name="Device Management System" 
           Language="1033" 
           Version="1.0.0" 
           Manufacturer="Your Company" 
           UpgradeCode="PUT-GUID-HERE">
    
    <Package InstallerVersion="200" 
             Compressed="yes" 
             InstallScope="perMachine" 
             Description="Device and Storage Management System"
             Comments="Manages devices, storage, and file synchronization" />
    
    <MajorUpgrade DowngradeErrorMessage="A newer version is already installed." />
    <MediaTemplate EmbedCab="yes" />
    
    <!-- Interactive UI -->
    <UIRef Id="WixUI_InstallDir" />
    <UIRef Id="WixUI_ErrorProgressText" />
    
    <Property Id="WIXUI_INSTALLDIR" Value="INSTALLFOLDER" />
    
    <!-- Support for silent install (Windows Server) -->
    <Property Id="MSIUSEREALADMINDETECTION" Value="1" />
    
    <Feature Id="ProductFeature" Title="Device Management System" Level="1">
      <ComponentGroupRef Id="ProductComponents" />
      <ComponentRef Id="ServiceComponent" />
    </Feature>
    
    <!-- Installation directory -->
    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="ProgramFilesFolder">
        <Directory Id="INSTALLFOLDER" Name="DeviceManagement" />
      </Directory>
      
      <Directory Id="ProgramMenuFolder">
        <Directory Id="ApplicationProgramsFolder" Name="Device Management System"/>
      </Directory>
    </Directory>
    
    <!-- Components -->
    <ComponentGroup Id="ProductComponents" Directory="INSTALLFOLDER">
      <!-- Main executable -->
      <Component Id="MainExecutable" Guid="*">
        <File Id="AgentExe" 
              Source="$(var.SourceDir)\\agent.exe" 
              KeyPath="yes" />
      </Component>
      
      <!-- Configuration -->
      <Component Id="ConfigFiles" Guid="*">
        <File Id="ConfigJson" 
              Source="$(var.SourceDir)\\config.json" 
              KeyPath="yes" />
      </Component>
      
      <!-- Python dependencies -->
      <Component Id="PythonRuntime" Guid="*">
        <File Id="Python310Dll" 
              Source="$(var.SourceDir)\\python310.dll" 
              KeyPath="yes" />
      </Component>
    </ComponentGroup>
    
    <!-- Windows Service -->
    <Component Id="ServiceComponent" Directory="INSTALLFOLDER" Guid="*">
      <File Id="ServiceExe" Source="$(var.SourceDir)\\agent.exe" />
      
      <ServiceInstall Id="ServiceInstaller"
                      Type="ownProcess"
                      Name="DeviceManagementAgent"
                      DisplayName="Device Management Agent"
                      Description="Manages device registration and file synchronization"
                      Start="auto"
                      Account="LocalSystem"
                      ErrorControl="normal"
                      Interactive="no" />
      
      <ServiceControl Id="StartService" 
                      Start="install" 
                      Stop="both" 
                      Remove="uninstall" 
                      Name="DeviceManagementAgent" 
                      Wait="yes" />
    </Component>
    
    <!-- Start Menu shortcuts -->
    <DirectoryRef Id="ApplicationProgramsFolder">
      <Component Id="ApplicationShortcut" Guid="*">
        <Shortcut Id="ApplicationStartMenuShortcut"
                  Name="Device Management Agent"
                  Description="Manage device registration and sync"
                  Target="[INSTALLFOLDER]agent.exe"
                  WorkingDirectory="INSTALLFOLDER"/>
        
        <RemoveFolder Id="CleanUpShortCut" Directory="ApplicationProgramsFolder" On="uninstall"/>
        <RegistryValue Root="HKCU" 
                       Key="Software\\DeviceManagement" 
                       Name="installed" 
                       Type="integer" 
                       Value="1" 
                       KeyPath="yes"/>
      </Component>
    </DirectoryRef>
    
    <!-- Custom actions -->
    <CustomAction Id="ConfigureService" 
                  Directory="INSTALLFOLDER" 
                  ExeCommand="[INSTALLFOLDER]agent.exe --config"
                  Execute="deferred"
                  Impersonate="no"
                  Return="check" />
    
    <InstallExecuteSequence>
      <Custom Action="ConfigureService" After="InstallFiles">
        NOT REMOVE
      </Custom>
    </InstallExecuteSequence>
    
  </Product>
</Wix>
"""
        
        wix_file = self.msi_dir / "installer.wxs"
        wix_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(wix_file, 'w') as f:
            f.write(wix_template)
        
        print(f"Created WiX configuration: {wix_file}")
        return wix_file
    
    def build_executable(self):
        """Build executable using cx_Freeze"""
        
        print("Building executable...")
        
        build_options = {
            "build_exe": {
                "packages": [
                    "socketio",
                    "requests",
                    "psutil",
                    "win32api",
                    "win32service",
                    "win32serviceutil",
                    "wmi"
                ],
                "includes": [],
                "excludes": ["tkinter", "unittest"],
                "include_files": [],
            }
        }
        
        executables = [
            Executable(
                script="src/agent/agent.py",
                base="Win32Service" if sys.platform == "win32" else None,
                target_name="agent.exe",
                icon=None  # Add your icon here
            )
        ]
        
        # Run cx_Freeze
        setup(
            name="DeviceManagementAgent",
            version="1.0.0",
            description="Device Management Agent",
            options=build_options,
            executables=executables
        )
        
        print("Executable built successfully")
    
    def build_msi(self):
        """Build MSI installer using WiX"""
        
        print("Building MSI installer...")
        
        # Paths
        wix_file = self.create_installer_config()
        wixobj_file = self.msi_dir / "installer.wixobj"
        msi_file = self.dist_dir / "DeviceManagement.msi"
        
        self.dist_dir.mkdir(exist_ok=True)
        
        try:
            # Compile WiX source
            print("Compiling WiX source...")
            subprocess.run([
                "candle.exe",
                str(wix_file),
                "-out", str(wixobj_file),
                f"-dSourceDir={self.build_dir / 'exe.win-amd64-3.10'}"
            ], check=True)
            
            # Link to create MSI
            print("Linking MSI...")
            subprocess.run([
                "light.exe",
                str(wixobj_file),
                "-out", str(msi_file),
                "-ext", "WixUIExtension",
                "-ext", "WixUtilExtension"
            ], check=True)
            
            print(f"\nMSI created successfully: {msi_file}")
            print(f"Size: {msi_file.stat().st_size / 1024 / 1024:.2f} MB")
            
        except subprocess.CalledProcessError as e:
            print(f"Error building MSI: {e}")
            return False
        except FileNotFoundError:
            print("ERROR: WiX Toolset not found!")
            print("Please install WiX Toolset from: https://wixtoolset.org/")
            return False
        
        return True
    
    def build(self):
        """Main build process"""
        
        print("=" * 60)
        print("Building Device Management System Installer")
        print("=" * 60)
        
        # Clean previous builds
        self.clean_build()
        
        # Fix Python embed permissions BEFORE building
        python_embed = Path(sys.exec_prefix)
        self.fix_python_embed_permissions(python_embed)
        
        # Build executable
        self.build_executable()
        
        # Fix permissions on build output
        build_output = self.build_dir / f"exe.{sys.platform}-{sys.version_info[0]}.{sys.version_info[1]}"
        if build_output.exists():
            print(f"\nFixing permissions on build output...")
            self.fix_python_embed_permissions(build_output)
        
        # Build MSI
        if self.build_msi():
            print("\n" + "=" * 60)
            print("BUILD SUCCESSFUL!")
            print("=" * 60)
            print(f"\nInstaller location: {self.dist_dir / 'DeviceManagement.msi'}")
            print("\nInstallation options:")
            print("  Interactive: Double-click the MSI file")
            print("  Silent:      msiexec /i DeviceManagement.msi /quiet /norestart")
            print("  Uninstall:   msiexec /x DeviceManagement.msi /quiet /norestart")
        else:
            print("\nBUILD FAILED")
            return False
        
        return True


def main():
    """Main entry point"""
    builder = MSIBuilder()
    
    if not builder.build():
        sys.exit(1)


if __name__ == '__main__':
    main()
