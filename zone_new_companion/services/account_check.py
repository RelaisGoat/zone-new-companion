"""Fast, single-request account check (player_api.php, no retries, no fallbacks).

Used for backup accounts: one GET per account with short timeouts, so checking
many accounts stays quick and a dead server costs a few seconds at most.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests

from zone_new_companion.models import Credentials, PortalType
from zone_new_companion.services.network import normalize_url

TIMEOUT = (4, 8)  # connect, read (seconds)
MAX_PARALLEL = 6
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "*/*"}


class CheckError(Exception):
    pass


def check_account(account: Credentials) -> dict[str, str]:
    """Same keys as XtreamService.fetch_connection_info. Raises CheckError with a readable reason."""
    if account.portal_type == PortalType.M3U:
        return {"Type": "M3U Playlist", "URL": account.base_url}
    if account.portal_type != PortalType.XTREAM:
        raise CheckError("type de compte non vérifiable")
    url = normalize_url(account.base_url, "player_api.php")
    try:
        response = requests.get(
            url,
            params={"username": account.username, "password": account.password},
            headers=_HEADERS,
            timeout=TIMEOUT,
        )
    except requests.Timeout as exc:
        raise CheckError("le serveur ne répond pas") from exc
    except requests.ConnectionError as exc:
        text = str(exc).lower()
        if "name or service not known" in text or "getaddrinfo" in text or "nameresolution" in text:
            raise CheckError("serveur introuvable") from exc
        raise CheckError("connexion au serveur impossible") from exc
    except requests.RequestException as exc:
        raise CheckError(str(exc)) from exc
    if response.status_code >= 400:
        from zone_new_companion.services.playback_monitor import explain_http

        raise CheckError(f"HTTP {response.status_code} : {explain_http(response.status_code)}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise CheckError("réponse illisible (ce n'est pas un serveur Xtream ?)") from exc
    user = payload.get("user_info", {}) if isinstance(payload, dict) else {}
    if not isinstance(user, dict) or str(user.get("auth", "1")) == "0" or not user.get("status"):
        return {"Status": "Unknown"}
    expiry = "Unlimited"
    exp_date = str(user.get("exp_date") or "").strip()
    if exp_date.isdigit():
        expiry = datetime.fromtimestamp(int(exp_date)).astimezone().strftime("%Y-%m-%d %H:%M")
    return {
        "Status": str(user.get("status", "Unknown")),
        "Expiry": expiry,
        "Active/Max Connections": f"{user.get('active_cons', '0')}/{user.get('max_connections', '?')}",
    }


def check_many(accounts: list[Credentials]) -> list[tuple[dict[str, str] | None, str]]:
    """Check accounts in parallel (bounded). Returns (info, error) per account, same order."""

    def one(account: Credentials) -> tuple[dict[str, str] | None, str]:
        try:
            return check_account(account), ""
        except CheckError as exc:
            return None, str(exc)
        except Exception as exc:  # noqa: BLE001
            return None, str(exc)

    if not accounts:
        return []
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(accounts))) as pool:
        return list(pool.map(one, accounts))
