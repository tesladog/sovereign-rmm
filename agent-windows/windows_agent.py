"""Windows Agent - Full Featured"""
import asyncio, json, os, platform, socket, sys, time
from datetime import datetime
import websockets, requests, psutil
try:
    import win32api, wmi
    WINDOWS = True
except: WINDOWS = False
class Agent:
    def __init__(self, server_url, token):
        self.server_url = server_url.rstrip('/')
        self.token = token
        self.device_id = self.get_device_id()
        self.hostname = socket.gethostname()
    def get_device_id(self):
        import uuid
        config_file = "agent_config.json"
        if os.path.exists(config_file):
            with open(config_file) as f: return json.load(f).get('device_id')
        device_id = str(uuid.uuid4())
        with open(config_file,'w') as f: json.dump({'device_id':device_id},f)
        return device_id
    def register(self):
        try:
            ip = socket.gethostbyname(self.hostname)
        except: ip = None
        data = {'hostname': self.hostname, 'device_type': 'laptop' if psutil.sensors_battery() else 'desktop', 
                'platform': 'windows', 'ip_address': ip, 'os_version': platform.platform()}
        try:
            r = requests.post(f"{self.server_url}/api/devices/", json=data)
            if r.status_code in [200,201]:
                print(f"Registered: {self.device_id}")
                return True
        except Exception as e: print(f"Registration failed: {e}")
        return False
    async def run(self):
        ws_url = self.server_url.replace('http://','ws://').replace('https://','wss://')
        ws_url = f"{ws_url}/ws/agent"
        while True:
            try:
                async with websockets.connect(ws_url) as websocket:
                    await websocket.send(json.dumps({"type":"register","device_id":self.device_id,"platform":"windows"}))
                    print("Connected to server")
                    while True:
                        await asyncio.sleep(30)
                        cpu = psutil.cpu_percent()
                        ram = psutil.virtual_memory()
                        await websocket.send(json.dumps({"type":"heartbeat","cpu_usage":cpu,"ram_used":ram.used,"ram_total":ram.total}))
            except Exception as e:
                print(f"Connection error: {e}")
                await asyncio.sleep(10)
if __name__ == "__main__":
    server_url = os.getenv('SERVER_URL','http://localhost:8000')
    token = os.getenv('AGENT_TOKEN','')
    agent = Agent(server_url, token)
    agent.register()
    asyncio.run(agent.run())
