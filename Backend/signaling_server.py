import asyncio
import json
import os
from aiohttp import web, WSMsgType

# Store connections: {ws: role}
connected = {}

async def websocket_handler(request):
    ws = web.WebSocketResponse(max_msg_size=0)
    
    # Check if this is a real WebSocket request
    if not ws.can_prepare(request):
        # If it's just a health check or a browser visit, return OK
        return web.Response(text="Signaling Server Active", status=200)

    await ws.prepare(request)
    
    role = "unknown"
    connected[ws] = role
    print(f"Client connected from {request.remote}. Total: {len(connected)}")
    
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                for conn in list(connected.keys()):
                    if conn != ws:
                        try:
                            await conn.send_bytes(msg.data)
                        except: pass
            
            elif msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    if data.get("type") == "register":
                        role = data.get("role", "unknown")
                        connected[ws] = role
                        print(f"Client registered: {role}")
                        
                        data["_sender_role"] = role
                        msg_str = json.dumps(data)
                        for conn in list(connected.keys()):
                            if conn != ws:
                                try: await conn.send_str(msg_str)
                                except: pass
                        
                        roles = [connected[c] for c in connected]
                        if "android_phone" in roles and "controller" in roles:
                            status = json.dumps({"type": "connected"})
                            for c in connected:
                                try: await c.send_str(status)
                                except: pass
                        continue
                    
                    data["_sender_role"] = connected.get(ws, "unknown")
                    tagged = json.dumps(data)
                    for conn in list(connected.keys()):
                        if conn != ws:
                            try: await conn.send_str(tagged)
                            except: pass
                except: pass
            
            elif msg.type == WSMsgType.ERROR:
                print(f"WebSocket error: {ws.exception()}")

    finally:
        if ws in connected:
            del connected[ws]
        print(f"Client disconnected. Total: {len(connected)}")
    
    return ws

async def health_check(request):
    return web.Response(text="OK", status=200)

app = web.Application()
app.add_routes([
    web.get('/', websocket_handler),       # Smart handler (WS or HTTP OK)
    web.get('/ws', websocket_handler),     # Explicit WS path
    web.get('/health', health_check),      # Backup health path
    web.head('/', health_check)            # HEAD support
])

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting Ultra-Stable Signaling Server on 0.0.0.0:{port}")
    web.run_app(app, host='0.0.0.0', port=port)
