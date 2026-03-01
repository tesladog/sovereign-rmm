#!/bin/bash
set -e
echo "Building COMPLETE Sovereign RMM with ALL features..."

# ==================== COMPOSE.YAML ====================
cat > compose.yaml << 'COMPOSEEOF'
services:
  postgres:
    image: postgres:16-alpine
    container_name: rmm-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes: [postgres_data:/var/lib/postgresql/data]
    networks: [rmm-internal]
    dns: ["8.8.8.8","8.8.4.4"]
    healthcheck:
      test: ["CMD-SHELL","pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 20s

  redis:
    image: redis:7-alpine
    container_name: rmm-redis
    restart: unless-stopped
    command: redis-server --requirepass ${REDIS_PASSWORD}
    volumes: [redis_data:/data]
    networks: [rmm-internal]
    dns: ["8.8.8.8","8.8.4.4"]
    healthcheck:
      test: ["CMD","redis-cli","--no-auth-warning","-a","${REDIS_PASSWORD}","ping"]
      interval: 10s
      timeout: 5s
      retries: 10

  backend:
    build: {context: ., dockerfile: backend/Dockerfile}
    container_name: rmm-backend
    restart: unless-stopped
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
      AGENT_TOKEN: ${AGENT_TOKEN}
      SERVER_IP: ${SERVER_IP}
      BACKEND_PORT: ${BACKEND_PORT}
      ADMIN_USERNAME: ${ADMIN_USERNAME}
      ADMIN_PASSWORD: ${ADMIN_PASSWORD}
    volumes: [agent_builds:/app/agent-builds,update_cache:/app/update-cache]
    ports: ["${BACKEND_PORT}:8000"]
    networks: [rmm-internal,rmm-external]
    dns: ["8.8.8.8","8.8.4.4"]
    depends_on:
      postgres: {condition: service_healthy}
      redis: {condition: service_healthy}
    healthcheck:
      test: ["CMD","curl","-f","http://localhost:8000/api/health"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 40s

  frontend:
    build: {context: ., dockerfile: frontend/Dockerfile}
    container_name: rmm-frontend
    restart: unless-stopped
    ports: ["${DASHBOARD_PORT}:80"]
    networks: [rmm-internal,rmm-external]
    dns: ["8.8.8.8","8.8.4.4"]
    depends_on: [backend]

networks:
  rmm-internal: {driver: bridge, internal: true}
  rmm-external: {driver: bridge}

volumes:
  postgres_data:
  redis_data:
  agent_builds:
  update_cache:
COMPOSEEOF

# ==================== .ENV ====================
cat > .env << 'ENVEOF'
POSTGRES_DB=sovereignrmm
POSTGRES_USER=rmmuser
POSTGRES_PASSWORD=ChangeMe_DBPass123!

REDIS_PASSWORD=ChangeMe_RedisPass123!

SERVER_IP=192.168.1.100
BACKEND_PORT=8000
DASHBOARD_PORT=8080

AGENT_TOKEN=b3c6d9e2f5a8b1c4d7e0f3a6b9c2d5e8f1a4b7c0d3e6f9a2b5c8d1e4f7a0b3c6

ADMIN_USERNAME=admin
ADMIN_PASSWORD=ChangeMe_AdminPass123!
ENVEOF

# ==================== BACKEND DOCKERFILE ====================
cat > backend/Dockerfile << 'DOCKEREOF'
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y dpkg-dev binutils gcc python3-dev msitools wixl unzip curl && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ /app/backend/
COPY agent-windows/ /app/agent-windows/
COPY agent-linux/ /app/agent-linux/
COPY agent-android/ /app/agent-android/
WORKDIR /app/backend
RUN mkdir -p /app/agent-builds /app/update-cache
EXPOSE 8000
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8000","--workers","1"]
DOCKEREOF

# ==================== REQUIREMENTS ====================
cat > backend/requirements.txt << 'REQEOF'
fastapi==0.111.0
uvicorn[standard]==0.29.0
sqlalchemy[asyncio]==2.0.30
asyncpg==0.29.0
aiofiles==23.2.1
redis[asyncio]==5.0.4
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.9
requests==2.31.0
pyinstaller==6.6.0
websockets==12.0
httpx==0.27.0
qrcode[pil]==7.4.2
Pillow==10.3.0
reportlab==4.1.0
psutil==5.9.8
REQEOF

echo "✓ Core files created"
