from .channel_list import ChannelListWidget
from .dialogs import PlaylistDialog, SettingsDialog, StalkerDialog, XtreamDialog
from .epg_widget import EPGWidget
from .main_window import MainWindow
from .player_widget import PlayerWidget
from .playlist_widget import PlaylistWidget

__all__ = [
    "MainWindow", "PlaylistWidget", "ChannelListWidget",
    "PlayerWidget", "EPGWidget", "PlaylistDialog",
    "SettingsDialog", "XtreamDialog", "StalkerDialog"
]
