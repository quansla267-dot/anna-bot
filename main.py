import os
import logging
import datetime
import asyncio
import google.generativeai as genai
from supabase import create_client, Client
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# Cấu hình logging
logging.basicConfig(level=logging.INFO)

# Lấy các biến môi trường từ Render
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Khởi tạo Gemini & Supabase Client
genai.configure(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

model = genai.GenerativeModel('gemini-3.1-flash-lite')

# Hàm ghi lịch hẹn vào Supabase
def save_reminder(user_id: int, task: str, remind_at_iso: str):
    try:
        data = {
            "user_id": user_id,
            "task": task,
            "remind_at": remind_at_iso,
            "is_sent": False
        }
        supabase.table("reminders").insert(data).execute()
        return True
    except Exception as e:
        logging.error(f"Lỗi lưu Supabase: {e}")
        return False

# Tiến trình chạy ngầm quét Supabase và gửi thông báo nhắc việc
async def check_and_send_reminders(app):
    while True:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            now_iso = now_utc.isoformat()

            # Lấy danh sách nhắc việc chưa gửi đến thời điểm hiện tại
            response = supabase.table("reminders") \
                .select("*") \
                .eq("is_sent", False) \
                .lte("remind_at", now_iso) \
                .execute()

            reminders = response.data
            for item in reminders:
                user_id = item["user_id"]
                task = item["task"]
                reminder_id = item["id"]

                msg = f"⏰ **NHẮC VIỆC BẠN QUÂN:**\n\n📌 Nội dung: {task}"
                await app.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")

                # Đánh dấu đã phát thông báo thành công
                supabase.table("reminders").update({"is_sent": True}).eq("id", reminder_id).execute()

        except Exception as e:
            logging.error(f"Lỗi tiến trình nhắc việc: {e}")

        await asyncio.sleep(30)  # Quét lại mỗi 30 giây

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if ALLOWED_USER_ID and str(ALLOWED_USER_ID) != "0" and str(user_id) != str(ALLOWED_USER_ID):
        await update.message.reply_text("Xin lỗi, bạn không có quyền sử dụng bot này.")
        return

    user_text = update.message.text
    sent_message = await update.message.reply_text("Dạ, Anna đang xử lý...")

    try:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        now_vn = now_utc + datetime.timedelta(hours=7)
        
        weekdays = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
        weekday_str = weekdays[now_vn.weekday()]
        date_str = now_vn.strftime("%d/%m/%Y")
        time_str = now_vn.strftime("%H:%M:%S")
        
        full_prompt = (
            f"[HỆ THỐNG]: Mốc thời gian thực hiện tại là {weekday_str}, ngày {date_str}, lúc {time_str} (Múi giờ UTC+7).\n"
            f"[YÊU CẦU]: Bạn là Trợ lý Anna phục vụ bạn Quản Hữu Quân.\n"
            f"Nếu câu hỏi chứa yêu cầu đặt nhắc việc (ví dụ: 'nhắc tôi...', 'đặt lịch...'), hãy trả lời tự nhiên đồng thời trích xuất thông tin theo định dạng:\n"
            f"[[REMINDER|Nội dung công việc|YYYY-MM-DDTHH:MM:SS+07:00]] ở cuối câu trả lời.\n"
            f"Nếu không có yêu cầu nhắc việc, trả lời bình thường.\n\n"
            f"Tin nhắn của bạn Quân: {user_text}"
        )

        response = model.generate_content(full_prompt)
        reply_text = response.text

        # Tự động bóc tách và lưu vào Supabase
        if "[[REMINDER|" in reply_text:
            try:
                parts = reply_text.split("[[REMINDER|")[1].split("]]")[0].split("|")
                task_desc = parts[0].strip()
                remind_time_str = parts[1].strip()

                save_reminder(user_id, task_desc, remind_time_str)
                
                clean_reply = reply_text.split("[[REMINDER|")[0].strip()
                clean_reply += f"\n\n✅ *Đã ghi nhận nhắc việc vào hệ thống!*"
                reply_text = clean_reply
            except Exception as ex:
                logging.error(f"Lỗi bóc tách nhắc việc: {ex}")

        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=sent_message.message_id,
            text=reply_text,
            parse_mode="Markdown"
        )

    except Exception as e:
        logging.error(f"Lỗi: {e}")
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=sent_message.message_id,
            text=f"Lỗi rồi bạn Quân ơi: {str(e)}"
        )

async def post_init(app):
    asyncio.create_task(check_and_send_reminders(app))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
