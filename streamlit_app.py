import streamlit as st
import genanki
import json
import random
import tempfile
import time
from google import genai
from google.genai import types
from google.genai.errors import APIError

st.set_page_config(page_title="Snap to Anki", page_icon="✦", layout="centered")

# Minimalist Ambient Styling
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* Ambient background */
    .stApp {
        background: linear-gradient(135deg, #f5f6f8 0%, #e9ecef 100%);
        color: #2b2d42;
    }

    /* Clean typography */
    .clean-header {
        font-size: 2.2rem;
        font-weight: 500;
        text-align: center;
        color: #1a1a2e;
        letter-spacing: -0.5px;
        margin-bottom: 0.2rem;
    }

    .clean-sub {
        font-size: 0.95rem;
        text-align: center;
        color: #6c757d;
        font-weight: 400;
        margin-bottom: 2rem;
    }

    /* Card/Tab containers */
    div[data-testid="stVerticalBlock"] > div, .stTabs [data-baseweb="tab-list"] {
        border-radius: 12px;
    }

    /* Sleek buttons */
    .stButton>button {
        background: #2b2d42 !important;
        color: #ffffff !important;
        font-weight: 500 !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 0.6rem 2rem !important;
        transition: all 0.2s ease !important;
        width: 100%;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04) !important;
    }

    .stButton>button:hover {
        background: #4a4e69 !important;
        transform: translateY(-1px);
        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.08) !important;
    }

    /* Form Inputs */
    input, textarea, [data-baseweb="select"] {
        background-color: #ffffff !important;
        border: 1px solid #dcdfe6 !important;
        border-radius: 10px !important;
        color: #2b2d42 !important;
    }

    /* Download button */
    div[data-testid="stDownloadButton"] > button {
        background-color: #4a4e69 !important;
        color: #ffffff !important;
        border-radius: 10px !important;
        border: none !important;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 class="clean-header">✦ Snap Notes to Anki</h1>', unsafe_allow_html=True)
st.markdown('<p class="clean-sub">Transform notes into structured flashcard decks seamlessly.</p>', unsafe_allow_html=True)

api_key = st.secrets.get("GEMINI_API_KEY", None)
if not api_key:
    api_key = st.sidebar.text_input("Enter Gemini API Key", type="password")

deck_name = st.text_input("Deck Name", value="My Study Deck")

# Add this slider:
target_cards = st.slider("Target Number of Cards", min_value=5, max_value=50, value=25, step=5)

input_tab1, input_tab2 = st.tabs(["📁 Upload File/PDF", "📷 Snap Photo"])
uploaded_file = None

with input_tab1:
    file_upload = st.file_uploader("Upload Notes (PDF, JPG, PNG)", type=["pdf", "png", "jpg", "jpeg"])
    if file_upload:
        uploaded_file = file_upload

with input_tab2:
    camera_photo = st.camera_input("Take a photo of your notes")
    if camera_photo:
        uploaded_file = camera_photo

# Candidate models ordered by preference
CANDIDATE_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite"
]

def generate_with_fallback_and_retry(client, file_bytes, mime_type, prompt):
    """Attempts generation across candidate models with automatic retries on 503/429."""
    for model_name in CANDIDATE_MODELS:
        for attempt in range(3):  # Retry up to 3 times per model
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[
                        types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                        prompt
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )
                return response.text, model_name
            except APIError as e:
                # If overloaded (503) or rate-limited (429), back off and retry
                if e.code in (503, 429) and attempt < 2:
                    wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                    time.sleep(wait_time)
                    continue
                # If retries for this model are exhausted, move to the next model in the list
                break
            except Exception:
                break
    raise RuntimeError("All available Gemini models are currently overloaded. Please wait 1-2 minutes and try again.")

if st.button("Generate Flashcard Deck", type="primary"):
    if not api_key:
        st.error("Please provide a Gemini API Key.")
    elif not uploaded_file:
        st.warning("Please upload a file or take a photo first.")
    else:
        with st.spinner("Analyzing notes and compiling Anki deck..."):
            try:
                client = genai.Client(api_key=api_key)
                file_bytes = uploaded_file.getvalue()
                mime_type = getattr(uploaded_file, "type", None) or "image/jpeg"

                prompt = f"""
You are an exhaustive Anki flashcard creator following the Minimum Information Principle.
Analyze the provided notes thoroughly and create at least {target_cards} distinct flashcards.

CRITICAL EXTRACTION RULES:
1. EXHAUSTIVE COVERAGE: Do not summarize. Extract every formula, definition, rule, date, step, and nuance.
2. ATOMIC FACT PRINCIPLE: One single question and one specific answer per card. 
   - Never list multiple items on the back.
   - If a concept has 3 parts or steps, make 3 separate cards (e.g., Step 1 card, Step 2 card, Step 3 card).
3. QUESTION TYPES TO GENERATE:
   - "What is..." / "Define..." (Key terminology)
   - "Why..." / "How does X cause Y?" (Mechanisms & relationships)
   - "What is the formula for...?" (Math / Science)
   - "What is the difference between X and Y?" (Contrast cards)
4. OUTPUT FORMAT:
   Return strictly a valid JSON array of objects with 'front' and 'back' fields.
   Example:
   [
     {{"front": "[Topic] What is X?", "back": "Definition of X."}},
     {{"front": "[Topic] Why does Y occur?", "back": "Direct cause of Y."}}
   ]
"""

                raw_json, used_model = generate_with_fallback_and_retry(
                    client, file_bytes, mime_type, prompt
                )

                cards = json.loads(raw_json)

                if not cards:
                    st.warning("No flashcards could be extracted. Please check the document clarity.")
                else:
                    model_id = random.randrange(1 << 30, 1 << 31)
                    deck_id = random.randrange(1 << 30, 1 << 31)

                    anki_model = genanki.Model(
                        model_id,
                        'Mobile QA Model',
                        fields=[{'name': 'Question'}, {'name': 'Answer'}],
                        templates=[{
                            'name': 'Card 1',
                            'qfmt': '<div style="font-family: system-ui, sans-serif; font-size: 1.2rem; text-align: center; padding: 20px;">{{Question}}</div>',
                            'afmt': '{{FrontSide}}<hr id="answer"><div style="font-family: system-ui, sans-serif; font-size: 1.1rem; color: #166534; text-align: center; padding: 20px;">{{Answer}}</div>',
                        }]
                    )

                    deck = genanki.Deck(deck_id, deck_name)
                    for card in cards:
                        deck.add_note(genanki.Note(model=anki_model, fields=[card.get('front', ''), card.get('back', '')]))

                    with tempfile.NamedTemporaryFile(delete=False, suffix=".apkg") as tmp_file:
                        genanki.Package(deck).write_to_file(tmp_file.name)
                        with open(tmp_file.name, "rb") as f:
                            apkg_data = f.read()

                    st.success(f"Generated {len(cards)} flashcards using {used_model}!")
                    st.download_button(
                        label="📥 Download .apkg Deck",
                        data=apkg_data,
                        file_name=f"{deck_name.replace(' ', '_')}.apkg",
                        mime="application/octet-stream"
                    )

            except Exception as e:
                st.error(f"Error: {e}")
