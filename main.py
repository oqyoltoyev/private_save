from telethon import TelegramClient, events
from telethon.sessions import StringSession
import sqlite3
import time
import os
import asyncio
import psutil
import base64  # Base64 kodlash va dekodlash uchun

# Telegram API sozlamalari
string_session = '1ApWapzMBuwR3liRMi-gvBScfa_YqQ0Rg-4K7TB7cwxS7KfbEUY5tSxPKtBAJwIGvqbGanKaUH83S8t_2Nlh_JbtJZC7G7hvxg8ET9PnQHqDz-LtEqdugK2DbMPWyXiK2iEw1Vh7SpiD1zq_5l7a1sFDe6qCEqI-pIDOdxA0uZxxFKriPoYgLevUz-AwAhqEwn60yNg-eslGyVYQH38zw3dlDBz3HSoaEFXTdgiuARJmkdA_oDA4KatJ6URxvFOHXeJO3p1rpHSehhddGxgfUfb6laMJ6hOaR8istZe6gwbD0odxtrYRyETIGsrdPWEpW9XCEWshC2l7r4KGALPopeATZ_IdoiPU='  # Bu yerga StringSession ma'lumotini qo'shing

client = TelegramClient(StringSession(string_session), api_id=24720214, api_hash="09ed497cc8083edb349dc55f1fa82b90")

