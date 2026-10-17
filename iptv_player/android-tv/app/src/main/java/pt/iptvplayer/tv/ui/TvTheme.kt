package pt.iptvplayer.tv.ui

import androidx.compose.foundation.layout.RowScope
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.tv.material3.Button
import androidx.tv.material3.ButtonDefaults

/**
 * Single source of truth for the TV palette — the same neutral-dark surfaces and coral-red
 * accent as the desktop app and the logo. Screens reference these tokens instead of literals.
 */
internal object TvColors {
    val Background = Color(0xFF0E0E10)
    val Sidebar = Color(0xFF141416)
    val Panel = Color(0xFF1C1C1F)
    val PanelFocused = Color(0xFF2C2C30)
    val Placeholder = Color(0xFF18181B)
    val Border = Color(0xFF3A3A40)
    val Selected = Color(0xFF3A1A22)
    val Airing = Color(0xFF4A1F28)
    val Accent = Color(0xFFE8455A)
    val OnAccent = Color(0xFF0E0E10)
    val Muted = Color(0xFFA8A8AD)
    val Live = Color(0xFFE50914)
    val Warning = Color(0xFFF0B429)
    val Caution = Color(0xFFFFB36B)
    val Gold = Color(0xFFF5C518)
    val Overlay = Color(0xF2141416)
    val OverlaySoft = Color(0xE6141416)
    val Dialog = Color(0xF01C1C1F)
    val Toast = Color(0xB80E0E10)
    val Scrim = Color(0xE6080809)
    val ScrimSoft = Color(0xD9080809)
    val ScrimStrong = Color(0xF2080809)
}

internal val Background = TvColors.Background
internal val Panel = TvColors.Panel
internal val PanelFocused = TvColors.PanelFocused
internal val Accent = TvColors.Accent
internal val Muted = TvColors.Muted

internal val PlayerPanel = TvColors.Overlay
internal val PlayerFocused = TvColors.PanelFocused
internal val PlayerAccent = TvColors.Accent
internal val PlayerMuted = TvColors.Muted

/** tv-material Button in the brand colours: coral when focused, so focus is obvious from the sofa. */
@Composable
internal fun BrandButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    content: @Composable RowScope.() -> Unit,
) = Button(
    onClick = onClick,
    modifier = modifier,
    enabled = enabled,
    colors = ButtonDefaults.colors(
        containerColor = TvColors.PanelFocused,
        contentColor = Color.White,
        focusedContainerColor = TvColors.Accent,
        focusedContentColor = Color.White,
        pressedContainerColor = TvColors.Accent,
        pressedContentColor = Color.White,
        disabledContainerColor = TvColors.Panel,
        disabledContentColor = TvColors.Muted,
    ),
    content = content,
)
