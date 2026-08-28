import os
import logging
import datetime
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# Cau hinh logging
logging.basicConfig(level=logging.INFO)

# Lay bien moi truong
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")

genai.configure(api_key=GEMINI_API_KEY)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if ALLOWED_USER_ID and str(ALLOWED_USER_ID) != "0" and str(user_id) != str(ALLOWED_USER_ID):
        await update.message.reply_text("Xin lỗi, bạn không có quyền sử dụng bot này.")
        return

    user_text = update.message.text
    sent_message = await update.message.reply_text("Dạ, Anna đang xử lý...")

    try:
        # Lay gio UTC va cong 7 tieng ra gio Viet Nam
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        now_vn = now_utc + datetime.timedelta(hours=7)
        now_str = now_vn.strftime("Thu %w, ngay %d/%m/%Y, luc %H:%M")
        
        prompt = (
            f"[THONG TIN THOI GIAN THUC]: Bay gio chinh xác la: {now_str}.\n"
            f"Ban la Tro ly Anna. Hay tra loi tin nhan sau cua ban Quan dua tren dung moc thoi gian thuc tren:\n"
            f"Tin nhan: '{user_text}'"
        )

        model = genai.GenerativeModel('gemini-3.1-flash-lite')
        response = model.generate_content(prompt)
        reply_text = response.text

        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=sent_message.message_id,
            text=reply_text
        )

    except Exception as e:
        logging.error(f"Loi: {e}")
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=sent_message.message_id,
            text=f"Lỗi rồi bạn Quân ơi: {str(e)}"
        )

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
