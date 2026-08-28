import os
import io
import logging
import datetime
import asyncio
import json
import pandas as pd
from google import genai
from supabase import create_client, Client
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    filters,
)

# 1. CẤU HÌNH HỆ THỐNG & BIẾN MÔI TRƯỜNG
logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Khởi tạo Client Gemini SDK mới & Supabase Client
ai_client = genai.Client(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 2. THAO TÁC CƠ SỞ DỮ LIỆU SUPABASE
def insert_task_record(data: dict):
    """Tạo bản ghi DRAFT trong Supabase theo Schema v2.0"""
    try:
        res = supabase.table("tasks_events").insert(data).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logging.error(f"Lỗi insert Supabase: {e}")
        return None

def update_task_status(task_id: str, status: str):
    """Cập nhật trạng thái DRAFT -> CONFIRMED / CANCELLED"""
    try:
        supabase.table("tasks_events").update({"status": status}).eq("id", task_id).execute()
        return True
    except Exception as e:
        logging.error(f"Lỗi update Supabase: {e}")
        return False

# 3. TIẾN TRÌNH NHẮC LỊCH NGẦM (BACKGROUND SCHEDULER)
async def check_and_send_reminders(app):
    """Tiến trình quét và gửi thông báo cho các nhiệm vụ đã CONFIRMED"""
    while True:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            now_iso = now_utc.isoformat()

            response = (
                supabase.table("tasks_events")
                .select("*")
                .eq("status", "CONFIRMED")
                .eq("is_retroactive", False)
                .eq("is_sent", False)
                .lte("remind_at", now_iso)
                .execute()
            )

            for item in response.data:
                user_id = item["user_id"]
                title = item["title"]
                cat = item["category"]
                task_id = item["id"]

                cat_map = {
                    "GROUP_A_TASK": "📌 Công việc (Nhóm A)",
                    "GROUP_B_SCHEDULE": "📅 Lịch công tác (Nhóm B)",
                    "GROUP_C_PERSONAL": "🏠 Cá nhân (Nhóm C)"
                }
                group_str = cat_map.get(cat, "Nhiệm vụ")

                msg = f"⏰ **ANNA NHẮC LỊCH BẠN QUÂN!**\n\n[{group_str}]\n👉 **Nội dung:** {title}"
                await app.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")

                supabase.table("tasks_events").update({"is_sent": True}).eq("id", task_id).execute()

        except Exception as e:
            logging.error(f"Lỗi Tiến trình Nhắc lịch: {e}")

        await asyncio.sleep(30)

# 4. GIAO DIỆN INLINE CARD 3 TẦNG (SRS v2.0)
def build_inline_card_markup(task_id: str, current_cat: str):
    """Bàn phím nút bấm tương tác trực tiếp 3 tầng"""
    keyboard = [
        # Tầng 1: Xác nhận & Hủy
        [
            InlineKeyboardButton("✅ Duyệt & Lưu", callback_data=f"confirm_{task_id}"),
            InlineKeyboardButton("❌ Hủy bỏ", callback_data=f"cancel_{task_id}"),
        ],
        # Tầng 2: Đổi nhóm A / B / C
        [
            InlineKeyboardButton("🏷️ Nhóm A (Việc)", callback_data=f"setcat_GROUP_A_TASK_{task_id}"),
            InlineKeyboardButton("🏷️ Nhóm B (Lịch)", callback_data=f"setcat_GROUP_B_SCHEDULE_{task_id}"),
            InlineKeyboardButton("🏷️ Nhóm C (Cá nhân)", callback_data=f"setcat_GROUP_C_PERSONAL_{task_id}"),
        ],
        # Tầng 3: Thời gian nhắc
        [
            InlineKeyboardButton("🔔 Trước 15 phút", callback_data=f"remind_15_{task_id}"),
            InlineKeyboardButton("🔔 Trước 1 giờ", callback_data=f"remind_60_{task_id}"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# 5. XỬ LÝ DỮ LIỆU ĐẦU VÀO (TEXT, VOICE, IMAGE)
async def process_input_and_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_content, content_type="TEXT"):
    user_id = update.effective_user.id

    if ALLOWED_USER_ID and str(ALLOWED_USER_ID) != "0" and str(user_id) != str(ALLOWED_USER_ID):
        await update.message.reply_text("Xin lỗi, bạn không có quyền truy cập Trợ lý Anna.")
        return

    sent_msg = await update.message.reply_text("⚡ Anna đang bóc tách ngữ cảnh...")

    try:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        now_vn = now_utc + datetime.timedelta(hours=7)
        now_str = now_vn.strftime("%Y-%m-%d %H:%M:%S (%A)")

        prompt_system = (
            f"Thời gian hiện tại: {now_str} (Giờ Việt Nam GMT+7).\n"
            f"Phân tích dữ liệu đầu vào của bạn Quản Hữu Quân và xuất DUY NHẤT một chuỗi JSON hợp lệ với cấu trúc:\n"
            f"{{\n"
            f'  "is_task": true/false,\n'
            f'  "title": "Tên chi tiết công việc/sự kiện",\n'
            f'  "category": "GROUP_A_TASK" hoặc "GROUP_B_SCHEDULE" hoặc "GROUP_C_PERSONAL",\n'
            f'  "start_time": "YYYY-MM-DD HH:MM:SS",\n'
            f'  "is_retroactive": true (nếu là nhật ký quá khứ) / false (nếu là lịch tương lai),\n'
            f'  "remind_at": "YYYY-MM-DD HH:MM:SS" (thời điểm gửi thông báo)\n'
            f"}}\n"
        )

        # Gọi Gemini qua SDK google-genai mới
        if content_type == "TEXT":
            response = ai_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"{prompt_system}\nNội dung văn bản: '{raw_content}'"
            )
        elif content_type in ["VOICE", "IMAGE"]:
            response = ai_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[prompt_system, raw_content]
            )

        res_text = response.text.strip()

        if "```json" in res_text:
            res_text = res_text.split("```json")[1].split("```")[0].strip()
        elif "```" in res_text:
            res_text = res_text.split("```")[1].split("```")[0].strip()

        data_json = json.loads(res_text)

        if data_json.get("is_task"):
            record = {
                "user_id": user_id,
                "title": data_json.get("title"),
                "category": data_json.get("category", "GROUP_A_TASK"),
                "start_time": data_json.get("start_time"),
                "remind_at": data_json.get("remind_at"),
                "is_retroactive": data_json.get("is_retroactive", False),
                "status": "DRAFT",
                "is_sent": False
            }
            inserted = insert_task_record(record)
            task_id = inserted["id"]

            cat_names = {
                "GROUP_A_TASK": "📌 Công việc (Nhóm A)",
                "GROUP_B_SCHEDULE": "📅 Lịch công tác (Nhóm B)",
                "GROUP_C_PERSONAL": "🏠 Cá nhân (Nhóm C)"
            }

            type_str = "📜 NHẬT KÝ QUÁ KHỨ" if record["is_retroactive"] else "🎯 KẾ HOẠCH TƯƠNG LAI"

            card_text = (
                f"📝 **DỰ THẢO NHIỆM VỤ (INLINE CARD v2.0)**\n"
                f"----------------------------------------\n"
                f"🔹 **Loại:** {type_str}\n"
                f"🔹 **Nội dung:** {record['title']}\n"
                f"🔹 **Phân loại:** {cat_names.get(record['category'])}\n"
                f"🔹 **Thời gian:** {record['start_time']}\n"
                f"----------------------------------------\n"
                f"👇 *Mời bạn Quân chọn thao tác bên dưới:* "
            )

            reply_markup = build_inline_card_markup(task_id, record["category"])
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=sent_msg.message_id,
                text=card_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=sent_msg.message_id,
                text=res_text
            )

    except Exception as e:
        logging.error(f"Lỗi xử lý input: {e}")
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=sent_msg.message_id,
            text=f"Dạ, em gặp trục trặc khi bóc tách: {e}"
        )

