package com.mikeyphw.xdm.android.engine

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import com.mikeyphw.xdm.android.R
import com.mikeyphw.xdm.android.XdmApplication
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * MP09 foreground recording host; one Go process authority, no second network
 * downloader, no stored authorization headers or arbitrary FFmpeg command.
 * All user controls are explicit, internal intents. The Go engine independently
 * owns every durable fragment and the MP08 published-byte verification gate.
 *
 * Android may impose OS-level dataSync FGS time budgets. Those are surfaced as
 * recovery-required, NEVER fabricated as Stop & Save or a completed file.
 */
class AndroidLiveRecordingService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var poller: Job? = null
    private val stopping = AtomicBoolean(false)
    private var captureId: String? = null
    private var destinationKey: String? = null
    private var paused = false
    private val authority: AndroidEngineProcessAuthority
        get() = (application as XdmApplication).androidEngineProcessAuthority

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "Live media recording", NotificationManager.IMPORTANCE_LOW))
        // Android 10+ type is explicitly declared and never faked as playback.
        val notice = notification("Recording session initializing", false)
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION_ID, notice, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(NOTIFICATION_ID, notice)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // No automatic resurrection of a signed URL after process death.
        if (intent == null) {
            update("Recording interrupted — reopen capture to recover", true)
            stopSelf()
            return START_NOT_STICKY
        }
        when (intent.action) {
            START -> {
                if (poller != null || stopping.get()) return START_NOT_STICKY
                val capture = intent.getStringExtra(CAPTURE).orEmpty()
                if (!ID.matches(capture)) { update("Invalid recording request", true); stopSelf();return START_NOT_STICKY }
                val target = intent.getStringExtra(DESTINATION).orEmpty()
                if (!ID.matches(target)) { update("Invalid recording destination", true); stopSelf(); return START_NOT_STICKY }
                captureId = capture
                destinationKey = target
                val payload = JSONObject()
                    .put("capture_id", capture)
                    .put("action", "start")
                    .put("protocol", intent.getStringExtra(PROTOCOL).orEmpty())
                    .put("video_url", intent.getStringExtra(VIDEO).orEmpty())
                    .put("audio_url", intent.getStringExtra(AUDIO).orEmpty())
                    .put("video_representation_id", intent.getStringExtra(VIDEO_REP).orEmpty())
                    .put("audio_representation_id", intent.getStringExtra(AUDIO_REP).orEmpty())
                    .put("require_audio", intent.getBooleanExtra(REQUIRE_AUDIO, false))
                    .put("dvr_capable", intent.getBooleanExtra(DVR, false))
                    .put("user_limit_ms", intent.getLongExtra(USER_LIMIT_MS, 0L))
                    .put("user_limit_bytes", intent.getLongExtra(USER_LIMIT_BYTES, 0L))
                poller = scope.launch { runRecording(payload) }
            }
            STOP_SAVE, PAUSE, RESUME, CANCEL_DISCARD -> {
                val id = captureId ?: return START_NOT_STICKY
                if (intent.getStringExtra(CAPTURE) != id) return START_NOT_STICKY
                when (intent.action) {
                    STOP_SAVE, CANCEL_DISCARD -> {
                        if (!stopping.compareAndSet(false,true)) return START_NOT_STICKY
                        poller?.cancel()
                        poller = null
                    }
                }
                scope.launch {
                    val action = when (intent.action) {
                        STOP_SAVE -> "stop_save"
                        CANCEL_DISCARD -> "cancel_discard"
                        PAUSE -> "pause"
                        else -> "resume"
                    }
                    val body = JSONObject().put("action", action).put("capture_id", id)
                    if (action == "stop_save") body.put("destination_key", destinationKey.orEmpty())
                    val result = authority.submitMediaUiCommand("android.media.live", body)
                    if (result.ok && result.status == "completed") {
                        update("Recording verified and saved", false)
                        stopSelf()
                    } else if (result.ok && action == "cancel_discard") {
                        update("Recording discarded", false)
                        stopSelf()
                    } else if (result.ok && action == "resume") {
                        stopping.set(false)
                        paused = false
                        poller = scope.launch { pollLoop(id) }
                        update("Recording resumed", false)
                    } else if (result.ok && action == "pause") {
                        poller?.cancel()
                        poller = null
                        paused = true
                        update("Recording paused", false)
                    } else {
                        // A failed Stop & Save must remain retryable, or the user
                        // must be able to explicitly discard after inspecting it.
                        stopping.set(false)
                        update("Recording requires review — retry Save or discard", true)
                    }
                }
            }
            else -> update("Unknown recording action refused", true)
        }
        return START_NOT_STICKY
    }

    private suspend fun runRecording(request: JSONObject) {
        val result = authority.submitMediaUiCommand("android.media.live", request)
        if (!result.ok) {
            update("Recording could not start — check authorization", true)
            poller = null
            return
        }
        if (result.allTracksEnded || result.status == "stop_pending_verification") {
            update("Source ended — choose Stop & Save", false)
            poller = null
            return
        }
        update("Recording live media", false)
        pollLoop(request.getString("capture_id"))
    }

    private suspend fun pollLoop(id: String) {
        while (scope.coroutineContext.isActive && !stopping.get()) {
            val result = authority.submitMediaUiCommand("android.media.live",
                JSONObject().put("capture_id", id).put("action", "poll"))
            if (!result.ok) {
                update("Recording interrupted — partial media may need recovery", true)
                poller = null
                return
            }
            if (result.status == "paused" || result.status == "stop_pending_verification" || result.allTracksEnded) {
                update(if (result.status == "paused") "Recording paused" else "Stop & Save required", false)
                poller = null
                return
            }
            delay(result.nextPollAfterMs.coerceIn(500L,30_000L))
        }
    }

    private fun update(message: String, review: Boolean) {
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification(message, review))
    }
    private fun actionPendingIntent(actionName: String, requestCode: Int): PendingIntent? {
        val id = captureId ?: return null
        val request = Intent(this, AndroidLiveRecordingService::class.java).apply {
            action = actionName
            putExtra(CAPTURE, id)
            if (actionName == STOP_SAVE) putExtra(DESTINATION, destinationKey.orEmpty())
        }
        return PendingIntent.getService(this, requestCode, request,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    private fun notification(message: String, review: Boolean): Notification {
        val text = if (review) "$message — recording is not marked complete" else message
        val builder = Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("XDM live recording")
            .setContentText(text)
            .setOngoing(!review)
            .setOnlyAlertOnce(true)
            .setCategory(Notification.CATEGORY_PROGRESS)
        actionPendingIntent(STOP_SAVE, 101)?.let {
            builder.addAction(Notification.Action.Builder(null, "Stop & Save", it).build())
        }
        actionPendingIntent(if (paused) RESUME else PAUSE, 102)?.let {
            builder.addAction(Notification.Action.Builder(null, if (paused) "Resume" else "Pause (DVR)", it).build())
        }
        actionPendingIntent(CANCEL_DISCARD, 103)?.let {
            builder.addAction(Notification.Action.Builder(null, "Discard", it).build())
        }
        return builder.build()
    }

    // Android 15+ limits dataSync foreground-service time even when the user
    // did not set a recording duration. This is a platform interruption,
    // NEVER consent for Stop & Save or a playable-complete receipt.
    override fun onTimeout(startId: Int, fgsType: Int) {
        update("Android interrupted recording — partial media needs recovery", true)
        stopping.set(true)
        poller?.cancel()
        stopSelf(startId)
    }

    override fun onDestroy() {
        poller?.cancel()
        scope.cancel()
        super.onDestroy()
        // Important: never erase durable fragments or fake an automatic Stop.
    }

    companion object {
        const val START = "com.mikeyphw.xdm.android.LIVE_START"
        const val STOP_SAVE = "com.mikeyphw.xdm.android.LIVE_STOP_SAVE"
        const val PAUSE = "com.mikeyphw.xdm.android.LIVE_PAUSE"
        const val RESUME = "com.mikeyphw.xdm.android.LIVE_RESUME"
        const val CANCEL_DISCARD = "com.mikeyphw.xdm.android.LIVE_CANCEL_DISCARD"
        const val CAPTURE = "capture_id"
        const val PROTOCOL = "protocol"
        const val VIDEO = "video_url"
        const val AUDIO = "audio_url"
        const val VIDEO_REP = "video_representation_id"
        const val AUDIO_REP = "audio_representation_id"
        const val REQUIRE_AUDIO = "require_audio"
        const val DVR = "dvr_capable"
        const val USER_LIMIT_MS = "user_limit_ms"
        const val USER_LIMIT_BYTES = "user_limit_bytes"
        const val DESTINATION = "destination_key"
        private const val CHANNEL = "xdm-mp09-live"
        private const val NOTIFICATION_ID = 49109
        private val ID = Regex("^[A-Za-z0-9_-]{1,96}$")

        /** App-internal, user-initiated only: call after showing explicit selection. */
        fun start(context: Context, selection: Intent) {
            require(selection.action == START)
            selection.setClass(context, AndroidLiveRecordingService::class.java)
            context.startForegroundService(selection)
        }
    }
}
