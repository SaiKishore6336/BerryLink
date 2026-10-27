package app.berrylink.companion.ui

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.pm.ActivityInfo
import android.view.View
import android.view.WindowManager
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner

/**
 * While paired, the phone is a face-only landscape display: immersive system
 * bars, screen kept awake, and sensor landscape so either way the phone is
 * turned still works. The rest of the app (pairing, settings, typed questions)
 * remains portrait.
 */
@Composable
fun CompanionWindowMode(faceMode: Boolean) {
    val activity = LocalContext.current.findActivity()
    val view = LocalView.current
    val lifecycleOwner = LocalLifecycleOwner.current

    LaunchedEffect(activity, faceMode) {
        val host = activity ?: return@LaunchedEffect
        if (faceMode) {
            applyFaceWindow(host, view)
        } else {
            host.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
            host.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            WindowCompat.getInsetsController(host.window, view)
                .show(WindowInsetsCompat.Type.systemBars())
        }
    }

    // Immersive flags can be dropped while a permission dialog, the IME or
    // another app has focus. Re-apply them whenever the face is resumed.
    DisposableEffect(lifecycleOwner, activity, faceMode, view) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME && faceMode) {
                activity?.let { applyFaceWindow(it, view) }
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
}

private fun applyFaceWindow(host: Activity, view: View) {
    host.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
    host.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    WindowCompat.getInsetsController(host.window, view).apply {
        systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        hide(WindowInsetsCompat.Type.systemBars())
    }
}

private fun Context.findActivity(): Activity? {
    var current: Context? = this
    while (current is ContextWrapper) {
        if (current is Activity) return current
        current = current.baseContext
    }
    return current as? Activity
}
