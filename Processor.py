import os
import json
import pandas as pd
from google import genai
from dotenv import load_dotenv
import PIL.Image

# 1. Dynamically find the folder where this script lives
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, '.env')

# 2. Force load_dotenv to use that exact .env file
load_dotenv(env_path)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 3. Configure the Gemini Client
client = genai.Client(api_key=GEMINI_API_KEY)

def extract_vocabulary(image_path):
    """Acts as the 'Brain' of our bot."""
    print(f"🧠 Brain engaged: Analyzing {image_path}...")
    
    try:
        img = PIL.Image.open(image_path)
    except Exception as e:
        return None, f"🚨 Error opening image: {e}"

    # We adjusted the prompt to grab exactly what your new table format needs
    prompt = """
    Analyze this image of a textbook page. Extract all the useful vocabulary words.
    Return the data STRICTLY as a valid JSON array of objects.
    Each object MUST have exactly these 7 keys:
    1. "word": The vocabulary word itself.
    2. "translation": The translation into Uzbek (or empty string if unknown).
    3. "part_of_speech": The part of speech in lowercase (e.g., noun, verb, adjective, adverb, preposition).
    4. "definition": A clear, short English definition.
    5. "conjugation": If the word is a verb, provide its past simple and past participle (e.g., "cleaned, cleaned" or "abseiled, abseiled"). If not a verb, leave as an empty string.
    6. "example": An example sentence using the word.
    7. "pronunciation": Phonetic spelling with slashes (e.g., "/ˈtɜː.ki/").
    
    Output ONLY the raw JSON array. Do not include markdown blocks like ```json or any conversational text.
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=[prompt, img]
        )
        
        raw_text = response.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
            
        return raw_text.strip(), None
    except Exception as e:
        return None, f"🚨 API Error: {e}"

def format_pos_tag(pos):
    """Helper function to map the part of speech to the specific app tags"""
    pos = str(pos).lower().strip()
    # Mapping based on your screenshot
    mapping = {
        'verb': 'verb::1',
        'noun': 'noun::2',
        'adjective': 'adjective::3',
        'adverb': 'adverb::4',
        'preposition': 'preposition::5'
    }
    # Default to 0 if it's a weird part of speech we didn't account for
    return mapping.get(pos, f"{pos}::0")

def convert_to_excel(json_data, output_filename="vocab_list.xlsx"):
    """Acts as the 'Converter', mapping data to your exact 13-column template."""
    print("📊 Converter engaged: Transforming data with Pandas...")
    try:
        data = json.loads(json_data)
        
        # Build the exact rows needed for the DataFrame
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
            
        # Load our formatted rows into Pandas and export to Excel
        df = pd.DataFrame(formatted_rows)
        output_path = os.path.join(BASE_DIR, output_filename)
        df.to_excel(output_path, index=False)
        
        return output_path, None
    except Exception as e:
        return None, f"🚨 Pandas Error: {e}"

if __name__ == "__main__":
    test_image = os.path.join(BASE_DIR, "test_page.jpg") 
    
    if os.path.exists(test_image):
        json_result, error = extract_vocabulary(test_image)
        
        if error:
            print(error)
        else:
            print("✅ Brain successfully extracted data!")
            excel_file, convert_error = convert_to_excel(json_result)
            
            if convert_error:
                print(convert_error)
            else:
                print(f"🎉 Success! Beautifully formatted Excel file saved to: {excel_file}")
    else:
        print(f"⚠️ Hold up, PM! Could not find '{test_image}'.")