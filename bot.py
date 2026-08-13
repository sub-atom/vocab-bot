import os
import asyncio
import sqlite3
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv
from aiohttp import web
from pypdf import PdfReader, PdfWriter

from Processor import extract_vocabulary, convert_to_excel, merge_excel_files

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))

bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"), default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()

# --- 1. SQLITE DATABASE SETUP ---
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

# --- 2. MULTI-LANGUAGE UI DICTIONARY ---
UI = {
    "en": {
        "welcome": "Welcome to the Result Vocabulary Bot! 🎓\nLet's get you set up.",
        "ask_target": "🎯 **What language do you want to translate your words into?**\n*(Type it below, e.g., Uzbek, Russian, Arabic)*",
        "tutorial": "🚀 **How to use this bot:**\n\n**1. Download WordTheme**\n[Android (Google Play)](https://play.google.com/store/apps/details?id=fr.cedriccreusot.wordtheme) | [iOS (App Store)](https://apps.apple.com/us/app/wordtheme-custom-dictionary/id1527659918)\n\n**2. Prime the App**\nOpen WordTheme once and click through the intro screen so the app is awake.\n\n**3. Import your Vocabulary**\nTap the **three dots (⋮)** or the **Share icon** next to the Excel file here in Telegram. Tap **Share**, scroll through your apps, and select **WordTheme**.\n\n**4. Save**\nSelect *'Create New Theme'* and you are ready to play!\n\n*(Send me a photo, PDF, or text to begin!)*",
        "btn_trans": "🇺🇿 Translations Only",
        "btn_desc": "📖 Descriptions Only",
        "btn_both": "⭐ Both",
        "got_file": "📄 File secured! What do you want to extract?",
        "merge_add": "🛒 **Excel File Added!**\nYou have {} file(s) in your Merge Queue.",
        "merge_btn": "🔗 Merge Files Now",
        "clear_btn": "❌ Clear Queue",
        "ask_master": "🔗 **Please type a name for the new Master Theme** (e.g., 'Unit 1-3 Review').",
        "settings_btn": "⚙️ Settings"
    },
    "ru": {
        "welcome": "Добро пожаловать в Result Vocabulary Bot! 🎓\nДавайте настроим его.",
        "ask_target": "🎯 **На какой язык вы хотите переводить слова?**\n*(Напишите ниже, например: Русский, Узбекский, Арабский)*",
        "tutorial": "🚀 **Как использовать бота:**\n\n**1. Скачайте WordTheme**\n[Android](https://play.google.com/store/apps/details?id=fr.cedriccreusot.wordtheme) | [iOS](https://apps.apple.com/us/app/wordtheme-custom-dictionary/id1527659918)\n\n**2. Подготовьте приложение**\nОткройте WordTheme один раз и пропустите вступление.\n\n**3. Импорт словаря**\nНажмите на **три точки (⋮)** или **иконку Поделиться** рядом с файлом Excel в Telegram. Нажмите **Поделиться** и выберите **WordTheme**.\n\n**4. Сохранение**\nВыберите *'Создать новую тему'*, и всё готово!\n\n*(Отправьте мне фото, PDF или текст, чтобы начать!)*",
        "btn_trans": "🇷🇺 Только Перевод",
        "btn_desc": "📖 Только Описание",
        "btn_both": "⭐ Оба варианта",
        "got_file": "📄 Файл получен! Что вы хотите извлечь?",
        "merge_add": "🛒 **Файл Excel добавлен!**\nВ вашей очереди {} файл(ов).",
        "merge_btn": "🔗 Объединить файлы",
        "clear_btn": "❌ Очистить очередь",
        "ask_master": "🔗 **Напишите название для новой главной темы** (например, 'Повторение 1-3').",
        "settings_btn": "⚙️ Настройки"
    },
    "uz": {
        "welcome": "Result Vocabulary Bot-ga xush kelibsiz! 🎓\nKeling, sozlashni boshlaymiz.",
        "ask_target": "🎯 **So'zlaringizni qaysi tilga tarjima qilishni xohlaysiz?**\n*(Quyida yozing, masalan: O'zbek, Rus, Arab)*",
        "tutorial": "🚀 **Botdan qanday foydalanish kerak:**\n\n**1. WordTheme-ni yuklab oling**\n[Android](https://play.google.com/store/apps/details?id=fr.cedriccreusot.wordtheme) | [iOS](https://apps.apple.com/us/app/wordtheme-custom-dictionary/id1527659918)\n\n**2. Ilovani tayyorlang**\nWordTheme-ni bir marta oching va kirish qismini o'tkazib yuboring.\n\n**3. Lug'atni import qilish**\nTelegramdagi Excel fayli yonidagi **uchta nuqta (⋮)** yoki **Ulashish tugmasini** bosing. **Ulashish**-ni tanlab, **WordTheme**-ni toping.\n\n**4. Saqlash**\n*'Yangi mavzu yaratish'* ni tanlang va tayyor!\n\n*(Boshlash uchun rasm, PDF yoki matn yuboring!)*",
        "btn_trans": "🇺🇿 Faqat Tarjima",
        "btn_desc": "📖 Faqat Ta'rif",
        "btn_both": "⭐ Ikkalasi",
        "got_file": "📄 Fayl qabul qilindi! Nima ajratib olaylik?",
        "merge_add": "🛒 **Excel fayl qo'shildi!**\nNavbatda {} ta fayl bor.",
        "merge_btn": "🔗 Fayllarni Birlashtirish",
        "clear_btn": "❌ Navbatni Tozalash",
        "ask_master": "🔗 **Yangi Asosiy Mavzu nomini yozing** (masalan, '1-3 Unit Takrorlash').",
        "settings_btn": "⚙️ Sozlamalar"
    }
}

