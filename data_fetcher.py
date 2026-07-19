"""
Collecte de données sportives
Football-Data.org (gratuit, fiable) + The Odds API (cotes 1xBet/Melbet)
"""
import httpx
import asyncio
from datetime import datetime, date, timedelta, timezone
from config import ODDS_API_KEY, FOOTBALL_DATA_KEY
import os
import logging

logger = logging.getLogger(__name__)
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# Compétitions disponibles sur le plan gratuit Football-Data.org
COMPETITIONS = {
    "PL":  "Premier League",
    "PD":  "La Liga",
    "BL1": "Bundesliga",
    "SA":  "Serie A",
    "FL1": "Ligue 1",
    "CL":  "Champions League",
    "EC":  "Euro",
    "WC":  "Coupe du Monde",
}

ODDS_SPORT_KEYS = [
    "soccer_epl",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
]

# ══════════════════════════════════════════
#  CACHE SYSTÈME
# ══════════════════════════════════════════
_cache = {}
CACHE_DURATION_MINUTES = 30


def _get_cache(key: str, max_minutes: int = None):
    if max_minutes is None:
        max_minutes = CACHE_DURATION_MINUTES
    if key in _cache:
        cached_at, value = _cache[key]
        age_minutes = (datetime.now() - cached_at).total_seconds() / 60
        if age_minutes < max_minutes:
            logger.info(f"📦 Cache hit: {key} ({age_minutes:.0f}min)")
            return value
    return None


def _set_cache(key: str, value):
    _cache[key] = (datetime.now(), value)
    logger.info(f"💾 Cache set: {key}")


async def fetch(url, headers=None, params=None):
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return {}


# ══════════════════════════════════════════
#  MATCHS - Football-Data.org
# ══════════════════════════════════════════

async def get_matches_for_date(target_date: str) -> list:
    """Récupère les matchs pour une date donnée via Football-Data.org"""
    if not FOOTBALL_DATA_KEY:
        logger.warning("⚠️ FOOTBALL_DATA_KEY non configurée, impossible de récupérer les matchs via Football-Data.org")
        return []

    cache_key = f"matches_{target_date}"
    # Cache 15 minutes pour les matchs du jour
    cached = _get_cache(cache_key, max_minutes=15)
    if cached is not None:
        return cached

    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    matches = []

    for comp_code, comp_name in COMPETITIONS.items():
        try:
            data = await fetch(
                f"{FOOTBALL_DATA_BASE}/competitions/{comp_code}/matches",
                headers=headers,
                params={"dateFrom": target_date, "dateTo": target_date}
            )
            for m in data.get("matches", []):
                home = m.get("homeTeam", {})
                away = m.get("awayTeam", {})
                score = m.get("score", {})
                full_time = score.get("fullTime", {})
                status = m.get("status", "SCHEDULED")

                matches.append({
                    "match_id": str(m.get("id", "")),
                    "sport": "football",
                    "home_team": home.get("name", ""),
                    "away_team": away.get("name", ""),
                    "home_team_id": home.get("id", 0),
                    "away_team_id": away.get("id", 0),
                    "league": comp_name,
                    "league_code": comp_code,
                    "country": m.get("area", {}).get("name", ""),
                    "kickoff": m.get("utcDate", ""),
                    "status": status,
                    "home_score": full_time.get("home"),
                    "away_score": full_time.get("away"),
                    "is_popular": True,
                })
            await asyncio.sleep(0.5)  # Respecter rate limit
        except Exception as e:
            logger.error(f"Error fetching {comp_code}: {e}")

    logger.info(f"✅ {len(matches)} matchs récupérés pour {target_date}")
    _set_cache(cache_key, matches)
    return matches


