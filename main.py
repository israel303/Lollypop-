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

async def load_threads_from_group():
    """Load threads data from backup message in group"""
    global user_threads, backup_message_id
    
    try:
        # Get the general topic messages (topic_id = 1 is usually general)
        messages = []
        async for message in app_instance.bot.get_chat_history(GROUP_ID, limit=50):
            if (message.message_thread_id == 1 and 
                message.text and 
                message.text.startswith("🔄 BACKUP_THREADS:")):
                messages.append(message)
        
        if messages:
            # Get the latest backup message
            latest_message = messages[0]  # Most recent first
            backup_message_id = latest_message.message_id
            
            # Extract JSON from message
            json_text = latest_message.text.replace("🔄 BACKUP_THREADS:", "").strip()
            if json_text:
                user_threads = json.loads(json_text)
                logging.info(f"Loaded {len(user_threads)} threads from backup")
            else:
                user_threads = {}
        else:
            logging.info("No backup found, starting fresh")
            user_threads = {}
            
    except Exception as e:
        logging.error(f"Failed to load threads backup: {e}")
        user_threads = {}

async def save_threads_to_group():
    """Save threads data as message in group"""
    global backup_message_id
    
    try:
        json_text = json.dumps(user_threads, ensure_ascii=False, indent=2)
        backup_text = f"🔄 BACKUP_THREADS:\n{json_text}"
        
        if backup_message_id:
            # Update existing message
            try:
                await app_instance.bot.edit_message_text(
                    chat_id=GROUP_ID,
                    message_id=backup_message_id,
                    text=backup_text,
                    message_thread_id=1  # General topic
                )
                logging.info("Updated threads backup")
            except Exception as e:
                logging.warning(f"Failed to edit backup message: {e}")
                # If edit fails, create new message
                backup_message_id = None
        
        if not backup_message_id:
            # Create new backup message
            msg = await app_instance.bot.send_message(
                chat_id=GROUP_ID,
                text=backup_text,
                message_thread_id=1  # General topic
            )
            backup_message_id = msg.message_id
            logging.info("Created new threads backup")
            
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
        
        # Save immediately when new thread is created
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

    # Create new thread if doesn't exist
    if thread_id is None:
        try:
            thread_id = await open_thread_for_user(context.application, user)
            logging.info(f"Created new thread {thread_id} for user {user_id}")
        except Exception as e:
            logging.error(f"Failed to create thread for user {user_id}: {e}")
            return

    try:
        # Forward different message types
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
    except Exception as e:
        logging.error(f"Failed to forward message from user {user_id}: {e}")

async def handle_group_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle replies from admin group and forward to users"""
    if not update.message or not update.message.is_topic_message:
        return
    
    # Ignore backup messages
    if update.message.text and update.message.text.startswith("🔄 BACKUP_THREADS:"):
        return

    thread_id = update.message.message_thread_id
    
    # Find user by thread ID
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
    """Backup threads every 10 minutes"""
    while True:
        await asyncio.sleep(600)  # 10 minutes
        if user_threads:  # Only backup if there's data
            await save_threads_to_group()
            logging.info("Periodic backup completed")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors"""
    logging.error(f"Exception while handling an update: {context.error}")

def main():
    """Main function to run the bot"""
    global app_instance
    
    # Set up logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    logger = logging.getLogger(__name__)
    
    try:
        # Create application
        app = Application.builder().token(TOKEN).build()
        app_instance = app

        # Add handlers
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
        
        # Add error handler
        app.add_error_handler(error_handler)

        # Load threads from backup before starting
        async def post_init(application):
            await load_threads_from_group()
            # Start periodic backup task
            asyncio.create_task(periodic_backup())
            
        app.post_init = post_init

        # Start webhook (Render compatible)
        logger.info(f"Starting bot with webhook: {WEBHOOK_URL}/webhook")
        logger.info(f"Listening on port: {PORT}")
        
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL + "/webhook",
            url_path="/webhook"
        )
        
    except Exception as e:
        logging.error(f"Failed to start bot: {e}")
        raise

if __name__ == "__main__":
    main()