# Handlers riêng cho Text, Voice, Image
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_input_and_reply(update, context, update.message.text, content_type="TEXT")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await context.bot.get_file(update.message.voice.file_id)
    audio_bytes = await file.download_as_bytearray()
    audio_data = {"mime_type": "audio/ogg", "data": bytes(audio_bytes)}
    await process_input_and_reply(update, context, audio_data, content_type="VOICE")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    img_bytes = await file.download_as_bytearray()
    img_data = {"mime_type": "image/jpeg", "data": bytes(img_bytes)}
    await process_input_and_reply(update, context, img_data, content_type="IMAGE")

# 6. XỬ LÝ SỰ KIỆN NÚT BẤM (CALLBACK QUERY)
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("confirm_"):
        task_id = data.replace("confirm_", "")
        update_task_status(task_id, "CONFIRMED")
        await query.edit_message_text(
            text=query.message.text + "\n\n✅ **ĐÃ DUYỆT & LƯU CSDL THÀNH CÔNG!**",
            parse_mode="Markdown"
        )
    elif data.startswith("cancel_"):
        task_id = data.replace("cancel_", "")
        update_task_status(task_id, "CANCELLED")
        await query.edit_message_text(
            text=query.message.text + "\n\n❌ **ĐÃ HỦY THẺ NHÁP NÀY.**",
            parse_mode="Markdown"
        )
    elif data.startswith("setcat_"):
        parts = data.split("_")
        new_cat = f"{parts[1]}_{parts[2]}_{parts[3]}"
        task_id = parts[4]
        supabase.table("tasks_events").update({"category": new_cat}).eq("id", task_id).execute()
        await query.edit_message_text(
            text=query.message.text + f"\n\n🔄 *Đã đổi nhóm thành công! Bấm Duyệt & Lưu để hoàn tất.*",
            reply_markup=build_inline_card_markup(task_id, new_cat),
            parse_mode="Markdown"
        )

