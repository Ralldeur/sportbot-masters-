"""
Moteur de prédiction sportive
Logique statistique + scoring multi-facteurs
"""
import math
from typing import Optional
from dataclasses import dataclass
from data_fetcher import calculate_implied_probability, calculate_value_bet
import logging

logger = logging.getLogger(__name__)


@dataclass
class Prediction:
    match_id: str
    sport: str
    home_team: str
    away_team: str
    home_win_prob: float      # % probabilité victoire domicile
    draw_prob: float          # % nul (football)
    away_win_prob: float      # % probabilité victoire extérieur
    predicted_score: str      # ex: "2-1"
    best_selection: str       # Meilleure sélection recommandée
    best_odds: float
    value_bet: float          # >0 = value bet
    confidence: float         # 0-100
    risk_level: str           # faible / moyen / élevé / tres_eleve
    justification: list       # Liste de raisons
    stake_pct: float          # % bankroll conseillé


# ══════════════════════════════════════════
#  MODÈLE STATISTIQUE PRINCIPAL
# ══════════════════════════════════════════

class PredictionEngine:

    # Moyenne de buts attendus par match dans les grands championnats
    LEAGUE_AVG_GOALS = 1.35
    # Poids de fusion modèle Poisson / marché (0.65 / 0.35)
    MODEL_BLEND = 0.65

    def __init__(self):
        self.model_version = "2.0.0"

    def predict_football(self, match_data: dict) -> Prediction:
        """
        Prédit le résultat d'un match de football.
        
        Modèle amélioré :
        - xG multiplicatif (attaque * défense adverse)
        - Distribution de Poisson pour 1/X/2
        - Fusion avec les probabilités implicites du marché
        - Forme domicile / extérieur séparée
        - H2H pondéré par récence et différence de buts
        """
        home = match_data.get("home_stats", {})
        away = match_data.get("away_stats", {})
        h2h = match_data.get("h2h", [])
        home_injuries = match_data.get("home_injuries", [])
        away_injuries = match_data.get("away_injuries", [])
        odds_map = match_data.get("odds", {})

        has_full_stats = bool(home and away)
        has_odds = bool(odds_map)

        # ── 1. SCORES DE FORME ─────────────────────
        home_form_score = self._form_score(
            home.get("home_form", home.get("form", "")),
            home.get("goals_for_avg", self.LEAGUE_AVG_GOALS),
            home.get("goals_against_avg", self.LEAGUE_AVG_GOALS)
        )
        away_form_score = self._form_score(
            away.get("away_form", away.get("form", "")),
            away.get("goals_for_avg", self.LEAGUE_AVG_GOALS),
            away.get("goals_against_avg", self.LEAGUE_AVG_GOALS)
        )

        # ── 2. INDICES OFFENSIFS / DÉFENSIFS ───────
        home_attack = home.get("attack_index",
                              home.get("goals_for_avg", self.LEAGUE_AVG_GOALS) / self.LEAGUE_AVG_GOALS)
        home_defense = home.get("defense_index",
                                home.get("goals_against_avg", self.LEAGUE_AVG_GOALS) / self.LEAGUE_AVG_GOALS)
        away_attack = away.get("attack_index",
                              away.get("goals_for_avg", self.LEAGUE_AVG_GOALS) / self.LEAGUE_AVG_GOALS)
        away_defense = away.get("defense_index",
                                away.get("goals_against_avg", self.LEAGUE_AVG_GOALS) / self.LEAGUE_AVG_GOALS)

        # ── 3. xG DE BASE (modèle multiplicatif) ───
        home_xg = self.LEAGUE_AVG_GOALS * home_attack * away_defense
        away_xg = self.LEAGUE_AVG_GOALS * away_attack * home_defense

        # ── 4. AJUSTEMENTS CONTEXTUELS ─────────────
        key_players_home = sum(1 for p in home_injuries if p.get("is_key_player"))
        key_players_away = sum(1 for p in away_injuries if p.get("is_key_player"))
        h2h_bonus = self._h2h_analysis(h2h, match_data["home_team"])

        # Avantage domicile + forme + blessures + H2H
        home_xg *= (1 + (home_form_score - 50) / 200 + 0.06)
        away_xg *= (1 + (away_form_score - 50) / 200 - 0.04)
        home_xg -= key_players_home * 0.12
        away_xg -= key_players_away * 0.10
        home_xg += h2h_bonus / 100
        away_xg -= h2h_bonus / 100

        home_xg = max(0.1, round(home_xg, 2))
        away_xg = max(0.1, round(away_xg, 2))

        # ── 5. PROBABILITÉS PAR POISSON ────────────
        poisson_probs = self._poisson_match_probabilities(home_xg, away_xg)

        # ── 6. FUSION AVEC LE MARCHÉ ───────────────
        final_probs = self._blend_with_market(poisson_probs, odds_map)

        home_prob = round(max(5, final_probs["1"] * 100), 1)
        draw_prob = round(max(5, final_probs["X"] * 100), 1)
        away_prob = round(max(5, final_probs["2"] * 100), 1)

        # Normalisation à 100%
        total_prob = home_prob + draw_prob + away_prob
        home_prob = round(home_prob / total_prob * 100, 1)
        draw_prob = round(draw_prob / total_prob * 100, 1)
        away_prob = round(max(5, 100 - home_prob - draw_prob), 1)

        # ── 7. SCORE PRÉDIT ────────────────────────
        home_goals = round(home_xg)
        away_goals = round(away_xg)
        predicted_score = f"{home_goals}-{away_goals}"

        # ── 8. SÉLECTION RECOMMANDÉE ───────────────
        probs = {
            "1": home_prob,
            "X": draw_prob,
            "2": away_prob,
            "1X": home_prob + draw_prob,
            "X2": draw_prob + away_prob,
        }
        best_selection = max(probs, key=probs.get)
        best_prob = probs[best_selection]

        # ── 9. COTES ET VALUE BET ─────────────────
        best_odds = odds_map.get(best_selection)
        if best_odds is None and best_selection == "1X" and "1" in odds_map and "X" in odds_map:
            best_odds = 1 / (1 / odds_map["1"] + 1 / odds_map["X"])
        elif best_odds is None and best_selection == "X2" and "2" in odds_map and "X" in odds_map:
            best_odds = 1 / (1 / odds_map["2"] + 1 / odds_map["X"])
        best_odds = round(best_odds, 2) if best_odds is not None else 1.5
        value = calculate_value_bet(best_prob, best_odds)

        # ── 10. CONFIANCE, RISQUE ET MISE ───────────
        confidence = self._compute_confidence(
            best_prob, home_form_score, away_form_score, h2h,
            has_odds=has_odds, has_full_stats=has_full_stats
        )
        risk_level = self._risk_level(best_odds, confidence)
        stake_pct = self._kelly_stake(best_prob / 100, best_odds)

        # ── 11. JUSTIFICATION ────────────────────
        justification = self._build_justification(
            home=match_data["home_team"],
            away=match_data["away_team"],
            home_form=home.get("home_form", home.get("form", "N/A")),
            away_form=away.get("away_form", away.get("form", "N/A")),
            home_xg=home_xg,
            away_xg=away_xg,
            h2h_bonus=h2h_bonus,
            home_injuries=len(home_injuries),
            away_injuries=len(away_injuries),
            value=value
        )

        return Prediction(
            match_id=match_data["match_id"],
            sport="football",
            home_team=match_data["home_team"],
            away_team=match_data["away_team"],
            home_win_prob=home_prob,
            draw_prob=draw_prob,
            away_win_prob=away_prob,
            predicted_score=predicted_score,
            best_selection=best_selection,
            best_odds=best_odds,
            value_bet=value,
            confidence=confidence,
            risk_level=risk_level,
            justification=justification,
            stake_pct=stake_pct
        )

    def predict_basketball(self, match_data: dict) -> Prediction:
        """Prédiction basketball - basé sur points marqués/encaissés."""
        home_ppg = match_data.get("home_ppg", 105)   # Points par match
        away_ppg = match_data.get("away_ppg", 102)
        home_form = self._form_score(match_data.get("home_form", ""))
        away_form = self._form_score(match_data.get("away_form", ""))

        home_prob = 50 + (home_ppg - away_ppg) * 0.8 + (home_form - away_form) * 0.5 + 5
        home_prob = max(20, min(80, home_prob))
        away_prob = 100 - home_prob

        total_points = home_ppg + away_ppg
        over_under_line = match_data.get("ou_line", total_points)
        ou_selection = "Over" if total_points > over_under_line else "Under"
        best_prob = home_prob if home_prob > away_prob else away_prob
        best_selection = "1" if home_prob > away_prob else "2"
        best_odds = match_data.get("odds", {}).get(best_selection, 1.80)
        value = calculate_value_bet(best_prob, best_odds)

        return Prediction(
            match_id=match_data["match_id"],
            sport="basketball",
            home_team=match_data["home_team"],
            away_team=match_data["away_team"],
            home_win_prob=home_prob,
            draw_prob=0,
            away_win_prob=away_prob,
            predicted_score=f"{round(home_ppg)}-{round(away_ppg)}",
            best_selection=best_selection,
            best_odds=best_odds,
            value_bet=value,
            confidence=self._compute_confidence(best_prob, home_form, away_form, []),
            risk_level=self._risk_level(best_odds, best_prob),
            justification=[
                f"📊 Moy. points {match_data['home_team']}: {home_ppg:.1f}/match",
                f"📊 Moy. points {match_data['away_team']}: {away_ppg:.1f}/match",
                f"🏠 Avantage domicile estimé"
            ],
            stake_pct=self._kelly_stake(best_prob / 100, best_odds)
        )

    def predict_mma(self, match_data: dict) -> Prediction:
        """Prédiction MMA/UFC - basé sur stats de combat."""
        fighter1 = match_data.get("fighter1", {})
        fighter2 = match_data.get("fighter2", {})

        f1_wins = fighter1.get("wins", 10)
        f1_losses = fighter1.get("losses", 2)
        f2_wins = fighter2.get("wins", 8)
        f2_losses = fighter2.get("losses", 3)

        f1_win_rate = f1_wins / max(1, f1_wins + f1_losses) * 100
        f2_win_rate = f2_wins / max(1, f2_wins + f2_losses) * 100

        # Facteurs MMA: striking accuracy, grappling, reach, récence victoires
        f1_striking = fighter1.get("striking_accuracy", 45)
        f2_striking = fighter2.get("striking_accuracy", 43)

        f1_prob = (f1_win_rate * 0.5 + f1_striking * 0.3 + 20) / 1.2
        f1_prob = max(20, min(80, f1_prob))
        f2_prob = 100 - f1_prob

        best_selection = "1" if f1_prob > f2_prob else "2"
        best_prob = max(f1_prob, f2_prob)
        best_odds = match_data.get("odds", {}).get(best_selection, 1.90)

        return Prediction(
            match_id=match_data["match_id"],
            sport="mma",
            home_team=fighter1.get("name", "Fighter 1"),
            away_team=fighter2.get("name", "Fighter 2"),
            home_win_prob=f1_prob,
            draw_prob=0,
            away_win_prob=f2_prob,
            predicted_score="",
            best_selection=best_selection,
            best_odds=best_odds,
            value_bet=calculate_value_bet(best_prob, best_odds),
            confidence=min(70, best_prob * 0.85),
            risk_level=self._risk_level(best_odds, best_prob),
            justification=[
                f"🥊 {fighter1.get('name')}: {f1_wins}V/{f1_losses}D ({f1_win_rate:.0f}%)",
                f"🥊 {fighter2.get('name')}: {f2_wins}V/{f2_losses}D ({f2_win_rate:.0f}%)",
                f"📊 Striking accuracy: {f1_striking}% vs {f2_striking}%"
            ],
            stake_pct=self._kelly_stake(best_prob / 100, best_odds)
        )

    # ══════════════════════════════════════════
    #  CUSTOM ODDS - Générateur de combinés
    # ══════════════════════════════════════════

    def build_combo(self, target_odds: float, available_matches: list,
                    mode: str = "balanced") -> dict:
        """
        Construit un combiné pour atteindre une cote cible.
        
        mode: 'safe' | 'balanced' | 'aggressive'
        """
        # Déterminer le nombre de sélections selon la cote cible
        n_selections = self._estimate_selections_count(target_odds)

        # Filtrer et scorer les matchs disponibles
        scored = self._score_matches_for_combo(available_matches, mode)

        if len(scored) < n_selections:
            n_selections = len(scored)

        # Construire le combiné optimal
        selected = []
        combo_odds = 1.0
        attempts = 0

        for match in scored:
            if len(selected) >= n_selections:
                break
            if combo_odds * match["odds"] > target_odds * 1.3:
                continue  # Évite de trop dépasser la cote cible

            selected.append(match)
            combo_odds *= match["odds"]
            attempts += 1

        # Ajustement si cote insuffisante
        if combo_odds < target_odds * 0.7 and len(scored) > len(selected):
            remaining = [m for m in scored if m not in selected]
            for m in remaining:
                if combo_odds * m["odds"] <= target_odds * 1.2:
                    selected.append(m)
                    combo_odds *= m["odds"]
                    break

        # Calcul probabilité globale
        combo_prob = 1.0
        for s in selected:
            combo_prob *= (s["probability"] / 100)
        combo_prob *= 100

        risk_level = self._combo_risk_level(combo_odds, len(selected))
        stake_advice = self._combo_stake_advice(risk_level)

        return {
            "selections": selected,
            "total_odds": round(combo_odds, 2),
            "target_odds": target_odds,
            "probability": round(combo_prob, 2),
            "risk_level": risk_level,
            "stake_advice": stake_advice,
            "mode": mode,
            "n_matches": len(selected)
        }

    def _estimate_selections_count(self, target_odds: float) -> int:
        if target_odds <= 5:
            return 2
        elif target_odds <= 10:
            return 3
        elif target_odds <= 25:
            return 4
        elif target_odds <= 50:
            return 5
        elif target_odds <= 100:
            return 7
        else:
            return 10

    def _score_matches_for_combo(self, matches: list, mode: str) -> list:
        """Score et trie les matchs pour la construction du combiné."""
        scored = []
        for m in matches:
            prob = m.get("probability", 50)
            odds = m.get("odds", 1.5)

            if mode == "safe" and odds > 2.5:
                continue  # En mode safe, évite les grosses cotes
            if mode == "aggressive" and odds < 1.5:
                continue  # En mode agressif, évite les trop faibles cotes

            score = prob * 0.7 + (1 / odds) * 30
            scored.append({**m, "score": score})

        return sorted(scored, key=lambda x: x["score"], reverse=True)

    # ══════════════════════════════════════════
    #  MÉTHODES UTILITAIRES
    # ══════════════════════════════════════════

    def _form_score(self, form_str: str, goals_for_avg: float = 1.35,
                    goals_against_avg: float = 1.35) -> float:
        """
        Convertit une chaîne de forme en score (0-100).
        Pondère les matchs récents et intègre la différence de buts moyenne.
        """
        if not form_str:
            return 50.0
        score = 0
        weights = [1.0, 0.9, 0.8, 0.7, 0.6]  # Matchs récents plus importants
        for i, result in enumerate(reversed(form_str[-5:])):
            w = weights[i] if i < len(weights) else 0.5
            if result == "V":
                score += 22 * w
            elif result == "N":
                score += 10 * w
            elif result == "D":
                score -= 5 * w

        # Ajustement selon la différence de buts moyenne
        goal_diff = goals_for_avg - goals_against_avg
        score += max(-15, min(15, goal_diff * 8))

        return max(0, min(100, score))

    def _poisson_prob(self, lambda_val: float, k: int) -> float:
        """Probabilité de Poisson P(X=k) avec lambda."""
        return (lambda_val ** k) * math.exp(-lambda_val) / math.factorial(k)

    def _poisson_match_probabilities(self, home_xg: float, away_xg: float,
                                     max_goals: int = 7) -> dict:
        """
        Retourne les probabilités 1/X/2 via la distribution de Poisson.
        """
        home_prob = draw_prob = away_prob = 0.0
        for h in range(max_goals + 1):
            p_h = self._poisson_prob(home_xg, h)
            for a in range(max_goals + 1):
                p_a = self._poisson_prob(away_xg, a)
                joint = p_h * p_a
                if h > a:
                    home_prob += joint
                elif h == a:
                    draw_prob += joint
                else:
                    away_prob += joint
        total = home_prob + draw_prob + away_prob
        if total > 0:
            home_prob /= total
            draw_prob /= total
            away_prob /= total
        return {"1": home_prob, "X": draw_prob, "2": away_prob}

    def _blend_with_market(self, model_probs: dict, odds_map: dict) -> dict:
        """
        Fusionne les probabilités du modèle avec les probabilités implicites
        du marché (si les cotes 1X2 sont disponibles).
        """
        if not (odds_map and "1" in odds_map and "X" in odds_map and "2" in odds_map):
            return model_probs

        odds_1 = odds_map["1"]
        odds_x = odds_map["X"]
        odds_2 = odds_map["2"]

        if odds_1 <= 1 or odds_x <= 1 or odds_2 <= 1:
            return model_probs

        # Probabilités implicites brutes
        raw_market = {
            "1": 1 / odds_1,
            "X": 1 / odds_x,
            "2": 1 / odds_2,
        }
        margin = sum(raw_market.values())
        market_probs = {k: v / margin for k, v in raw_market.items()}

        blend = self.MODEL_BLEND
        return {
            "1": blend * model_probs["1"] + (1 - blend) * market_probs["1"],
            "X": blend * model_probs["X"] + (1 - blend) * market_probs["X"],
            "2": blend * model_probs["2"] + (1 - blend) * market_probs["2"],
        }

    def _h2h_analysis(self, h2h: list, home_team: str) -> float:
        """
        Analyse l'historique des confrontations directes.
        Prend en compte la récence, le lieu du match, le résultat
        (victoire/nul/défaite) et la différence de buts.
        """
        if not h2h:
            return 0.0

        sorted_h2h = sorted(
            h2h,
            key=lambda x: x.get("date", ""),
            reverse=True
        )

        total_weight = 0.0
        score = 0.0
        for i, m in enumerate(sorted_h2h):
            w = 1.0 if i < 3 else (0.6 if i < 6 else 0.3)

            team1_was_home = m.get("team1_was_home", False)
            home_winner = m.get("home_winner", False)
            draw = m.get("draw", False)

            if draw:
                # Match nul : légère pénalité si H2H très favorable d'habitude,
                # sinon neutre
                margin = m.get("team1_goals", 0) - m.get("team2_goals", 0)
                pass
            elif (home_winner and team1_was_home) or (not home_winner and not team1_was_home):
                # team1 (l'équipe actuellement à domicile) a gagné
                margin = m.get("team1_goals", 0) - m.get("team2_goals", 0)
                score += w * (1.0 + min(abs(margin), 3) * 0.15)
            else:
                # team1 a perdu
                margin = m.get("team2_goals", 0) - m.get("team1_goals", 0)
                score -= w * (1.0 + min(abs(margin), 3) * 0.15)

            total_weight += w

        if total_weight == 0:
            return 0.0
        avg_score = score / total_weight
        return round(max(-10, min(10, avg_score * 7)), 1)

    def _compute_confidence(self, prob: float, home_form: float,
                             away_form: float, h2h: list,
                             has_odds: bool = True, has_full_stats: bool = True) -> float:
        """
        Calcule un niveau de confiance global (0-100).
        Intègre la qualité et la quantité des données disponibles.
        """
        base = prob * 0.55
        form_factor = abs(home_form - away_form) * 0.25
        h2h_factor = min(len(h2h) * 1.5, 12)
        data_score = 0.0
        if has_full_stats:
            data_score += 10
        if has_odds:
            data_score += 10
        if h2h:
            data_score += 8

        confidence = base + form_factor + h2h_factor + data_score
        return round(min(95, max(15, confidence)), 1)

    def _risk_level(self, odds: float, confidence: float) -> str:
        if odds <= 1.80 and confidence >= 65:
            return "faible"
        elif odds <= 2.50 and confidence >= 55:
            return "moyen"
        elif odds <= 5.00:
            return "élevé"
        else:
            return "tres_eleve"

    def _combo_risk_level(self, total_odds: float, n: int) -> str:
        if total_odds <= 5 and n <= 3:
            return "faible"
        elif total_odds <= 20 and n <= 5:
            return "moyen"
        elif total_odds <= 100:
            return "élevé"
        else:
            return "tres_eleve"

    def _kelly_stake(self, prob: float, odds: float, fraction: float = 0.25) -> float:
        """
        Critère de Kelly fractionné pour conseiller la mise.
        Fraction = 25% du Kelly complet (conservateur).
        """
        if odds <= 1:
            return 1.0
        kelly = (prob * odds - 1) / (odds - 1)
        stake = max(0, kelly * fraction * 100)
        return round(min(5, stake), 1)  # Max 5% de la bankroll

    def _combo_stake_advice(self, risk_level: str) -> float:
        stakes = {
            "faible": 3.0,
            "moyen": 2.0,
            "élevé": 1.0,
            "tres_eleve": 0.5
        }
        return stakes.get(risk_level, 1.0)

    def _build_justification(self, **kwargs) -> list:
        reasons = []
        if kwargs.get("home_form"):
            reasons.append(f"📈 Forme {kwargs.get('home', '')}: {kwargs['home_form']}")
        if kwargs.get("away_form"):
            reasons.append(f"📉 Forme {kwargs.get('away', '')}: {kwargs['away_form']}")
        if kwargs.get("home_xg") and kwargs.get("away_xg"):
            reasons.append(
                f"⚡ Buts attendus: {kwargs['home_xg']:.1f} vs {kwargs['away_xg']:.1f}")
        if kwargs.get("h2h_bonus", 0) > 2:
            reasons.append(f"🔄 Historique favorable en H2H (+{kwargs['h2h_bonus']:.0f}pts)")
        if kwargs.get("home_injuries", 0) > 0:
            reasons.append(f"🏥 {kwargs['home_injuries']} blessé(s) domicile")
        if kwargs.get("away_injuries", 0) > 0:
            reasons.append(f"🏥 {kwargs['away_injuries']} blessé(s) extérieur")
        if kwargs.get("value", 0) > 0.05:
            reasons.append(f"💰 VALUE BET détecté (+{kwargs['value']*100:.1f}%)")
        return reasons


# Instance singleton
engine = PredictionEngine()
