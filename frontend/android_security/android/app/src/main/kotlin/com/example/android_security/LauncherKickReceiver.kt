package com.example.android_security

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class LauncherKickReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context?, intent: Intent?) {
        // Dummy receiver - toggling its state forces many Android launchers 
        // to re-scan the manifest and update their icon visibility.
    }
}
