import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart
from dotenv import load_dotenv
from aiohttp import web  # <-- Our new dummy server library!

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
        "Send me a photo of an English textbook page, and I will instantly extract the "
        "vocabulary into a perfectly formatted Excel file for your flashcards!"
    )
    await message.answer(welcome_text)

@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    processing_msg = await message.answer("📸 Got the photo! My AI Brain is analyzing it... This might take a few seconds.")
    
    try:
        photo_file = await bot.get_file(message.photo[-1].file_id)
        temp_image_path = os.path.join(BASE_DIR, "temp_telegram_image.jpg")
        await bot.download_file(photo_file.file_path, temp_image_path)
        
        await processing_msg.edit_text("🧠 Brain engaged: Extracting vocabulary...")
        json_data, brain_error = extract_vocabulary(temp_image_path)
        
        if brain_error:
            await processing_msg.edit_text(f"🚨 Brain Error: {brain_error}")
            os.remove(temp_image_path)
            return
            
        await processing_msg.edit_text("📊 Converter engaged: Formatting into Excel...")
        excel_filename = "vocab_export.xlsx"
        excel_path, conv_error = convert_to_excel(json_data, excel_filename)
        
        if conv_error:
            await processing_msg.edit_text(f"🚨 Converter Error: {conv_error}")
            os.remove(temp_image_path)
            return
            
        # Step D: Send the Excel file back to the Telegram chat
        document = FSInputFile(excel_path)
        caption_text = (
            "🎉 Here is your formatted vocabulary list!\n\n"
            "🍏 **iOS Users:** Telegram opens this in a 'preview' mode. "
            "To import it, tap the **Share icon** (top right corner) and select your flashcard app or 'Save to Files'."
        )
        await message.answer_document(document, caption=caption_text)
        
        await processing_msg.delete()
        os.remove(temp_image_path)
        os.remove(excel_path)
        
    except Exception as e:
        await message.answer(f"🚨 An unexpected error occurred: {e}")

# --- THE DUMMY WEB SERVER ---
async def handle_web(request):
    return web.Response(text="Bot is running smoothly on Render!")

async def main() -> None:
    print("🚀 Bot is officially online and listening for messages...")
    
    # 1. Start the dummy web server on the port Render assigns
    app = web.Application()
    app.router.add_get('/', handle_web)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    # 2. Start the Telegram bot polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
