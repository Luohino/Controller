"""
Full P2P Test: Python Offerer + Python Answerer over WebSocket Signaling.
If this works, `aiortc` is fine and the crash is in Flutter's native libwebrtc.
"""
import asyncio
import json
import websockets

# ---- We test WITHOUT aiortc first, just pure signaling ----

async def run_offerer(uri):
    print("[OFFERER] Connecting to signaling server...")
    ws = await websockets.connect(uri)
    await ws.send(json.dumps({"type": "register", "role": "controller"}))
    print("[OFFERER] Registered. Sending request_offer...")
    await ws.send(json.dumps({"type": "request_offer"}))
    print("[OFFERER] Waiting for messages...")
    
    async for msg in ws:
        data = json.loads(msg)
        data.pop("_sender_role", None)
        t = data.get("type")
        print(f"[OFFERER] Got: {t}")
        
        if t == "offer":
            print(f"[OFFERER] Received offer SDP ({len(data['sdp'])} chars)")
            print(f"[OFFERER] SDP preview: {data['sdp'][:150]}...")
            # Send a fake answer back
            await ws.send(json.dumps({
                "type": "answer",
                "sdp": "v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n"
            }))
            print("[OFFERER] Fake answer sent!")
            
        elif t == "candidate":
            print(f"[OFFERER] Got ICE candidate: {data.get('candidate', '')[:60]}...")
            
        elif t == "heartbeat":
            print(f"[OFFERER] Heartbeat from: {data.get('device_id')}")
            
        elif t == "register":
            print(f"[OFFERER] (ignoring register echo)")

async def run_target(uri):
    print("[TARGET] Connecting to signaling server...")
    ws = await websockets.connect(uri)
    await ws.send(json.dumps({"type": "register", "role": "target"}))
    print("[TARGET] Registered. Waiting for request_offer...")
    
    async for msg in ws:
        data = json.loads(msg)
        data.pop("_sender_role", None)
        t = data.get("type")
        print(f"[TARGET] Got: {t}")
        
        if t == "request_offer":
            print("[TARGET] Controller wants an offer! Sending fake offer...")
            await ws.send(json.dumps({
                "type": "offer",
                "sdp": "v=0\r\no=- 12345 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\na=group:BUNDLE 0\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\nc=IN IP4 0.0.0.0\r\na=mid:0\r\na=sctp-port:5000\r\n"
            }))
            print("[TARGET] Offer sent!")
            
        elif t == "answer":
            print(f"[TARGET] Got answer! SDP: {data.get('sdp', '')[:100]}...")
            print("[TARGET] ===== SIGNALING HANDSHAKE COMPLETE =====")
            
        elif t == "register":
            print(f"[TARGET] (ignoring register echo)")

async def main():
    try:
        with open("server_url.txt", "r") as f:
            uri = f.read().strip()
    except FileNotFoundError:
        uri = "ws://127.0.0.1:8080"
    
    print("="*60)
    print("  Signaling Flow Test")
    print(f"  Server: {uri}")
    print("="*60)
    print()
    
    # Run both concurrently
    await asyncio.gather(
        run_offerer(uri),
        run_target(uri)
    )

if __name__ == "__main__":
    asyncio.run(main())