# 7. XUẤT BÁO CÁO EXCEL DIRECTLY (/baocao)
async def export_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sent_msg = await update.message.reply_text("📊 Anna đang kết xuất báo cáo Excel...")
    try:
        response = supabase.table("tasks_events").select("*").execute()
        data = response.data

        if not data:
            await sent_msg.edit_text("Hiện chưa có dữ liệu công việc trong CSDL.")
            return

        df = pd.DataFrame(data)
        col_map = {
            "title": "Nội dung công việc / Lịch trình",
            "category": "Nhóm phân loại",
            "start_time": "Thời gian thực hiện",
            "status": "Trạng thái",
            "is_retroactive": "Lịch quá khứ (Retro)"
        }
        df = df.rename(columns=col_map)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Nhật ký công việc")
        output.seek(0)

        now_str = datetime.datetime.now().strftime("%d%m%Y_%H%M")
        file_name = f"BaoCao_CongViec_Anna_{now_str}.xlsx"

        await update.message.reply_document(
            document=output,
            filename=file_name,
            caption="📄 **BÁO CÁO CÔNG VIỆC CHUYÊN NGHIỆP (EXCEL)**\nĐã xuất trực tiếp từ CSDL Supabase.",
            parse_mode="Markdown"
        )
        await sent_msg.delete()

    except Exception as e:
        logging.error(f"Lỗi xuất báo cáo: {e}")
        await sent_msg.edit_text(f"Lỗi xuất báo cáo: {e}")

# 8. KHỞI CHẠY BOT
async def post_init(app):
    asyncio.create_task(check_and_send_reminders(app))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("baocao", export_report))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    app.run_polling()
