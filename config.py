"""
Configuration du SportBot
"""
import os
from dotenv import load_dotenv

load_dotenv()

# === TELEGRAM ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# === API SPORTS ===
FOOTBALL_DATA_KEY = os.getenv("FOOTBALL_DATA_KEY", "")  # football-data.org
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
SPORTRADAR_KEY = os.getenv("SPORTRADAR_KEY", "")
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")  # The Odds API (gratuit jusqu'à 500 req/mois)

# === BASE DE DONNÉES ===
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///sportbot.db")

# === PARAMÈTRES DU BOT ===
MAX_BETS_PER_DAY = 5          # Nombre max de paris par jour
MIN_PROBABILITY = 55.0         # Probabilité minimale pour recommander un pari (%)
MIN_VALUE_BET = 0.05           # Valeur minimale d'un value bet (5%)
MAX_COMBO_SELECTIONS = 12      # Nombre max de sélections dans un combiné

# === BOOKMAKERS CIBLES ===
BOOKMAKERS = ["1xbet", "melbet", "betway", "bet365"]
PRIMARY_BOOKMAKER = "1xbet"

# === SPORTS SUPPORTÉS ===
SUPPORTED_SPORTS = {
    "football": {"emoji": "⚽", "api": "api_football"},
    "basketball": {"emoji": "🏀", "api": "api_basketball"},
    "tennis": {"emoji": "🎾", "api": "api_tennis"},
    "mma": {"emoji": "🥊", "api": "sportradar"},
    "american_football": {"emoji": "🏈", "api": "sportradar"},
}

# === CLASSIFICATION DES RISQUES ===
RISK_LEVELS = {
    "faible": {"max_odds": 1.80, "emoji": "🟢", "stake_pct": 5},
    "moyen": {"max_odds": 2.50, "emoji": "🟡", "stake_pct": 3},
    "élevé": {"max_odds": 5.00, "emoji": "🟠", "stake_pct": 2},
    "tres_eleve": {"max_odds": 999, "emoji": "🔴", "stake_pct": 1},
}

# === MESSAGES D'AVERTISSEMENT ===
RISK_WARNING = (
    "⚠️ *AVERTISSEMENT* : Les paris sportifs comportent des risques. "
    "Ne misez jamais plus que ce que vous pouvez vous permettre de perdre. "
    "Ce bot fournit des analyses, pas des garanties de gains."
)
