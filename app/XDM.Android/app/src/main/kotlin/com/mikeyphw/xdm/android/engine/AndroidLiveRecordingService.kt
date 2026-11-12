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
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
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
    @Volatile private var poller: Job? = null
    @Volatile private var captureId: String? = null
    @Volatile private var destinationKey: String? = null
    @Volatile private var dvrVerified = false
    private val lifecycle = AndroidMP09RecordingLifecycleState()
    private val commandMutex = Mutex()
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
        // Android must not resurrect expired URLs or implicitly publish after
        // process death. The user must reopen the capture and reauthorize.
        if (intent == null) {
            reportTerminalFailure("Recording interrupted — review stored fragments")
            return START_NOT_STICKY
        }
        when (intent.action) {
            START -> {
                val capture = intent.getStringExtra(CAPTURE).orEmpty()
                val target = intent.getStringExtra(DESTINATION).orEmpty()
                if (!ID.matches(capture) || !ID.matches(target)) {
                    if (lifecycle.phase() == AndroidMP09RecordingLifecycleState.Phase.New)
                        reportTerminalFailure("Invalid recording selection")
                    else update("Invalid second recording selection refused", true)
                    return START_NOT_STICKY
                }
                if (!lifecycle.beginStart()) {
                    update("Recording already started or requires review", true)
                    return START_NOT_STICKY
                }
                captureId = capture
                destinationKey = target
                dvrVerified = intent.getBooleanExtra(DVR, false)
                val payload = JSONObject()
                    .put("capture_id", capture)
                    .put("action", if (intent.getBooleanExtra(RECOVER_INTERRUPTED, false))
                        "resume_interrupted" else "start")
                    .put("video_option_id", intent.getStringExtra(VIDEO_OPTION).orEmpty())
                    .put("audio_option_id", intent.getStringExtra(AUDIO_OPTION).orEmpty())
                    .put("expected_revision", intent.getStringExtra(EXPECTED_REVISION).orEmpty())
                    .put("protocol", intent.getStringExtra(PROTOCOL).orEmpty())
                    .put("video_url", intent.getStringExtra(VIDEO).orEmpty())
                    .put("audio_url", intent.getStringExtra(AUDIO).orEmpty())
                    .put("video_representation_id", intent.getStringExtra(VIDEO_REP).orEmpty())
                    .put("audio_representation_id", intent.getStringExtra(AUDIO_REP).orEmpty())
                    .put("require_audio", intent.getBooleanExtra(REQUIRE_AUDIO, false))
                    .put("dvr_capable", dvrVerified)
                    .put("user_limit_ms", intent.getLongExtra(USER_LIMIT_MS, 0L))
                    .put("user_limit_bytes", intent.getLongExtra(USER_LIMIT_BYTES, 0L))
                update("Starting verified recording…", false)
                poller = scope.launch { runRecording(payload) }
            }
            STOP_SAVE, PAUSE, RESUME, CANCEL_DISCARD -> {
                val id = captureId
                if (id == null) {
                    // No automatic resurrection after process death.
                    reportTerminalFailure("Recording controls expired — reopen capture for review")
                    return START_NOT_STICKY
                }
                if (intent.getStringExtra(CAPTURE) != id) {
                    // A stale notification MUST NOT stop a newer active service.
                    update("Stale recording control refused", true)
                    return START_NOT_STICKY
                }
                val control = when (intent.action) {
                    STOP_SAVE -> AndroidMP09RecordingLifecycleState.Control.StopSave
                    CANCEL_DISCARD -> AndroidMP09RecordingLifecycleState.Control.Discard
                    PAUSE -> AndroidMP09RecordingLifecycleState.Control.Pause
                    else -> AndroidMP09RecordingLifecycleState.Control.Resume
                }
                if (!lifecycle.begin(control, dvrVerified)) {
                    update("Recording action unavailable or already in progress", true)
                    return START_NOT_STICKY
                }
                if (control != AndroidMP09RecordingLifecycleState.Control.Resume) {
                    poller?.cancel()
                    poller = null
                }
                update("Processing ${control.name}…", false)
                scope.launch { runControl(id, control) }
            }
            else -> update("Unknown recording action refused", true)
        }
        return START_NOT_STICKY
    }

    private suspend fun runControl(id: String, control: AndroidMP09RecordingLifecycleState.Control) {
        val action = when (control) {
            AndroidMP09RecordingLifecycleState.Control.StopSave -> "stop_save"
            AndroidMP09RecordingLifecycleState.Control.Discard -> "cancel_discard"
            AndroidMP09RecordingLifecycleState.Control.Pause -> "pause"
            AndroidMP09RecordingLifecycleState.Control.Resume -> "resume"
        }
        val body = JSONObject().put("action", action).put("capture_id", id)
        if (action == "stop_save") body.put("destination_key", destinationKey.orEmpty())
        val result = try {
            commandMutex.withLock { authority.submitMediaUiCommand("android.media.live", body) }
        } catch (cancelled: kotlinx.coroutines.CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            null
        }
        val accepted = when (control) {
            AndroidMP09RecordingLifecycleState.Control.StopSave -> result?.ok == true && result.status == "completed"
            AndroidMP09RecordingLifecycleState.Control.Discard -> result?.ok == true && result.status == "cancel_pending_cleanup"
            AndroidMP09RecordingLifecycleState.Control.Pause -> result?.ok == true && result.status == "paused"
            AndroidMP09RecordingLifecycleState.Control.Resume -> result?.ok == true && result.status == "capturing"
        }
        val phase = lifecycle.complete(control, accepted)
        when (phase) {
            AndroidMP09RecordingLifecycleState.Phase.Saved -> {
                if (result != null && result.cleanupPending)
                    update("Recording saved — fragment cleanup requires review", true)
                else update("Recording verified and saved", false)
                stopSelf()
            }
            AndroidMP09RecordingLifecycleState.Phase.Discarded -> {
                update("Recording discarded after verified cleanup", false)
                stopSelf()
            }
            AndroidMP09RecordingLifecycleState.Phase.Paused -> {
                update(if (accepted) "Recording paused" else "Resume failed — try again", !accepted)
            }
            AndroidMP09RecordingLifecycleState.Phase.Recording -> {
                update(if (accepted) "Recording resumed" else "Pause failed — recording continues", !accepted)
                if (poller == null) poller = scope.launch { pollLoop(id) }
            }
            AndroidMP09RecordingLifecycleState.Phase.Review -> {
                update("Save or discard not verified — retry or review fragments", true)
            }
            else -> update("Recording action requires review", true)
        }
    }

    private suspend fun runRecording(request: JSONObject) {
        val id = request.getString("capture_id")
        val result = try {
            commandMutex.withLock { authority.submitMediaUiCommand("android.media.live", request) }
        } catch (cancelled: kotlinx.coroutines.CancellationException) {
            throw cancelled
        } catch (_: Exception) { null }
        if (result?.ok != true) {
            lifecycle.startFailed()
            reportTerminalFailure("Recording could not start — reauthorize the media source")
            return
        }
        if (!lifecycle.started()) return
        if (result.allTracksEnded || result.status == "stop_pending_verification") {
            lifecycle.interrupted()
            update("Source ended — choose Stop & Save", false)
            return
        }
        update("Recording live media", false)
        pollLoop(id)
    }

    private suspend fun pollLoop(id: String) {
        while (kotlinx.coroutines.currentCoroutineContext().isActive && lifecycle.canPoll()) {
            val result = try {
                commandMutex.withLock {
                    authority.submitMediaUiCommand("android.media.live",
                        JSONObject().put("capture_id", id).put("action", "poll"))
                }
            } catch (cancelled: kotlinx.coroutines.CancellationException) {
                throw cancelled
            } catch (_: Exception) { null }
            if (!lifecycle.canPoll()) return
            if (result?.ok != true) {
                lifecycle.interrupted()
                update("Recording interrupted — review fragments or retry Stop & Save", true)
                return
            }
            if (result.status == "paused" || result.status == "stop_pending_verification" || result.allTracksEnded) {
                lifecycle.interrupted()
                update(if (result.status == "paused") "Recording paused outside this service — review" else "Stop & Save required", true)
                return
            }
            delay(result.nextPollAfterMs.coerceIn(500L, 30_000L))
        }
    }

    private fun reportTerminalFailure(message: String) {
        // A failed start must never leave an idle dataSync foreground service
        // running indefinitely. Try a separate non-ongoing error notification;
        // POST_NOTIFICATIONS may be denied, so this is best effort only.
        runCatching {
            val notice = Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle("XDM recording requires attention")
                .setContentText(message)
                .setOngoing(false)
                .setOnlyAlertOnce(true)
                .build()
            getSystemService(NotificationManager::class.java).notify(FAILURE_NOTIFICATION_ID, notice)
        }
        stopSelf()
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
        val actions = lifecycle.available(dvrVerified)
        if (AndroidMP09RecordingLifecycleState.Control.StopSave in actions)
            actionPendingIntent(STOP_SAVE, 101)?.let {
                builder.addAction(Notification.Action.Builder(null, "Stop & Save", it).build())
            }
        if (AndroidMP09RecordingLifecycleState.Control.Pause in actions)
            actionPendingIntent(PAUSE, 102)?.let {
                builder.addAction(Notification.Action.Builder(null, "Pause (DVR)", it).build())
            }
        if (AndroidMP09RecordingLifecycleState.Control.Resume in actions)
            actionPendingIntent(RESUME, 102)?.let {
                builder.addAction(Notification.Action.Builder(null, "Resume", it).build())
            }
        if (AndroidMP09RecordingLifecycleState.Control.Discard in actions)
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
        lifecycle.interrupted()
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
        const val RECOVER_INTERRUPTED = "recover_interrupted"
        const val VIDEO_OPTION = "video_option_id"
        const val AUDIO_OPTION = "audio_option_id"
        const val EXPECTED_REVISION = "expected_revision"
        private const val CHANNEL = "xdm-mp09-live"
        private const val NOTIFICATION_ID = 49109
        private const val FAILURE_NOTIFICATION_ID = 49110
        private val ID = Regex("^[A-Za-z0-9_-]{1,96}$")

        /** App-internal, user-initiated only: call after showing explicit selection. */
        fun start(context: Context, selection: Intent) {
            require(selection.action == START)
            selection.setClass(context, AndroidLiveRecordingService::class.java)
            context.startForegroundService(selection)
        }
    }
}
