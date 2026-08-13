import os
import json
import pandas as pd
from google import genai
from google.genai import types 
from dotenv import load_dotenv
import PIL.Image
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, '.env')
load_dotenv(env_path)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

def extract_vocabulary(file_path=None, text_content=None, mime_type=None, mode="both", target_language="Uzbek"):
    
    mode_instructions = ""
    if mode == "translations":
        # AI now translates to whatever language the user chose in settings!
        mode_instructions = f"CRITICAL: Leave the 'definition' key as an empty string (\"\"). Only provide {target_language} translations in the 'translation' key."
    elif mode == "descriptions":
        mode_instructions = "CRITICAL: You MUST place the English definition inside the 'translation' key. Leave the 'definition' key as an empty string (\"\")."
    else:
        mode_instructions = f"CRITICAL: Provide the English definition in 'definition' AND the {target_language} translation in 'translation'."
    
    prompt = f"""
    CRITICAL INSTRUCTION: You are a strict, exhaustive data extraction algorithm. 
    Analyze the provided document, image, or text. 
    
    You MUST extract EVERY SINGLE vocabulary word present in the text. 
    DO NOT summarize. DO NOT skip words. DO NOT randomly sample. 
    
    {mode_instructions}

    Return the data STRICTLY as a valid JSON array of objects.
    Each object MUST have exactly these 8 keys:
    1. "word": The vocabulary word itself.
    2. "translation": The translation (or empty string if skipped).
    3. "part_of_speech": The part of speech in lowercase (e.g., noun, verb, adjective).
    4. "definition": A clear, short English definition (or empty string if skipped).
    5. "conjugation": If the word is a verb, provide its past simple and past participle. If not, leave empty.
    6. "example": An example sentence using the word.
    7. "pronunciation": Phonetic spelling with slashes.
    8. "theme": The unit name or topic. Keep it CONCISE. (e.g., 'Unit 5' OR 'Food'). Invent one if missing.
    
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

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=contents,
                config=types.GenerateContentConfig(max_output_tokens=8192, temperature=0.1)
            )
            if uploaded_pdf: client.files.delete(name=uploaded_pdf.name)
            
            raw_text = response.text.strip()
            if raw_text.startswith("```json"): raw_text = raw_text[7:]
            if raw_text.endswith("```"): raw_text = raw_text[:-3]
            return raw_text.strip(), None
            
        except Exception as e:
            error_message = str(e)
            if "503" in error_message and attempt < (max_retries - 1):
                wait_time = (attempt + 1) * 2
                print(f"⚠️ API busy. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            if uploaded_pdf:
                try: client.files.delete(name=uploaded_pdf.name)
                except: pass
            if "503" in error_message:
                return None, "Google's AI is currently overloaded with global traffic. Please wait 1 minute and try again!"
            return None, f"🚨 API Error: {error_message}"

def format_pos_tag(pos):
    mapping = {'verb': 'verb::1', 'noun': 'noun::2', 'adjective': 'adjective::3', 'adverb': 'adverb::4', 'preposition': 'preposition::5'}
    return mapping.get(str(pos).lower().strip(), f"{pos}::0")

def convert_to_excel(json_data, output_filename="vocab_list.xlsx"):
    try:
        data = json.loads(json_data)
        formatted_rows = [{
            "Theme": item.get("theme", "Vocabulary"),
            "Is Under The Theme": "", "Word": item.get("word", ""), "Translation": item.get("translation", ""),
            "Tags": format_pos_tag(item.get("part_of_speech", "")), "Image": "", "Audio": "",
            "Definition": item.get("definition", ""), "Conjugation": item.get("conjugation", ""),
            "Declensions": "", "Examples": item.get("example", ""), "Pronunciation": item.get("pronunciation", ""),
            "Transcription": ""
        } for item in data]
        df = pd.DataFrame(formatted_rows)
        out_path = os.path.join(BASE_DIR, output_filename)
        df.to_excel(out_path, index=False)
        return out_path, None
    except Exception as e: return None, f"🚨 Pandas Error: {e}"

def merge_excel_files(file_paths, master_theme, output_filename):
    try:
        dataframes = [pd.read_excel(path) for path in file_paths]
        combined_df = pd.concat(dataframes, ignore_index=True)
        combined_df['Theme'] = master_theme
        out_path = os.path.join(BASE_DIR, output_filename)
        combined_df.to_excel(out_path, index=False)
        return out_path, None
    except Exception as e: return None, f"🚨 Merge Error: {e}"
