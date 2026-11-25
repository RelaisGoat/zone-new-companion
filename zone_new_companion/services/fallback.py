"""Find "the same channel" on another account (backup / fallback accounts).

* Same server  → stream ids belong to the server, not to the account: just swap
  the credentials in the link.
* Other server → download that account's channel list once, then match by EPG
  id (``canalplus360.fr``), then by cleaned-up name ("FR - CANAL+ 360 FHD ◉"
  → "canal+ 360").
"""

from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse

from zone_new_companion.models import Credentials, MediaItem, PortalType
from zone_new_companion.services.network import normalize_url

LOGGER = logging.getLogger("zone.fallback")

_QUALITY_TOKENS = {
    "uhd", "4k", "8k", "fhd", "hd", "sd", "lq", "hq", "hevc", "h265", "h264", "1080p", "720p", "1080", "720",
    "50fps", "60fps", "fps", "backup", "raw", "vip", "multi", "multiaudio", "low", "plus+",
}
_QUALITY_RANK = {"8k": 6, "4k": 5, "uhd": 5, "fhd": 4, "1080p": 4, "1080": 4, "hd": 3, "720p": 3, "720": 3, "sd": 1, "lq": 0}
_COUNTRY_PREFIX = re.compile(r"^\s*[\[(|]?\s*[a-z]{2,3}\s*[\])|:\-–]+\s*", re.IGNORECASE)


