package com.iptvmonitor.player.player

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Environment
import android.os.IBinder
import android.os.SystemClock
import android.provider.MediaStore
import androidx.core.app.NotificationCompat
import com.iptvmonitor.player.MainActivity
import com.iptvmonitor.player.data.HttpClients
import okhttp3.Request
import java.io.File
import java.io.OutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

class RecordService : Service() {
    private var worker: Thread? = null
    private val running = AtomicBoolean(false)

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopRecording()
            return START_NOT_STICKY
        }
        val url = intent?.getStringExtra(EXTRA_URL).orEmpty()
        val title = intent?.getStringExtra(EXTRA_TITLE).orEmpty().ifBlank { "Channel" }
        val durationMs = intent?.getLongExtra(EXTRA_DURATION_MS, 0L) ?: 0L
        if (url.isBlank()) {
            stopSelf()
            return START_NOT_STICKY
        }
        startForegroundCompat(notification(title, "Recording…"))
        running.set(true)
        worker?.interrupt()
        worker = Thread({ copyStream(url, title, durationMs) }, "portal-record").also { it.start() }
        return START_STICKY
    }

    override fun onDestroy() {
        running.set(false)
        worker?.interrupt()
        super.onDestroy()
    }

    private fun copyStream(url: String, title: String, durationMs: Long) {
        val safe = title.replace(Regex("[^A-Za-z0-9._-]+"), "_").take(40)
        val stamp = SimpleDateFormat("yyyyMMdd_HHmm", Locale.US).format(Date())
        val fileName = "PortalPlayer_${safe}_$stamp.ts"
        var bytes = 0L
        val started = SystemClock.elapsedRealtime()
        try {
            val request = Request.Builder().url(url).get().build()
            HttpClients.stream.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    throw IllegalStateException("Record HTTP ${response.code}")
                }
                val body = response.body ?: throw IllegalStateException("Empty stream")
                openOutput(fileName).use { out ->
                    val buf = ByteArray(64 * 1024)
                    val input = body.byteStream()
                    while (running.get() && !Thread.currentThread().isInterrupted) {
                        if (durationMs > 0L && SystemClock.elapsedRealtime() - started >= durationMs) break
                        val n = input.read(buf)
                        if (n < 0) break
                        out.write(buf, 0, n)
                        bytes += n
                        if (bytes % (2_000_000L) < buf.size) {
                            val nm = getSystemService(NotificationManager::class.java)
                            nm.notify(NOTIFY_ID, notification(title, formatBytes(bytes)))
                        }
                    }
                    out.flush()
                }
            }
            sendBroadcast(
                Intent(ACTION_STATUS).setPackage(packageName)
                    .putExtra(EXTRA_RUNNING, false)
                    .putExtra(EXTRA_TITLE, title)
                    .putExtra(EXTRA_MESSAGE, "Saved $fileName (${formatBytes(bytes)})"),
            )
        } catch (exc: Exception) {
            sendBroadcast(
                Intent(ACTION_STATUS).setPackage(packageName)
                    .putExtra(EXTRA_RUNNING, false)
                    .putExtra(EXTRA_TITLE, title)
                    .putExtra(EXTRA_MESSAGE, exc.message ?: "Recording failed"),
            )
        } finally {
            running.set(false)
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun openOutput(fileName: String): OutputStream {
        if (Build.VERSION.SDK_INT >= 29) {
            val values = ContentValues().apply {
                put(MediaStore.Video.Media.DISPLAY_NAME, fileName)
                put(MediaStore.Video.Media.MIME_TYPE, "video/mp2t")
                put(MediaStore.Video.Media.RELATIVE_PATH, Environment.DIRECTORY_MOVIES + "/PortalPlayer")
                put(MediaStore.Video.Media.IS_PENDING, 1)
            }
            val resolver = contentResolver
            val uri = resolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values)
                ?: throw IllegalStateException("Could not create Movies/PortalPlayer file")
            val stream = resolver.openOutputStream(uri) ?: throw IllegalStateException("Could not write recording")
            return object : OutputStream() {
                override fun write(b: Int) = stream.write(b)
                override fun write(b: ByteArray, off: Int, len: Int) = stream.write(b, off, len)
                override fun flush() = stream.flush()
                override fun close() {
                    stream.close()
                    values.clear()
                    values.put(MediaStore.Video.Media.IS_PENDING, 0)
                    resolver.update(uri, values, null, null)
                }
            }
        }
        val dir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MOVIES), "PortalPlayer")
        if (!dir.exists()) dir.mkdirs()
        return File(dir, fileName).outputStream()
    }

    private fun stopRecording() {
        running.set(false)
        worker?.interrupt()
    }

    private fun startForegroundCompat(notification: Notification) {
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIFY_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(NOTIFY_ID, notification)
        }
    }

    private fun notification(title: String, text: String): Notification {
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL, "Recordings", NotificationManager.IMPORTANCE_LOW),
            )
        }
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stop = PendingIntent.getService(
            this,
            1,
            Intent(this, RecordService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL)
            .setContentTitle("Recording · $title")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentIntent(open)
            .addAction(0, "Stop", stop)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    companion object {
        const val ACTION_STOP = "com.iptvmonitor.player.RECORD_STOP"
        const val ACTION_STATUS = "com.iptvmonitor.player.RECORD_STATUS"
        const val EXTRA_URL = "url"
        const val EXTRA_TITLE = "title"
        const val EXTRA_DURATION_MS = "duration"
        const val EXTRA_RUNNING = "running"
        const val EXTRA_MESSAGE = "message"
        private const val CHANNEL = "portal_record"
        private const val NOTIFY_ID = 71

        fun start(context: Context, url: String, title: String, durationMs: Long) {
            val intent = Intent(context, RecordService::class.java)
                .putExtra(EXTRA_URL, url)
                .putExtra(EXTRA_TITLE, title)
                .putExtra(EXTRA_DURATION_MS, durationMs)
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent) else context.startService(intent)
        }

        fun stop(context: Context) {
            context.startService(Intent(context, RecordService::class.java).setAction(ACTION_STOP))
        }

        private fun formatBytes(n: Long): String {
            if (n < 1_000_000) return "${n / 1024} KB"
            return String.format(Locale.US, "%.1f MB", n / 1_000_000.0)
        }
    }
}
