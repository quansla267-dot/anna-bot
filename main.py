import os
import logging
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")

# Cau hinh Gemini AI
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-3.1-flash-lite')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Kiem tra ID
    if ALLOWED_USER_ID and str(ALLOWED_USER_ID) != "0" and str(user_id) != str(ALLOWED_USER_ID):
        await update.message.reply_text("Xin lỗi, bạn không có quyền sử dụng bot này.")
        return

    user_text = update.message.text
    sent_message = await update.message.reply_text("Dạ, Anna đang suy nghĩ...")

    try:
        # Goi Gemini AI
        response = model.generate_content(user_text)
        reply_text = response.text

        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=sent_message.message_id,
            text=reply_text
        )

    except Exception as e:
        logging.error(f"Loi Gemini: {e}")
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=sent_message.message_id,
            text=f"Lỗi rồi bạn Quân ơi: {str(e)}"
        )

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
