import os
import logging
import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
import google.generativeai as genai

# Cấu hình logging
logging.basicConfig(level=logging.INFO)

# Lấy các biến môi trường
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")

# Khởi tạo Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-3.1-flash-lite')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Kiểm tra ID người dùng
    if ALLOWED_USER_ID and str(ALLOWED_USER_ID) != "0" and str(user_id) != str(ALLOWED_USER_ID):
        await update.message.reply_text("Xin lỗi, bạn không có quyền sử dụng bot này.")
        return

    user_text = update.message.text
    sent_message = await update.message.reply_text("Dạ, Anna đang xử lý...")

    try:
        # 1. Tính toán thời gian thực theo múi giờ Việt Nam (UTC+7)
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        now_vn = now_utc + datetime.timedelta(hours=7)
        
        weekdays = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
        weekday_str = weekdays[now_vn.weekday()]
        date_str = now_vn.strftime("%d/%m/%Y")
        time_str = now_vn.strftime("%H:%M:%S")
        
        # 2. Tạo prompt ép mốc thời gian thực vào đầu tin nhắn
        full_prompt = (
            f"[HỆ THỐNG]: Mốc thời gian thực hiện tại là {weekday_str}, ngày {date_str}, lúc {time_str}.\n"
            f"[VAI TRÒ]: Bạn là Trợ lý Anna phục vụ bạn Quản Hữu Quân. BẮT BUỘC dùng mốc thời gian thực trên để trả lời.\n\n"
            f"Câu hỏi của bạn Quân: {user_text}"
        )

        # 3. Gửi cho Gemini xử lý
        response = model.generate_content(full_prompt)
        reply_text = response.text

        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=sent_message.message_id,
            text=reply_text
        )

    except Exception as e:
        logging.error(f"Lỗi: {e}")
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=sent_message.message_id,
            text=f"Lỗi rồi bạn Quân ơi: {str(e)}"
        )

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
