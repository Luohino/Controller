# PC Controller Setup

Install and run the desktop monitoring controller on Windows.

---

## Prerequisites

- Python 3.10 or newer
- Windows 10/11
- A deployed signaling server (see `Backend/setup.md`)

---

## Step 1: Install Python

If Python is not installed, download it from [python.org](https://www.python.org/downloads/).

During installation, check **"Add Python to PATH"**.

Verify installation:
```powershell
python --version
```

---

## Step 2: Install Dependencies

Open a terminal in the `Monitoring/` directory and run:

```powershell
pip install -r requirements.txt
```

This installs:
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

If `pyaudio` fails to install, use the prebuilt wheel:
```powershell
pip install pipwin
pipwin install pyaudio
```

---

## Step 3: Configure the Server URL

Edit `Monitoring/server_url.txt` and replace the placeholder with your deployed Render URL:

```
wss://YOUR_RENDER_APP_NAME.onrender.com/ws
```

---

## Step 4: Configure Firebase (Optional)

The controller uses Firebase Firestore to store historical device registrations. This is optional but recommended for persistent device tracking across restarts.

1. Go to [Firebase Console](https://console.firebase.google.com/).
2. Create a new project.
3. Enable **Firestore Database** in test mode.
4. Copy your project ID (e.g., `my-project-12345`).
5. Open `Monitoring/main.py` and replace the placeholder:

```python
self.project_id = "my-project-12345"
```

---

## Step 5: Run the Controller

```powershell
python main.py
```

Or use the launcher script:
```powershell
.\start_controller.bat
```

The controller will:
1. Connect to the signaling server
2. Wait for the Android agent to come online
3. Display the device in the "Select Target Device" screen

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: No module named 'customtkinter'` | Run `pip install customtkinter` |
| `PyAudio installation fails` | Use `pip install pipwin && pipwin install pyaudio` |
| Controller shows "OFFLINE" | Check that `server_url.txt` has the correct WSS URL |
| No devices appear | Ensure the Android agent is installed, running, and connected to the internet |