# --- 3. MEMORY STATES ---
pending_tasks = {}
merge_queues = {}
awaiting_theme = {}
awaiting_target = {}

# Persistent bottom keyboard for Settings
def get_main_keyboard(lang="en"):
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=UI[lang]["settings_btn"])]], resize_keyboard=True)

def get_options_keyboard(lang):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=UI[lang]["btn_trans"], callback_data="mode_translations")],
        [InlineKeyboardButton(text=UI[lang]["btn_desc"], callback_data="mode_descriptions")],
        [InlineKeyboardButton(text=UI[lang]["btn_both"], callback_data="mode_both")]
    ])

def get_merge_keyboard(lang):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=UI[lang]["merge_btn"], callback_data="merge_now")],
        [InlineKeyboardButton(text=UI[lang]["clear_btn"], callback_data="merge_clear")]
    ])

# --- 4. ONBOARDING & SETTINGS ---
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
        lang = user[0]
        await message.answer(UI[lang]["tutorial"], reply_markup=get_main_keyboard(lang), disable_web_page_preview=True)

@dp.callback_query(F.data.startswith("setui_"))
async def set_ui_callback(callback_query: CallbackQuery):
    ui_lang = callback_query.data.split("_")[1]
    save_user(callback_query.from_user.id, ui_lang, "Uzbek") # Default target
    awaiting_target[callback_query.from_user.id] = True
    await callback_query.message.edit_text(UI[ui_lang]["welcome"])
    await callback_query.message.answer(UI[ui_lang]["ask_target"])

@dp.message(F.text.in_(["⚙️ Settings", "⚙️ Настройки", "⚙️ Sozlamalar"]))
async def settings_handler(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="setui_en"), 
         InlineKeyboardButton(text="🇷🇺 Русский", callback_data="setui_ru"), 
         InlineKeyboardButton(text="🇺🇿 O'zbek", callback_data="setui_uz")]
    ])
    await message.answer("🌍 Change UI Language or type a new target translation language below!", reply_markup=kb)
    awaiting_target[message.from_user.id] = True

# --- 5. CORE AI ENGINE ---
async def process_and_send(message: Message, processing_msg: Message, file_path=None, text_content=None, mime_type=None, mode="both", target_lang="Uzbek"):
    try:
        await processing_msg.edit_text("🧠 Brain engaged...")
        json_data, brain_error = extract_vocabulary(file_path=file_path, text_content=text_content, mime_type=mime_type, mode=mode, target_language=target_lang)
        
        if brain_error:
            await processing_msg.edit_text(brain_error)
            if file_path and os.path.exists(file_path): os.remove(file_path)
            return
            
        await processing_msg.edit_text("📊 Formatting...")
        excel_path, conv_error = convert_to_excel(json_data, f"vocab_{message.from_user.id}.xlsx")
        
        if conv_error:
            await processing_msg.edit_text(conv_error)
            if file_path and os.path.exists(file_path): os.remove(file_path)
            return
            
        await message.answer_document(FSInputFile(excel_path))
        await processing_msg.delete()
        if file_path and os.path.exists(file_path): os.remove(file_path)
        if os.path.exists(excel_path): os.remove(excel_path)
    except Exception as e:
        await message.answer(f"🚨 Error: {e}")
        if file_path and os.path.exists(file_path): os.remove(file_path)

# --- 6. FILE HANDLERS ---
@dp.callback_query(F.data.startswith("mode_"))
async def process_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id not in pending_tasks: return
    user_data = get_user(user_id)
    target_lang = user_data[1] if user_data else "Uzbek"
    
    mode = callback_query.data.split("_")[1] 
    task = pending_tasks.pop(user_id)
    p_msg = await callback_query.message.edit_text("⚙️ Starting process...")
    await process_and_send(callback_query.message, p_msg, task.get('file_path'), task.get('text_content'), task.get('mime_type'), mode, target_lang)

