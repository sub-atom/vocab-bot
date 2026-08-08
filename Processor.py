import os
import json
import pandas as pd
from google import genai
from dotenv import load_dotenv
import PIL.Image
import time  # <-- NEW: We need this to make the bot pause before retrying

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, '.env')
load_dotenv(env_path)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

def extract_vocabulary(file_path=None, text_content=None, mime_type=None):
    """Acts as the 'Brain' of our bot. Now with Auto-Retry for 503 Server Errors!"""
    
    prompt = """
    Analyze the provided textbook page, document, or text. Extract all the useful vocabulary words.
    Return the data STRICTLY as a valid JSON array of objects.
    Each object MUST have exactly these 7 keys:
    1. "word": The vocabulary word itself.
    2. "translation": The translation into Uzbek (or empty string if unknown).
    3. "part_of_speech": The part of speech in lowercase (e.g., noun, verb, adjective, adverb, preposition).
    4. "definition": A clear, short English definition.
    5. "conjugation": If the word is a verb, provide its past simple and past participle. If not, leave empty.
    6. "example": An example sentence using the word.
    7. "pronunciation": Phonetic spelling with slashes (e.g., "/ˈtɜː.ki/").
    
    Output ONLY the raw JSON array. Do not include markdown blocks like ```json or any conversational text.
    """
    
    contents = [prompt]
    uploaded_pdf = None
    
    # 1. Handle Plain Text
    if text_content:
        contents.append(f"Text to analyze:\n{text_content}")
        
    # 2. Handle Files (PDFs or Images)
    elif file_path:
        if mime_type == 'application/pdf':
            uploaded_pdf = client.files.upload(file=file_path)
            contents.append(uploaded_pdf)
        else:
            img = PIL.Image.open(file_path)
            contents.append(img)
    else:
        return None, "🚨 Error: No text or file provided!"

    # 3. THE RETRY LOOP (Protects against 503 errors)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=contents
            )
            
            # Clean up the PDF from Google's cloud
            if uploaded_pdf:
                client.files.delete(name=uploaded_pdf.name)
            
            raw_text = response.text.strip()
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
                
            return raw_text.strip(), None
            
        except Exception as e:
            error_message = str(e)
            # If it is a 503 error, wait and try again
            if "503" in error_message and attempt < (max_retries - 1):
                wait_time = (attempt + 1) * 2  # Waits 2s, then 4s
                print(f"⚠️ Google API busy. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                continue
            
            # If we run out of retries or it's a different error, return a friendly message
            if uploaded_pdf:
                client.files.delete(name=uploaded_pdf.name)
                
            if "503" in error_message:
                return None, "Google's AI is currently overloaded with global traffic. Please wait 1 minute and send your file again!"
            else:
                return None, f"🚨 API Error: {error_message}"

# ... (Keep the format_pos_tag and convert_to_excel functions exactly the same below this)

def format_pos_tag(pos):
    pos = str(pos).lower().strip()
    mapping = {
        'verb': 'verb::1',
        'noun': 'noun::2',
        'adjective': 'adjective::3',
        'adverb': 'adverb::4',
        'preposition': 'preposition::5'
    }
    return mapping.get(pos, f"{pos}::0")

def convert_to_excel(json_data, output_filename="vocab_list.xlsx"):
    print("📊 Converter engaged: Transforming data with Pandas...")
    try:
        data = json.loads(json_data)
        formatted_rows = []
        for item in data:
            row = {
                "Theme": "Introduction Unit",
                "Is Under The Theme": "",
                "Word": item.get("word", ""),
                "Translation": item.get("translation", ""),
                "Tags": format_pos_tag(item.get("part_of_speech", "")),
                "Image": "",
                "Audio": "",
                "Definition": item.get("definition", ""),
                "Conjugation": item.get("conjugation", ""),
                "Declensions": "",
                "Examples": item.get("example", ""),
                "Pronunciation": item.get("pronunciation", ""),
                "Transcription": ""
            }
            formatted_rows.append(row)
            
        df = pd.DataFrame(formatted_rows)
        output_path = os.path.join(BASE_DIR, output_filename)
        df.to_excel(output_path, index=False)
        return output_path, None
    except Exception as e:
        return None, f"🚨 Pandas Error: {e}"
