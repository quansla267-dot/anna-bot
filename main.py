import os
import logging
import datetime
import zoneinfo
import asyncio
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

# Múi giờ Việt Nam
TZ_VN = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")

def ask_gemini(user_text):
    # Lấy thời gian thực tế tại Việt Nam ngay thời điểm gửi
    now = datetime.datetime.now(TZ_VN)
    now_str = now.strftime("%A, ngày %d/%m/%Y, lúc %H:%M:%S")
    
    prompt = (
        f"[THÔNG TIN HỆ THỐNG]: Bây giờ BẮT BUỘC phải tính theo mốc thời gian thực này: {now_str}.\n"
        f"Bạn là Trợ lý Anna. Hãy trả lời câu hỏi/yêu cầu sau của bạn Quân một cách ngắn gọn, chính xác dựa trên mốc thời gian thực trên:\n"
        f"Nội dung từ bạn Quân: '{user_text}'"
    )
    
    model = genai.GenerativeModel('gemini-3.1-flash-lite')
    response = model.generate_content(prompt)
    return response.text

# Tiến trình chạy ngầm quét lịch hẹn
async def check_reminders(app):
    while True:
        try:
            now_iso = datetime.datetime.now(TZ_VN).isoformat()
            response = supabase.table("reminders") \
                .select("*") \
                .lte("remind_at", now_iso) \
                .eq("is_notified", False) \
                .execute()

            for item in response.data:
                await app.bot.send_message(
                    chat_id=item["user_id"], 
                    text=f"⏰ **[NHẮC LỊCH LÀM VIỆC]**\n\nBạn Quân ơi, đến giờ thực hiện công việc: **{item['task']}** rồi nhé!"
                )
                supabase.table("reminders").update({"is_notified": True}).eq("id", item["id"]).execute()
        except Exception as e:
            logging.error(f"Lỗi cron nhắc lịch: {e}")
            
        await asyncio.sleep(30)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if ALLOWED_USER_ID and str(ALLOWED_USER_ID) != "0" and str(user_id) != str(ALLOWED_USER_ID):
        await update.message.reply_text("Xin lỗi, bạn không có quyền sử dụng bot này.")
        return

    user_text = update.message.text
    sent_message = await update.message.reply_text("Dạ, Anna đang suy nghĩ...")

    try:
        # Gọi Gemini xử lý với thời gian thực ép cứng
        reply_text = ask_gemini(user_text)

        # Nếu tin nhắn chứa yêu cầu nhắc việc, lưu vào Supabase
        if any(w in user_text.lower() for w in ["nhắc", "hẹn", "lịch", "họp"]):
            try:
                # Tạm thời đặt mốc nhắc (có thể nâng cấp AI tự bóc tách giờ sau)
                remind_time = datetime.datetime.now(TZ_VN) + datetime.timedelta(days=1)
                supabase.table("reminders").insert({
                    "user_id": str(user_id),
                    "task": user_text,
                    "remind_at": remind_time.isoformat(),
                    "is_notified": False
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
    
    loop = asyncio.get_event_loop()
    loop.create_task(check_reminders(app))
    
    app.run_polling()