def _strip_accents(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def normalize_name(name: str) -> str:
    """'FR - CANAL+ 360 FHD ◉' -> 'canal+ 360'."""
    text = _strip_accents(name).lower()
    text = _COUNTRY_PREFIX.sub("", text)
    text = re.sub(r"[^\w+ ]+", " ", text)  # keep letters, digits, '+' and spaces
    words = [word for word in text.split() if word not in _QUALITY_TOKENS]
    return " ".join(words).strip()


def country_of(name: str) -> str:
    match = _COUNTRY_PREFIX.match(_strip_accents(name))
    return re.sub(r"[^a-z]", "", match.group(0).lower()) if match else ""


def quality_rank(name: str) -> int:
    tokens = re.sub(r"[^\w]+", " ", _strip_accents(name).lower()).split()
    return max((_QUALITY_RANK.get(token, -1) for token in tokens), default=-1)


def _server_key(base_url: str) -> str:
    parsed = urlparse(base_url if "://" in base_url else f"http://{base_url}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"{(parsed.hostname or '').lower()}:{port}"


def account_label(credentials: Credentials) -> str:
    if credentials.name and credentials.name not in ("Lien collé", "Manuel", "Last Used"):
        return credentials.name
    host = credentials.base_url.split("://", 1)[-1].split("/", 1)[0]
    return f"{credentials.username or 'playlist'}@{host}"


@dataclass(slots=True)
class Candidate:
    name: str
    url: str
    epg_id: str


@dataclass(slots=True)
class Resolution:
    url: str
    method: str


class ChannelMatcher:
    """Caches each backup account's channel list for a few hours."""

    CACHE_TTL_S = 6 * 3600

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, list[Candidate]]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------- catalog
    def _catalog(self, backup: Credentials) -> list[Candidate]:
        key = f"{backup.portal_type.value}|{backup.base_url}|{backup.username}"
        with self._lock:
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < self.CACHE_TTL_S:
                return cached[1]
        if backup.portal_type == PortalType.XTREAM:
            candidates = self._xtream_catalog(backup)
        elif backup.portal_type == PortalType.M3U:
            candidates = self._m3u_catalog(backup)
        else:
            candidates = []
        with self._lock:
            self._cache[key] = (time.monotonic(), candidates)
        LOGGER.info("Liste des chaînes de %s : %d chaînes", account_label(backup), len(candidates))
        return candidates

    @staticmethod
    def _xtream_catalog(backup: Credentials) -> list[Candidate]:
        from zone_new_companion.services.xtream_service import XtreamService

        rows = XtreamService._coerce_row_list(  # noqa: SLF001 - reuse the tolerant parser
            XtreamService()._request_api(backup, action="get_live_streams"),  # noqa: SLF001
        )
        candidates = []
        for row in rows:
            stream_id = row.get("stream_id")
            if not stream_id:
                continue
            candidates.append(
                Candidate(
                    name=str(row.get("name", "")),
                    url=normalize_url(backup.base_url, f"live/{backup.username}/{backup.password}/{stream_id}.ts"),
                    epg_id=str(row.get("epg_channel_id") or "").strip().lower(),
                ),
            )
        return candidates

    @staticmethod
    def _m3u_catalog(backup: Credentials) -> list[Candidate]:
        from zone_new_companion.services.network_optimizer import OptimizedSession

        response = OptimizedSession().get(backup.base_url, timeout=30)
        response.raise_for_status()
        candidates: list[Candidate] = []
        pending: tuple[str, str] | None = None
        for raw in response.text.splitlines():
            line = raw.strip()
            if line.startswith("#EXTINF"):
                name = line.rsplit(",", 1)[-1].strip()
                epg = re.search(r'tvg-id="([^"]*)"', line)
                pending = (name, (epg.group(1) if epg else "").strip().lower())
            elif line and not line.startswith("#") and pending:
                candidates.append(Candidate(name=pending[0], url=line, epg_id=pending[1]))
                pending = None
        return candidates

    # ------------------------------------------------------------ matching
    def resolve(self, primary: Credentials, item: MediaItem, backup: Credentials) -> Resolution | None:
        stream_id = str(item.metadata.get("stream_id") or item.id or "").strip()
        if (
            backup.portal_type == PortalType.XTREAM
            and primary.portal_type == PortalType.XTREAM
            and stream_id
            and _server_key(primary.base_url) == _server_key(backup.base_url)
        ):
            url = normalize_url(backup.base_url, f"live/{backup.username}/{backup.password}/{stream_id}.ts")
            return Resolution(url, f"même serveur, chaîne {stream_id}")

        if backup.portal_type == PortalType.STALKER:
            LOGGER.warning("Compte de secours Stalker non pris en charge pour la bascule : %s", account_label(backup))
            return None

        catalog = self._catalog(backup)
        if not catalog:
            return None
        wanted_quality = quality_rank(item.name)

        wanted_country = country_of(item.name)

        def best(matches: list[Candidate]) -> Candidate:
            # Same country, then same quality as the original, then the best available.
            return sorted(
                matches,
                key=lambda c: (
                    country_of(c.name) == wanted_country,
                    quality_rank(c.name) == wanted_quality,
                    quality_rank(c.name),
                ),
                reverse=True,
            )[0]

        epg_id = str(item.metadata.get("epg_channel_id") or item.metadata.get("tvg_id") or "").strip().lower()
        if epg_id:
            by_epg = [c for c in catalog if c.epg_id == epg_id]
            if by_epg:
                pick = best(by_epg)
                return Resolution(pick.url, f"autre serveur, même identifiant EPG {epg_id} → « {pick.name} »")

        wanted = normalize_name(item.name)
        if not wanted:
            return None
        exact = [c for c in catalog if normalize_name(c.name) == wanted]
        if exact:
            pick = best(exact)
            return Resolution(pick.url, f"autre serveur, même nom → « {pick.name} »")
        # Last resort: one name contains the other ("canal+ 360" vs "canal+ 360 france").
        loose = [
            c for c in catalog
            if (n := normalize_name(c.name)) and len(n) >= 4 and (n.startswith(wanted + " ") or wanted.startswith(n + " "))
        ]
        if loose:
            pick = best(loose)
            return Resolution(pick.url, f"autre serveur, nom proche → « {pick.name} »")
        return None


channel_matcher = ChannelMatcher()
