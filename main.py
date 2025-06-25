import os
import logging
import json
import asyncio
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "10000"))
THREAD_MAP_FILE = "user_threads.json"

user_threads = {}

def load_threads():
    global user_threads
    if os.path.exists(THREAD_MAP_FILE):
        with open(THREAD_MAP_FILE, "r") as f:
            user_threads = json.load(f)

def save_threads():
    with open(THREAD_MAP_FILE, "w") as f:
        json.dump(user_threads, f)

async def open_thread_for_user(app: Application, user) -> int:
    name = user.full_name
    user_id = user.id
    username = f"@{user.username}" if user.username else "לא קיים"

    msg = await app.bot.send_message(
        chat_id=GROUP_ID,
        text=(
            f"📬 פנייה חדשה מ- {name}\n"
            f"🆔 ID: {user_id}\n"
            f"🧑‍💻 שם משתמש: {username}"
        ),
        message_thread_id=None
    )
    return msg.message_thread_id

async def forward_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    thread_id = user_threads.get(user_id)

    if thread_id is None:
        thread_id = await open_thread_for_user(context.application, user)
        user_threads[user_id] = thread_id

    if update.message.text:
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=update.message.text,
            message_thread_id=thread_id
        )
    elif update.message.photo:
        await context.bot.send_photo(
            chat_id=GROUP_ID,
            photo=update.message.photo[-1].file_id,
            caption=update.message.caption or "",
            message_thread_id=thread_id
        )
    elif update.message.document:
        await context.bot.send_document(
            chat_id=GROUP_ID,
            document=update.message.document.file_id,
            caption=update.message.caption or "",
            message_thread_id=thread_id
        )
    elif update.message.video:
        await context.bot.send_video(
            chat_id=GROUP_ID,
            video=update.message.video.file_id,
            caption=update.message.caption or "",
            message_thread_id=thread_id
        )

async def handle_group_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.is_topic_message:
        return

    thread_id = update.message.message_thread_id
    for uid, tid in user_threads.items():
        if tid == thread_id:
            try:
                await context.bot.copy_message(
                    chat_id=int(uid),
                    from_chat_id=update.effective_chat.id,
                    message_id=update.message.message_id
                )
            except Exception as e:
                logging.error(f"Can't send to user {uid}: {e}")
            break

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📚 ברוך הבא לספריית אולדטאון! כתוב לי כל דבר שתרצה לשתף עם ההנהלה.")

async def periodic_save():
    while True:
        save_threads()
        await asyncio.sleep(600)

async def main():
    load_threads()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.PRIVATE, forward_to_group))
    app.add_handler(MessageHandler(filters.ALL & filters.Chat(GROUP_ID), handle_group_reply))

    asyncio.create_task(periodic_save())

    await app.bot.set_webhook(url=WEBHOOK_URL + "/webhook")
    await app.start()
    await app.updater.start_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_path="/webhook"
    )
    await app.updater.idle()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())