"""Application controller."""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from zone_new_companion.services.logger_service import logger_service

from PyQt6.QtCore import QObject, QThreadPool, pyqtSignal

from zone_new_companion.config import AppConfig, ConfigStore
from zone_new_companion.models import Credentials, MediaItem, PlaylistCategory, PortalType
from zone_new_companion.services.base import PortalService
from zone_new_companion.services.m3u_service import M3UService
from zone_new_companion.services.ocr_service import OCRService
from zone_new_companion.services.account_check import MAX_PARALLEL as MAX_PARALLEL_CHECKS
from zone_new_companion.services.account_check import check_account
from zone_new_companion.services.fallback import account_label, channel_matcher
from zone_new_companion.services.playback_monitor import PlaybackSession, Source
from zone_new_companion.services.stalker_service import StalkerService
from zone_new_companion.services.stream_verifier import StreamVerifier
from zone_new_companion.services.xtream_service import XtreamService
from zone_new_companion.state import StateStore
from zone_new_companion.workers.task_worker import TaskWorker

LOGGER = logging.getLogger(__name__)


def classify_backup(info: dict[str, str]) -> tuple[str, bool | None]:
    """('invalid'|'free'|'full'|'unknown', line_was_free) from an account check."""
    if info.get("Type") == "M3U Playlist":
        return "unknown", None
    if str(info.get("Status", "")).lower() != "active":
        return "invalid", None
    active, _, maximum = str(info.get("Active/Max Connections", "")).partition("/")
    if active.isdigit() and maximum.isdigit():
        return ("full", False) if int(active) >= int(maximum) else ("free", True)
    return "unknown", None


class _CheckEmitter(QObject):
    result = pyqtSignal(object, object, str)
    done = pyqtSignal()


