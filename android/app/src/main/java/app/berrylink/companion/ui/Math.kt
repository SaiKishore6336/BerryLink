package app.berrylink.companion.ui

import kotlin.math.cos
import kotlin.math.sin

internal const val PI_F = 3.1415927f

internal fun sinF(value: Float): Float = sin(value.toDouble()).toFloat()

internal fun cosF(value: Float): Float = cos(value.toDouble()).toFloat()
