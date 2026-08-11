import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart
from dotenv import load_dotenv
from aiohttp import web
from pypdf import PdfReader, PdfWriter

# Import our new merge tool!
from Processor import extract_vocabulary, convert_to_excel, merge_excel_files

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, '.env')
load_dotenv(env_path)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

pending_tasks = {}

# --- NEW: State Memory for the Merge feature ---
merge_queues = {}
awaiting_theme = {}

@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    welcome_text = (
        f"What's up, {message.from_user.full_name}! 🤖\n\n"
        "Send me a **photo**, a **PDF document**, an **uncompressed PNG**, or **type text** to extract vocabulary.\n\n"
        "**Bonus:** You can also drop multiple `.xlsx` dictionary files here to merge them into one master list!"
    )
    await message.answer(welcome_text)

def get_options_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇿 Translations Only", callback_data="mode_translations")],
        [InlineKeyboardButton(text="📖 Descriptions Only", callback_data="mode_descriptions")],
        [InlineKeyboardButton(text="⭐ Both", callback_data="mode_both")]
    ])

# Keyboard for the Merge Queue
def get_merge_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Merge Files Now", callback_data="merge_now")],
        [InlineKeyboardButton(text="❌ Clear Queue", callback_data="merge_clear")]
    ])

async def process_and_send(message: Message, processing_msg: Message, file_path=None, text_content=None, mime_type=None, mode="both"):
    try:
        await processing_msg.edit_text("🧠 Brain engaged: Extracting vocabulary...")
        
        json_data, brain_error = extract_vocabulary(file_path=file_path, text_content=text_content, mime_type=mime_type, mode=mode)
        
        if brain_error:
            await processing_msg.edit_text(f"🚨 Brain Error: {brain_error}")
            if file_path and os.path.exists(file_path): os.remove(file_path)
            return
            
        await processing_msg.edit_text("📊 Converter engaged: Formatting into Excel...")
        excel_filename = f"vocab_export_{message.from_user.id}.xlsx"
        excel_path, conv_error = convert_to_excel(json_data, excel_filename)
        
        if conv_error:
            await processing_msg.edit_text(f"🚨 Converter Error: {conv_error}")
            if file_path and os.path.exists(file_path): os.remove(file_path)
            return
            
        document = FSInputFile(excel_path)
        caption_text = (
            "🎉 Here is your formatted vocabulary list!\n\n"
            "🍏 **iOS Users:** Tap the **Share icon** (top right) and select your flashcard app to import."
        )
        await message.answer_document(document, caption=caption_text)
        
        await processing_msg.delete()
        if file_path and os.path.exists(file_path): os.remove(file_path)
        if os.path.exists(excel_path): os.remove(excel_path)
        
    except Exception as e:
        await message.answer(f"🚨 An unexpected error occurred: {e}")
        if file_path and os.path.exists(file_path): os.remove(file_path)

# --- BUTTON CLICK HANDLERS ---
@dp.callback_query(F.data.startswith("mode_"))
async def process_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id not in pending_tasks:
        await callback_query.message.edit_text("⚠️ No pending file found. Please send your document again.")
        return

    mode = callback_query.data.split("_")[1] 
    task = pending_tasks.pop(user_id)
    processing_msg = await callback_query.message.edit_text("⚙️ Choice confirmed! Starting process...")

    await process_and_send(
        message=callback_query.message,
        processing_msg=processing_msg,
        file_path=task.get('file_path'),
        text_content=task.get('text_content'),
        mime_type=task.get('mime_type'),
        mode=mode
    )

@dp.callback_query(F.data == "merge_now")
async def merge_now_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id not in merge_queues or not merge_queues[user_id]:
        await callback_query.message.edit_text("⚠️ Your queue is empty!")
        return
        
    # Tell the bot we are waiting for a Master Theme name!
    awaiting_theme[user_id] = True
    await callback_query.message.edit_text(
        f"🔗 You have {len(merge_queues[user_id])} files ready to merge!\n\n"
        "**Please type a name for the new Master Theme** (e.g., 'Unit 1-3 Review' or 'Final Exam Vocab').\n"
        "I will apply this theme to every word in the merged file."
    )

@dp.callback_query(F.data == "merge_clear")
async def merge_clear_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id in merge_queues:
        for path in merge_queues[user_id]:
            if os.path.exists(path): os.remove(path)
        merge_queues.pop(user_id)
        
    if user_id in awaiting_theme:
        awaiting_theme.pop(user_id)
        
    await callback_query.message.edit_text("🗑️ Queue cleared!")

