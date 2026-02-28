FROM python:3.12-slim

WORKDIR /app

# Install all build dependencies for MSI, DEB, APK generation
RUN apt-get update && apt-get install -y \
    # MSI building (Windows installers)
    msitools wixl osslsigncode \
    # DEB building (Debian/Ubuntu packages)
    dpkg-dev fakeroot debhelper \
    # General build tools
    gcc g++ make binutils \
    python3-dev \
    # Android APK signing
    openjdk-17-jdk-headless \
    zipalign apksigner \
    # Utilities
    curl wget unzip zip \
    # Python packaging
    pyinstaller \
    && rm -rf /var/lib/apt/lists/*

# Install Android SDK tools for APK building
ENV ANDROID_HOME=/opt/android-sdk
RUN mkdir -p ${ANDROID_HOME} && \
    wget -q https://dl.google.com/android/repository/commandlinetools-linux-9477386_latest.zip -O /tmp/tools.zip && \
    unzip -q /tmp/tools.zip -d ${ANDROID_HOME}/cmdline-tools && \
    rm /tmp/tools.zip && \
    yes | ${ANDROID_HOME}/cmdline-tools/bin/sdkmanager --sdk_root=${ANDROID_HOME} "build-tools;33.0.0" "platform-tools"

ENV PATH="${ANDROID_HOME}/platform-tools:${ANDROID_HOME}/build-tools/33.0.0:${PATH}"

# Copy requirements and install Python packages
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all source code
COPY backend/ /app/backend/
COPY agent-windows/ /app/agent-windows/
COPY agent-linux/ /app/agent-linux/
COPY agent-android/ /app/agent-android/

WORKDIR /app/backend

# Create directories for builds and updates
RUN mkdir -p /app/agent-builds /app/update-cache /app/lockdown-data

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
