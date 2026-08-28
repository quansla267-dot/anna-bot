import os
import logging
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from supabase import create_client, Client

# Cau hinh logging
logging.basicConfig(level=logging.INFO)

# Lay bien moi truong
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")

# Khoi tao Gemini AI
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Khoi tao Supabase Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Kiem tra ID người dung
    if ALLOWED_USER_ID and str(ALLOWED_USER_ID) != "0" and str(user_id) != str(ALLOWED_USER_ID):
        await update.message.reply_text("Xin lỗi, bạn không có quyền sử dụng bot này.")
        return

    user_text = update.message.text
    sent_message = await update.message.reply_text("Dạ, em đang suy nghĩ...")

    try:
        # Goi Gemini AI
        response = model.generate_content(user_text)
        reply_text = response.text

        # Luu vao Supabase
        try:
            supabase.table("chat_logs").insert({
                "user_id": str(user_id),
                "message": user_text,
                "response": reply_text
            }).execute()
        except Exception as e:
            logging.error(f"Loi Supabase: {e}")

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
            text="Có lỗi xảy ra khi xử lý yêu cầu, bạn thử lại nhé!"
        )

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
