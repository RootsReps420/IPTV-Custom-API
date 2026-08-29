package com.iptvmonitor.player

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.iptvmonitor.player.data.AppSettings

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val settings = AppSettings(context)
        val action = intent.action
        val boot = action == Intent.ACTION_BOOT_COMPLETED && settings.autoStartBoot
        val wake = (action == Intent.ACTION_USER_PRESENT || action == Intent.ACTION_SCREEN_ON) &&
            settings.autoStartWake
        if (!boot && !wake) return
        val launch = Intent(context, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        }
        context.startActivity(launch)
    }
}
