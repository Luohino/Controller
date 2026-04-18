import asyncio
import json
import websockets

class Signaling:
    def __init__(self, project_id=None):
        try:
            with open("server_url.txt", "r") as f:
                self.uri = f.read().strip()
        except FileNotFoundError:
            self.uri = "ws://127.0.0.1:8080"
            
        self.ws = None
        self.callbacks = {
            "offer": None,
            "answer": None,
            "candidate": None,
            "heartbeat": None,
            "request_offer": None
        }
        self.receive_task = None

    async def connect(self):
        if not self.ws:
            # Enable pings to keep devtunnels connection alive
            self.ws = await websockets.connect(
                self.uri, 
                ping_interval=20, 
                ping_timeout=20
            )
            await self.ws.send(json.dumps({"type": "register", "role": "controller"}))
            self.receive_task = asyncio.create_task(self._listen())

    async def _listen(self):
        try:
            async for message in self.ws:
                data = json.loads(message)
                # Strip internal metadata
                data.pop("_sender_role", None)
                mtype = data.get("type")
                if mtype in self.callbacks and self.callbacks[mtype]:
                    await self.callbacks[mtype](data)
        except Exception as e:
            print(f"WS Disconnected: {e}")
            self.ws = None

    async def send_message(self, msg):
        """Generic message sender."""
        await self.connect()
        await self.ws.send(json.dumps(msg))

    async def check_device_status(self, device_id=None):
        return self.ws is not None and not getattr(self.ws, 'closed', False)
