package com.mikeyphw.xdm.android

import android.app.Application
import android.content.Context
import androidx.test.runner.AndroidJUnitRunner
import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTextReplacement
import com.mikeyphw.xdm.android.engine.MP11LiveLibraryReview
import com.mikeyphw.xdm.android.engine.MP11VerifiedLiveRecording
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Execute only against a real Android Compose host. No mock engine, MediaStore
 * publication, credential mutation, or destructive device action is performed.
 * Tests exercise exactly the production UI composables invoked by Media/Library.
 */
class MP11P04LiveRecordingUiInstrumentedTest {
    @get:Rule val composeRule = createComposeRule()

    @Test fun recordingActionsRespectDvrAndUnknownState() {
        val calls = mutableListOf<String>()
        val state = mutableStateOf("capturing")
        val dvr = mutableStateOf(false)
        composeRule.setContent {
            XdmTheme {
                MP11P04RecordingControls(state.value, 3, false, dvr.value) { calls.add(it) }
            }
        }
        composeRule.onNodeWithTag(MP11P04Tags.Controls).assertExists()
        composeRule.onNodeWithTag(MP11P04Tags.Stop).assertExists().performClick()
        composeRule.onNodeWithTag(MP11P04Tags.Discard).assertExists()
        composeRule.onNodeWithTag(MP11P04Tags.Pause).assertDoesNotExist()
        composeRule.runOnIdle { assertEquals(listOf("stop_save"), calls); dvr.value = true }
        composeRule.onNodeWithTag(MP11P04Tags.Pause).assertExists().performClick()
        composeRule.runOnIdle { state.value = "paused" }
        composeRule.onNodeWithTag(MP11P04Tags.Resume).assertExists().performClick()
        composeRule.onNodeWithTag(MP11P04Tags.Pause).assertDoesNotExist()
        composeRule.runOnIdle { state.value = "unexpected:https://secret.example/?token=PRIVATE" }
        listOf(MP11P04Tags.Stop, MP11P04Tags.Pause, MP11P04Tags.Resume,
            MP11P04Tags.Discard, MP11P04Tags.Refresh).forEach {
            composeRule.onNodeWithTag(it).assertDoesNotExist()
        }
        composeRule.runOnIdle { assertEquals(listOf("stop_save", "pause", "resume"), calls) }
    }

    @Test fun refreshNeedsAllThreeSameOriginUrlsAndExplicitApprove() {
        val approved = mutableStateOf(0)
        composeRule.setContent {
            var root by remember { mutableStateOf("") }
            var video by remember { mutableStateOf("") }
            var audio by remember { mutableStateOf("") }
            XdmTheme {
                MP11P04RefreshDialog(root, video, audio,
                    onRoot = { root = it }, onVideo = { video = it }, onAudio = { audio = it },
                    onApprove = { approved.value++ }, onDismiss = {})
            }
        }
        val confirm = composeRule.onNodeWithTag(MP11P04Tags.ConfirmRefresh)
        confirm.assertIsNotEnabled()
        composeRule.onNodeWithTag(MP11P04Tags.Root).performScrollTo()
            .performTextInput("https://media.example/live.m3u8?sig=one")
        composeRule.onNodeWithTag(MP11P04Tags.Video).performScrollTo()
            .performTextInput("https://media.example/video.m3u8?sig=two")
        composeRule.onNodeWithTag(MP11P04Tags.Audio).performScrollTo()
            .performTextInput("https://other.example/audio.m3u8")
        confirm.assertIsNotEnabled()
        composeRule.onNodeWithTag(MP11P04Tags.Audio).performScrollTo()
            .performTextReplacement("https://media.example/audio.m3u8?sig=three")
        confirm.assertIsEnabled().performClick()
        composeRule.runOnIdle { assertEquals(1, approved.value) }
    }

