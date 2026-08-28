import os
import logging
import datetime
import json
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)

def get_gemini_model():
    # Truyền thời gian thực tế của hệ thống
    now = datetime.datetime.now()
    system_instruction = (
        f"Hôm nay chính xác là Thứ Sáu, ngày {now.day} tháng {now.month} năm {now.year}, thời gian hiện tại là {now.strftime('%H:%M')}. "
        f"Bạn là Trợ lý Anna thông minh, chuyên quản lý công việc và nhắc lịch cho bạn Quân. "
        f"Nếu tin nhắn của bạn Quân có ý định đặt lịch/nhắc việc, hãy phân tích thời gian và nội dung. "
        f"Trả lời ngắn gọn, lịch sự, chu đáo."
    )
    return genai.GenerativeModel(
        model_name='gemini-3.1-flash-lite',
        system_instruction=system_instruction
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if ALLOWED_USER_ID and str(ALLOWED_USER_ID) != "0" and str(user_id) != str(ALLOWED_USER_ID):
        await update.message.reply_text("Xin lỗi, bạn không có quyền sử dụng bot này.")
        return

    user_text = update.message.text
    sent_message = await update.message.reply_text("Dạ, Anna đang suy nghĩ...")

    try:
        model = get_gemini_model()
        response = model.generate_content(user_text)
        reply_text = response.text

        # Thử lưu thông tin vào Supabase nếu câu lệnh chứa từ khóa nhắc việc
        if any(word in user_text.lower() for word in ["nhắc", "hẹn", "lịch", "họp", "công việc"]):
            try:
                supabase.table("reminders").insert({
                    "user_id": str(user_id),
                    "task": user_text,
                    "remind_at": datetime.datetime.now().isoformat()
                }).execute()
            except Exception as se:
                logging.error(f"Lỗi lưu Supabase: {se}")

        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=sent_message.message_id,
            text=reply_text
        )

    except Exception as e:
        logging.error(f"Lỗi Gemini: {e}")
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=sent_message.message_id,
            text=f"Lỗi rồi bạn Quân ơi: {str(e)}"
        )

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
