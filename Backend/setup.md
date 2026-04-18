# Backend Deployment Guide

Deploy the signaling relay server on Render (free tier).

---

## Prerequisites

- A GitHub account
- A [Render](https://render.com/) account (free tier works)

---

## Step 1: Push to GitHub

1. Create a new repository on GitHub (public or private).
2. Push the contents of the `Backend/` folder to the root of the repository:

```
signaling_server.py
requirements.txt
```

Make sure `requirements.txt` contains:

```
aiohttp
```

---

## Step 2: Deploy on Render

1. Go to [https://dashboard.render.com/](https://dashboard.render.com/).
2. Click **New +** and select **Web Service**.
3. Connect your GitHub account and select the repository you created.
4. Configure the service:

| Setting          | Value                          |
|------------------|--------------------------------|
| Name             | Choose any name (e.g. `my-relay`) |
| Region           | Pick the closest to your location |
| Runtime          | **Python 3**                   |
| Build Command    | `pip install -r requirements.txt` |
| Start Command    | `python signaling_server.py`   |
| Instance Type    | **Free**                       |

5. Click **Deploy Web Service**.

---

## Step 3: Get Your WebSocket URL

Once deployed, Render assigns a public URL like:

```
https://my-relay.onrender.com
```

Your WebSocket URL is:

```
wss://my-relay.onrender.com/ws
```

---

## Step 4: Configure the Project

Update the WebSocket URL in three locations:

### 1. PC Controller
Edit `Monitoring/server_url.txt`:
```
wss://my-relay.onrender.com/ws
```

### 2. Android Agent (Dart)
Edit `frontend/android_security/lib/server_url.dart`:
```dart
const String SERVER_URL = "wss://my-relay.onrender.com/ws";
```

### 3. Android Agent (Kotlin Native Service)
Edit `frontend/android_security/android/app/src/main/kotlin/com/example/android_security/MonitoringService.kt`:
```kotlin
const val SERVER_URL = "wss://my-relay.onrender.com/ws"
```

After updating, rebuild the Android APK:
```bash
cd frontend/android_security/
flutter build apk --release
```

---

## Verifying the Server

Visit `https://my-relay.onrender.com/health` in your browser. If the server is running, it returns `OK`.

You can also test the WebSocket connection:
```bash
python Monitoring/test_handshake.py
```

---

## Notes

- Render free tier services spin down after 15 minutes of inactivity. The first connection after idle may take 30-60 seconds.
- For production use, upgrade to a paid Render instance to eliminate cold starts.
- The server is stateless. No data is stored. It only relays messages between connected clients.
