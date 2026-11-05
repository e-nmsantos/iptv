package pt.iptvplayer.tv.data

import pt.iptvplayer.tv.BuildConfig

/** Default User-Agent for catalog, EPG and playback requests; tracks the real app version. */
val APP_USER_AGENT: String = "IPTVPlayerTV/${BuildConfig.VERSION_NAME}"
