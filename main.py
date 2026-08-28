import os
import logging
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from supabase import create_client, Client

# Cấu hình logging
logging.basicConfig(level=logging.INFO)

# Lấy các biến môi trường
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")

# Khởi tạo Gemini AI
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Khởi tạo Supabase Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Kiểm tra quyền truy cập của người dùng
    if ALLOWED_USER_ID and str(user_id) != str(ALLOWED_USER_ID):
        await update.message.reply_text("Xin lỗi, bạn không có quyền sử dụng bot này.")
        return

    user_text = update.message.text
    
    # Gửi thông báo đang xử lý
    sent_message = await update.message.reply_text("Dạ, Anna đang suy nghĩ...")

    try:
        # Gọi Gemini AI trả lời
        response = model.generate_content(user_text)
        reply_text = response.text

        # Lưu lịch sử chat vào Supabase (nếu cần)
        try:
            supabase.table("chat_logs").insert({
                "user_id": str(user_id),
                "message": user_text,
                "response": reply_text
            }).execute()
        except Exception as e:
            logging.error(f"Lỗi lưu Supabase: {e}")

        # Cập nhật tin nhắn phản hồi cho bạn Quân
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=sent_message.message_id,
            text=reply_text
        )

    except Exception as e:
        logging.error(f"Lỗi xử lý Gemini: {e}")
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=sent_message.message_id,
            text="Có lỗi xảy ra khi xử lý yêu cầu, bạn Quân thử lại nhé!"
        )

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
