from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from dispatcher.queue.db import create_job, get_job_status
from dispatcher.bot.validation import validate_prompt
from dispatcher.bot.rate_limit import check_rate_limit


async def generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    prompt = " ".join(context.args)

    if not prompt:
        await update.message.reply_text("Usage: /generate <prompt>")
        return

    ok, reason = validate_prompt(prompt)
    if not ok:
        await update.message.reply_text(f"Prompt rejected: {reason}")
        return

    allowed, wait = check_rate_limit(user_id)
    if not allowed:
        await update.message.reply_text(f"Rate limit. Try again in {wait}s.")
        return

    job = create_job(user_id=user_id, prompt=prompt, raw_prompt=prompt, model="ltx-video")
    await update.message.reply_text(f"Queued (job {job['id'][:8]}). Use /status {job['id'][:8]} to check.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /status <job_id>")
        return
    job_id = context.args[0]
    job = get_job_status(job_id)
    if not job:
        await update.message.reply_text("Job not found.")
        return
    await update.message.reply_text(f"Job {job_id[:8]}: {job['status']}")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /cancel <job_id>")
        return
    job_id = context.args[0]
    job = get_job_status(job_id)
    if not job or job["user_id"] != update.effective_user.id or job["status"] != "pending":
        await update.message.reply_text("Cannot cancel (not yours or already running).")
        return
    from dispatcher.queue.db import _client
    _client.table("jobs").update({"status": "cancelled"}).eq("id", job_id).execute()
    await update.message.reply_text("Cancelled.")