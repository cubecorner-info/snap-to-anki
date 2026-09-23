import io
import json
import os
import random
import re
import genanki
from PIL import Image
import streamlit as st
import google.generativeai as genai

# ------------------------------------------------------------------------------
# 1. Page Configuration & Setup
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="Snap to Anki",
    page_icon="✦",
    layout="centered"
)

# Soft, minimalist custom styling
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* Subtle ambient background */
    .stApp {
        background: linear-gradient(135deg, #f4f5f7 0%, #e9ecef 100%);
        color: #2b2d42;
    }

    /* Minimalist Typography */
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

    /* Clean Card Layout */
    div[data-testid="stVerticalBlock"] > div {
        border-radius: 14px;
    }

    /* Primary Action Button */
    .stButton>button {
        background: #2b2d42 !important;
        color: #ffffff !important;
        font-weight: 500 !important;
        border: none !important;
        border-radius: 12px !important;
        padding: 0.6rem 2rem !important;
        transition: all 0.2s ease !important;
        width: 100%;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05) !important;
    }

    .stButton>button:hover {
        background: #4a4e69 !important;
        transform: translateY(-1px);
        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.08) !important;
    }

    /* Form Fields & Containers */
    input, textarea, [data-baseweb="select"] {
        background-color: #ffffff !important;
        border: 1px solid #dcdfe6 !important;
        border-radius: 10px !important;
        color: #2b2d42 !important;
    }

    /* Download Button Specific Styling */
    div[data-testid="stDownloadButton"] > button {
        background-color: #4a4e69 !important;
        color: #ffffff !important;
        border-radius: 12px !important;
        border: none !important;
    }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------------------
# 2. Minimalist Header
# ------------------------------------------------------------------------------
st.markdown('<h1 class="clean-header">✦ Snap to Anki</h1>', unsafe_allow_html=True)
st.markdown('<p class="clean-sub">Transform notes into structured flashcards seamlessly.</p>', unsafe_allow_html=True)

# ------------------------------------------------------------------------------
# 3. API Key Management
# ------------------------------------------------------------------------------
api_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

if not api_key:
    st.info("Please set `GEMINI_API_KEY` in your environment or Streamlit secrets to proceed.")
    st.stop()

genai.configure(api_key=api_key)

# ------------------------------------------------------------------------------
# 4. Processing Functions
# ------------------------------------------------------------------------------
def generate_cards_from_gemini(image: Image.Image, num_cards: int) -> list[dict]:
    models_to_try = ["gemini-1.5-flash", "gemini-1.5-pro"]
    
    prompt = f"""
    Analyze the provided document/notes and create exactly {num_cards} clear, high-quality study cards.
    Keep both questions and answers concise, logical, and easy to memorize.
    
    Return strictly a JSON array containing objects with 'question' and 'answer' keys.
    [
      {{"question": "What is mitochondrial DNA?", "answer": "Maternal DNA found within the mitochondria of eukaryotic cells."}}
    ]
    """

    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(
                model_name=model_name,
                generation_config={"response_mime_type": "application/json"}
            )
            response = model.generate_content([prompt, image])
            clean_text = re.sub(r"```(?:json)?\n?|\n?```", "", response.text).strip()
            return json.loads(clean_text)
        except Exception:
            continue

    st.error("Unable to process the image. Please verify your connection or try another upload.")
    return []

def build_anki_package(cards: list[dict], deck_name: str) -> bytes:
    deck_id = random.randrange(1 << 30, 1 << 31)
    model_id = random.randrange(1 << 30, 1 << 31)

    anki_model = genanki.Model(
        model_id,
        'Minimalist Note Model',
        fields=[{'name': 'Question'}, {'name': 'Answer'}],
        templates=[{
            'name': 'Card 1',
            'qfmt': '{{Question}}',
            'afmt': '{{FrontSide}}<hr id="answer">{{Answer}}',
        }],
        css="""
        .card { font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 18px; text-align: center; color: #2b2d42; padding: 20px; }
        #answer { color: #4a4e69; margin-top: 15px; }
        """
    )

    anki_deck = genanki.Deck(deck_id, deck_name)

    for card in cards:
        q = card.get("question", "")
        a = card.get("answer", "")
        note = genanki.Note(model=anki_model, fields=[q, a])
        anki_deck.add_note(note)

    buffer = io.BytesIO()
    anki_deck.write_to_buffer(buffer)
    buffer.seek(0)
    return buffer.getvalue()

# ------------------------------------------------------------------------------
# 5. Interface
# ------------------------------------------------------------------------------
deck_title = st.text_input("Deck Title", value="Study Deck")
card_count = st.slider("Number of cards", min_value=3, max_value=25, value=10)

st.write("---")

input_method = st.radio("Input Method", ["Upload Image", "Camera Capture"], horizontal=True)

image_data = None
if input_method == "Camera Capture":
    image_data = st.camera_input("Take photo")
else:
    image_data = st.file_uploader("Select an image", type=["png", "jpg", "jpeg", "webp"])

if image_data:
    image = Image.open(image_data)
    st.image(image, caption="Source Notes", use_column_width=True)

    if st.button("Generate Flashcards"):
        with st.spinner("Analyzing notes..."):
            flashcard_data = generate_cards_from_gemini(image, card_count)

        if flashcard_data:
            st.success(f"Generated {len(flashcard_data)} cards.")
            
            with st.expander("Preview Deck", expanded=True):
                for idx, c in enumerate(flashcard_data, 1):
                    st.markdown(f"**Q{idx}:** {c.get('question')}")
                    st.markdown(f"**A{idx}:** {c.get('answer')}")
                    st.markdown("---")

            apkg_bytes = build_anki_package(flashcard_data, deck_title)
            
            st.download_button(
                label="Download .apkg",
                data=apkg_bytes,
                file_name=f"{deck_title.lower().replace(' ', '_')}.apkg",
                mime="application/octet-stream"
            )