@dp.callback_query(F.data == "merge_now")
async def merge_now_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    lang = get_user(user_id)[0] if get_user(user_id) else "en"
    awaiting_theme[user_id] = True
    await callback_query.message.edit_text(UI[lang]["ask_master"])

@dp.callback_query(F.data == "merge_clear")
async def merge_clear_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id in merge_queues:
        for path in merge_queues[user_id]:
            if os.path.exists(path): os.remove(path)
        merge_queues.pop(user_id)
    await callback_query.message.edit_text("🗑️ Queue cleared!")

@dp.message(F.document)
async def handle_document(message: Message) -> None:
    user = get_user(message.from_user.id)
    if not user: return await message.answer("Please type /start first!")
    lang = user[0]
    
    ext = (message.document.file_name or "").split('.')[-1].lower()
    
    if ext == 'xlsx':
        user_id = message.from_user.id
        doc_file = await bot.get_file(message.document.file_id)
        temp_path = os.path.join(BASE_DIR, f"q_{user_id}_{message.message_id}.xlsx")
        await bot.download_file(doc_file.file_path, temp_path)
        
        if user_id not in merge_queues: merge_queues[user_id] = []
        merge_queues[user_id].append(temp_path)
        
        await message.answer(UI[lang]["merge_add"].format(len(merge_queues[user_id])), reply_markup=get_merge_keyboard(lang))
        return

    mime = message.document.mime_type
    if mime in ['application/pdf', 'image/png', 'image/jpeg']:
        status_msg = await message.answer("📄 Downloading...")
        doc_file = await bot.get_file(message.document.file_id)
        temp_path = os.path.join(BASE_DIR, f"doc_{message.from_user.id}_{message.message_id}.{ext}")
        await bot.download_file(doc_file.file_path, temp_path)
        
        if mime == 'application/pdf':
            reader = PdfReader(temp_path)
            if len(reader.pages) > 5:
                writer = PdfWriter()
                for i in range(5): writer.add_page(reader.pages[i])
                with open(temp_path, "wb") as f_out: writer.write(f_out)
                await message.answer("⚠️ Sliced to first 5 pages for safety.")
        
        pending_tasks[message.from_user.id] = {'file_path': temp_path, 'mime_type': mime, 'text_content': None}
        await status_msg.edit_text(UI[lang]["got_file"], reply_markup=get_options_keyboard(lang))

@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    user = get_user(message.from_user.id)
    if not user: return await message.answer("Please type /start first!")
    lang = user[0]
    
    status_msg = await message.answer("📸 Downloading...")
    photo_file = await bot.get_file(message.photo[-1].file_id)
    temp_path = os.path.join(BASE_DIR, f"img_{message.from_user.id}_{message.message_id}.jpg")
    await bot.download_file(photo_file.file_path, temp_path)
    
    pending_tasks[message.from_user.id] = {'file_path': temp_path, 'mime_type': 'image/jpeg', 'text_content': None}
    await status_msg.edit_text(UI[lang]["got_file"], reply_markup=get_options_keyboard(lang))

@dp.message(F.text)
async def handle_text(message: Message) -> None:
    if message.text.startswith('/'): return 
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user: return await message.answer("Please type /start first!")
    lang = user[0]
    
    # Check if they are setting a new Target Language
    if awaiting_target.get(user_id):
        save_user(user_id, lang, message.text)
        awaiting_target.pop(user_id)
        await message.answer(f"✅ Target language saved as: **{message.text}**\n\n" + UI[lang]["tutorial"], reply_markup=get_main_keyboard(lang), disable_web_page_preview=True)
        return
        
    # Check if they are setting a Master Theme for merge
    if awaiting_theme.get(user_id):
        master_theme = message.text
        p_msg = await message.answer("⚙️ Merging...")
        q_files = merge_queues.get(user_id, [])
        merged_path, err = merge_excel_files(q_files, master_theme, f"merged_{user_id}.xlsx")
        
        if err: await p_msg.edit_text(err)
        else:
            await message.answer_document(FSInputFile(merged_path))
            if os.path.exists(merged_path): os.remove(merged_path)
            
        for path in q_files:
            if os.path.exists(path): os.remove(path)
        merge_queues.pop(user_id, None)
        awaiting_theme.pop(user_id, None)
        await p_msg.delete()
        return
    
    pending_tasks[user_id] = {'file_path': None, 'mime_type': None, 'text_content': message.text}
    await message.answer(UI[lang]["got_file"], reply_markup=get_options_keyboard(lang))

# --- DUMMY WEB SERVER ---
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
