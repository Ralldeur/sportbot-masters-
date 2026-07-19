"""
SportBot Telegram - Bot de Paris Sportifs
Architecture principale
"""

import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from config import BOT_TOKEN, ADMIN_ID
from handlers import (
    start_handler, today_handler, bestbets_handler,
    safe_handler, explain_handler, help_handler, customodds_handler,
    history_handler, stats_handler,
    clearhistory_handler, delete_bet_handler
)
from scheduler import setup_scheduler
from database import init_db

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    if update and hasattr(update, 'effective_message'):
        await update.effective_message.reply_text(
            "❌ Une erreur s'est produite. Réessaie dans quelques instants."
        )


def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # Commandes principales
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("today", today_handler))
    app.add_handler(CommandHandler("bestbets", bestbets_handler))
    app.add_handler(CommandHandler("safe", safe_handler))
    app.add_handler(CommandHandler("explain", explain_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("customodds", customodds_handler))
    app.add_handler(CommandHandler("historique", history_handler))
    app.add_handler(CommandHandler("stats", stats_handler))
    app.add_handler(CommandHandler("clearhistory", clearhistory_handler))
    app.add_handler(CommandHandler("deletecoupon", delete_bet_handler))

    # Callbacks pour les boutons
    app.add_handler(CallbackQueryHandler(button_callback))

    # Gestion des erreurs
    app.add_error_handler(error_handler)

    # Planificateur de tâches
    setup_scheduler(app)

    logger.info("🚀 SportBot démarré avec succès!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("explain_"):
        bet_id = data.split("_")[1]
        from handlers import explain_bet
        await explain_bet(query, bet_id)
    elif data.startswith("track_"):
        bet_id = data.split("_")[1]
        from handlers import track_bet
        await track_bet(query, bet_id, context)
    elif data.startswith("odds_safe"):
        from handlers import customodds_safe
        await customodds_safe(query, context)
    elif data.startswith("odds_aggressive"):
        from handlers import customodds_aggressive
        await customodds_aggressive(query, context)
    elif data == "refresh_today":
        await today_handler(update, context)
    elif data == "today":
        await today_handler(update, context)
    elif data == "bestbets":
        from handlers import bestbets_handler
        await bestbets_handler(update, context)
    elif data == "safe":
        from handlers import safe_handler
        await safe_handler(update, context)
    elif data == "historique":
        from handlers import history_handler
        await history_handler(update, context)
    elif data == "help":
        from handlers import explain_handler
        await explain_handler(update, context)
    elif data == "customodds":
        await query.message.reply_text(
            "🎯 Tape la commande:\n`/customodds 10`\n\nExemples:\n"
            "/customodds 5\n/customodds 20\n/customodds 100",
            parse_mode="Markdown"
        )
    elif data == "save_combo":
        from handlers import save_combo_handler
        await save_combo_handler(query, context)
    elif data == "confirm_clear":
        from database import delete_user_bets
        user_id = query.from_user.id
        delete_user_bets(user_id)
        await query.message.reply_text(
            "🗑️ *Historique supprimé !*\n\n"
            "Tous tes coupons ont été effacés.",
            parse_mode="Markdown"
        )
    elif data == "cancel_clear":
        await query.message.reply_text("✅ Suppression annulée.")


if __name__ == "__main__":
    main()
