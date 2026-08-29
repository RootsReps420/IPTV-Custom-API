package com.iptvmonitor.player.player

import android.app.Activity
import android.os.Build
import android.view.WindowManager
import kotlin.math.abs

object AfrController {
    fun apply(
        activity: Activity,
        frameRate: Float,
        videoWidth: Int,
        videoHeight: Int,
        switchRefresh: Boolean,
        switchResolution: Boolean,
        only5060: Boolean,
    ) {
        if (Build.VERSION.SDK_INT < 23) return
        if (!switchRefresh || frameRate <= 1f) {
            clear(activity)
            return
        }
        val target = targetRate(frameRate)
        if (only5060 && abs(target - 50f) > 1.5f && abs(target - 60f) > 1.5f) return
        val display = activity.windowManager.defaultDisplay
        val modes = display.supportedModes
        if (modes.isEmpty()) {
            val lp = activity.window.attributes
            lp.preferredRefreshRate = target
            activity.window.attributes = lp
            return
        }
        val chosen = modes.minBy { mode: android.view.Display.Mode ->
            val rateScore = abs(mode.refreshRate - target) * 1000f
            val resScore = if (switchResolution && videoWidth > 0 && videoHeight > 0) {
                (abs(mode.physicalWidth - videoWidth) + abs(mode.physicalHeight - videoHeight)).toFloat()
            } else {
                0f
            }
            rateScore + resScore
        }
        val lp = activity.window.attributes
        lp.preferredDisplayModeId = chosen.modeId
        activity.window.attributes = lp
    }

    fun clear(activity: Activity) {
        if (Build.VERSION.SDK_INT < 23) return
        val lp = activity.window.attributes
        lp.preferredDisplayModeId = 0
        lp.preferredRefreshRate = 0f
        activity.window.attributes = lp
        activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    fun targetRate(fps: Float): Float {
        return when {
            abs(fps - 23.976f) < 0.6f || abs(fps - 24f) < 0.6f -> 24f
            abs(fps - 25f) < 0.6f -> 50f
            abs(fps - 29.97f) < 0.6f || abs(fps - 30f) < 0.6f -> 60f
            abs(fps - 50f) < 1.2f -> 50f
            abs(fps - 59.94f) < 0.6f || abs(fps - 60f) < 1.2f -> 60f
            else -> fps
        }
    }
}
