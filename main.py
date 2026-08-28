import os
import io
import logging
import datetime
import asyncio
import json
import pandas as pd
import google.generativeai as genai
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

# 1. CAU HINH LOGGING & BIEN MOI TRUONG
logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Khởi tạo Gemini & Supabase Client
genai.configure(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
model = genai.GenerativeModel("gemini-3.1-flash-lite")

# 2. CAC HAM XU LY DATABASE SUPABASE
def insert_task_record(data: dict):
    """Lưu bản ghi vào Supabase theo Schema v2.0"""
    try:
        res = supabase.table("tasks_events").insert(data).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logging.error(f"Loi insert Supabase: {e}")
        return None

def update_task_status(task_id: str, status: str):
    """Cập nhật trạng thái DRAFT, CONFIRMED, COMPLETED, CANCELLED"""
    try:
        supabase.table("tasks_events").update({"status": status}).eq("id", task_id).execute()
        return True
    except Exception as e:
        logging.error(f"Loi update Supabase: {e}")
        return False

# 3. TIEN TRINH CHAY NGAM NHAC LIEU (BACKGROUND TASK)
async def check_and_send_reminders(app):
    """Tiến trình ngầm quét lịch hẹn tương lai và gửi thông báo"""
    while True:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            now_iso = now_utc.isoformat()

            # Quét các việc đã CONFIRMED, là lịch tương lai, chưa gửi thông báo
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

                msg = f"⏰ **ANNA NHẮC LỊCH BẠN QUÂN!**\n\n[{group_str}]\n👉 Nội dung: **{title}**"
                await app.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")

                # Đánh dấu đã gửi
                supabase.table("tasks_events").update({"is_sent": True}).eq("id", task_id).execute()

        except Exception as e:
            logging.error(f"Loi Tien trinh Nhac lich: {e}")

        await asyncio.sleep(30)

# 4. TAO GIAO DIEN INLINE CARD 3 TANG (SRS v2.0)
def build_inline_card_markup(task_id: str, current_cat: str):
    """Tạo bàn phím nút bấm 3 tầng tương tác trực tiếp"""
    keyboard = [
        # Tầng 1: Xác nhận & Hủy
        [
            InlineKeyboardButton("✅ Duyệt & Lưu", callback_data=f"confirm_{task_id}"),
            InlineKeyboardButton("❌ Hủy bỏ", callback_data=f"cancel_{task_id}"),
        ],
        # Tầng 2: Đổi phân loại Nhóm A/B/C
        [
            InlineKeyboardButton("🏷️ Nhóm A (Việc)", callback_data=f"setcat_GROUP_A_TASK_{task_id}"),
            InlineKeyboardButton("🏷️ Nhóm B (Lịch)", callback_data=f"setcat_GROUP_B_SCHEDULE_{task_id}"),
            InlineKeyboardButton("🏷️ Nhóm C (Cá nhân)", callback_data=f"setcat_GROUP_C_PERSONAL_{task_id}"),
        ],
        # Tầng 3: Tùy chỉnh nhắc nhở
        [
            InlineKeyboardButton("🔔 Nhắc trước 15p", callback_data=f"remind_15_{task_id}"),
            InlineKeyboardButton("🔔 Nhắc trước 1h", callback_data=f"remind_60_{task_id}"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# 5. XU LY TIN NHAN DA PHUONG THUC (TEXT/VOICE/IMAGE)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if ALLOWED_USER_ID and str(ALLOWED_USER_ID) != "0" and str(user_id) != str(ALLOWED_USER_ID):
        await update.message.reply_text("Xin lỗi, bạn không có quyền truy cập Trợ lý Anna.")
        return

    user_text = update.message.text
    sent_msg = await update.message.reply_text("⚡ Anna đang bóc tách ngữ cảnh...")

    try:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        now_vn = now_utc + datetime.timedelta(hours=7)
        now_str = now_vn.strftime("%Y-%m-%d %H:%M:%S")

        prompt = (
            f"Thời gian hiện tại: {now_str} (Giờ Việt Nam GMT+7).\n"
            f"Phân tích tin nhắn của bạn Quản Hữu Quân và xuất kết quả DUY NHẤT theo định dạng JSON với cấu trúc:\n"
            f"{{\n"
            f'  "is_task": true/false,\n'
            f'  "title": "Tên chi tiết công việc/sự kiện",\n'
            f'  "category": "GROUP_A_TASK" hoặc "GROUP_B_SCHEDULE" hoặc "GROUP_C_PERSONAL",\n'
            f'  "start_time": "YYYY-MM-DD HH:MM:SS",\n'
            f'  "is_retroactive": true (nếu là nhật ký quá khứ) / false (nếu là lịch tương lai),\n'
            f'  "remind_at": "YYYY-MM-DD HH:MM:SS" (thời điểm gửi thông báo, mặc định bằng start_time hoặc trước 30p)\n'
            f"}}\n"
            f"Tin nhắn: '{user_text}'"
        )

        response = model.generate_content(prompt)
        res_text = response.text.strip()
        
        # Bóc tách JSON
        if "```json" in res_text:
            res_text = res_text.split("```json")[1].split("```")[0].strip()
        elif "```" in res_text:
            res_text = res_text.split("```")[1].split("```")[0].strip()

        data_json = json.loads(res_text)

        if data_json.get("is_task"):
            # Tạo bản ghi DRAFT trong Supabase
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
            # Câu trả lời hội thoại bình thường
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=sent_msg.message_id,
                text=res_text
            )

    except Exception as e:
        logging.error(f"Loi xu ly message: {e}")
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=sent_msg.message_id,
            text=f"Dạ, em gặp chút trục trặc: {e}"
        )

# 6. XU LY INTERACTIVE BUTTONS (CALLBACK QUERY)
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("confirm_"):
        task_id = data.replace("confirm_", "")
        update_task_status(task_id, "CONFIRMED")
        await query.edit_message_text(
            text=query.message.text + "\n\n✅ **ĐÃ XÁC NHẬN & ĐỒNG BỘ CSDL THÀNH CÔNG!**",
            parse_mode="Markdown"
        )
    elif data.startswith("cancel_"):
        task_id = data.replace("cancel_", "")
        update_task_status(task_id, "CANCELLED")
        await query.edit_message_text(
            text=query.message.text + "\n\n❌ **ĐÃ HỦY NHIỆM VỤ NÀY.**",
            parse_mode="Markdown"
        )
    elif data.startswith("setcat_"):
        parts = data.split("_")
        new_cat = f"{parts[1]}_{parts[2]}_{parts[3]}"
        task_id = parts[4]
        
        supabase.table("tasks_events").update({"category": new_cat}).eq("id", task_id).execute()
        await query.edit_message_text(
            text=query.message.text + f"\n\n🔄 *Đã cập nhật phân loại mới! Bấm Duyệt để hoàn tất.*",
            reply_markup=build_inline_card_markup(task_id, new_cat),
            parse_mode="Markdown"
        )

# 7. XUẤT BÁO CÁO FILE EXCEL TRỰC TIẾP (/baocao)
async def export_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sent_msg = await update.message.reply_text("📊 Anna đang kết xuất báo cáo Excel...")
    try:
        response = supabase.table("tasks_events").select("*").execute()
        data = response.data

        if not data:
            await sent_msg.edit_text("Hiện chưa có dữ liệu công việc trong CSDL.")
            return

        df = pd.DataFrame(data)
        
        # Đổi tên cột chuẩn hành chính
        col_map = {
            "title": "Nội dung công việc / Lịch trình",
            "category": "Nhóm phân loại",
            "start_time": "Thời gian thực hiện",
            "status": "Trạng thái",
            "is_retroactive": "Lịch quá khứ (Retro)"
        }
        df = df.rename(columns=col_map)
        
        # Xuất ra bộ nhớ đệm Stream
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
        logging.error(f"Loi xuat bao cao: {e}")
        await sent_msg.edit_text(f"Lỗi xuất báo cáo: {e}")

# 8. KHOI CHAY BOT
async def post_init(app):
    asyncio.create_task(check_and_send_reminders(app))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    # Handlers
    app.add_handler(CommandHandler("baocao", export_report))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    app.run_polling()
