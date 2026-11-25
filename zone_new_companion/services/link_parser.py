"""Turn any pasted IPTV link into connection credentials.

Supported inputs (anything a provider usually hands out):

* ``http://host:port/get.php?username=U&password=P&type=m3u_plus``
* ``http://host:port/player_api.php?username=U&password=P``
* ``http://host:port/xmltv.php?username=U&password=P``
* ``http://host:port/live/U/P/123.ts`` (also ``movie/`` and ``series/``)
* ``http://host:port/U/P/123`` (short Xtream stream links)
* ``http://host/playlist.m3u`` / ``.m3u8`` (plain M3U playlist)
* ``http://host/c/`` or ``.../portal.php`` (Stalker portal, MAC required)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from zone_new_companion.models import Credentials, PortalType

_XTREAM_API_FILES = {"get.php", "player_api.php", "xmltv.php", "panel_api.php"}
_XTREAM_STREAM_PREFIXES = {"live", "movie", "series", "timeshift"}


@dataclass(slots=True)
class ParsedLink:
    """Result of parsing a pasted link."""

    portal_type: PortalType | None
    base_url: str = ""
    username: str = ""
    password: str = ""
    playlist_url: str = ""
    needs_mac: bool = False
    description: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.portal_type is not None and not self.error

    def to_credentials(self, mac_address: str = "") -> Credentials:
        if self.portal_type == PortalType.M3U:
            return Credentials(name="Lien collé", base_url=self.playlist_url, portal_type=PortalType.M3U)
        return Credentials(
            name="Lien collé",
            base_url=self.base_url,
            portal_type=self.portal_type or PortalType.XTREAM,
            username=self.username,
            password=self.password,
            mac_address=mac_address,
        )


def _clean(raw: str) -> str:
    text = raw.strip().strip('"').strip("'")
    if text and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
        text = "http://" + text
    # Collapse duplicated slashes in the path (``host//get.php``) but keep ``http://``.
    scheme, sep, rest = text.partition("://")
    rest = re.sub(r"/{2,}", "/", rest)
    return f"{scheme}{sep}{rest}"


def _base(parsed) -> str:
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme or 'http'}://{host}{port}"


def parse_link(raw: str) -> ParsedLink:
    """Detect portal type and extract server / username / password."""
    if not raw or not raw.strip():
        return ParsedLink(portal_type=None, error="")
    text = _clean(raw)
    try:
        parsed = urlparse(text)
        _ = parsed.port  # raises on garbage ports
    except ValueError:
        return ParsedLink(portal_type=None, error="Lien illisible.")
    if not parsed.hostname:
        return ParsedLink(portal_type=None, error="Pas de serveur trouvé dans le lien.")

    base = _base(parsed)
    segments = [seg for seg in parsed.path.split("/") if seg]
    filename = segments[-1].lower() if segments else ""
    query = {key.lower(): values[0] for key, values in parse_qs(parsed.query).items() if values}

    # 1. Xtream API style links (credentials in query string)
    if filename in _XTREAM_API_FILES or ("username" in query and "password" in query):
        username = query.get("username", "")
        password = query.get("password", "")
        if not username or not password:
            return ParsedLink(
                portal_type=None,
                base_url=base,
                error="Le lien ne contient pas username et password.",
            )
        return ParsedLink(
            portal_type=PortalType.XTREAM,
            base_url=base,
            username=username,
            password=password,
            description=f"Lien Xtream ({filename or 'API'})",
        )

    # 2. Stalker portals
    lowered_path = parsed.path.lower()
    if lowered_path.rstrip("/").endswith("/c") or "portal.php" in lowered_path or "stalker_portal" in lowered_path:
        return ParsedLink(
            portal_type=PortalType.STALKER,
            base_url=text.rstrip("/"),
            needs_mac=True,
            description="Portail Stalker (adresse MAC requise)",
        )

    # 3. Plain playlists
    if filename.endswith((".m3u", ".m3u8")) and len(segments) < 3:
        return ParsedLink(portal_type=PortalType.M3U, playlist_url=text, description="Playlist M3U")

    # 4. Xtream stream links: /live/U/P/ID.ext or /U/P/ID
    if len(segments) >= 4 and segments[0].lower() in _XTREAM_STREAM_PREFIXES:
        return ParsedLink(
            portal_type=PortalType.XTREAM,
            base_url=base,
            username=segments[1],
            password=segments[2],
            description=f"Lien de chaîne Xtream ({segments[0].lower()})",
        )
    if len(segments) == 3 and re.match(r"^\d+(\.\w+)?$", segments[2]):
        return ParsedLink(
            portal_type=PortalType.XTREAM,
            base_url=base,
            username=segments[0],
            password=segments[1],
            description="Lien de chaîne Xtream (format court)",
        )

    if filename.endswith((".m3u", ".m3u8")):
        return ParsedLink(portal_type=PortalType.M3U, playlist_url=text, description="Playlist M3U")

    return ParsedLink(
        portal_type=None,
        base_url=base,
        error="Format non reconnu. Colle un lien get.php, player_api.php, un lien de chaîne ou une playlist .m3u.",
    )