async def get_team_recent_form(team_id: int, comp_code: str = "PL") -> dict:
    """Récupère la forme récente d'une équipe."""
    cache_key = f"form_{team_id}"
    cached = _get_cache(cache_key)
    if cached is not None:
        return cached

    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    data = await fetch(
        f"{FOOTBALL_DATA_BASE}/teams/{team_id}/matches",
        headers=headers,
        params={"status": "FINISHED", "limit": 5}
    )

    form = ""
    home_form = ""
    away_form = ""
    goals_for, goals_against = [], []

    for m in data.get("matches", []):
        home = m.get("homeTeam", {})
        away = m.get("awayTeam", {})
        score = m.get("score", {}).get("fullTime", {})
        is_home = home.get("id") == team_id

        if is_home:
            scored = score.get("home", 0) or 0
            conceded = score.get("away", 0) or 0
            winner = m.get("score", {}).get("winner", "")
            won = winner == "HOME_TEAM"
            draw = winner == "DRAW"
            home_form += "V" if won else ("N" if draw else "D")
        else:
            scored = score.get("away", 0) or 0
            conceded = score.get("home", 0) or 0
            winner = m.get("score", {}).get("winner", "")
            won = winner == "AWAY_TEAM"
            draw = winner == "DRAW"
            away_form += "V" if won else ("N" if draw else "D")

        goals_for.append(scored)
        goals_against.append(conceded)
        form += "V" if won else ("N" if draw else "D")

    goals_for_avg = round(sum(goals_for)/len(goals_for), 2) if goals_for else 1.2
    goals_against_avg = round(sum(goals_against)/len(goals_against), 2) if goals_against else 1.2
    league_avg = 1.35
    result = {
        "form": form,
        "home_form": home_form or form,
        "away_form": away_form or form,
        "goals_for_avg": goals_for_avg,
        "goals_against_avg": goals_against_avg,
        "attack_index": round(goals_for_avg / league_avg, 2),
        "defense_index": round(goals_against_avg / league_avg, 2),
    }
    _set_cache(f"form_{team_id}", result)
    return result


async def get_head_to_head(team1_id: int, team2_id: int) -> list:
    """Récupère l'historique H2H."""
    cache_key = f"h2h_{team1_id}_{team2_id}"
    cached = _get_cache(cache_key, max_minutes=1440)  # Cache 24h
    if cached is not None:
        return cached

    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    data = await fetch(
        f"{FOOTBALL_DATA_BASE}/teams/{team1_id}/matches",
        headers=headers,
        params={"status": "FINISHED", "limit": 10}
    )

    h2h = []
    for m in data.get("matches", []):
        home_id = m.get("homeTeam", {}).get("id")
        away_id = m.get("awayTeam", {}).get("id")
        if team2_id in [home_id, away_id]:
            winner = m.get("score", {}).get("winner", "")
            score_ft = m.get("score", {}).get("fullTime", {})
            home_goals = score_ft.get("home", 0) or 0
            away_goals = score_ft.get("away", 0) or 0
            team1_goals = home_goals if home_id == team1_id else away_goals
            team2_goals = away_goals if home_id == team1_id else home_goals
            home_winner = winner == "HOME_TEAM"
            draw = winner == "DRAW"
            h2h.append({
                "date": m.get("utcDate", ""),
                "home_team_id": home_id,
                "away_team_id": away_id,
                "home_winner": home_winner,
                "draw": draw,
                "team1_was_home": home_id == team1_id,
                "team1_goals": team1_goals,
                "team2_goals": team2_goals,
            })

    _set_cache(cache_key, h2h)
    return h2h


async def get_fixture_result(fixture_id: str) -> dict:
    """Récupère le résultat d'un match terminé."""
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    data = await fetch(f"{FOOTBALL_DATA_BASE}/matches/{fixture_id}", headers=headers)

    if data:
        score = data.get("score", {})
        full_time = score.get("fullTime", {})
        winner = score.get("winner", "")
        return {
            "status": data.get("status", ""),
            "home_score": full_time.get("home", 0),
            "away_score": full_time.get("away", 0),
            "home_winner": winner == "HOME_TEAM",
        }
    return {}


# ══════════════════════════════════════════
#  COTES - The Odds API (1xBet/Melbet)
# ══════════════════════════════════════════

