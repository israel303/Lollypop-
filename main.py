import os
import logging
import json
import asyncio
from io import BytesIO
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Validate environment variables
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")

GROUP_ID_STR = os.getenv("ADMIN_GROUP_ID")
if not GROUP_ID_STR:
    raise ValueError("ADMIN_GROUP_ID environment variable is required")
GROUP_ID = int(GROUP_ID_STR)

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
if not WEBHOOK_URL:
    raise ValueError("WEBHOOK_URL environment variable is required")

PORT = int(os.getenv("PORT", "10000"))

# Global variables
user_threads = {}
backup_message_id = None
app_instance = None

async def load_threads_from_group(bot):
    """Load threads data from a JSON file in the group"""
    global user_threads, backup_message_id
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("Deleted webhook to allow getUpdates")

        try:
            updates = await bot.get_updates(limit=50)
            backup_found = False
            
            for update in reversed(updates):
                if (hasattr(update, 'message') and update.message and
                    update.message.chat.id == GROUP_ID and
                    update.message.message_thread_id == 1 and
                    update.message.document and
                    update.message.document.file_name == "threads_backup.json"):
                    
                    backup_message_id = update.message.message_id
                    file = await bot.get_file(update.message.document.file_id)
                    file_content = await file.download_as_bytearray()
                    user_threads.update(json.loads(file_content.decode('utf-8')))
                    logging.info(f"Loaded {len(user_threads)} threads from backup")
                    backup_found = True
                    break
            
            if not backup_found:
                logging.info("No backup file found, starting fresh")
                user_threads.clear()
                
        except Exception as e:
            logging.warning(f"Could not load from updates: {e}")
            user_threads.clear()
            
        await bot.set_webhook(url=WEBHOOK_URL + "/webhook")
        logging.info("Webhook set after loading updates")
            
    except Exception as e:
        logging.error(f"Failed to load threads backup: {e}")
        user_threads.clear()

async def save_threads_to_group():
    """Save user_threads as a JSON file in the group"""
    global backup_message_id
    
    try:
        json_text = json.dumps(user_threads, ensure_ascii=False, indent=2)
        file_data = BytesIO(json_text.encode('utf-8'))
        file_data.name = "threads_backup.json"
        
        new_msg = await app_instance.bot.send_document(
            chat_id=GROUP_ID,
            document=file_data,
            caption="🔄 BACKUP_THREADS: User threads backup",
            message_thread_id=1
        )
        
        old_backup_message_id = backup_message_id
        backup_message_id = new_msg.message_id
        logging.info("Created new backup message")
        
        if old_backup_message_id:
            try:
                await app_instance.bot.delete_message(
                    chat_id=GROUP_ID,
                    message_id=old_backup_message_id
                )
                logging.info("Deleted old backup message")
            except Exception as e:
                logging.warning(f"Failed to delete old backup message: {e}")
                
    except Exception as e:
        logging.error(f"Failed to save threads backup: {e}")

async def open_thread_for_user(app: Application, user) -> int:
    """Create a new thread for user in the admin group"""
    name = user.full_name or "Unknown"
    user_id = user.id
    username = f"@{user.username}" if user.username else "לא קיים"

    try:
        msg = await app.bot.send_message(
            chat_id=GROUP_ID,
            text=(
                f"📬 פנייה חדשה מ- {name}\n"
                f"🆔 ID: {user_id}\n"
                f"🧑‍💻 שם משתמש: {username}"
            ),
            message_thread_id=None
        )
        thread_id = msg.message_thread_id
        
        user_threads[str(user_id)] = thread_id
        await save_threads_to_group()
        
        return thread_id
    except Exception as e:
        logging.error(f"Failed to create thread for user {user_id}: {e}")
        raise

async def forward_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Forward user messages to the admin group"""
    user = update.effective_user
    user_id = str(user.id)
    thread_id = user_threads.get(user_id)

    if thread_id is None:
        try:
            thread_id = await open_thread_for_user(context.application, user)
            logging.info(f"Created new thread {thread_id} for user {user_id}")
        except Exception as e:
            logging.error(f"Failed to create thread for user {user_id}: {e}")
            return

    try:
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
        elif update.message.voice:
            await context.bot.send_voice(
                chat_id=GROUP_ID,
                voice=update.message.voice.file_id,
                caption=update.message.caption or "",
                message_thread_id=thread_id
            )
        elif update.message.audio:
            await context.bot.send_audio(
                chat_id=GROUP_ID,
                audio=update.message.audio.file_id,
                caption=update.message.caption or "",
                message_thread_id=thread_id
            )
        elif update.message.sticker:
            await context.bot.send_sticker(
                chat_id=GROUP_ID,
                sticker=update.message.sticker.file_id,
                message_thread_id=thread_id
            )
        logging.info(f"Forwarded message from user {user_id} to thread {thread_id}")
    except Exception as e:
        logging.error(f"Failed to forward message from user {user_id}: {e}")

async def handle_group_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle replies from admin group and forward to users"""
    if not update.message or not update.message.is_topic_message:
        return
    
    if update.message.document and update.message.document.file_name == "threads_backup.json":
        return

    thread_id = update.message.message_thread_id
    
    target_user_id = None
    for uid, tid in user_threads.items():
        if tid == thread_id:
            target_user_id = uid
            break
    
    if target_user_id:
        try:
            await context.bot.copy_message(
                chat_id=int(target_user_id),
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
            logging.info(f"Forwarded reply to user {target_user_id}")
        except Exception as e:
            logging.error(f"Failed to send reply to user {target_user_id}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await update.message.reply_text(
        "📚 ברוך הבא לספריית אולדטאון! כתוב לי כל דבר שתרצה לשתף עם ההנהלה."
    )

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual backup command for admins"""
    if update.effective_chat.id == GROUP_ID:
        await save_threads_to_group()
        await update.message.reply_text("✅ הגיבוי נשמר בהצלחה!")

async def periodic_backup():
    """Backup threads every 30 minutes"""
    while True:
        await asyncio.sleep(1800)
        if user_threads:
            await save_threads_to_group()
            logging.info("Periodic backup completed")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logging.error(f"Update caused error: {context.error}")

def main():
    """Main function to run the bot"""
    global app_instance
    
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    logger = logging.getLogger(__name__)
    
    async def run_bot():
        try:
            app = Application.builder().token(TOKEN).build()
            app_instance = app

            await app.initialize()

            await load_threads_from_group(app.bot)

            app.add_handler(CommandHandler("start", start))
            app.add_handler(CommandHandler("backup", backup_command))
            app.add_handler(MessageHandler(
                filters.ALL & filters.ChatType.PRIVATE, 
                forward_to_group
            ))
            app.add_handler(MessageHandler(
                filters.ALL & filters.Chat(GROUP_ID), 
                handle_group_reply
            ))
            
            app.add_error_handler(error_handler)

            asyncio.create_task(periodic_backup())

            await app.bot.delete_webhook(drop_pending_updates=True)
            await app.bot.set_webhook(url=WEBHOOK_URL + "/webhook")
            
            logger.info(f"Starting webhook: {WEBHOOK_URL}/webhook")
            logger.info(f"Listening on port: {PORT}")
            
            await app.run_webhook(
                listen="0.0.0.0",
                port=PORT,
                url_path="/webhook",
                webhook_url=WEBHOOK_URL + "/webhook"
            )
            
        except Exception as e:
            logger.error(f"Failed to start application: {e}")
            raise
            
    asyncio.run(run_bot())

if __name__ == "__main__":
    main()