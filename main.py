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


async def progress_callback(current, total, message, user_id, msg_id, file_name, start_time):
    data = await update_progress(user_id, msg_id, file_name, current, total, start_time)
    progress = (current / total) * 100

    # Fayl yuklash jarayoni haqida ma'lumot
    await message.edit(
        f"📂 **Yuklanmoqda...**\n"
        f"✅ Progress: {progress:.2f}%\n"
        f"🔽 Yuklangan hajm: {current} / {total} bayt\n"
        f"🚀 Internet tezligi: {data['download_speed']:.2f} bayt/sek\n"
        f"⏳ Qolgan vaqt: {data['remaining_time'] // 60}m {data['remaining_time'] % 60}s\n"
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
        with open(download_restricted_content, "rb") as image2string:
            converted_string = base64.b64encode(image2string.read())

        with open("encoded_image.txt", "wb") as file:
            file.write(converted_string)

        # Faylni qayta dekodlash va rasmni yaratish
        with open("encoded_image.txt", 'rb') as file:
            byte = file.read()

        with open("decoded_image.jpg", 'wb') as decodeit:
            decodeit.write(base64.b64decode(byte))

        # Foydalanuvchiga natijani yuborish
        await client.send_file("me", "decoded_image.jpg", caption="Userbot yordamida saqlangan ✓")

        # Oraliq fayllarni o'chirish
        os.remove(download_restricted_content)
        os.remove("decoded_image.jpg")
        os.remove("encoded_image.txt")

    except Exception as e:
        print(f"Xatolik: {e}")
        await event.respond(f"Xatolik yuz berdi: {e}")


async def main():
    await client.start()
    print("Bot ishga tushdi...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