async def get_all_real_odds() -> list:
    cache_key = "all_odds"
    cached = _get_cache(cache_key, max_minutes=120)
    if cached is not None:
        return cached

    all_odds = []
    for sport_key in ODDS_SPORT_KEYS:
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h,totals",
            "oddsFormat": "decimal",
            "bookmakers": "onexbet,melbet",
        }
        data = await fetch(f"{ODDS_API_BASE}/sports/{sport_key}/odds", params=params)
        if isinstance(data, list):
            for event in data:
                match_odds = {
                    "home_team": event.get("home_team", ""),
                    "away_team": event.get("away_team", ""),
                    "kickoff": event.get("commence_time", ""),
                    "sport": sport_key,
                    "bookmakers": {}
                }
                for bm in event.get("bookmakers", []):
                    bm_name = "1xBet" if bm["key"] == "onexbet" else "Melbet"
                    match_odds["bookmakers"][bm_name] = {"h2h": {}, "totals": {}}
                    for market in bm.get("markets", []):
                        if market["key"] == "h2h":
                            for o in market["outcomes"]:
                                match_odds["bookmakers"][bm_name]["h2h"][o["name"]] = o["price"]
                        elif market["key"] == "totals":
                            for o in market["outcomes"]:
                                k = f"{o['name']}_{o.get('point', 2.5)}"
                                match_odds["bookmakers"][bm_name]["totals"][k] = o["price"]
                all_odds.append(match_odds)
        await asyncio.sleep(0.5)

    logger.info(f"✅ {len(all_odds)} événements avec cotes 1xBet/Melbet")
    _set_cache("all_odds", all_odds)
    return all_odds


def find_best_odds(odds_data, home_team, away_team):
    best = {
        "1": {"odds": 0, "bookmaker": None},
        "X": {"odds": 0, "bookmaker": None},
        "2": {"odds": 0, "bookmaker": None},
        "Over_2.5": {"odds": 0, "bookmaker": None},
        "Under_2.5": {"odds": 0, "bookmaker": None},
    }
    home_l = home_team.lower().strip()
    away_l = away_team.lower().strip()

    for event in odds_data:
        ev_home = event.get("home_team", "").lower().strip()
        ev_away = event.get("away_team", "").lower().strip()
        if not (home_l in ev_home or ev_home in home_l or
                away_l in ev_away or ev_away in away_l):
            continue
        for bm_name, bm_data in event.get("bookmakers", {}).items():
            for team, odds_val in bm_data.get("h2h", {}).items():
                tl = team.lower()
                if tl in ev_home or ev_home in tl:
                    if odds_val > best["1"]["odds"]:
                        best["1"] = {"odds": odds_val, "bookmaker": bm_name}
                elif "draw" in tl:
                    if odds_val > best["X"]["odds"]:
                        best["X"] = {"odds": odds_val, "bookmaker": bm_name}
                elif tl in ev_away or ev_away in tl:
                    if odds_val > best["2"]["odds"]:
                        best["2"] = {"odds": odds_val, "bookmaker": bm_name}
            for key, odds_val in bm_data.get("totals", {}).items():
                if "Over" in key and "2.5" in key:
                    if odds_val > best["Over_2.5"]["odds"]:
                        best["Over_2.5"] = {"odds": odds_val, "bookmaker": bm_name}
                elif "Under" in key and "2.5" in key:
                    if odds_val > best["Under_2.5"]["odds"]:
                        best["Under_2.5"] = {"odds": odds_val, "bookmaker": bm_name}
    return best


