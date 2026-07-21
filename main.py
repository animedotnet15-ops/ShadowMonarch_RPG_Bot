import asyncio
import logging
import os

from database import database
from bot import bot, dp


async def run_health_server() -> None:
    port = os.getenv("PORT")
    if not port:
        return
    from aiohttp import web

    async def health(_request):
        return web.Response(text="Shadow Monarch RPG bot is running.")

    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(port))
    await site.start()
    logging.getLogger("main").info(f"Health server listening on :{port}")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    await database.init()
    await bot.delete_webhook(drop_pending_updates=True)
    await run_health_server()
    logging.getLogger("main").info("Shadow Monarch RPG bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
