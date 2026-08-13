import os
import json
import uuid
import zipfile
import shutil
import asyncio
import time
from datetime import datetime
import edge_tts
from google import genai
from google.genai import types
from dotenv import load_dotenv
import PIL.Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

def get_time():
    return datetime.utcnow().isoformat()[:-3] + 'Z'

async def extract_and_compile_wt(file_path=None, text_content=None, mime_type=None, target_language="Uzbek", progress_callback=None, user_id=1):
    # 1. Ask the AI Brain for the data
    prompt = f"""
    CRITICAL INSTRUCTION: You are a strict data extraction algorithm. 
    Extract EVERY vocabulary word from the document. DO NOT summarize or skip words.
    Translate the word into {target_language}.
    
    Return STRICTLY a JSON array of objects with exactly these 10 keys:
    1. "word": The English word.
    2. "translation": The {target_language} translation.
    3. "part_of_speech": The part of speech in lowercase (noun, verb, etc. - or empty string).
    4. "definition": A clear English definition (or empty string).
    5. "conjugation": If verb, past simple and past participle (or empty string).
    6. "declension": Plurals or variations (or empty string).
    7. "example": Example sentence (or empty string).
    8. "transcription": Phonetic spelling WITHOUT slashes.
    9. "pronunciation": Phonetic spelling WITH slashes.
    10. "theme": Short unit name or topic. Invent one if missing.
    
    Output ONLY the raw JSON array. Do not include markdown blocks like ```json or any conversational text.
    """
    
    contents = [prompt]
    uploaded_pdf = None
    
    if text_content:
        contents.append(f"Text to analyze:\n{text_content}")
    elif file_path:
        if mime_type == 'application/pdf':
            uploaded_pdf = client.files.upload(file=file_path)
            contents.append(uploaded_pdf)
        else:
            img = PIL.Image.open(file_path)
            contents.append(img)
    else:
        return None, "🚨 Error: No text or file provided!"

    try:
        # We run Gemini in a separate thread so it doesn't freeze the bot
        response = await asyncio.to_thread(
            client.models.generate_content,
            model='gemini-3.6-flash',
            contents=contents,
            config=types.GenerateContentConfig(max_output_tokens=8192, temperature=0.1)
        )
    except Exception as e:
        if uploaded_pdf:
            try: client.files.delete(name=uploaded_pdf.name)
            except: pass
        return None, f"🚨 AI Engine Error: {e}"

    if uploaded_pdf:
        try: client.files.delete(name=uploaded_pdf.name)
        except: pass

    raw_text = response.text.strip()
    if raw_text.startswith("```json"): raw_text = raw_text[7:]
    if raw_text.endswith("```"): raw_text = raw_text[:-3]

    try:
        vocab_data = json.loads(raw_text.strip())
    except Exception as e:
        return None, f"🚨 JSON Parse Error: AI output was corrupted. {e}"

    if not vocab_data:
        return None, "🚨 No vocabulary found in the document."

    # 2. Build the WordTheme Architecture
    build_dir = os.path.join(BASE_DIR, f"wt_build_{user_id}_{int(time.time())}")
    os.makedirs(os.path.join(build_dir, "audio"), exist_ok=True)
    os.makedirs(os.path.join(build_dir, "images"), exist_ok=True)

    wt_database = {
        "libelle": f"Result Vocab ({target_language})",
        "identifier": str(uuid.uuid4()),
        "version": "3",
        "dm": get_time(),
        "listAssoWT": [],
        "ltheme": [],
        "lword": [],
        "ltag": [],
        "atw": [],
        "listWordThemeAssociation": [{"idTheme": -1, "idWord": -1}]
    }

    theme_map = {} 
    tag_map = {} 
    next_theme_id = 1
    next_tag_id = 1
    next_word_id = 1
    total_words = len(vocab_data)
    
    for i, item in enumerate(vocab_data):
        word = item.get("word", "").strip()
        if not word: continue

        # --- Generate Neural Audio ---
        audio_filename = f"{uuid.uuid4()}.mp3"
        try:
            communicate = edge_tts.Communicate(word, "en-US-AriaNeural")
            await communicate.save(os.path.join(build_dir, "audio", audio_filename))
        except Exception as e:
            audio_filename = "" 
            print(f"Audio failed for {word}: {e}")

        # Update the live progress bar in Telegram
        if progress_callback:
            await progress_callback(i + 1, total_words)

        # --- Map the Theme ---
        theme_name = item.get("theme", "General").strip()
        if theme_name not in theme_map:
            theme_map[theme_name] = next_theme_id
            wt_database["ltheme"].append({"id": next_theme_id, "uid": str(uuid.uuid4()), "l": theme_name, "dm": get_time()})
            next_theme_id += 1
        t_id = theme_map[theme_name]

        # --- Map the Part of Speech Tag ---
        pos = item.get("part_of_speech", "").lower().strip()
        if pos:
            if pos not in tag_map:
                tag_map[pos] = next_tag_id
                wt_database["ltag"].append({"id": next_tag_id, "l": pos + "\n", "c": 1})
                next_tag_id += 1
            wt_database["atw"].append({"t": tag_map[pos], "w": next_word_id})

        # --- Build the Rich Text Fields (GCL) ---
        gcl = []
        def add_gcl(t_val, text):
            if text and str(text).strip():
                gcl.append({
                    "uid": str(uuid.uuid4()), "t": t_val, "i": len(gcl)+1, "dm": get_time(),
                    "lcw": [{"uid": str(uuid.uuid4()), "l": str(text).strip(), "i": 1, "dm": get_time()}]
                })
        
        add_gcl(1, item.get("definition"))
        add_gcl(2, item.get("conjugation"))
        add_gcl(3, item.get("declension"))
        add_gcl(4, item.get("example"))
        add_gcl(9, item.get("transcription"))
        add_gcl(10, item.get("pronunciation"))

        # --- Construct the Word ---
        word_obj = {
            "id": next_word_id,
            "uid": str(uuid.uuid4()),
            "m": word,
            "t": item.get("translation", ""),
            "dc": get_time(),
            "dm": get_time(),
            "tm": 4,
            "gcl": gcl
        }
        if audio_filename:
            word_obj["s"] = audio_filename

        wt_database["lword"].append(word_obj)
        wt_database["listAssoWT"].append({"t": t_id, "w": next_word_id})
        next_word_id += 1

    # 3. Zip into .wt format
    with open(os.path.join(build_dir, "dictionary.txt"), "w", encoding="utf-8") as f:
        json.dump(wt_database, f, separators=(',', ':'))

    output_wt = os.path.join(BASE_DIR, f"Result_Vocab_{user_id}_{int(time.time())}.wt")
    
    with zipfile.ZipFile(output_wt, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(os.path.join(build_dir, "dictionary.txt"), "dictionary.txt")
        for root, _, files in os.walk(os.path.join(build_dir, "audio")):
            for file in files:
                zf.write(os.path.join(root, file), f"audio/{file}")

    shutil.rmtree(build_dir, ignore_errors=True)
    return output_wt, None