async def get_full_match_data(match, all_odds):
    home_id = match.get("home_team_id")
    away_id = match.get("away_team_id")

    # Séquentiel pour respecter le rate limit (10 req/min)
    if home_id and away_id:
        home_form = await get_team_recent_form(home_id)
        await asyncio.sleep(1)
        away_form = await get_team_recent_form(away_id)
        await asyncio.sleep(1)
        h2h = await get_head_to_head(home_id, away_id)
        await asyncio.sleep(1)
    else:
        # Si pas d'IDs équipe (source The Odds API), on utilise les stats par défaut
        home_form = {
            "form": "", "home_form": "", "away_form": "",
            "goals_for_avg": 1.35, "goals_against_avg": 1.35,
            "attack_index": 1.0, "defense_index": 1.0,
        }
        away_form = {
            "form": "", "home_form": "", "away_form": "",
            "goals_for_avg": 1.35, "goals_against_avg": 1.35,
            "attack_index": 1.0, "defense_index": 1.0,
        }
        h2h = []

    real_odds = find_best_odds(all_odds, match["home_team"], match["away_team"])
    odds_map = {}
    if real_odds["1"]["odds"] > 0:
        odds_map["1"] = real_odds["1"]["odds"]
        odds_map["1_bookmaker"] = real_odds["1"]["bookmaker"]
    if real_odds["X"]["odds"] > 0:
        odds_map["X"] = real_odds["X"]["odds"]
    if real_odds["2"]["odds"] > 0:
        odds_map["2"] = real_odds["2"]["odds"]
        odds_map["2_bookmaker"] = real_odds["2"]["bookmaker"]
    if real_odds["Over_2.5"]["odds"] > 0:
        odds_map["Over 2.5"] = real_odds["Over_2.5"]["odds"]
    if real_odds["Under_2.5"]["odds"] > 0:
        odds_map["Under 2.5"] = real_odds["Under_2.5"]["odds"]
    if odds_map.get("1") and odds_map.get("X"):
        odds_map["1X"] = round(1 / (1 / odds_map["1"] + 1 / odds_map["X"]), 2)
    if odds_map.get("2") and odds_map.get("X"):
        odds_map["X2"] = round(1 / (1 / odds_map["2"] + 1 / odds_map["X"]), 2)

    return {
        **match,
        "home_stats": home_form,
        "away_stats": away_form,
        "h2h": h2h,
        "home_injuries": [],
        "away_injuries": [],
        "odds": odds_map,
        "has_real_odds": len(odds_map) > 0,
    }


async def get_matches_today():
    today = date.today().strftime("%Y-%m-%d")
    tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")

    today_matches = await get_matches_for_date(today)

    FINISHED = ["FINISHED", "AWARDED", "CANCELLED", "POSTPONED",
                "IN_PLAY", "PAUSED", "HALFTIME"]

    # Filtrer les matchs terminés ET les matchs dont l'heure est passée
    from datetime import datetime as dt, timezone
    now_utc = dt.now(timezone.utc)

    upcoming = []
    for m in today_matches:
        if m["status"] in FINISHED:
            continue
        try:
            kickoff = dt.fromisoformat(m["kickoff"].replace("Z", "+00:00"))
            if kickoff > now_utc:
                upcoming.append(m)
        except Exception:
            if m["status"] not in FINISHED:
                upcoming.append(m)

    if len(upcoming) < 3:
        logger.info("⚠️ Peu de matchs à venir aujourd'hui, ajout de demain...")
        tomorrow_matches = await get_matches_for_date(tomorrow)
        tomorrow_upcoming = []
        for m in tomorrow_matches:
            if m["status"] not in FINISHED:
                tomorrow_upcoming.append(m)
        return upcoming + tomorrow_upcoming

    return upcoming

def _matches_from_odds(odds_data: list) -> list:
    """Fallback : construit une liste de matchs depuis les cotes The Odds API."""
    matches = []
    seen = set()
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=90)
    league_map = {
        "soccer_epl": "Premier League",
        "soccer_france_ligue_one": "Ligue 1",
        "soccer_uefa_champs_league": "Champions League",
        "soccer_spain_la_liga": "La Liga",
        "soccer_germany_bundesliga": "Bundesliga",
        "soccer_italy_serie_a": "Serie A",
    }
    for event in odds_data:
        kickoff = event.get("kickoff", "")
        if not kickoff:
            continue
        try:
            ko = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
        except Exception:
            continue
        if not (now <= ko <= cutoff):
            continue
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        if not home or not away:
            continue
        key = (home.lower(), away.lower())
        if key in seen:
            continue
        seen.add(key)
        sport = event.get("sport", "")
        matches.append({
            "match_id": event.get("match_id") or f"{home.lower()}_{away.lower()}_{kickoff}",
            "sport": "football",
            "home_team": home,
            "away_team": away,
            "home_team_id": None,
            "away_team_id": None,
            "league": league_map.get(sport, "Football"),
            "league_code": sport,
            "country": "World",
            "kickoff": kickoff,
            "status": "SCHEDULED",
            "home_score": None,
            "away_score": None,
            "is_popular": True,
        })
    return matches


