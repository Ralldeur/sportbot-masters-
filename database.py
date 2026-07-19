"""
Base de données - PostgreSQL (Railway) + SQLite (local)
Les données persistent même après redéploiement
"""
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Détection automatique: PostgreSQL sur Railway, SQLite en local
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Railway donne parfois "postgres://" au lieu de "postgresql://"
if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
if DATABASE_URL and DATABASE_URL.startswith("postgresql"):
    # PostgreSQL sur Railway
    import psycopg2
    import psycopg2.extras
    USE_POSTGRES = True
    logger.info("✅ Utilisation de PostgreSQL (Railway)")
else:
    # SQLite en local
    import sqlite3
    USE_POSTGRES = False
    DB_PATH = "sportbot.db"
    logger.info("✅ Utilisation de SQLite (local)")


def get_connection():
    """Retourne une connexion à la base de données."""
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn


def init_db():
    """Initialise toutes les tables."""
    # Log pour debug
    logger.info(f"🗄️ DATABASE_URL présente: {bool(DATABASE_URL)}")
    logger.info(f"🗄️ USE_POSTGRES: {USE_POSTGRES}")
    if DATABASE_URL:
        logger.info(f"🗄️ URL commence par: {DATABASE_URL[:20]}...")
    conn = get_connection()
    try:
        if USE_POSTGRES:
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TEXT,
                is_premium INTEGER DEFAULT 0,
                notifications_enabled INTEGER DEFAULT 1,
                language TEXT DEFAULT 'fr',
                bankroll REAL DEFAULT 0,
                total_bets INTEGER DEFAULT 0,
                won_bets INTEGER DEFAULT 0
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS bets (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                created_at TEXT,
                sport TEXT,
                matches TEXT,
                selections TEXT,
                total_odds REAL,
                risk_level TEXT,
                probability REAL,
                stake_advice REAL,
                status TEXT DEFAULT 'pending',
                result_checked_at TEXT,
                notes TEXT
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS tracked_matches (
                id SERIAL PRIMARY KEY,
                bet_id INTEGER,
                match_id TEXT,
                sport TEXT,
                home_team TEXT,
                away_team TEXT,
                selection TEXT,
                odds REAL,
                kickoff TEXT,
                status TEXT DEFAULT 'pending',
                final_score TEXT
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                match_id TEXT,
                notify_at TEXT,
                message TEXT,
                sent INTEGER DEFAULT 0
            )''')
        else:
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TEXT,
                is_premium INTEGER DEFAULT 0,
                notifications_enabled INTEGER DEFAULT 1,
                language TEXT DEFAULT 'fr',
                bankroll REAL DEFAULT 0,
                total_bets INTEGER DEFAULT 0,
                won_bets INTEGER DEFAULT 0
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                created_at TEXT,
                sport TEXT,
                matches TEXT,
                selections TEXT,
                total_odds REAL,
                risk_level TEXT,
                probability REAL,
                stake_advice REAL,
                status TEXT DEFAULT 'pending',
                result_checked_at TEXT,
                notes TEXT
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS tracked_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bet_id INTEGER,
                match_id TEXT,
                sport TEXT,
                home_team TEXT,
                away_team TEXT,
                selection TEXT,
                odds REAL,
                kickoff TEXT,
                status TEXT DEFAULT 'pending',
                final_score TEXT
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                match_id TEXT,
                notify_at TEXT,
                message TEXT,
                sent INTEGER DEFAULT 0
            )''')
        conn.commit()
        logger.info("✅ Base de données initialisée")
    except Exception as e:
        logger.error(f"❌ Erreur init DB: {e}")
        conn.rollback()
    finally:
        conn.close()


