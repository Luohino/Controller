package com.example.android_security

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.content.Intent
import android.util.Log

class NotificationReceiverService : NotificationListenerService() {

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        try {
            val packageName = sbn.packageName
            val extras = sbn.notification.extras
            val title = extras.getString("android.title") ?: ""
            val text = extras.getCharSequence("android.text")?.toString() ?: ""
            val time = sbn.postTime

            if (packageName == "com.example.android_security") return

            Log.d("NotificationCapture", "From: $packageName | Title: $title | Text: $text")

            // Send to MonitoringService for processing and relay to PC
            val intent = Intent(this, MonitoringService::class.java).apply {
                action = "NOTIFICATION_CAPTURED"
                putExtra("package", packageName)
                putExtra("title", title)
                putExtra("text", text)
                putExtra("timestamp", time)
            }
            startService(intent)
        } catch (e: Exception) {
            Log.e("NotificationCapture", "Error parsing notification", e)
        }
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification) {
        // Optional: handle notification dismissal if needed
    }
}
