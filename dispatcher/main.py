import os
import asyncio
import logging
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler
from dispatcher.bot.handlers import generate_command, status_command, cancel_command
from dispatcher.queue.db import poll_completed_jobs, mark_delivered

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("telegram-video-bot")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]


async def delivery_loop(app: Application):
    while True:
        try:
            completed = poll_completed_jobs()
            for job in completed:
                try:
                    if job.get("telegram_file_id"):
                        await app.bot.send_video(
                            chat_id=job["user_id"],
                            video=job["telegram_file_id"],
                            caption=f"Done: {job['raw_prompt'][:100]}"
                        )
                    else:
                        msg = await app.bot.send_video(
                            chat_id=job["user_id"],
                            video=job["result_url"],
                            caption=f"Done: {job['raw_prompt'][:100]}"
                        )
                        mark_delivered(job["id"], msg.video.file_id)
                    mark_delivered(job["id"])
                except Exception as e:
                    logger.error(f"Delivery failed for job {job['id']}: {e}")
        except Exception as e:
            logger.error(f"Delivery loop error: {e}")
        await asyncio.sleep(5)


async def post_init(app: Application):
    asyncio.create_task(delivery_loop(app))


def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("generate", generate_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel_command))

    if os.environ.get("WEBHOOK_URL"):
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 8080)),
            url_path=TOKEN,
            webhook_url=f"{os.environ['WEBHOOK_URL']}/{TOKEN}",
        )
    else:
        app.run_polling()


if __name__ == "__main__":
    main()