# SQLite ma'lumotlar bazasi sozlamalari
conn = sqlite3.connect("downloads.db")
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    message_id INTEGER,
    file_name TEXT,
    file_size INTEGER,
    downloaded_size INTEGER,
    start_time REAL,
    status TEXT
)
""")
conn.commit()

# Fayl progressini yangilash
async def update_progress(user_id, message_id, file_name, current, total, start_time):
    elapsed_time = time.time() - start_time
    download_speed = current / elapsed_time if elapsed_time > 0 else 0
    remaining_time = int((total - current) / download_speed) if download_speed > 0 else 0

    cursor.execute("""
    INSERT OR REPLACE INTO downloads (id, user_id, message_id, file_name, file_size, downloaded_size, start_time, status)
    VALUES (
        (SELECT id FROM downloads WHERE user_id=? AND message_id=?),
        ?, ?, ?, ?, ?, ?, 'active'
    )
    """, (user_id, message_id, user_id, message_id, file_name, total, current, start_time))
    conn.commit()

    return {
        "elapsed_time": elapsed_time,
        "download_speed": download_speed,
        "remaining_time": remaining_time
    }

# Progress bar
def progress_bar(current_bytes, total_bytes, length=30):
    current_mb = current_bytes / (1024 * 1024)
    total_mb = total_bytes / (1024 * 1024)
    progress = current_mb / total_mb if total_mb > 0 else 0
    filled_length = int(length * progress)
    bar = '█' * filled_length + '-' * (length - filled_length)
    return f"[{bar}] {current_mb:.2f}MB / {total_mb:.2f}MB ({progress * 100:.2f}%)"

last_edit_time = {}  # Floodni oldini olish uchun global sozlama

# Fayl yuklanish progressini yangilash
async def progress_callback(current, total, message, user_id, msg_id, file_name, start_time):
    now = time.time()

    # flooddan himoya qilish: har 10 soniyada bir marta yangilash
    if user_id in last_edit_time:
        if now - last_edit_time[user_id] < 10:
            return
    last_edit_time[user_id] = now

    data = await update_progress(user_id, msg_id, file_name, current, total, start_time)
    bar = progress_bar(current, total)
    remaining = f"{data['remaining_time'] // 60}m {data['remaining_time'] % 60}s"
    speed = data['download_speed'] / 1024  # KB/s

    await message.edit(
        f"📂 **Yuklanmoqda...**\n"
        f"{bar}\n"
        f"🚀 Tezlik: {speed:.2f} KB/s\n"
        f"⏳ Qolgan vaqt: {remaining}\n"
    )

# Fayl yuklash komandasi
@client.on(events.NewMessage(pattern=r'\.download (-?\d+) \| (\d+)'))
async def download_handler(event):
    try:
        channel_id = int(event.pattern_match.group(1))
        msg_id = int(event.pattern_match.group(2))
        user_id = event.sender_id

        user_entity = await client.get_entity(user_id)
        message = await client.send_message(user_entity, "Yuklanish boshlandi...")

        msg = await client.get_messages(channel_id, ids=msg_id)
        caption = f"{msg.message}" if msg.message else "Fayl mavjud emas"

        if msg.media:
            start_time = time.time()
            file = await client.download_media(
                msg, progress_callback=lambda current, total: progress_callback(current, total, message, user_id, msg_id, msg.file.name, start_time)
            )

            # Faylni yuborish va holatini yangilash
            await client.send_file(user_entity, file, caption=caption)
            await message.edit("✅ Fayl muvaffaqiyatli yuklandi.")

            cursor.execute("UPDATE downloads SET status='completed' WHERE user_id=? AND message_id=?", (user_id, msg_id))
            conn.commit()

            if os.path.exists(file):
                os.remove(file)
                print(f"Fayl o'chirildi: {file}")
        else:
            await message.edit("Matnli xabar yuklandi.")

    except Exception as e:
        await event.respond(f"❌ Xatolik yuz berdi: {str(e)}")
        print(f"Xatolik: {e}")

# Holat haqida ma'lumot
@client.on(events.NewMessage(pattern=r'\.holat'))
async def status_handler(event):
    # Server holati
    cpu_usage = psutil.cpu_percent()
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    # Yuklanayotgan fayllar
    cursor.execute("SELECT * FROM downloads WHERE status='active'")
    active_downloads = cursor.fetchall()

    if not active_downloads:
        await event.respond(
            f"📊 **Server holati**:\n"
            f"🖥 CPU yuklanishi: {cpu_usage}%\n"
            f"💾 RAM: {memory.percent}% ishlatilmoqda ({memory.used // (1024 ** 2)} MB / {memory.total // (1024 ** 2)} MB)\n"
            f"💽 Disk: {disk.percent}% ishlatilmoqda ({disk.used // (1024 ** 3)} GB / {disk.total // (1024 ** 3)} GB)\n\n"
            f"📂 Hozirda yuklanayotgan fayllar mavjud emas."
        )
        return

    status_message = (
        f"📊 **Server holati**:\n"
        f"🖥 CPU yuklanishi: {cpu_usage}%\n"
        f"💾 RAM: {memory.percent}% ishlatilmoqda ({memory.used // (1024 ** 2)} MB / {memory.total // (1024 ** 2)} MB)\n"
        f"💽 Disk: {disk.percent}% ishlatilmoqda ({disk.used // (1024 ** 3)} GB / {disk.total // (1024 ** 3)} GB)\n\n"
        f"📂 **Yuklanayotgan fayllar**: {len(active_downloads)}\n\n"
    )

    for download in active_downloads:
        elapsed_time = time.time() - download[6]
        download_speed = download[5] / elapsed_time if elapsed_time > 0 else 0
        remaining_time = int((download[4] - download[5]) / download_speed) if download_speed > 0 else 0

        status_message += (
            f"📁 Fayl: `{download[3]}`\n"
            f"🔽 Yuklangan: {download[5]} / {download[4]} bayt\n"
            f"🚀 Tezlik: {download_speed:.2f} bayt/sek\n"
            f"⏳ Qolgan vaqt: {remaining_time // 60}m {remaining_time % 60}s\n"
            f"⏳ Boshlangan vaqt: {time.strftime('%H:%M:%S', time.localtime(download[6]))}\n\n"
        )

    await event.respond(status_message)

# Rasmni Base64 kodlash va qayta tiklash
@client.on(events.NewMessage(outgoing=True, pattern=r'\.shu'))
async def savepic(event):
    try:
        # Xabarni o'chirish
        await event.delete()

        # Javob xabaridan media yuklash
        get_restricted_content = await event.get_reply_message()
        if not get_restricted_content or not get_restricted_content.media:
            await event.respond("Iltimos, javob xabarda rasm biriktirilgan bo'lsin!")
            return

        download_restricted_content = await get_restricted_content.download_media()

        # Media faylni base64 kodlash
        with open(download_restricted_content, "rb") as img_file:
            encoded_img = base64.b64encode(img_file.read()).decode()

        await event.respond(f"📷 Fayl Base64 kodlandi:\n{encoded_img}")

    except Exception as e:
        await event.respond(f"❌ Xatolik yuz berdi: {str(e)}")

# Main qism
client.start()
client.run_until_disconnected()
