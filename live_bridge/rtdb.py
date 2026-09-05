"""RTDB read transport for FantaLab live room (Read-Only).

Reads the auction/ and assign/ nodes over plain HTTPS on a per-shard host.
Unauthenticated GET requests; zero sockets required. Compatible with Vercel serverless functions.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from typing import Any
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

#: Firebase regional host; only shard varies.
REGIONAL = "https://fantalab-{shard}.europe-west1.firebasedatabase.app"
#: Default namespace for rooms with db: null
DEFAULT = "https://fantalab-79eaa-default-rtdb.europe-west1.firebasedatabase.app"

DEFAULT_TIMEOUT = 3.5


def shard_url(db: int | str | None) -> str:
    """Resolve Firebase host for a room's shard."""
    if db is None or db == "" or str(db).strip().lower() in ("none", "null", "default", "auto"):
        return DEFAULT
    return REGIONAL.format(shard=str(db).strip())


def node_url(db: int | str | None, path: str) -> str:
    """Build full .json URL for a node path like auction/<room_id>."""
    return f"{shard_url(db)}/{path.strip('/')}.json"


ROOM_SHARD_CACHE: dict[str, Any] = {}


def read_snapshot(
    db: int | str | None,
    path: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any] | None:
    """One-shot GET of a node -> dict snapshot, or None if empty/absent.
    
    Firebase returns literal 'null' for an absent or empty node.
    """
    url = node_url(db, path)
    try:
        try:
            resp = requests.get(url, timeout=timeout)
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
            resp = requests.get(url, timeout=timeout, verify=False)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.debug(f"Error reading RTDB node {url}: {exc}")
        return None


def _is_valid_lot(state: dict[str, Any] | None) -> bool:
    """Check if snapshot represents an active player lot (not reset or empty)."""
    if not state or not isinstance(state, dict):
        return False
    if state.get("update_type") == "reset":
        return False
    # If it has player_id or price or timeToPass
    return bool(state.get("player_id") or state.get("price"))


def _probe_shard(s: int | str | None, room_id: str, timeout: float = 2.0) -> tuple[dict[str, Any] | None, str | None, int | str | None, bool]:
    """Probe both auction/ and assign/ on a given shard.
    
    Returns (active_lot_snapshot, node_name, shard, room_exists_here).
    """
    room_exists = False
    for node in ("auction", "assign"):
        snap = read_snapshot(s, f"{node}/{room_id}", timeout=timeout)
        if snap is not None:
            room_exists = True
            if _is_valid_lot(snap):
                return snap, node, s, True
    return None, None, s, room_exists


def read_active_lot(
    db: int | str | None,
    room_id: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[dict[str, Any] | None, str | None, int | str | None]:
    """Read current active lot from auction/ or assign/ node.
    
    Returns (snapshot, node_name, active_shard).
    When db is 'auto' or None, checks cached shard first, then default shard, then probes shards 0..23 concurrently.
    """
    if not room_id:
        return None, None, db

    clean_room = str(room_id).strip()

    # If specific shard given (not auto/None)
    if db is not None and str(db).strip().lower() not in ("auto", "none", "null", ""):
        snap, node, s, exists = _probe_shard(db, clean_room, timeout=timeout)
        if exists:
            ROOM_SHARD_CACHE[clean_room] = db
        return snap, (node or "auction"), db

    # Check memory cache if already resolved
    cached_shard = ROOM_SHARD_CACHE.get(clean_room)
    if cached_shard is not None:
        snap, node, s, exists = _probe_shard(cached_shard, clean_room, timeout=timeout)
        if exists:
            return snap, (node or "auction"), cached_shard

    # Step 1: Probe default shard first
    snap, node, s, exists = _probe_shard(None, clean_room, timeout=1.8)
    if exists:
        ROOM_SHARD_CACHE[clean_room] = "default"
        return snap, (node or "auction"), "default"

    # Step 2: Concurrently probe numeric shards 0..23
    candidate_shards = [str(i) for i in range(24)]
    detected_shard = None

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {
            executor.submit(_probe_shard, sh, clean_room, 2.0): sh
            for sh in candidate_shards
        }
        for fut in as_completed(futures):
            try:
                res_snap, res_node, res_shard, room_found = fut.result()
                if room_found:
                    ROOM_SHARD_CACHE[clean_room] = res_shard
                    detected_shard = res_shard
                if res_snap is not None:
                    executor.shutdown(wait=False, cancel_futures=True)
                    return res_snap, res_node, res_shard
            except Exception:
                pass

    # If room exists on a detected shard but currently idle / reset
    if detected_shard is not None:
        return None, "auction", detected_shard

    # No active lot found across probed shards
    return None, "auction", None
