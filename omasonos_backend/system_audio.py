from __future__ import annotations

import http.server
import json
import os
import shutil
import socket
import subprocess
import threading
from pathlib import Path
from typing import Any


class SystemAudioError(RuntimeError):
    pass


class _StreamHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib callback name
        self._headers()

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        router: SystemAudioRouter = self.server.router  # type: ignore[attr-defined]
        if self.path.split("?", 1)[0] != "/system-audio.mp3":
            self.send_error(404)
            return
        if not router._client_lock.acquire(blocking=False):
            self.send_error(503, "Audio stream is already connected")
            return
        try:
            self._headers()
            router._client_connected.set()
            process = router._encoder
            if process is None or process.stdout is None:
                return
            while router.running:
                chunk = process.stdout.read(16384)
                if not chunk:
                    return
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            router._client_lock.release()

    def _headers(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Connection", "close")
        self.end_headers()

    def log_message(self, _format: str, *args: Any) -> None:
        return


class _AudioServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class SystemAudioRouter:
    """Route the current PulseAudio/PipeWire desktop mix to one Sonos stream."""

    sink_name = "omasonos_system_audio"
    stream_port = 1499

    def __init__(self) -> None:
        self._module_id = ""
        self._sink_index = ""
        self._previous_default = ""
        self._moved_inputs: dict[str, str] = {}
        self._encoder: subprocess.Popen[bytes] | None = None
        self._server: _AudioServer | None = None
        self._server_thread: threading.Thread | None = None
        self._client_lock = threading.Lock()
        self._client_connected = threading.Event()
        self.url = ""
        self.room_label = ""

    @staticmethod
    def _recovery_path() -> Path:
        runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        return Path(runtime) / "omasonos-system-audio.json"

    def _save_recovery_state(self) -> None:
        path = self._recovery_path()
        payload = {
            "previousDefault": self._previous_default,
            "movedInputs": self._moved_inputs,
        }
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload), encoding="utf-8")
        temp.chmod(0o600)
        os.replace(temp, path)

    @classmethod
    def recover_stale(cls) -> None:
        """Restore audio left behind if the shell killed a routing backend."""
        path = cls._recovery_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            return
        previous = str(payload.get("previousDefault", "") or "")
        moved = payload.get("movedInputs", {})
        if not isinstance(moved, dict):
            moved = {}
        try:
            if previous:
                cls._run("pactl", "set-default-sink", previous)
            sinks = {
                fields[0]: fields[1]
                for line in cls._run("pactl", "list", "short", "sinks").splitlines()
                if len(fields := line.split()) >= 2
            }
            stale_indices = {idx for idx, name in sinks.items() if name == cls.sink_name}
            for input_id, current_sink in cls._sink_inputs().items():
                if current_sink not in stale_indices or not previous:
                    continue
                cls._run(
                    "pactl", "move-sink-input", input_id,
                    str(moved.get(input_id, "") or previous),
                )
            for line in cls._run("pactl", "list", "short", "modules").splitlines():
                fields = line.split(maxsplit=2)
                if len(fields) >= 3 and fields[1] == "module-null-sink" \
                        and f"sink_name={cls.sink_name}" in fields[2]:
                    cls._run("pactl", "unload-module", fields[0])
        finally:
            path.unlink(missing_ok=True)

    @property
    def running(self) -> bool:
        return self._module_id != "" and self._encoder is not None

    def status(self) -> dict[str, Any]:
        return {
            "active": self.running,
            "roomLabel": self.room_label if self.running else "",
            "url": self.url if self.running else "",
        }

    @staticmethod
    def _run(*args: str) -> str:
        try:
            result = subprocess.run(
                args, check=True, capture_output=True, text=True, timeout=8
            )
        except FileNotFoundError as exc:
            raise SystemAudioError(f"Missing required command: {args[0]}") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise SystemAudioError(detail) from exc
        except subprocess.TimeoutExpired as exc:
            raise SystemAudioError(f"Timed out running {args[0]}") from exc
        return result.stdout.strip()

    @classmethod
    def _sink_inputs(cls) -> dict[str, str]:
        inputs: dict[str, str] = {}
        for line in cls._run("pactl", "list", "short", "sink-inputs").splitlines():
            fields = line.split()
            if len(fields) >= 2:
                inputs[fields[0]] = fields[1]
        return inputs

    @classmethod
    def _sink_index_for_name(cls, name: str) -> str:
        for line in cls._run("pactl", "list", "short", "sinks").splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] == name:
                return fields[0]
        raise SystemAudioError("PipeWire did not create the OmaSonos output")

    @staticmethod
    def _local_ip_for(peer_ip: str) -> str:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((peer_ip, 1400))
            return str(sock.getsockname()[0])
        except OSError as exc:
            raise SystemAudioError("Could not determine a LAN address for Sonos") from exc
        finally:
            sock.close()

    @classmethod
    def _open_server(cls) -> _AudioServer:
        try:
            return _AudioServer(("0.0.0.0", cls.stream_port), _StreamHandler)
        except OSError as exc:
            raise SystemAudioError(
                f"OmaSonos streaming port {cls.stream_port} is unavailable"
            ) from exc

    def start(self, *, speaker_ip: str, room_label: str) -> str:
        if self.running:
            raise SystemAudioError("System audio routing is already active")
        for command in ("pactl", "ffmpeg"):
            if shutil.which(command) is None:
                raise SystemAudioError(f"Missing required command: {command}")

        try:
            self._client_connected.clear()
            self._previous_default = self._run("pactl", "get-default-sink")
            self._moved_inputs = self._sink_inputs()
            self._save_recovery_state()
            self._module_id = self._run(
                "pactl", "load-module", "module-null-sink",
                f"sink_name={self.sink_name}",
                "sink_properties=device.description=OmaSonos_System_Audio",
                "rate=44100", "channels=2",
            )
            self._sink_index = self._sink_index_for_name(self.sink_name)
            self._run("pactl", "set-default-sink", self.sink_name)
            for input_id in self._moved_inputs:
                self._run("pactl", "move-sink-input", input_id, self.sink_name)

            local_ip = self._local_ip_for(speaker_ip)
            self._server = self._open_server()
            self._server.router = self  # type: ignore[attr-defined]
            port = self._server.server_address[1]
            self.url = f"http://{local_ip}:{port}/system-audio.mp3"
            self.room_label = room_label
            self._encoder = subprocess.Popen(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "pulse", "-i", f"{self.sink_name}.monitor",
                    "-ac", "2", "-ar", "44100", "-codec:a", "libmp3lame",
                    "-b:a", "320k", "-f", "mp3", "pipe:1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self._server_thread = threading.Thread(
                target=self._server.serve_forever,
                name="omasonos-system-audio",
                daemon=True,
            )
            self._server_thread.start()
            return self.url
        except Exception:
            self.stop()
            raise

    def wait_for_client(self, timeout: float = 8.0) -> bool:
        return self._client_connected.wait(timeout)

    def stop(self) -> None:
        encoder, self._encoder = self._encoder, None
        if encoder is not None:
            encoder.terminate()
            try:
                encoder.wait(timeout=2)
            except subprocess.TimeoutExpired:
                encoder.kill()
                encoder.wait(timeout=2)

        server, self._server = self._server, None
        if server is not None:
            if self._server_thread is not None and self._server_thread.is_alive():
                server.shutdown()
            server.server_close()
        thread, self._server_thread = self._server_thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)

        if self._previous_default:
            try:
                self._run("pactl", "set-default-sink", self._previous_default)
            except SystemAudioError:
                pass
        if self._module_id:
            current = {}
            try:
                current = self._sink_inputs()
            except SystemAudioError:
                pass
            for input_id, current_sink in current.items():
                if current_sink != self._sink_index:
                    continue
                try:
                    self._run(
                        "pactl", "move-sink-input", input_id,
                        self._moved_inputs.get(input_id) or self._previous_default,
                    )
                except SystemAudioError:
                    pass
            try:
                self._run("pactl", "unload-module", self._module_id)
            except SystemAudioError:
                pass
        self._module_id = ""
        self._sink_index = ""
        self._previous_default = ""
        self._moved_inputs = {}
        self.url = ""
        self.room_label = ""
        self._client_connected.clear()
        self._recovery_path().unlink(missing_ok=True)
