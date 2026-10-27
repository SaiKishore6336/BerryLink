package app.berrylink.companion

import android.content.pm.ActivityInfo
import android.graphics.Color
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import app.berrylink.companion.ui.BerryLinkApp
import app.berrylink.companion.ui.theme.BerryLinkTheme

class MainActivity : ComponentActivity() {
    private val viewModel: BerryViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Start directly in the paired landscape face experience. Doing this
        // before setContent avoids a portrait frame when the app is relaunched
        // with a stored pairing.
        if (viewModel.state.value.paired != null) {
            requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
        }
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
        )
        setContent {
            BerryLinkTheme {
                BerryLinkApp(viewModel)
            }
        }
    }
}
