import os
import asyncio
import sqlite3
import time
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv
from aiohttp import web
from pypdf import PdfReader, PdfWriter

from Processor import extract_and_compile_wt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))

bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"), default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()

# --- SQLITE DATABASE ---
DB_PATH = os.path.join(BASE_DIR, "users.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, ui_lang TEXT, target_lang TEXT)''')
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT ui_lang, target_lang FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def save_user(user_id, ui_lang, target_lang):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("REPLACE INTO users (user_id, ui_lang, target_lang) VALUES (?, ?, ?)", (user_id, ui_lang, target_lang))
    conn.commit()
    conn.close()

init_db()

# --- UI DICTIONARY ---
UI = {
    "en": {
        "welcome": "Welcome to the Result Vocabulary Bot! 🎓\nLet's get you set up.",
        "ask_target": "🎯 **What language do you want to translate your words into?**",
        "btn_target_uz": "🇺🇿 Uzbek",
        "btn_target_ru": "🇷🇺 Russian",
        "btn_target_other": "✍️ Other",
        "ask_other": "✍️ **Please type the language you want to translate into:**",
        "tutorial": "🚀 **How to use this bot:**\n\n**1. Download WordTheme**\n[Android (Google Play)](https://play.google.com/store/apps/details?id=fr.jmmoriceau.wordtheme) | [iOS (App Store)](https://apps.apple.com/us/app/wordtheme/id1603902951)\n\n**2. Prime the App**\nOpen WordTheme once and click through the intro screen.\n\n**3. Generate & Import**\nSend me a photo, PDF, or text. I will generate a native `.wt` file loaded with neural audio and definitions. \n\nTap the generated file in Telegram to open it directly in WordTheme!\n\n*(Send a file to begin!)*",
        "settings_btn": "⚙️ Settings",
        "got_file": "📄 File secured! Compiling native WordTheme package..."
    }
}
# Fallback logic maps RU/UZ directly to EN for simplicity if omitted, assuming standard UI.
for lang in ["ru", "uz"]: UI[lang] = UI["en"] 

awaiting_target = {}

def get_main_keyboard(lang="en"):
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=UI["en"]["settings_btn"])]], resize_keyboard=True)

def get_target_keyboard(lang="en"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=UI["en"]["btn_target_uz"], callback_data="target_Uzbek")],
        [InlineKeyboardButton(text=UI["en"]["btn_target_ru"], callback_data="target_Russian")],
        [InlineKeyboardButton(text=UI["en"]["btn_target_other"], callback_data="target_other")]
    ])

# --- ONBOARDING & SETTINGS ---
@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    user = get_user(message.from_user.id)
    if not user:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🇬🇧 English", callback_data="setui_en"), 
             InlineKeyboardButton(text="🇷🇺 Русский", callback_data="setui_ru"), 
             InlineKeyboardButton(text="🇺🇿 O'zbek", callback_data="setui_uz")]
        ])
        await message.answer("🌍 Please choose your interface language / Выберите язык / Tilni tanlang:", reply_markup=kb)
    else:
        await message.answer(UI["en"]["tutorial"], reply_markup=get_main_keyboard(), disable_web_page_preview=True)

@dp.callback_query(F.data.startswith("setui_"))
async def set_ui_callback(callback_query: CallbackQuery):
    ui_lang = callback_query.data.split("_")[1]
    save_user(callback_query.from_user.id, ui_lang, "Uzbek") 
    await callback_query.message.edit_text(UI["en"]["welcome"])
    await callback_query.message.answer(UI["en"]["ask_target"], reply_markup=get_target_keyboard())

@dp.callback_query(F.data.startswith("target_"))
async def target_callback(callback_query: CallbackQuery):
    selection = callback_query.data.split("_")[1]
    user_id = callback_query.from_user.id
    
    if selection == "other":
        awaiting_target[user_id] = True
        await callback_query.message.edit_text(UI["en"]["ask_other"])
    else:
        save_user(user_id, "en", selection)
        await callback_query.message.delete()
        await callback_query.message.answer(f"✅ Target language saved as: **{selection}**\n\n" + UI["en"]["tutorial"], reply_markup=get_main_keyboard(), disable_web_page_preview=True)

@dp.message(F.text.in_(["⚙️ Settings", "⚙️ Настройки", "⚙️ Sozlamalar"]))
async def settings_handler(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="setui_en"), 
         InlineKeyboardButton(text="🇷🇺 Русский", callback_data="setui_ru"), 
         InlineKeyboardButton(text="🇺🇿 O'zbek", callback_data="setui_uz")]
    ])
    await message.answer("🌍 Change UI Language:", reply_markup=kb)