# --- TELEGRAM HANDLERS ---
@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    status_msg = await message.answer("📸 Downloading photo...")
    photo_file = await bot.get_file(message.photo[-1].file_id)
    temp_path = os.path.join(BASE_DIR, f"temp_image_{message.from_user.id}_{message.message_id}.jpg")
    await bot.download_file(photo_file.file_path, temp_path)
    
    pending_tasks[message.from_user.id] = {'file_path': temp_path, 'mime_type': 'image/jpeg', 'text_content': None}
    await status_msg.edit_text("📸 Photo secured! What do you want to extract?", reply_markup=get_options_keyboard())

@dp.message(F.document)
async def handle_document(message: Message) -> None:
    filename = message.document.file_name or ""
    ext = filename.split('.')[-1].lower()
    
    # --- NEW: Hitting an Excel File adds it to the Shopping Cart! ---
    if ext == 'xlsx':
        user_id = message.from_user.id
        doc_file = await bot.get_file(message.document.file_id)
        temp_path = os.path.join(BASE_DIR, f"queue_{user_id}_{message.message_id}.xlsx")
        await bot.download_file(doc_file.file_path, temp_path)
        
        if user_id not in merge_queues:
            merge_queues[user_id] = []
        merge_queues[user_id].append(temp_path)
        
        count = len(merge_queues[user_id])
        await message.answer(
            f"🛒 **Excel File Added!**\n"
            f"You have {count} file(s) in your Merge Queue. Send more files to add to the queue, or click below to merge them!",
            reply_markup=get_merge_keyboard()
        )
        return

    # Standard AI extraction for PDFs/PNGs
    mime = message.document.mime_type
    if mime in ['application/pdf', 'image/png', 'image/jpeg']:
        status_msg = await message.answer(f"📄 Downloading {ext.upper()} file...")
        doc_file = await bot.get_file(message.document.file_id)
        temp_path = os.path.join(BASE_DIR, f"temp_doc_{message.from_user.id}_{message.message_id}.{ext}")
        await bot.download_file(doc_file.file_path, temp_path)
        
        if mime == 'application/pdf':
            try:
                reader = PdfReader(temp_path)
                total_pages = len(reader.pages)
                max_safe_pages = 5
                
                if total_pages > max_safe_pages:
                    await message.answer(f"⚠️ **Safety System Activated!**\nSlicing off the first {max_safe_pages} pages to prevent crashing.")
                    writer = PdfWriter()
                    for i in range(max_safe_pages):
                        writer.add_page(reader.pages[i])
                    with open(temp_path, "wb") as f_out:
                        writer.write(f_out)
            except Exception as e:
                await status_msg.edit_text(f"🚨 PDF Slicer Error: {e}")
                if os.path.exists(temp_path): os.remove(temp_path)
                return
        
        pending_tasks[message.from_user.id] = {'file_path': temp_path, 'mime_type': mime, 'text_content': None}
        await status_msg.edit_text("📄 Document secured! What do you want to extract?", reply_markup=get_options_keyboard())
    else:
        await message.answer("⚠️ I can only process PDFs, PNGs, JPGs, or Excel files.")

@dp.message(F.text)
async def handle_text(message: Message) -> None:
    if message.text.startswith('/'): return 
    
    user_id = message.from_user.id
    
    # --- NEW: Check if the user is giving us a Master Theme ---
    if awaiting_theme.get(user_id):
        master_theme = message.text
        processing_msg = await message.answer(f"⚙️ Applying theme '{master_theme}' and merging files...")
        
        queue_files = merge_queues.get(user_id, [])
        output_name = f"master_merged_{user_id}.xlsx"
        
        merged_path, err = merge_excel_files(queue_files, master_theme, output_name)
        
        if err:
            await processing_msg.edit_text(err)
        else:
            doc = FSInputFile(merged_path)
            await message.answer_document(doc, caption=f"🎉 Merge Complete! Master Theme: {master_theme}")
            if os.path.exists(merged_path): os.remove(merged_path)
            
        # Cleanup
        for path in queue_files:
            if os.path.exists(path): os.remove(path)
        merge_queues.pop(user_id, None)
        awaiting_theme.pop(user_id, None)
        await processing_msg.delete()
        return
    
    # Standard text extraction logic
    pending_tasks[user_id] = {'file_path': None, 'mime_type': None, 'text_content': message.text}
    await message.answer("📝 Text secured! What do you want to extract?", reply_markup=get_options_keyboard())

# --- DUMMY WEB SERVER ---
async def handle_web(request):
    return web.Response(text="Bot is running smoothly on Render!")

async def main() -> None:
    print("🚀 Bot is officially online and listening for messages...")
    app = web.Application()
    app.router.add_get('/', handle_web)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
