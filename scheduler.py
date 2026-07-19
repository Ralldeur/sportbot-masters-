"""
Scheduler - Tâches automatiques et vérification des résultats
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from telegram.ext import Application
from telegram.constants import ParseMode
from database import get_pending_bets, update_bet_status, get_connection
from data_fetcher import get_fixture_result

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════
#  VÉRIFICATEUR DE RÉSULTATS
# ══════════════════════════════════════════

async def check_results(app: Application):
    """
    Vérifie automatiquement les résultats de tous les paris en attente.
    Lance une notification à l'utilisateur avec le résultat.
    """
    logger.info("🔍 Vérification des résultats en cours...")
    pending_bets = get_pending_bets()

    if not pending_bets:
        logger.info("✅ Aucun paris en attente.")
        return

    conn = get_connection()
    c = conn.cursor()

    for bet in pending_bets:
        try:
            # Récupérer les matchs individuels du coupon
            from database import USE_POSTGRES
            if USE_POSTGRES:
                c.execute('SELECT * FROM tracked_matches WHERE bet_id = %s', (bet["id"],))
                cols = [desc[0] for desc in c.description]
                tracked = [dict(zip(cols, row)) for row in c.fetchall()]
            else:
                c.execute('SELECT * FROM tracked_matches WHERE bet_id = ?', (bet["id"],))
                tracked = [dict(row) for row in c.fetchall()]

            all_done = True
            all_won = True
            results_detail = []

            for match in tracked:
                if match["status"] != "pending":
                    won = match["status"] == "won"
                    results_detail.append({
                        "match": f"{match['home_team']} vs {match['away_team']}",
                        "status": match["status"],
                        "score": match.get("final_score", "N/A")
                    })
                    if not won:
                        all_won = False
                    continue

                # Vérifier si le match est terminé
                match_id = match["match_id"]

                # Si ID non numérique (ex: "odds_Chelsea_Nottingham")
                # on ne peut pas vérifier le résultat sans vrai ID Football-Data
                if not str(match_id).isdigit():
                    try:
                        from datetime import datetime as dt, timezone
                        kickoff_str = match.get("kickoff", "")
                        if kickoff_str:
                            kickoff = dt.fromisoformat(kickoff_str.replace("Z", "+00:00"))
                            now = dt.now(timezone.utc)
                            # Si le match est passé depuis plus de 2h → supposer terminé
                            from datetime import timedelta
                            if now > kickoff + timedelta(hours=2):
                                logger.info(f"Match {match_id} supposé terminé (ID non numérique)")
                                # On ne peut pas savoir le résultat sans ID
                                # On laisse en pending pour suivi manuel
                                all_done = False
                                continue
                            else:
                                all_done = False
                                continue
                        else:
                            all_done = False
                            continue
                    except Exception as ex:
                        logger.error(f"Error checking kickoff: {ex}")
                        all_done = False
                        continue

                result = await get_fixture_result(str(match_id))
                status = result.get("status", "")

                # Football-Data.org utilise FINISHED, API-Football utilise FT
                if status not in ["FT", "AET", "PEN", "FINISHED", "AWARDED"]:
                    all_done = False
                    continue

                # Déterminer si la sélection est gagnante
                match_result = _evaluate_selection(match["selection"], result)
                match_status = "won" if match_result else "lost"
                final_score = f"{result.get('home_score', '?')}-{result.get('away_score', '?')}"


                # Mettre à jour le match dans la DB
                if USE_POSTGRES:
                    c.execute('''UPDATE tracked_matches
                                 SET status=%s, final_score=%s
                                 WHERE id=%s''',
                              (match_status, final_score, match["id"]))
                else:
                    c.execute('''UPDATE tracked_matches
                                 SET status=?, final_score=?
                                 WHERE id=?''',
                              (match_status, final_score, match["id"]))

                results_detail.append({
                    "match": f"{match['home_team']} vs {match['away_team']}",
                    "status": match_status,
                    "score": final_score
                })

                if not match_result:
                    all_won = False

            conn.commit()

            if all_done:
                # Mettre à jour le statut du coupon
                bet_status = "won" if all_won else "lost"
                notes = json.dumps(results_detail)
                update_bet_status(bet["id"], bet_status, notes)

                # Envoyer la notification à l'utilisateur
                await _notify_bet_result(
                    app, bet["user_id"], bet["id"],
                    bet_status, results_detail, bet
                )

        except Exception as e:
            logger.error(f"Error checking bet {bet['id']}: {e}")

    conn.close()
    logger.info("✅ Vérification des résultats terminée.")


def _evaluate_selection(selection: str, result: dict) -> bool:
    """Détermine si une sélection est gagnante selon le résultat."""
    home_score = result.get("home_score", 0) or 0
    away_score = result.get("away_score", 0) or 0
    winner = result.get("winner")  # True=home, False=away, None=draw

    if selection == "1":
        return winner is True
    elif selection == "2":
        return winner is False
    elif selection == "X":
        return winner is None
    elif selection == "1X":
        return winner is not False
    elif selection == "X2":
        return winner is not True
    elif selection == "Over 2.5":
        return (home_score + away_score) > 2.5
    elif selection == "Under 2.5":
        return (home_score + away_score) <= 2.5
    elif selection == "Over 1.5":
        return (home_score + away_score) > 1.5
    elif selection == "BTTS":
        return home_score > 0 and away_score > 0
    return False


async def _notify_bet_result(app, user_id: int, bet_id: int,
                              status: str, results: list, bet: dict):
    """Envoie une notification Telegram avec le résultat du coupon."""
    status_emoji = "✅ COUPON GAGNÉ!" if status == "won" else "❌ COUPON PERDU"
    status_text = "Félicitations! Ton coupon est passé! 🎉" if status == "won" else "Dommage, le coupon n'est pas passé. Analyse ci-dessous:"

    text = f"""
