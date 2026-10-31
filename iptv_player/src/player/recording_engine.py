"""VLC remuxing for HLS and transport-stream background recordings."""

import shutil
import time

import vlc

DISK_RESERVE = 512 * 1024**2


def record_stream(session):
    """Write actual media packets, retaining earlier video across reconnections."""
    instance = player = media = None
    try:
        session.output_file.parent.mkdir(parents=True, exist_ok=True)
        check_disk(session.output_file.parent)
        instance = vlc.Instance("--quiet", "--no-video-title-show", "--intf=dummy")
        if instance is None:
            raise RuntimeError("Não foi possível iniciar o VLC para gravar.")
        player = instance.media_player_new()
        retries = 0
        announced = False
        while not session._stop_event.is_set():
            media = make_media(instance, session)
            player.set_media(media)
            if player.play() == -1:
                raise RuntimeError("Não foi possível iniciar a gravação.")
            last_growth = time.monotonic()
            reconnect = False
            while not session._stop_event.wait(0.5):
                size = session.output_file.stat().st_size if session.output_file.exists() else 0
                if size > session._bytes_written:
                    session._bytes_written = size
                    last_growth = time.monotonic()
                    if not announced:
                        announced = True
                        if session.on_started:
                            session.on_started()
                    if session.on_progress:
                        session.on_progress(size, session.elapsed_seconds)
                check_disk(session.output_file.parent)
                if session.duration_seconds > 0 and session.elapsed_seconds >= session.duration_seconds:
                    return
                if (player.get_state() in (vlc.State.Error, vlc.State.Ended)
                        or time.monotonic() - last_growth >= 30):
                    reconnect = True
                    break
            player.stop()
            media.release()
            media = None
            if not reconnect or session._stop_event.is_set():
                return
            if retries >= 3:
                raise RuntimeError("A ligação falhou após 3 tentativas. O conteúdo recebido foi guardado.")
            retries += 1
            if session._stop_event.wait(min(2**retries, 8)):
                return
    finally:
        if player is not None:
            player.stop()
            player.release()
        if media is not None:
            media.release()
        if instance is not None:
            instance.release()


def check_disk(folder):
    if shutil.disk_usage(folder).free < DISK_RESERVE:
        raise RuntimeError("Gravação interrompida: são necessários 512 MB livres. O conteúdo recebido foi guardado.")


def make_media(instance, session):
    media = instance.media_new(session.stream_url)
    try:
        destination = session.output_file.resolve().as_posix().replace("'", "\\'")
        options = [
            f":sout=#std{{access=file{{append}},mux=ts,dst='{destination}'}}",
            ":http-reconnect", ":network-caching=1500", ":no-sout-all",
        ]
        header_options = {
            "user-agent": "http-user-agent", "referer": "http-referrer",
            "referrer": "http-referrer", "cookie": "http-cookie",
        }
        for key, value in session.headers.items():
            option = header_options.get(key.lower())
            if option:
                options.append(f":{option}={value}")
        for option in options:
            media.add_option(option)
        return media
    except Exception:
        media.release()
        raise