class AppController:
    """Coordinate UI events, state, and services."""

    def __init__(self, state_store: StateStore, config_store: ConfigStore, log_dir: Path | None = None) -> None:
        self._state_store = state_store
        self._config_store = config_store
        self._config: AppConfig = config_store.load()
        self._thread_pool = QThreadPool.globalInstance()
        self._services: dict[PortalType, PortalService] = {
            PortalType.XTREAM: XtreamService(),
            PortalType.M3U: M3UService(),
            PortalType.STALKER: StalkerService(),
        }
        self._verifier = StreamVerifier()
        self._ocr_service = OCRService()
        self._navigation_stack: dict[str, list[list[MediaItem]]] = {"Live": [], "Movies": [], "Series": []}
        self._log_dir = log_dir or (Path.home() / ".zone-new-companion" / "logs")
        self._session: PlaybackSession | None = None
        self._on_playback_progress: Callable[[str], None] | None = None
        self._check_emitters: set[_CheckEmitter] = set()
        self._backup_states: dict[str, tuple[float, str, bool | None]] = {}

    @property
    def config(self) -> AppConfig:
        return self._config

    def history_entries(self) -> list[Credentials]:
        """Return successful credential history."""
        return list(self._config.successful_history)

    def _service_for(self, profile: Credentials) -> PortalService:
        """Get the appropriate service for the given profile."""
        try:
            service = self._services.get(profile.portal_type)
            if service is None:
                raise ValueError(f"Unsupported portal type: {profile.portal_type}")
            return service
        except Exception as e:
            LOGGER.error(f"Failed to get service for portal type {profile.portal_type}: {e}")
            raise

    def _validate_input(self, credentials: Credentials) -> str | None:
        """Validate input credentials with comprehensive error checking."""
        try:
            if not credentials.base_url:
                return "Il manque l'adresse du serveur."
            
            # Validate URL format
            if not credentials.base_url.startswith(('http://', 'https://')):
                return "L'adresse doit commencer par http:// ou https://"
            
            if re.search(r"\s", credentials.base_url):
                return "L'adresse ne doit pas contenir d'espaces."
            
            # Portal-specific validation
            if credentials.portal_type == PortalType.XTREAM:
                if not credentials.username or not credentials.password:
                    return "Xtream : identifiant et mot de passe requis."
                if len(credentials.username) < 3:
                    return "L'identifiant doit faire au moins 3 caractères."
                    
            elif credentials.portal_type == PortalType.M3U:
                if not credentials.base_url:
                    return "Il manque l'URL de la playlist."
                # Additional M3U validation
                if not any(ext in credentials.base_url.lower() for ext in ['.m3u', '.m3u8', 'get.php']):
                    LOGGER.warning("M3U URL doesn't contain typical M3U indicators")
                    
            elif credentials.portal_type == PortalType.STALKER:
                if not credentials.mac_address:
                    return "Stalker : adresse MAC requise."
                if not re.match(
                    r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$",
                    credentials.mac_address,
                ):
                    return "Adresse MAC au format 00:11:22:33:44:55."
            
            return None
            
        except Exception as e:
            LOGGER.error(f"Validation error: {e}")
            return f"Validation failed: {e}"

    def _normalize_credentials(self, credentials: Credentials) -> Credentials:
        """Normalize user input, including Xtream get.php links."""
        base = credentials.base_url.strip()
        if credentials.portal_type != PortalType.XTREAM:
            return credentials

        parsed = urlparse(base)
        if parsed.path.endswith("/get.php"):
            params = parse_qs(parsed.query)
            username = (params.get("username") or [credentials.username])[0]
            password = (params.get("password") or [credentials.password])[0]
            host = parsed.hostname or ""
            scheme = parsed.scheme or "http"
            port = f":{parsed.port}" if parsed.port else ""
            base = f"{scheme}://{host}{port}"
            return Credentials(
                name=credentials.name,
                base_url=base,
                portal_type=credentials.portal_type,
                username=username,
                password=password,
                mac_address=credentials.mac_address,
                saved_at=credentials.saved_at,
            )
        return credentials

    def connect(self, credentials: Credentials, on_success: Callable[[str], None], on_error: Callable[[str], None]) -> None:
        """Load categories asynchronously and persist profile."""
        try:
            LOGGER.info("Connexion à %s (%s)…", credentials.base_url, credentials.portal_type.value)
            
            credentials = self._normalize_credentials(credentials)
            self._config.last_input = credentials
            self._config_store.save(self._config)
            validation_error = self._validate_input(credentials)
            if validation_error:
                on_error(validation_error)
                return

            service = self._service_for(credentials)
            
            
            self._state_store.update(
                active_profile=credentials,
                busy=True,
                status_text=f"Connexion à {credentials.base_url}…",
            )

            def task() -> tuple[dict[str, list[PlaylistCategory]], dict[str, str]]:
                categories = service.fetch_categories(credentials)
                info = service.fetch_connection_info(credentials)
                return categories, info

            worker = TaskWorker(task)
            worker.signals.succeeded.connect(lambda payload: self._on_connected(credentials, payload, on_success))
            worker.signals.failed.connect(lambda message: self._on_error(message, on_error))
            worker.signals.finished.connect(lambda: self._state_store.update(busy=False))
            self._thread_pool.start(worker)
            
        except Exception as exc:
            LOGGER.error("Connexion impossible : %s", exc)
            on_error(str(exc))

    def _on_connected(
        self,
        credentials: Credentials,
        payload: tuple[dict[str, list[PlaylistCategory]], dict[str, str]],
        on_success: Callable[[str], None],
    ) -> None:
        categories, connection_info = payload
        self._remember_success(credentials)
        self._state_store.update(
            categories=categories,
            credential_info=connection_info,
            status_text="Catégories chargées.",
        )
        total = sum(len(rows) for rows in categories.values())
        LOGGER.info("Connecté à %s : %d catégories", credentials.base_url, total)
        if total == 0:
            LOGGER.warning(
                "Le serveur a répondu mais ne donne aucune catégorie : identifiants refusés, "
                "compte expiré ou serveur vide. Statut annoncé : %s",
                connection_info.get("Status", "inconnu"),
            )
        on_success(f"Connecté · {total} catégories")

    def load_items(
        self,
        tab_name: str,
        category: PlaylistCategory,
        on_success: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        """Load category items asynchronously."""
        state = self._state_store.state
        profile = state.active_profile
        if profile is None:
            on_error("Pas de connexion active.")
            return
        if self._state_store.state.busy:
            on_error("Patiente, une opération est déjà en cours.")
            return
        self._state_store.update(busy=True, status_text="Chargement…")

        def task() -> list[MediaItem]:
            return self._service_for(profile).fetch_items(profile, category)

        worker = TaskWorker(task)
        worker.signals.succeeded.connect(
            lambda items: self._on_items_loaded(tab_name, items, on_success, push_stack=False),
        )
        worker.signals.failed.connect(lambda message: self._on_error(message, on_error))
        worker.signals.finished.connect(lambda: self._state_store.update(busy=False))
        self._thread_pool.start(worker)

    def _on_items_loaded(
        self,
        tab_name: str,
        items: list[MediaItem],
        on_success: Callable[[str], None],
        *,
        push_stack: bool,
    ) -> None:
        current = dict(self._state_store.state.current_items)
        if push_stack and current.get(tab_name):
            self._navigation_stack[tab_name].append(list(current[tab_name]))
        current[tab_name] = items
        verification = dict(self._state_store.state.verification_results)
        verification[tab_name] = {}
        now_playing = dict(self._state_store.state.now_playing)
        now_playing[tab_name] = {}
        self._state_store.update(
            current_items=current,
            verification_results=verification,
            now_playing=now_playing,
            status_text=f"{len(items)} éléments chargés.",
        )
        LOGGER.info("%s : %d éléments chargés", tab_name, len(items))

        # Lightweight "now playing" prefetch for Live tab.
        if tab_name == "Live":
            self._prefetch_now_playing(items[:10])

    def play(self, item: MediaItem, on_success: Callable[[str], None], on_error: Callable[[str], None]) -> None:
        """Resolve the stream, then hand it to a monitored VLC session."""
        profile = self._state_store.state.active_profile
        if profile is None:
            on_error("Pas de connexion active.")
            return
        if self._session is not None:
            # Close the previous VLC: on a 1-connection line it would make the new one fail (401).
            self._session.cancel(close_player=True)

        self._state_store.update(status_text=f"Préparation de {item.name}…")
        if self._on_playback_progress is not None:
            self._on_playback_progress(f"Lancement de {item.name}…")
        LOGGER.info("Lecture demandée : %s", item.name)

        def task() -> tuple[str, str]:
            service = self._service_for(profile)
            stream_url = service.resolve_stream_url(profile, item)
            line_state = ""
            if profile.portal_type == PortalType.XTREAM:
                # player_api does not count as a connection: safe to ask before launching.
                try:
                    info = service.fetch_connection_info(profile)
                    line_state = info.get("Active/Max Connections", "")
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("Impossible de lire l'état de la ligne : %s", exc)
            return stream_url, line_state

        service = self._service_for(profile)

        def launch(payload: tuple[str, str]) -> None:
            stream_url, line_state = payload
            line_was_free: bool | None = None
            if line_state:
                _active, _, _maximum = line_state.partition("/")
                if _active.isdigit() and _maximum.isdigit():
                    line_was_free = int(_active) < int(_maximum)
                active, _, maximum = line_state.partition("/")
                if active.isdigit() and maximum.isdigit() and int(active) >= int(maximum):
                    LOGGER.warning(
                        "Ligne %s déjà pleine (%s) avant lancement : le serveur risque de refuser",
                        profile.username,
                        line_state,
                    )
                else:
                    LOGGER.info("Ligne %s : %s connexions avant lancement", profile.username, line_state)
                info = dict(self._state_store.state.credential_info)
                if info:
                    info["Active/Max Connections"] = line_state
                    self._state_store.update(credential_info=info)
            primary = Source(
                label=account_label(profile),
                url=stream_url,
                line_was_free=line_was_free,
                before_retry=lambda: service.fetch_connection_info(profile),
                note="compte principal",
            )
            session = PlaybackSession(
                primary,
                item.name,
                self._log_dir,
                retries=self._config.ui.auto_retries,
                next_source=self._fallback_iterator(profile, item),
            )
            if self._on_playback_progress is not None:
                session.progress.connect(self._on_playback_progress)
            session.finished.connect(
                lambda ok, message, current=session: (
                    self._on_playback_finished(ok, message, on_success, on_error)
                    if current is self._session
                    else None
                ),
            )
            self._session = session
            session.start()

        worker = TaskWorker(task)
        worker.signals.succeeded.connect(launch)
        worker.signals.failed.connect(lambda message: self._on_error(message, on_error))
        self._thread_pool.start(worker)

    def _fallback_iterator(self, profile: Credentials, item: MediaItem) -> Callable[[], Source | None] | None:
        """Yield backup accounts one by one, each with the matching channel link."""
        if item.item_type != "channel":
            return None
        backups = [
            backup
            for backup in self._config.backup_accounts
            if (backup.base_url, backup.username, backup.mac_address)
            != (profile.base_url, profile.username, profile.mac_address)
        ]
        if not backups:
            return None
        remaining: list[tuple[Credentials, bool | None]] | None = None

        def check(backup: Credentials) -> tuple[str, bool | None]:
            """('invalid'|'free'|'full'|'unknown', line_was_free)."""
            if backup.portal_type != PortalType.XTREAM:
                return "unknown", None
            try:
                info = check_account(backup)
            except Exception as exc:  # noqa: BLE001
                self._remember_backup_state(backup, "invalid", None)
                LOGGER.warning("Secours « %s » injoignable : %s", account_label(backup), exc)
                return "invalid", None
            state, free = classify_backup(info)
            self._remember_backup_state(backup, state, free)
            if state == "invalid":
                LOGGER.warning(
                    "Secours « %s » ignoré : statut %s", account_label(backup), info.get("Status", "inconnu"),
                )
            return state, free

        def plan() -> list[tuple[Credentials, bool | None]]:
            # Accounts that failed at the last check (start-up, « Tout vérifier » or a previous
            # fallback) are skipped straight away instead of waiting for them to time out again.
            known_bad = [b for b in backups if self._recent_backup_state(b) == "invalid"]
            to_check = [b for b in backups if b not in known_bad]
            if known_bad:
                LOGGER.info(
                    "%d compte(s) de secours ignoré(s) sans réessayer : en échec à la dernière vérification",
                    len(known_bad),
                )
            states: list[tuple[str, bool | None]] = []
            if to_check:
                with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_CHECKS, len(to_check))) as pool:
                    states = list(pool.map(check, to_check))
            order = {"free": 0, "unknown": 1, "full": 2}
            ranked = sorted(
                ((backup, state, free) for backup, (state, free) in zip(to_check, states) if state != "invalid"),
                key=lambda row: order[row[1]],
            )
            summary = ", ".join(
                f"{account_label(b)} ({ {'free': 'libre', 'full': 'occupé', 'unknown': '?'}[state] })"
                for b, state, _free in ranked
            )
            LOGGER.info("Ordre de bascule : %s", summary or "aucun compte de secours valide")
            return [(backup, free) for backup, _state, free in ranked]

        def next_source() -> Source | None:
            nonlocal remaining
            if remaining is None:
                remaining = plan()
            while remaining:
                backup, line_was_free = remaining.pop(0)
                label = account_label(backup)
                try:
                    resolution = channel_matcher.resolve(profile, item, backup)
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("Compte de secours « %s » injoignable : %s", label, self._humanize(str(exc)))
                    continue
                if resolution is None:
                    LOGGER.warning("« %s » introuvable sur le compte de secours « %s »", item.name, label)
                    continue
                backup_service = self._fresh_service(backup)
                return Source(
                    label=label,
                    url=resolution.url,
                    line_was_free=line_was_free,
                    before_retry=(
                        (lambda b=backup, svc=backup_service: svc.fetch_connection_info(b))
                        if backup.portal_type == PortalType.XTREAM
                        else None
                    ),
                    note=resolution.method,
                )
            return None

        return next_source

    def _fresh_service(self, account: Credentials) -> PortalService:
        """A separate service instance: they cache server endpoints, so never share one across servers."""
        return type(self._service_for(account))()

    # ------------------------------------------------------------ backups
    def backup_accounts(self) -> list[Credentials]:
        return list(self._config.backup_accounts)

    def set_backup_accounts(self, accounts: list[Credentials]) -> None:
        self._config.backup_accounts = list(accounts)
        self._config_store.save(self._config)
        LOGGER.info("Comptes de secours : %d enregistré(s)", len(accounts))

    BACKUP_STATE_TTL_S = 20 * 60

    @staticmethod
    def _backup_key(account: Credentials) -> str:
        return f"{account.portal_type.value}|{account.base_url.lower()}|{account.username}"

    def _remember_backup_state(self, account: Credentials, state: str, free: bool | None) -> None:
        self._backup_states[self._backup_key(account)] = (time.monotonic(), state, free)

    def _recent_backup_state(self, account: Credentials) -> str:
        entry = self._backup_states.get(self._backup_key(account))
        if entry is None or time.monotonic() - entry[0] > self.BACKUP_STATE_TTL_S:
            return ""
        return entry[1]

    def check_backups(
        self,
        accounts: list[Credentials],
        on_result: Callable[[Credentials, dict[str, str] | None, str], None],
        on_done: Callable[[], None],
    ) -> None:
        """Check backup accounts in the background, 6 at a time, one request each."""
        emitter = _CheckEmitter()
        emitter.result.connect(on_result)
        emitter.done.connect(on_done)
        self._check_emitters.add(emitter)

        def work() -> None:
            try:
                with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_CHECKS, max(1, len(accounts)))) as pool:
                    futures = {pool.submit(check_account, account): account for account in accounts}
                    for future in as_completed(futures):
                        account = futures[future]
                        try:
                            info = future.result()
                            self._remember_backup_state(account, *classify_backup(info))
                            emitter.result.emit(account, info, "")
                        except Exception as exc:  # noqa: BLE001
                            self._remember_backup_state(account, "invalid", None)
                            emitter.result.emit(account, None, str(exc))
            finally:
                emitter.done.emit()

        threading.Thread(target=work, name="backup-check", daemon=True).start()
        emitter.done.connect(lambda: self._check_emitters.discard(emitter))

    def _on_playback_finished(
        self,
        ok: bool,
        message: str,
        on_success: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        self._state_store.update(status_text=message)
        if ok:
            on_success(message)
        else:
            on_error(message + " — détails dans le Journal")

    def set_playback_progress_callback(self, callback: Callable[[str], None]) -> None:
        self._on_playback_progress = callback

    def set_auto_retries(self, retries: int) -> None:
        self._config.ui.auto_retries = retries
        self._config_store.save(self._config)

    def refresh_connection_info(self, on_success: Callable[[str], None], on_error: Callable[[str], None]) -> None:
        profile = self._state_store.state.active_profile
        if profile is None:
            return

        def task() -> dict[str, str]:
            return self._service_for(profile).fetch_connection_info(profile)

        def done(info: dict[str, str]) -> None:
            self._state_store.update(credential_info=info)
            cons = info.get("Active/Max Connections", "")
            LOGGER.info("Infos du compte rafraîchies%s", f" : connexions {cons}" if cons else "")
            on_success(f"Compte rafraîchi{f' · connexions {cons}' if cons else ''}")

        worker = TaskWorker(task)
        worker.signals.succeeded.connect(done)
        worker.signals.failed.connect(lambda message: self._on_error(message, on_error))
        self._thread_pool.start(worker)

    def activate_item(
        self,
        tab_name: str,
        item: MediaItem,
        on_success: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        """Handle navigation or playback by item type."""
        if item.item_type in {"series", "season"}:
            self._expand_series_item(tab_name, item, on_success, on_error)
            return
        self.play(item, on_success=on_success, on_error=on_error)

    def _expand_series_item(
        self,
        tab_name: str,
        item: MediaItem,
        on_success: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        profile = self._state_store.state.active_profile
        if profile is None:
            on_error("Pas de connexion active.")
            return
        self._state_store.update(busy=True, status_text=f"Ouverture de {item.name}…")

        def task() -> list[MediaItem]:
            return self._service_for(profile).fetch_series_children(profile, item)

        worker = TaskWorker(task)
        worker.signals.succeeded.connect(
            lambda items: self._on_items_loaded(tab_name, items, on_success, push_stack=True),
        )
        worker.signals.failed.connect(lambda message: self._on_error(message, on_error))
        worker.signals.finished.connect(lambda: self._state_store.update(busy=False))
        self._thread_pool.start(worker)

    def go_back(self, tab_name: str) -> bool:
        """Pop last media view for a tab."""
        if not self._navigation_stack[tab_name]:
            return False
        previous = self._navigation_stack[tab_name].pop()
        current = dict(self._state_store.state.current_items)
        current[tab_name] = previous
        verification = dict(self._state_store.state.verification_results)
        verification[tab_name] = {}
        self._state_store.update(
            current_items=current,
            verification_results=verification,
            status_text="Retour.",
        )
        return True

    def verify_tab_streams(
        self,
        tab_name: str,
        on_success: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        """Verify current tab streams for reachability and A/V."""
        profile = self._state_store.state.active_profile
        if profile is None:
            on_error("Pas de connexion active.")
            return
        tab_items = self._state_store.state.current_items.get(tab_name, [])
        if not tab_items:
            on_error("Rien à vérifier dans cette liste.")
            return
        if self._state_store.state.busy:
            on_error("Patiente, une opération est déjà en cours.")
            return
        self._state_store.update(busy=True, status_text=f"Vérification de {len(tab_items)} flux…")

        def task() -> dict[str, str]:
            service = self._service_for(profile)
            
            # Real-time verification callback
            def on_verification_update(item_id: str, status: str, verified_count: int, total_count: int):
                # Update verification results in real-time
                verification = dict(self._state_store.state.verification_results)
                if tab_name not in verification:
                    verification[tab_name] = {}
                verification[tab_name][item_id] = status
                
                # Update status text with progress
                progress_percent = (verified_count / total_count) * 100
                status_text = f"Vérification {verified_count}/{total_count} ({progress_percent:.0f} %)"
                
                self._state_store.update(
                    verification_results=verification,
                    status_text=status_text
                )
            
            return self._verifier.verify_items(service, profile, tab_items, progress_callback=on_verification_update)

        worker = TaskWorker(task)
        worker.signals.succeeded.connect(
            lambda results: self._on_verify_done(tab_name, results, on_success),
        )
        worker.signals.failed.connect(lambda message: self._on_error(message, on_error))
        worker.signals.finished.connect(lambda: self._state_store.update(busy=False))
        self._thread_pool.start(worker)

    def verify_single_item(
        self,
        tab_name: str,
        item: MediaItem,
        on_success: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        profile = self._state_store.state.active_profile
        if profile is None:
            on_error("Pas de connexion active.")
            return
        if item.item_type not in {"channel", "vod", "episode"}:
            on_error("Cet élément n'est pas un flux lisible.")
            return

        self._state_store.update(
            status_text=f"Vérification de {item.name}…",
            priority_verification_active=True
        )

        def task() -> dict[str, str]:
            service = self._service_for(profile)
            # Increase threads for priority verification
            original_max = self._thread_pool.maxThreadCount()
            self._thread_pool.setMaxThreadCount(original_max + 4)
            try:
                result = self._verifier.verify_item(service, profile, item)
                return {item.id: result.status}
            finally:
                self._thread_pool.setMaxThreadCount(original_max)

        worker = TaskWorker(task)
        worker.signals.succeeded.connect(lambda result_map: self._on_verify_done(tab_name, result_map, on_success))
        worker.signals.failed.connect(lambda message: self._on_error(message, on_error))
        self._thread_pool.start(worker)

    def verify_all_channels(
        self,
        tab_name: str,
        on_success: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        """Verify all channels in the current tab efficiently."""
        profile = self._state_store.state.active_profile
        if profile is None:
            on_error("Pas de connexion active.")
            return

        items = self._state_store.state.current_items.get(tab_name, [])
        if not items:
            on_error("Rien à vérifier dans cette liste.")
            return

        self._state_store.update(status_text=f"Vérification de {len(items)} flux…")

        def task() -> dict[str, str]:
            service = self._service_for(profile)
            # Multiply threads by 2 for verify all requests
            original_max = self._thread_pool.maxThreadCount()
            self._thread_pool.setMaxThreadCount(original_max * 2)
            try:
                # Use optimized worker count for large batches
                worker_count = min(48, max(16, len(items) // 5))
                return self._verifier.verify_items(service, profile, items, workers=worker_count)
            finally:
                self._thread_pool.setMaxThreadCount(original_max)

        worker = TaskWorker(task)
        worker.signals.succeeded.connect(lambda result_map: self._on_verify_done(tab_name, result_map, on_success))
        worker.signals.failed.connect(lambda message: self._on_error(message, on_error))
        self._thread_pool.start(worker)

    def verify_tab(
        self,
        tab_name: str,
        on_success: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        """Verify all channels in a specific tab from menu."""
        self.verify_all_channels(tab_name, on_success, on_error)

    def cancel_verification(
        self,
        on_success: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        """Cancel all ongoing verification processes."""
        try:
            LOGGER.info("Annulation des vérifications")
            # Clear verification queue and stop background verification
            self._state_store.update(
                background_verification_active=False,
                verification_queue=[],
                priority_verification_active=False,
                busy=False
            )
            on_success("Vérifications annulées")
        except Exception as e:
            logger_service.error(f"Failed to cancel verification: {e}")
            on_error(f"Failed to cancel verification: {e}")

    # All logs methods removed for performance

    def request_now_playing(
        self,
        tab_name: str,
        item: MediaItem,
    ) -> None:
        profile = self._state_store.state.active_profile
        if profile is None:
            return
        if item.item_type != "channel":
            return
        cached = self._state_store.state.now_playing.get(tab_name, {}).get(item.id, "")
        if cached:
            return

        def task() -> tuple[str, str]:
            title = self._service_for(profile).fetch_now_playing(profile, item)
            return item.id, title

        worker = TaskWorker(task)
        worker.signals.succeeded.connect(lambda pair: self._on_now_playing(tab_name, pair))
        self._thread_pool.start(worker)

    def _on_now_playing(self, tab_name: str, payload: tuple[str, str]) -> None:
        item_id, title = payload
        if not title:
            return
        now_playing = dict(self._state_store.state.now_playing)
        tab_map = dict(now_playing.get(tab_name, {}))
        tab_map[item_id] = title
        now_playing[tab_name] = tab_map
        self._state_store.update(now_playing=now_playing)

    def _prefetch_now_playing(self, items: list[MediaItem]) -> None:
        for item in items:
            if item.item_type == "channel":
                self.request_now_playing("Live", item)

    def _on_verify_done(
        self,
        tab_name: str,
        results: dict[str, str],
        on_success: Callable[[str], None],
    ) -> None:
        # Update current tab verification results
        verification = dict(self._state_store.state.verification_results)
        verification[tab_name] = results
        
        # Update persistent verification results (survives category changes)
        persistent_results = dict(self._state_store.state.persistent_verification_results)
        persistent_results.update(results)
        
        ok_count = sum(1 for status in results.values() if status.startswith("OK"))
        self._state_store.update(
            verification_results=verification,
            persistent_verification_results=persistent_results,
            status_text=f"Vérification : {ok_count}/{len(results)} joignables.",
        )
        LOGGER.info("Vérification terminée : %d/%d joignables", ok_count, len(results))
        on_success(f"Vérification : {ok_count}/{len(results)} OK")

    def reset_form(self) -> None:
        """Reset state without losing saved profiles."""
        self._state_store.update(
            active_profile=None,
            categories={"Live": [], "Movies": [], "Series": []},
            current_items={"Live": [], "Movies": [], "Series": []},
            verification_results={"Live": {}, "Movies": {}, "Series": {}},
            credential_info={},
            now_playing={"Live": {}, "Movies": {}, "Series": {}},
            status_text="Déconnecté.",
        )
        self._navigation_stack = {"Live": [], "Movies": [], "Series": []}

    def _remember_success(self, credentials: Credentials) -> None:
        LOGGER.debug("Connexion mémorisée : %s", credentials.base_url)
        stamped = Credentials(
            name=credentials.name,
            base_url=credentials.base_url,
            portal_type=credentials.portal_type,
            username=credentials.username,
            password=credentials.password,
            mac_address=credentials.mac_address,
            saved_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        key = (credentials.base_url, credentials.portal_type.value, credentials.username, credentials.mac_address)
        history: list[Credentials] = []
        for entry in self._config.successful_history:
            entry_key = (entry.base_url, entry.portal_type.value, entry.username, entry.mac_address)
            if entry_key != key:
                history.append(entry)
        history.insert(0, stamped)
        self._config.successful_history = history[:20]
        self._config_store.save(self._config)

    def clear_history(self) -> None:
        self._config.successful_history = []
        self._config_store.save(self._config)

    @staticmethod
    def _humanize(message: str) -> str:
        """Turn raw requests/HTTP errors into something readable."""
        import re as _re

        code = _re.search(r"\b(4\d\d|5\d\d) (?:Client|Server) Error", message)
        if code:
            from zone_new_companion.services.playback_monitor import explain_http

            value = int(code.group(1))
            return f"Le serveur a répondu HTTP {value} : {explain_http(value)}"
        lowered = message.lower()
        if "timed out" in lowered or "timeout" in lowered:
            return "Le serveur ne répond pas (délai dépassé)."
        if "name or service not known" in lowered or "getaddrinfo" in lowered or "nameresolution" in lowered:
            return "Serveur introuvable (adresse inconnue)."
        if "connection refused" in lowered or "max retries exceeded" in lowered:
            return "Connexion au serveur impossible."
        return message

    def _on_error(self, message: str, callback: Callable[[str], None]) -> None:
        message = self._humanize(message)
        LOGGER.error("%s", message)
        self._state_store.update(status_text=f"Erreur : {message}")
        callback(message)

    def save_ui_state(self, width: int, height: int) -> None:
        """Persist current window size."""
        self._config.ui.width = width
        self._config.ui.height = height
        self._config_store.save(self._config)
