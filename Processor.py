import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart
from dotenv import load_dotenv
from aiohttp import web
from pypdf import PdfReader, PdfWriter  # <-- NEW: Our PDF Safety Slicer library!

from Processor import extract_vocabulary, convert_to_excel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, '.env')
load_dotenv(env_path)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    welcome_text = (
        f"What's up, {message.from_user.full_name}! 🤖\n\n"
        "Send me a **photo**, a **PDF document**, an **uncompressed PNG**, or just **type some text**, "
        "and I will extract the vocabulary into a beautifully formatted Excel file!"
    )
    await message.answer(welcome_text)

# --- CENTRAL PROCESSING ENGINE ---
async def process_and_send(message: Message, processing_msg: Message, file_path=None, text_content=None, mime_type=None):
    try:
        await processing_msg.edit_text("🧠 Brain engaged: Extracting vocabulary...")
        json_data, brain_error = extract_vocabulary(file_path=file_path, text_content=text_content, mime_type=mime_type)
        
        if brain_error:
            await processing_msg.edit_text(f"🚨 Brain Error: {brain_error}")
            if file_path and os.path.exists(file_path): os.remove(file_path)
            return
            
        await processing_msg.edit_text("📊 Converter engaged: Formatting into Excel...")
        excel_filename = "vocab_export.xlsx"
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

# --- THE TELEGRAM HANDLERS ---

# 1. Handle Standard Photos (JPGs)
@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    processing_msg = await message.answer("📸 Got the photo! Analyzing...")
    photo_file = await bot.get_file(message.photo[-1].file_id)
    temp_path = os.path.join(BASE_DIR, "temp_image.jpg")
    await bot.download_file(photo_file.file_path, temp_path)
    await process_and_send(message, processing_msg, file_path=temp_path, mime_type="image/jpeg")

# 2. Handle Documents (PDFs, PNGs, etc.)
@dp.message(F.document)
async def handle_document(message: Message) -> None:
    mime = message.document.mime_type
    
    if mime in ['application/pdf', 'image/png', 'image/jpeg']:
        ext = mime.split('/')[-1]
        processing_msg = await message.answer(f"📄 Got the {ext.upper()} file! Checking safety limits...")
        doc_file = await bot.get_file(message.document.file_id)
        temp_path = os.path.join(BASE_DIR, f"temp_doc.{ext}")
        await bot.download_file(doc_file.file_path, temp_path)
        
        # --- NEW: PDF SAFETY SLICER ---
        if mime == 'application/pdf':
            try:
                reader = PdfReader(temp_path)
                total_pages = len(reader.pages)
                
                max_safe_pages = 5  # The AI token safety limit!
                
                if total_pages > max_safe_pages:
                    await processing_msg.edit_text(
                        f"⚠️ **Safety System Activated!**\n"
                        f"This PDF is {total_pages} pages long. To prevent the AI from crashing, "
                        f"I have sliced off the first {max_safe_pages} pages and will process those now.\n\n"
                        f"Please split the rest of your PDF into smaller chunks and send them separately!"
                    )
                    
                    # Create a new mini-PDF with just the first 5 pages
                    writer = PdfWriter()
                    for i in range(max_safe_pages):
                        writer.add_page(reader.pages[i])
                        
                    # Overwrite the original downloaded PDF with the safe, sliced version
                    with open(temp_path, "wb") as f_out:
                        writer.write(f_out)
                        
            except Exception as e:
                await message.answer(f"🚨 PDF Slicer Error: Could not read PDF safely. {e}")
                if os.path.exists(temp_path): os.remove(temp_path)
                return
        
        # Send it to the brain!
        await process_and_send(message, processing_msg, file_path=temp_path, mime_type=mime)
    else:
        await message.answer("⚠️ I can only process PDFs or Images (PNG/JPG). Please send a supported file!")

# 3. Handle Plain Text
@dp.message(F.text)
async def handle_text(message: Message) -> None:
    if message.text.startswith('/'): return 
    processing_msg = await message.answer("📝 Got the text! Analyzing...")
    await process_and_send(message, processing_msg, text_content=message.text)

# --- THE DUMMY WEB SERVER ---
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
