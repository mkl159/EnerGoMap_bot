"""Point d'entrée EnerGoMap_bot — long polling."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from energomap import db
from energomap.alerts import alert_watcher
from energomap.config import BOT_TOKEN
from energomap.handlers import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# httpx logge chaque requête en INFO → bruit dans les logs
logging.getLogger("httpx").setLevel(logging.WARNING)

COMMANDS = [
    BotCommand(command="start", description="Menu principal / onboarding"),
    BotCommand(command="position", description="📍 Chercher autour de moi"),
    BotCommand(command="carburant", description="⛽ Changer d'énergie"),
    BotCommand(command="stats", description="📊 Prix nationaux"),
    BotCommand(command="alertes", description="🔔 Mes alertes prix"),
    BotCommand(command="aide", description="ℹ️ Aide"),
]


async def main() -> None:
    await db.init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.set_my_commands(COMMANDS)
    me = await bot.get_me()
    logging.info("Bot démarré : @%s (id=%s)", me.username, me.id)
    watcher = asyncio.create_task(alert_watcher(bot))  # 🔔 worker alertes prix
    try:
        await dp.start_polling(bot)
    finally:
        watcher.cancel()


if __name__ == "__main__":
    asyncio.run(main())
