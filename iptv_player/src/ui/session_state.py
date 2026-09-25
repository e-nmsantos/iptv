"""Session restore/persist for the main window.

Extracted from ``main_window.py``. ``SessionStateMixin`` must be mixed into
a class that provides ``_settings``, ``_playlist_widget``, ``_live_list``,
``_content_tabs``, ``_content_stack``, ``_media_player``, ``_logger`` and
``_current_playlist_id``.
"""


class SessionStateMixin:
    """Persist and restore the last playlist, tab, group and channel."""

    def _restore_session_state(self, playlists: list):
        """Re-apply the last playlist, content tab, group and channel."""
        try:
            last_id = self._settings.get("last_playlist_id")
            if last_id and any(pl.get("id") == last_id for pl in playlists):
                self._playlist_widget.select_playlist(last_id)
                # Channel loading is asynchronous; the persisted group filter
                # and channel selection are re-applied only after the list is
                # populated (see _restore_session_group_and_channel).
                self._on_playlist_selected(
                    last_id,
                    after_load=self._restore_session_group_and_channel,
                )
            tab = int(self._settings.get("last_content_tab", 0))
            if tab in (0, 1, 2):
                # set_current_index does not emit tab_changed; sync the stack
                # and kick off the (lazy) catalog load like a manual click.
                self._content_tabs.set_current_index(tab)
                self._on_content_tab_changed(tab)
        except Exception as exc:
            self._logger.warning(f"Failed to restore session state: {exc}")

    def _restore_session_group_and_channel(self):
        """Apply the persisted group filter and last channel (post-load)."""
        try:
            group_filter = self._settings.get("last_group_filter")
            if isinstance(group_filter, (list, tuple)) and len(group_filter) == 2:
                self._live_list.set_group_filter(tuple(group_filter))
            last_channel_id = int(self._settings.get("last_channel_id") or 0)
            if last_channel_id:
                restored = self._live_list.restore_channel_by_url_or_id("", last_channel_id)
                if restored and self._settings.get("autoplay_last_channel", True):
                    channel = self._live_list.get_current_channel()
                    if channel:
                        self._on_channel_selected(channel)
        except Exception as exc:
            self._logger.warning(f"Failed to restore group/channel: {exc}")

    def _save_session_state(self):
        """Persist the last selection so it can be restored on next launch."""
        try:
            values = {"volume": self._media_player.get_volume()}
            if self._current_playlist_id:
                values["last_playlist_id"] = self._current_playlist_id
            values["last_content_tab"] = self._content_stack.currentIndex()
            current = self._live_list.get_current_channel()
            if current:
                values["last_channel_id"] = current.database_id
            values["last_group_filter"] = list(self._live_list.get_group_filter())
            self._settings.set_many(values)
        except Exception as exc:
            self._logger.warning(f"Failed to save session state: {exc}")
