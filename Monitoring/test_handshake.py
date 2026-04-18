"""
Standalone WebRTC Handshake Test Script
Tests the signaling flow and prints every step.
"""
import asyncio
import json
import websockets
from aiortc import RTCPeerConnection, RTCSessionDescription

async def test_handshake():
    # Read server URL
    try:
        with open("server_url.txt", "r") as f:
            uri = f.read().strip()
    except FileNotFoundError:
        uri = "ws://127.0.0.1:8080"
    
    print(f"[1] Connecting to signaling server: {uri}")
    
    try:
        ws = await websockets.connect(uri)
        print("[2] Connected! Registering as 'controller'...")
        await ws.send(json.dumps({"type": "register", "role": "controller"}))
    except Exception as e:
        print(f"[FAIL] Cannot connect to signaling server: {e}")
        print("       Make sure signaling_server.py is running!")
        return
    
    # Send request_offer to tell Flutter to create the offer
    print("[3] Sending 'request_offer' to Flutter device...")
    await ws.send(json.dumps({"type": "request_offer"}))
    print("[4] Waiting for Flutter's offer (the device must be running the app)...")
    
    pc = None
    offer_received = False
    
    async for message in ws:
        data = json.loads(message)
        data.pop("_sender_role", None)
        msg_type = data.get("type")
        
        print(f"\n[MSG] Received: type={msg_type}")
        
        if msg_type == "heartbeat":
            print(f"       Device: {data.get('device_id', 'unknown')}")
            continue
        
        if msg_type == "offer":
            offer_received = True
            sdp = data["sdp"]
            print(f"[5] OFFER RECEIVED! SDP length: {len(sdp)} chars")
            print(f"    First 200 chars of SDP:")
            print(f"    {sdp[:200]}")
            print()
            
            # Create peer connection as answerer
            print("[6] Creating RTCPeerConnection (answerer)...")
            pc = RTCPeerConnection()
            
            pc.on("datachannel", lambda ch: print(f"[DC] Data Channel received: {ch.label}"))
            pc.on("track", lambda t: print(f"[TRACK] Received track: {t.kind}"))
            pc.on("icecandidate", lambda c: asyncio.create_task(
                ws.send(json.dumps({
                    "type": "candidate",
                    "candidate": "candidate:" + c.to_sdp(),
                    "sdpMid": c.sdpMid, 
                    "sdpMLineIndex": c.sdpMLineIndex
                }))
            ) if getattr(c, 'sdpMid', None) is not None else None)
            
            print("[7] Setting remote description (Flutter's offer)...")
            try:
                await pc.setRemoteDescription(RTCSessionDescription(sdp, 'offer'))
                print("[7] SUCCESS! Remote description set.")
            except Exception as e:
                print(f"[7] FAILED: {e}")
                break
            
            print("[8] Creating answer...")
            try:
                answer = await pc.createAnswer()
                print(f"[8] SUCCESS! Answer SDP length: {len(answer.sdp)} chars")
            except Exception as e:
                print(f"[8] FAILED: {e}")
                break
            
            print("[9] Setting local description...")
            try:
                await pc.setLocalDescription(answer)
                print("[9] SUCCESS!")
            except Exception as e:
                print(f"[9] FAILED: {e}")
                break
            
            print("[10] Sending answer back to Flutter...")
            await ws.send(json.dumps({
                "type": "answer",
                "sdp": pc.localDescription.sdp
            }))
            print("[10] Answer sent! Waiting for data channel / candidates...")
            continue
        
        if msg_type == "candidate":
            c_str = data.get("candidate", "")
            print(f"       Candidate: {c_str[:80]}...")
            if pc and c_str:
                try:
                    from aiortc.sdp import candidate_from_sdp
                    raw = c_str[10:] if c_str.startswith("candidate:") else c_str
                    if raw.strip():
                        candidate = candidate_from_sdp(raw)
                        candidate.sdpMid = data["sdpMid"]
                        candidate.sdpMLineIndex = data["sdpMLineIndex"]
                        await pc.addIceCandidate(candidate)
                        print(f"       ICE candidate added OK")
                    else:
                        print(f"       Empty candidate, skipping")
                except Exception as e:
                    print(f"       ICE candidate ERROR: {e}")
            continue
    
    if not offer_received:
        print("\n[TIMEOUT] Never received an offer from Flutter.")
        print("          Make sure the Flutter app is running on the Android device.")
    
    if pc:
        await pc.close()

if __name__ == "__main__":
    print("=" * 60)
    print("  WebRTC Handshake Test Script")
    print("=" * 60)
    asyncio.run(test_handshake())
