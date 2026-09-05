"""Adapter bridging FantaLab RTDB live events and Fanta-Lab decision engine."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from live_bridge.drain import suggest_push
from live_bridge.rtdb import read_active_lot, read_snapshot

logger = logging.getLogger(__name__)

CACHE_PATH = Path("data/fantalab_listone_cache.json")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def parse_room_input(text: str) -> tuple[str, str | None]:
    """Extract clean room_id/fantaleague_id from bare UUID or full FantaLab URL.
    
    Returns (cleaned_id, error_or_link_type).
    link_type can be 'invite' if user pasted an invitation link instead of room link.
    """
    candidate = text.strip()
    if not candidate:
        return "", "empty"

    if _UUID_RE.match(candidate):
        return candidate, None

    if "fantalab.it" in candidate or "http" in candidate:
        try:
            parsed = urlsplit(candidate)
            query = parse_qs(parsed.query)

            if "invitation_id" in query or "join-asta" in parsed.path:
                inv_id = query.get("invitation_id", [""])[0]
                return inv_id or candidate, "invite"

            if "asta" in query:
                asta_id = query.get("asta", [""])[0]
                if _UUID_RE.match(asta_id):
                    return asta_id, None
        except Exception:
            pass

    return candidate, None


class FantaLabLiveAdapter:
    def __init__(self, cache_file: Path | str = CACHE_PATH):
        self.cache_file = Path(cache_file)
        self.listone_map: dict[str, dict[str, Any]] = {}
        self.name_to_uuid: dict[str, str] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self.listone_map = json.load(f)
                for uuid, entry in self.listone_map.items():
                    name = entry.get("name", "").strip().lower()
                    if name:
                        self.name_to_uuid[name] = uuid
            except Exception as e:
                logger.warning(f"Could not load listone cache: {e}")

    def resolve_player(self, player_id: str) -> dict[str, Any] | None:
        """Resolve a player UUID from FantaLab into known metadata."""
        if not player_id:
            return None
        return self.listone_map.get(str(player_id).strip())

    def get_advisory_snapshot(
        self,
        room_id: str,
        shard: int | str | None = None,
        *,
        active_profile_id: str = "my_team",
        auction_state: dict[str, Any] | None = None,
        all_players_by_name: dict[str, dict[str, Any]] | None = None,
        user_targets: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Fetch current auction or assign node, analyze lot, and compute advisory verdict."""
        if not room_id or not str(room_id).strip():
            return {
                "status": "error",
                "message": "Nessun Room ID specificato.",
                "lot": None,
            }

        cleaned_room_id, link_type = parse_room_input(room_id)

        if link_type == "invite":
            return {
                "status": "warning",
                "message": (
                    "Attenzione: hai inserito un link di invito (/join-asta?invitation_id=...). "
                    "L'ID di invito è diverso dall'ID dell'asta. "
                    "Apri la stanza nel browser su FantaLab e copia l'indirizzo della barra del browser (es. app.fantalab.it/asta?asta=...)."
                ),
                "lot": None,
                "room_id": cleaned_room_id,
            }

        state, node, active_shard = read_active_lot(shard, cleaned_room_id)

        if state is None:
            shard_disp = f"Shard {active_shard}" if active_shard is not None else "Shard Auto (tutti scansionati)"
            return {
                "status": "idle",
                "message": f"Stanza {cleaned_room_id} in ascolto ({shard_disp}). Nessun calciatore in battuta in questo istante.",
                "lot": None,
                "room_id": cleaned_room_id,
                "shard": active_shard,
            }

        player_uuid = state.get("player_id")
        price = state.get("price", 1)
        update_type = state.get("update_type")
        time_to_pass = state.get("timeToPass")
        last_bid_time = state.get("last_bid_time")
        asta_state = state.get("asta_state")
        bidder_team_id = state.get("fantateam_id")
        bidder_user_id = state.get("user_id")

        is_closed = (asta_state == "closed") or (update_type == "close_auction")

        if not player_uuid:
            return {
                "status": "idle",
                "message": "In attesa della chiamata del prossimo calciatore...",
                "lot": None,
                "update_type": update_type,
                "room_id": cleaned_room_id,
                "shard": active_shard,
                "node": node,
            }

        # Resolve player
        fl_meta = self.resolve_player(player_uuid) or {}
        player_name = fl_meta.get("name") or player_uuid
        player_role = fl_meta.get("role") or ""
        player_team = fl_meta.get("team") or ""

        # Match with Fanta-Lab dataset
        dataset_player: dict[str, Any] | None = None
        if all_players_by_name:
            norm_name = player_name.strip().lower()
            dataset_player = all_players_by_name.get(norm_name)
            if not dataset_player:
                for k, v in all_players_by_name.items():
                    if k in norm_name or norm_name in k:
                        dataset_player = v
                        break

        # Defaults from dataset or fallback
        if dataset_player:
            player_name = dataset_player.get("player", player_name)
            player_role = dataset_player.get("role", player_role)
            player_team = dataset_player.get("team", player_team)
            fair_price = (
                dataset_player.get("price_fair_live")
                or dataset_player.get("price_fair_scaled")
                or dataset_player.get("price_fair_1000")
                or 1
            )
            pts_exp = dataset_player.get("pts_exp", 0.0)
            score = dataset_player.get("score_composito", 0.0)
            fascia = dataset_player.get("fascia", 3)
        else:
            fair_price = price
            pts_exp = 0.0
            score = 0.0
            fascia = 4

        # Roster limits & budget of user's team
        user_targets = user_targets or {}
        auction_state = auction_state or {}
        teams = auction_state.get("teams", [])
        my_team = next((t for t in teams if t.get("id") == active_profile_id), teams[0] if teams else None)

        user_budget_remaining = my_team.get("remaining", 500) if my_team else 500
        my_roster = my_team.get("roster", []) if my_team else []
        role_roster_count = len([p for p in my_roster if p.get("role") == player_role])
        rs = auction_state.get("roster_structure") or {"P": 3, "D": 8, "C": 8, "A": 6}
        role_max_slots = rs.get(player_role, 8)
        slots_full = role_roster_count >= role_max_slots

        # Decision Advisory
        target_info = user_targets.get(player_name)
        is_target = target_info is not None

        advisory_action = "PASS"
        advisory_badge = "🔴 PASSA"
        advisory_color = "var(--danger)"
        advisory_text = ""
        max_limit_cr = None

        if slots_full:
            advisory_action = "DROP"
            advisory_badge = "🔴 REPARTO PIENO"
            advisory_color = "var(--danger)"
            advisory_text = f"Hai già completato gli slot di {player_role} ({role_roster_count}/{role_max_slots})."
        elif user_budget_remaining < price + 1:
            advisory_action = "DROP"
            advisory_badge = "🔴 BUDGET ESAURITO"
            advisory_color = "var(--danger)"
            advisory_text = f"Crediti residui ({user_budget_remaining} cr) insufficienti per rilanciare."
        elif is_target:
            target_max = target_info.get("max_price") or int(fair_price * 1.1)
            priority = target_info.get("priority", "T1")
            max_limit_cr = target_max

            if price < target_max:
                advisory_action = "RAISE"
                advisory_badge = f"🟢 RILANCIA ({priority})"
                advisory_color = "var(--success)"
                advisory_text = f"Target {priority}! Prezzo attuale {price} cr < Target Max ({target_max} cr). Consigliato rilanciare."
            else:
                advisory_action = "STOP"
                advisory_badge = "🔴 STOP TARGET"
                advisory_color = "var(--danger)"
                advisory_text = f"Prezzo ({price} cr) ha superato il tuo budget massimo impostato ({target_max} cr)."
        else:
            # Safe push / drain evaluation
            push_sugg = suggest_push(
                player_id=player_uuid,
                our_value=fair_price,
                current_price=price,
                contesters=2,
                in_our_plan=False,
            )

            if price < fair_price * 0.8:
                advisory_action = "BUY"
                advisory_badge = "🟢 CONSIGLIATO (Sottoprezzo)"
                advisory_color = "var(--success)"
                advisory_text = f"Occasione di valore: prezzo attuale {price} cr ben sotto il fair stimato ({int(fair_price)} cr)."
                max_limit_cr = int(fair_price)
            elif push_sugg:
                advisory_action = "PUSH"
                advisory_badge = "🟡 ALZA / PUSH"
                advisory_color = "var(--warning)"
                advisory_text = f"Puoi rilanciare in sicurezza fino a {push_sugg.cap} cr per far spendere i rivali."
                max_limit_cr = push_sugg.cap
            elif price <= fair_price:
                advisory_action = "CONSIDER"
                advisory_badge = "⚪ VALUTA"
                advisory_color = "var(--text-muted)"
                advisory_text = f"Prezzo di mercato coerente ({price} cr vs fair {int(fair_price)} cr)."
                max_limit_cr = int(fair_price)
            else:
                advisory_action = "PASS"
                advisory_badge = "🔴 PASSA"
                advisory_color = "var(--danger)"
                advisory_text = f"Prezzo in battuta ({price} cr) superiore al fair stimato ({int(fair_price)} cr). Lascia agli avversari."
                max_limit_cr = int(fair_price)

        lot_payload = {
            "player_id": player_uuid,
            "player_name": player_name,
            "role": player_role,
            "team": player_team,
            "price": price,
            "current_price": price,
            "fair_price": fair_price,
            "pts_exp": pts_exp,
            "score": score,
            "fascia": fascia,
            "bidder_team_id": bidder_team_id,
            "bidder_user_id": bidder_user_id,
            "time_to_pass": time_to_pass,
            "last_bid_time": last_bid_time,
            "is_closed": is_closed,
            "update_type": update_type,
            "advisory": {
                "action": advisory_action,
                "badge": advisory_badge,
                "color": advisory_color,
                "text": advisory_text,
                "max_limit_cr": max_limit_cr,
                "max_limit": max_limit_cr,
            },
        }

        return {
            "status": "active",
            "room_id": cleaned_room_id,
            "shard": active_shard,
            "node": node,
            "lot": lot_payload,
        }