    @Test fun destructiveDiscardNeedsSeparateConfirmationAndSupportsKeep() {
        val discards = mutableStateOf(0)
        composeRule.setContent {
            var confirm by remember { mutableStateOf(false) }
            XdmTheme {
                Column {
                    MP11P04RecordingControls("capturing", 2, true, false) { action ->
                        if (action == "discard") confirm = true
                    }
                    if (confirm) MP11P04DiscardDialog(
                        onConfirm = { discards.value++; confirm = false },
                        onKeep = { confirm = false },
                    )
                }
            }
        }
        composeRule.onNodeWithTag(MP11P04Tags.ConfirmDiscard).assertDoesNotExist()
        composeRule.onNodeWithTag(MP11P04Tags.Discard).performClick()
        composeRule.onNodeWithTag(MP11P04Tags.ConfirmDiscard).assertExists()
        composeRule.onNodeWithTag(MP11P04Tags.DiscardDialog).assertExists()
        composeRule.onNodeWithTag(MP11P04Tags.ConfirmDiscard).performClick()
        composeRule.runOnIdle { assertEquals(1, discards.value) }
    }

    @Test fun publishingRecoveryNeverOffersResumeOrDestructiveDiscard() {
        val state = mutableStateOf("publication_pending_review")
        val actions = mutableListOf<String>()
        composeRule.setContent {
            XdmTheme {
                MP11P04RecoveryDialog(state.value, 2,
                    onDiscard = { actions.add("discard") },
                    onResume = { actions.add("resume") },
                    onKeep = { actions.add("keep") })
            }
        }
        composeRule.onNodeWithTag(MP11P04Tags.RecoveryResume).assertDoesNotExist()
        composeRule.onNodeWithTag(MP11P04Tags.RecoveryDiscard).assertDoesNotExist()
        composeRule.runOnIdle { state.value = "recovery_review_required" }
        // HF01: prove the exact user-facing MP09 action survived extraction.
        composeRule.onNodeWithText("Reauthorize & resume").assertExists()
        composeRule.onNodeWithTag(MP11P04Tags.RecoveryResume).assertExists().performClick()
        composeRule.runOnIdle { assertEquals(listOf("resume"), actions) }
    }

    @Test fun onlyVerifiedLiveTileExposesOpenAndDetails() {
        val opens = mutableStateOf(0)
        val details = mutableStateOf(0)
        composeRule.setContent {
            XdmTheme {
                Column {
                    MP11P04VerifiedLiveTile(
                        MP11VerifiedLiveRecording("capture", "Live video", "pub1",
                            "content://media/external/downloads/5", 8192L, "video.mp4", true, 0L),
                        onOpen = { opens.value++ }, onDetails = { details.value++ },
                    )
                    MP11P04ReviewOnlyRow(MP11LiveLibraryReview("capture2", "Interrupted recording",
                        "Publication verification is pending"))
                }
            }
        }
        composeRule.onNodeWithTag(MP11P04Tags.VerifiedTile).assertExists()
        composeRule.onNodeWithTag(MP11P04Tags.ReviewOnly).assertExists()
        composeRule.onNodeWithTag(MP11P04Tags.OpenVerified).assertExists().performClick()
        composeRule.onNodeWithTag(MP11P04Tags.Details).assertExists().performClick()
        composeRule.runOnIdle { assertEquals(1, opens.value); assertEquals(1, details.value) }
    }
}

/**
 * MP11 P04 Compose-only host. Activated ONLY through the explicit Gradle property
 * xdm.mp11P04UiIsolatedHost=true. No Go engine, Room, JNI or media service is
 * started by this isolated test process. Production and all other Android tests
 * retain the real XdmApplication. This is UI evidence, never engine qualification.
 */
class MP11P04IsolatedComposeRunner : AndroidJUnitRunner() {
    override fun newApplication(cl: ClassLoader, className: String, context: Context): Application {
        require(className == XdmApplication::class.java.name) {
            "MP11_P04_UNEXPECTED_APPLICATION_CLASS"
        }
        return super.newApplication(cl, Application::class.java.name, context)
    }
}
