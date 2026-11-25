"""Launch VLC, read its own log in real time and explain what happens.

VLC is started with ``--file-logging`` so that every HTTP exchange it makes
(status codes, redirects, "first picture") ends up in a file we tail. That is
the only way to know what *VLC itself* received, as opposed to what the app
saw when it built the link.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from PyQt6.QtCore import QObject, pyqtSignal

from zone_new_companion.services.player_launcher import resolve_vlc_path

LOGGER = logging.getLogger("zone.vlc")

HTTP_EXPLANATIONS: dict[int, str] = {
    200: "flux reçu",
    206: "flux reçu",
    301: "redirection",
    302: "redirection vers le serveur de diffusion",
    400: "requête refusée par le serveur",
    401: "refusé : limite de connexions atteinte (ou identifiants invalides)",
    403: "interdit : compte expiré/suspendu ou IP bloquée",
    404: "chaîne introuvable sur le serveur",
    405: "méthode refusée par le serveur",
    429: "trop de requêtes, le serveur limite",
    456: "refus maison du fournisseur (lecteur non autorisé ou limite)",
    458: "refus maison du fournisseur",
    500: "erreur interne du serveur",
    502: "serveur de diffusion injoignable (502)",
    503: "serveur surchargé ou en maintenance",
    504: "serveur de diffusion trop lent (504)",
    509: "bande passante du serveur dépassée",
    551: "refus maison du fournisseur",
}

_RE_RESPONSE = re.compile(r"(?:incoming response: HTTP/\d(?:\.\d)? |HTTP answer code )(\d{3})")
_RE_REQUEST_HOST = re.compile(r"outgoing request: GET \S+ HTTP/\d\.\d Host: (\S+)")
_RE_REDIRECT = re.compile(r"redirecting to: (\S+)")
_RE_ACCESS_ERROR = re.compile(r"access error: (.+)")
_PICTURE = "Received first picture"
_DEAD = ("dead input", "Your input can't be opened", "nothing to play")


def explain_http(code: int) -> str:
    if code in HTTP_EXPLANATIONS:
        return HTTP_EXPLANATIONS[code]
    if 200 <= code < 300:
        return "OK"
    if 300 <= code < 400:
        return "redirection"
    if 400 <= code < 500:
        return "refusé par le serveur"
    return "erreur serveur"


def _host(url: str) -> str:
    try:
        return urlparse(url).hostname or url
    except ValueError:
        return url


@dataclass
class AttemptResult:
    ok: bool
    reason: str
    codes: list[int] = field(default_factory=list)
    idle: bool = False  # VLC opened but never tried to read the stream


class PlaybackSession(QObject):
    """One "play" click: launch, watch, retry if the server refuses."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    ATTEMPT_TIMEOUT_S = 30.0

    def __init__(
        self,
        stream_url: str,
        title: str,
        log_dir: Path,
        retries: int = 1,
        retry_delay_s: float = 6.0,
        line_was_free: bool | None = None,
    ) -> None:
        super().__init__()
        self._url = stream_url
        self._title = title
        self._log_dir = log_dir
        self._retries = max(0, retries)
        self._retry_delay = retry_delay_s
        self._line_was_free = line_was_free
        self._cancelled = threading.Event()
        self._process: subprocess.Popen | None = None

    # ------------------------------------------------------------------ API
    def start(self) -> None:
        threading.Thread(target=self._run, name="vlc-monitor", daemon=True).start()

    def cancel(self) -> None:
        self._cancelled.set()

    # ------------------------------------------------------------ internals
    def _log(self, level: int, message: str) -> None:
        LOGGER.log(level, message, extra={"source": "VLC"})

    def _run(self) -> None:
        try:
            self._run_inner()
        except Exception as exc:  # noqa: BLE001 - never die silently in a thread
            LOGGER.exception("Erreur interne pendant la lecture")
            self.finished.emit(False, f"erreur interne : {exc}")

    def _run_inner(self) -> None:
        vlc_path = resolve_vlc_path()
        if not vlc_path:
            self._log(logging.ERROR, "VLC introuvable. Installe-le depuis videolan.org.")
            self.finished.emit(False, "VLC introuvable")
            return

        attempts = self._retries + 1
        self._log(logging.INFO, f"▶ {self._title} — {self._url}")
        self._log(logging.INFO, f"VLC : {vlc_path}")
        last: AttemptResult | None = None
        for attempt in range(1, attempts + 1):
            if self._cancelled.is_set():
                break
            if attempt > 1:
                self.progress.emit(f"Nouvel essai {attempt}/{attempts} dans {self._retry_delay:.0f} s…")
                self._log(logging.INFO, f"Nouvel essai {attempt}/{attempts} dans {self._retry_delay:.0f} s")
                time.sleep(self._retry_delay)
            last = self._attempt(vlc_path, attempt, attempts)
            if last.ok:
                self.finished.emit(True, f"{self._title} : lecture en cours")
                return
            if last.idle:
                # VLC closed by the user, or a new channel was requested: stop quietly.
                self._log(logging.INFO, f"Suivi arrêté : {last.reason}")
                self.finished.emit(False, f"{self._title} : {last.reason}")
                return
            if last.codes and last.codes[-1] in (403, 404):
                # Retrying will not change a missing channel or a banned account.
                break
            self._stop_process()
        reason = last.reason if last else "annulé"
        self._log(logging.ERROR, f"✖ {self._title} : échec — {reason}")
        self.finished.emit(False, f"{self._title} : {reason}")

    def _attempt(self, vlc_path: str, attempt: int, attempts: int) -> AttemptResult:
        self._log_dir.mkdir(parents=True, exist_ok=True)
        log_file = self._log_dir / f"vlc-{int(time.time())}-{attempt}.log"
        cmd = [
            vlc_path,
            "--network-caching=1000",
            "--http-user-agent=Lavf/57.83.100",
            "--no-qt-error-dialogs",
            "--no-one-instance",
            "--no-playlist-enqueue",
            "--playlist-autostart",
            "--verbose=2",
            "--file-logging",
            f"--logfile={log_file}",
            "--log-verbose=2",
            self._url,
        ]
        # VLC is a normal windowed app: launch it as-is, no STARTUPINFO tweaks.
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self._log(logging.ERROR, f"Impossible de lancer VLC : {exc}")
            return AttemptResult(False, f"VLC n'a pas pu démarrer ({exc})")

        self.progress.emit(f"Connexion à {_host(self._url)}… (essai {attempt}/{attempts})")
        self._log(logging.INFO, f"Essai {attempt}/{attempts} : VLC lancé (PID {self._process.pid})")
        result = self._watch(log_file)
        self._prune_logs()
        return result

    def _watch(self, log_file: Path) -> AttemptResult:
        """Tail VLC's log until we know for sure, or until the deadline.

        Two Windows quirks shape this:
        * VLC writes HTTP dumps over several lines ("incoming response:" then
          "HTTP/1.1 302 Found" on the next line, then the headers);
        * its log file is written in blocks, so lines can arrive seconds late.
        So we only kill VLC on an *explicit* failure, never on silence.
        """
        deadline = time.monotonic() + self.ATTEMPT_TIMEOUT_S
        position = 0
        buffer = ""
        codes: list[int] = []
        saw_activity = False
        expect_status = False
        last_reported: tuple[str, int] | None = None
        current_host = _host(self._url)

        def record(code: int) -> None:
            nonlocal last_reported
            key = (current_host, code)
            if key == last_reported:  # VLC retries in HTTP/1.0 internally, skip duplicates
                return
            last_reported = key
            codes.append(code)
            level = logging.INFO if code < 400 else logging.WARNING
            self._log(level, f"{current_host} → HTTP {code} : {self._explain(code)}")

        def handle(raw: str) -> AttemptResult | None:
            nonlocal current_host, saw_activity, expect_status
            line = raw.strip()
            if not line:
                return None
            if "creating access" in line or "outgoing request" in line or "sending request" in line:
                saw_activity = True
            if expect_status:
                expect_status = False
                status = re.match(r"HTTP/\d(?:\.\d)?\s+(\d{3})", line)
                if status:
                    record(int(status.group(1)))
                    return None
            if line.endswith("incoming response:"):
                expect_status = True
                return None
            host_line = re.match(r"Host:\s*(\S+)", line)
            if host_line:
                current_host = host_line.group(1).split(":")[0]
                return None
            host_match = _RE_REQUEST_HOST.search(line)
            if host_match:
                current_host = host_match.group(1).split(":")[0]
                return None
            response = _RE_RESPONSE.search(line)
            if response:
                record(int(response.group(1)))
                return None
            redirect = _RE_REDIRECT.search(line)
            if redirect:
                target = _host(redirect.group(1))
                self._log(logging.INFO, f"Redirigé vers {target}")
                current_host = target
                return None
            if _PICTURE in line:
                self._log(logging.INFO, "✔ Première image reçue, la chaîne tourne")
                return AttemptResult(True, "lecture", codes)
            if any(marker in line for marker in _DEAD):
                if codes and codes[-1] >= 400:
                    code = codes[-1]
                    return AttemptResult(False, f"HTTP {code} — {self._explain(code)}", codes)
                return AttemptResult(False, "VLC n'a pas pu ouvrir le flux", codes)
            access_error = _RE_ACCESS_ERROR.search(line)
            if access_error and not codes:
                self._log(logging.WARNING, f"Erreur d'accès VLC : {access_error.group(1)}")
            return None

        def drain() -> AttemptResult | None:
            nonlocal position, buffer
            if not log_file.exists():
                return None
            try:
                with log_file.open("r", encoding="utf-8", errors="replace") as handle_file:
                    handle_file.seek(position)
                    chunk = handle_file.read()
                    position = handle_file.tell()
            except OSError:
                return None
            if not chunk:
                return None
            buffer += chunk.replace("\r", "")
            *lines, buffer = buffer.split("\n")
            for line in lines:
                outcome = handle(line)
                if outcome is not None:
                    return outcome
            return None

        while time.monotonic() < deadline and not self._cancelled.is_set():
            outcome = drain()
            if outcome is not None:
                return outcome
            if self._process is not None and self._process.poll() is not None:
                outcome = drain()  # VLC flushes its log when it exits
                if outcome is not None and not outcome.ok:
                    return outcome
                return AttemptResult(False, "VLC a été fermé", codes, idle=True)
            time.sleep(0.25)

        if self._cancelled.is_set():
            return AttemptResult(False, "annulé", codes, idle=True)
        if codes and codes[-1] >= 400:
            code = codes[-1]
            return AttemptResult(False, f"HTTP {code} — {self._explain(code)}", codes)
        # No explicit failure: VLC is most likely playing and its log is just late.
        if codes or saw_activity:
            self._log(
                logging.INFO,
                f"Pas de confirmation d'image après {self.ATTEMPT_TIMEOUT_S:.0f} s (VLC écrit son journal par paquets), "
                "mais aucune erreur : VLC est laissé ouvert",
            )
        else:
            self._log(
                logging.INFO,
                f"VLC n'a encore rien écrit après {self.ATTEMPT_TIMEOUT_S:.0f} s : laissé ouvert. "
                "S'il attend un clic, vérifie Outils › Préférences › Playlist › « Lancement automatique »",
            )
        return AttemptResult(True, "lecture (non confirmée)", codes)

    def _explain(self, code: int) -> str:
        if code == 401 and self._line_was_free:
            return "IP probablement bloquée pour le moment (la ligne était libre, ce n'est pas la limite de connexions)"
        return explain_http(code)

    def _stop_process(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass

    def _prune_logs(self, keep: int = 30) -> None:
        try:
            files = sorted(self._log_dir.glob("vlc-*.log"), key=os.path.getmtime)
            for stale in files[:-keep]:
                stale.unlink(missing_ok=True)
        except OSError:
            pass