def register_user(user_id: int, username: str, first_name: str):
    conn = get_connection()
    try:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute('''INSERT INTO users (user_id, username, first_name, joined_at)
                         VALUES (%s, %s, %s, %s)
                         ON CONFLICT (user_id) DO NOTHING''',
                      (user_id, username, first_name, datetime.now().isoformat()))
        else:
            c.execute('''INSERT OR IGNORE INTO users
                         (user_id, username, first_name, joined_at)
                         VALUES (?, ?, ?, ?)''',
                      (user_id, username, first_name, datetime.now().isoformat()))
        conn.commit()
    except Exception as e:
        logger.error(f"Error register_user: {e}")
        conn.rollback()
    finally:
        conn.close()


def save_bet(user_id: int, bet_data: dict) -> int:
    """Sauvegarde un coupon et retourne son ID."""
    logger.info(f"💾 Sauvegarde coupon pour user {user_id} - USE_POSTGRES={USE_POSTGRES}")
    conn = get_connection()
    try:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute('''INSERT INTO bets
                         (user_id, created_at, sport, matches, selections,
                          total_odds, risk_level, probability, stake_advice)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                         RETURNING id''',
                      (user_id,
                       datetime.now().isoformat(),
                       bet_data['sport'],
                       json.dumps(bet_data['matches']),
                       json.dumps(bet_data['selections']),
                       bet_data['total_odds'],
                       bet_data['risk_level'],
                       bet_data['probability'],
                       bet_data.get('stake_advice', 2.0)))
            bet_id = c.fetchone()[0]

            for match in bet_data['selections']:
                c.execute('''INSERT INTO tracked_matches
                             (bet_id, match_id, sport, home_team, away_team,
                              selection, odds, kickoff)
                             VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                          (bet_id, match.get('match_id', ''), match.get('sport', 'football'),
                           match.get('home_team', ''), match.get('away_team', ''),
                           match.get('selection', ''), match.get('odds', 0),
                           match.get('kickoff', '')))
        else:
            c.execute('''INSERT INTO bets
                         (user_id, created_at, sport, matches, selections,
                          total_odds, risk_level, probability, stake_advice)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                      (user_id,
                       datetime.now().isoformat(),
                       bet_data['sport'],
                       json.dumps(bet_data['matches']),
                       json.dumps(bet_data['selections']),
                       bet_data['total_odds'],
                       bet_data['risk_level'],
                       bet_data['probability'],
                       bet_data.get('stake_advice', 2.0)))
            bet_id = c.lastrowid

            for match in bet_data['selections']:
                c.execute('''INSERT INTO tracked_matches
                             (bet_id, match_id, sport, home_team, away_team,
                              selection, odds, kickoff)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                          (bet_id, match.get('match_id', ''), match.get('sport', 'football'),
                           match.get('home_team', ''), match.get('away_team', ''),
                           match.get('selection', ''), match.get('odds', 0),
                           match.get('kickoff', '')))

        conn.commit()
        return bet_id
    except Exception as e:
        logger.error(f"Error save_bet: {e}")
        conn.rollback()
        return 0
    finally:
        conn.close()


def get_user_bets(user_id: int, limit: int = 10) -> list:
    logger.info(f"📋 Récupération coupons user {user_id} - USE_POSTGRES={USE_POSTGRES}")
    conn = get_connection()
    try:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute('''SELECT * FROM bets WHERE user_id = %s
                         ORDER BY created_at DESC LIMIT %s''', (user_id, limit))
            cols = [desc[0] for desc in c.description]
            return [dict(zip(cols, row)) for row in c.fetchall()]
        else:
            c.execute('''SELECT * FROM bets WHERE user_id = ?
                         ORDER BY created_at DESC LIMIT ?''', (user_id, limit))
            return [dict(row) for row in c.fetchall()]
    except Exception as e:
        logger.error(f"Error get_user_bets: {e}")
        return []
    finally:
        conn.close()


def get_user_stats(user_id: int) -> dict:
    conn = get_connection()
    try:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute('''SELECT
                           COUNT(*) as total,
                           SUM(CASE WHEN status='won' THEN 1 ELSE 0 END) as won,
                           SUM(CASE WHEN status='lost' THEN 1 ELSE 0 END) as lost,
                           AVG(total_odds) as avg_odds,
                           AVG(probability) as avg_prob
                         FROM bets WHERE user_id = %s AND status != 'pending' ''',
                      (user_id,))
            cols = [desc[0] for desc in c.description]
            row = c.fetchone()
            return dict(zip(cols, row)) if row else {}
        else:
            c.execute('''SELECT
                           COUNT(*) as total,
                           SUM(CASE WHEN status='won' THEN 1 ELSE 0 END) as won,
                           SUM(CASE WHEN status='lost' THEN 1 ELSE 0 END) as lost,
                           AVG(total_odds) as avg_odds,
                           AVG(probability) as avg_prob
                         FROM bets WHERE user_id = ? AND status != 'pending' ''',
                      (user_id,))
            row = c.fetchone()
            return dict(row) if row else {}
    except Exception as e:
        logger.error(f"Error get_user_stats: {e}")
        return {}
    finally:
        conn.close()


def update_bet_status(bet_id: int, status: str, notes: str = ""):
    conn = get_connection()
    try:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute('''UPDATE bets SET status=%s, result_checked_at=%s, notes=%s
                         WHERE id=%s''',
                      (status, datetime.now().isoformat(), notes, bet_id))
        else:
            c.execute('''UPDATE bets SET status=?, result_checked_at=?, notes=?
                         WHERE id=?''',
                      (status, datetime.now().isoformat(), notes, bet_id))
        conn.commit()
    except Exception as e:
        logger.error(f"Error update_bet_status: {e}")
        conn.rollback()
    finally:
        conn.close()


def get_pending_bets() -> list:
    conn = get_connection()
    try:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute('''SELECT b.*, string_agg(tm.match_id, ',') as match_ids
                         FROM bets b
                         JOIN tracked_matches tm ON b.id = tm.bet_id
                         WHERE b.status = 'pending'
                         GROUP BY b.id''')
            cols = [desc[0] for desc in c.description]
            return [dict(zip(cols, row)) for row in c.fetchall()]
        else:
            c.execute('''SELECT b.*, GROUP_CONCAT(tm.match_id) as match_ids
                         FROM bets b
                         JOIN tracked_matches tm ON b.id = tm.bet_id
                         WHERE b.status = 'pending'
                         GROUP BY b.id''')
            return [dict(row) for row in c.fetchall()]
    except Exception as e:
        logger.error(f"Error get_pending_bets: {e}")
        return []
    finally:
        conn.close()


def delete_user_bets(user_id: int):
    """Supprime tous les coupons d'un utilisateur."""
    conn = get_connection()
    try:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute("DELETE FROM tracked_matches WHERE bet_id IN (SELECT id FROM bets WHERE user_id = %s)", (user_id,))
            c.execute("DELETE FROM bets WHERE user_id = %s", (user_id,))
        else:
            c.execute("DELETE FROM tracked_matches WHERE bet_id IN (SELECT id FROM bets WHERE user_id = ?)", (user_id,))
            c.execute("DELETE FROM bets WHERE user_id = ?", (user_id,))
        conn.commit()
        logger.info(f"Historique supprimé pour user {user_id}")
    except Exception as e:
        logger.error(f"Error delete_user_bets: {e}")
        conn.rollback()
    finally:
        conn.close()


def delete_single_bet(user_id: int, bet_id: int):
    """Supprime un coupon spécifique."""
    conn = get_connection()
    try:
        c = conn.cursor()
        if USE_POSTGRES:
            c.execute("DELETE FROM tracked_matches WHERE bet_id = %s", (bet_id,))
            c.execute("DELETE FROM bets WHERE id = %s AND user_id = %s", (bet_id, user_id))
        else:
            c.execute("DELETE FROM tracked_matches WHERE bet_id = ?", (bet_id,))
            c.execute("DELETE FROM bets WHERE id = ? AND user_id = ?", (bet_id, user_id))
        conn.commit()
        logger.info(f"Coupon #{bet_id} supprimé")
    except Exception as e:
        logger.error(f"Error delete_single_bet: {e}")
        conn.rollback()
    finally:
        conn.close()