🎰 *Résultat Coupon #{bet_id}*

{status_emoji}
{status_text}

*Détail des matchs:*
"""
    for r in results:
        m_emoji = "✅" if r["status"] == "won" else "❌"
        text += f"\n{m_emoji} {r['match']} → {r['score']}"

    # Analyse simple du résultat
    text += "\n\n"
    if status == "won":
        text += "💡 *Analyse:* Nos prédictions ont été validées par les résultats réels. Continue à suivre la gestion du risque!\n"
    else:
        losing_matches = [r for r in results if r["status"] == "lost"]
        text += f"💡 *Analyse:* {len(losing_matches)} sélection(s) ont échoué.\n"
        text += "Le sport reste imprévisible. C'est pourquoi nous conseillons des mises limitées.\n"

    text += "\n⚠️ _Joue toujours responsablement. Ne mise que ce que tu peux perdre._"

    try:
        await app.bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error notifying user {user_id}: {e}")


# ══════════════════════════════════════════
#  ALERTES MATCHS DU JOUR
# ══════════════════════════════════════════

async def send_morning_briefing(app: Application):
    """Envoie un briefing matinal avec les matchs importants du jour."""
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT user_id FROM users WHERE notifications_enabled = 1')
    users = [row["user_id"] for row in c.fetchall()]
    conn.close()

    message = (
        "☀️ *BONJOUR! Briefing Sportif du Jour*\n\n"
        "Voici les matchs importants à surveiller:\n\n"
        "⚽ Champions League, Ligue 1, Bundesliga\n"
        "🏀 NBA Playoffs\n"
        "🎾 ATP Masters\n\n"
        "Tape /today pour voir les analyses complètes!\n"
        "Tape /bestbets pour nos meilleures recommandations.\n\n"
        "Bonne chance et reste responsable! 🍀"
    )

    for user_id in users:
        try:
            await app.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
            await asyncio.sleep(0.05)  # Évite le rate limiting
        except Exception as e:
            logger.error(f"Error sending briefing to {user_id}: {e}")


async def send_odds_change_alerts(app: Application):
    """Détecte et notifie les changements significatifs de cotes."""
    # En prod: comparer les cotes actuelles vs cotes sauvegardées
    # Une chute de cote > 15% peut indiquer un mouvement de marché important
    logger.info("📊 Vérification des changements de cotes...")
    # Implémentation selon les données disponibles de l'API


# ══════════════════════════════════════════
#  SETUP DU SCHEDULER
# ══════════════════════════════════════════

def setup_scheduler(app: Application):
    """Configure toutes les tâches planifiées."""
    job_queue = app.job_queue

    # Callback async correct pour python-telegram-bot
    async def morning_briefing_job(context):
        await send_morning_briefing(app)

    async def check_results_job(context):
        await check_results(app)

    async def odds_alerts_job(context):
        await send_odds_change_alerts(app)

    # Briefing matinal à 8h00 (heure Abidjan = UTC+0)
    job_queue.run_daily(
        morning_briefing_job,
        time=datetime.strptime("08:00", "%H:%M").time(),
        name="morning_briefing"
    )

    # Vérification des résultats toutes les 30 minutes
    job_queue.run_repeating(
        check_results_job,
        interval=1800,  # 30 minutes
        first=60,
        name="check_results"
    )

    # Alertes cotes toutes les 2 heures
    job_queue.run_repeating(
        odds_alerts_job,
        interval=7200,
        first=120,
        name="odds_alerts"
    )

    logger.info("✅ Scheduler configuré (briefing 8h, résultats /30min, cotes /2h)")