# --- CORE AI ENGINE & PROGRESS BAR ---
async def process_and_send(message: Message, processing_msg: Message, file_path=None, text_content=None, mime_type=None, target_lang="Uzbek"):
    last_update_time = time.time()
    
    async def update_progress(current, total):
        nonlocal last_update_time
        now = time.time()
        if now - last_update_time > 1.5 or current == total:
            try:
                await processing_msg.edit_text(f"🎙️ Generating Neural Audio: {current}/{total} words...")
                last_update_time = now
            except Exception:
                pass

   try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model='gemini-3.6-flash',  # <--- CHANGE THIS BACK TO 3.6
            contents=contents,
            config=types.GenerateContentConfig(
                max_output_tokens=8192, 
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=vocab_schema
            )
        )
    except Exception as e:
        if uploaded_pdf:
            try: client.files.delete(name=uploaded_pdf.name)
            except: pass
        return None, f"🚨 AI Engine Error: {e}"
            
        await processing_msg.edit_text("📦 Packaging native WordTheme file...")
        
        document = FSInputFile(wt_path)
        await message.answer_document(document, caption="🎉 Your native WordTheme file is ready!\n\nTap it to open directly in the app.")
        
        await processing_msg.delete()
        if file_path and os.path.exists(file_path): os.remove(file_path)
        if os.path.exists(wt_path): os.remove(wt_path)
        
    except Exception as e:
        await message.answer(f"🚨 An unexpected error occurred: {e}")
        if file_path and os.path.exists(file_path): os.remove(file_path)

# --- FILE HANDLERS ---
@dp.message(F.document)
async def handle_document(message: Message) -> None:
    user = get_user(message.from_user.id)
    if not user: return await message.answer("Please type /start first!")
    target_lang = user[1]
    
    mime = message.document.mime_type
    ext = (message.document.file_name or "").split('.')[-1].lower()
    
    if mime in ['application/pdf', 'image/png', 'image/jpeg']:
        status_msg = await message.answer(UI["en"]["got_file"])
        doc_file = await bot.get_file(message.document.file_id)
        temp_path = os.path.join(BASE_DIR, f"doc_{message.from_user.id}_{message.message_id}.{ext}")
        await bot.download_file(doc_file.file_path, temp_path)
        
        if mime == 'application/pdf':
            reader = PdfReader(temp_path)
            # CRITICAL LIMIT: Slicing to 2 pages max to prevent token burnout on dense docs
            if len(reader.pages) > 2:
                writer = PdfWriter()
                for i in range(2): writer.add_page(reader.pages[i])
                with open(temp_path, "wb") as f_out: writer.write(f_out)
                await message.answer("⚠️ Sliced to first 2 pages to guarantee AI stability for dense dictionaries.")
        
        await process_and_send(message, status_msg, file_path=temp_path, mime_type=mime, target_lang=target_lang)

@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    user = get_user(message.from_user.id)
    if not user: return await message.answer("Please type /start first!")
    target_lang = user[1]
    
    status_msg = await message.answer(UI["en"]["got_file"])
    photo_file = await bot.get_file(message.photo[-1].file_id)
    temp_path = os.path.join(BASE_DIR, f"img_{message.from_user.id}_{message.message_id}.jpg")
    await bot.download_file(photo_file.file_path, temp_path)
    
    await process_and_send(message, status_msg, file_path=temp_path, mime_type='image/jpeg', target_lang=target_lang)

@dp.message(F.text)
async def handle_text(message: Message) -> None:
    if message.text.startswith('/'): return 
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user: return await message.answer("Please type /start first!")
    target_lang = user[1]
    
    if awaiting_target.get(user_id):
        save_user(user_id, "en", message.text)
        awaiting_target.pop(user_id)
        await message.answer(f"✅ Target language saved as: **{message.text}**\n\n" + UI["en"]["tutorial"], reply_markup=get_main_keyboard(), disable_web_page_preview=True)
        return
    
    status_msg = await message.answer(UI["en"]["got_file"])
    await process_and_send(message, status_msg, text_content=message.text, target_lang=target_lang)

async def handle_web(request): return web.Response(text="Bot is running smoothly on Render!")

async def main() -> None:
    print("🚀 Bot is officially online!")
    app = web.Application()
    app.router.add_get('/', handle_web)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080)))
    await site.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