async def fetch_todays_data_with_odds():
    # Cache basé sur l'heure (se renouvelle toutes les 15 minutes)
    from datetime import datetime as _dt
    slot = _dt.now().minute // 15
    cache_key = f"today_full_{date.today()}_{_dt.now().hour}_{slot}"
    cached = _get_cache(cache_key, max_minutes=15)
    if cached is not None:
        return cached

    logger.info("📡 Récupération des données du jour...")

    if not FOOTBALL_DATA_KEY:
        logger.warning("⚠️ FOOTBALL_DATA_KEY non configurée, utilisation du fallback The Odds API")

    try:
        matches = await get_matches_today()
    except Exception as e:
        logger.error(f"Error getting matches: {e}")
        matches = []

    try:
        all_odds = await get_all_real_odds()
    except Exception as e:
        logger.error(f"Error getting odds: {e}")
        all_odds = []

    # Fallback : si Football-Data n'a rien retourné, on utilise The Odds API
    if not matches and all_odds:
        logger.info("⚠️ Football-Data vide, fallback sur The Odds API pour la liste des matchs")
        matches = _matches_from_odds(all_odds)

    # Si toujours pas de matchs → retourner vide proprement
    if not matches:
        return {"matches": [], "all_odds": all_odds,
                "fetched_at": datetime.now().isoformat()}

    # Trier par date de coup d'envoi avant d'enrichir
    matches = sorted(matches, key=lambda m: m.get("kickoff", ""))

    # Enrichir seulement le premier match pour économiser le rate limit
    # Les autres matchs sont affichés avec les cotes seulement
    enriched = []
    for i, match in enumerate(matches[:5]):
        try:
            if i == 0:
                # Enrichissement complet pour le premier match seulement
                full = await get_full_match_data(match, all_odds)
                enriched.append(full)
            else:
                # Pour les autres: juste les cotes, pas de forme ni H2H
                real_odds = find_best_odds(all_odds, match["home_team"], match["away_team"])
                odds_map = {}
                if real_odds["1"]["odds"] > 0:
                    odds_map["1"] = real_odds["1"]["odds"]
                    odds_map["1_bookmaker"] = real_odds["1"]["bookmaker"]
                if real_odds["X"]["odds"] > 0:
                    odds_map["X"] = real_odds["X"]["odds"]
                if real_odds["2"]["odds"] > 0:
                    odds_map["2"] = real_odds["2"]["odds"]
                    odds_map["2_bookmaker"] = real_odds["2"]["bookmaker"]
                enriched.append({
                    **match,
                    "odds": odds_map,
                    "has_real_odds": len(odds_map) > 0,
                    "home_stats": {"form": "", "goals_for_avg": 1.3, "goals_against_avg": 1.2},
                    "away_stats": {"form": "", "goals_for_avg": 1.1, "goals_against_avg": 1.3},
                    "h2h": [],
                    "home_injuries": [],
                    "away_injuries": [],
                })
        except Exception as e:
            logger.error(f"Error enriching {match.get('match_id', '?')}: {e}")
            enriched.append({**match, "odds": {}, "has_real_odds": False,
                             "home_stats": {}, "away_stats": {}, "h2h": [],
                             "home_injuries": [], "away_injuries": []})

    logger.info(f"✅ {len(enriched)} matchs prêts")
    result = {"matches": enriched, "all_odds": all_odds,
              "fetched_at": datetime.now().isoformat()}
    _set_cache(cache_key, result)
    return result


def calculate_implied_probability(odds):
    return round((1 / odds) * 100, 2) if odds > 1 else 0.0


def calculate_value_bet(our_prob, bookmaker_odds):
    if bookmaker_odds <= 1:
        return -1.0
    return round((our_prob / 100) * bookmaker_odds - 1, 3)


def format_kickoff(kickoff_str):
    try:
        dt = datetime.fromisoformat(kickoff_str.replace("Z", "+00:00"))
        return dt.strftime("%d/%m à %Hh%M")
    except Exception:
        return "Aujourd'hui"
