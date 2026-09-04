import streamlit as st
import genanki
import json
import random
import tempfile
from google import genai
from google.genai import types

st.set_page_config(page_title="Snap to Anki", page_icon="📝", layout="centered")
st.title("📸 Snap Notes to Anki")

# Retrieve API key automatically from Streamlit Secrets or sidebar fallback
api_key = st.secrets.get("GEMINI_API_KEY", None)
if not api_key:
    api_key = st.sidebar.text_input("Enter Gemini API Key", type="password")

deck_name = st.text_input("Deck Name", value="My Study Deck")

# Tabs for uploading files or using the mobile camera directly
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

if st.button("Generate Flashcard Deck", type="primary"):
    if not api_key:
        st.error("Please provide a Gemini API Key (either in Streamlit Secrets or the sidebar).")
    elif not uploaded_file:
        st.warning("Please upload a file or snap a photo first.")
    else:
        with st.spinner("Analyzing notes and compiling Anki deck..."):
            try:
                # 1. Initialize Gemini client
                client = genai.Client(api_key=api_key)
                file_bytes = uploaded_file.getvalue()
                
                # Determine MIME type
                mime_type = getattr(uploaded_file, "type", None) or "image/jpeg"

                prompt = """
                Analyze the physical or digital notes in this document.
                Extract high-yield key concepts, formulas, definitions, and questions into atomic flashcards.
                Output strictly a valid JSON array of objects with 'front' and 'back' fields.
                Example format:
                [
                  {"front": "What is the primary function of the ribosome?", "back": "Protein synthesis."},
                  {"front": "State Newton's Second Law of Motion", "back": "F = ma (Force equals mass times acceleration)"}
                ]
                """

                # 2. Query Gemini model with strict JSON formatting
                response = client.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=[
                        types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                        prompt
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )

                cards = json.loads(response.text)

                if not cards:
                    st.warning("No flashcards could be extracted. Please check the document clarity.")
                else:
                    # 3. Build native .apkg deck with genanki
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

                    st.success(f"Generated {len(cards)} flashcards!")
                    st.download_button(
                        label="📥 Download .apkg Deck",
                        data=apkg_data,
                        file_name=f"{deck_name.replace(' ', '_')}.apkg",
                        mime="application/octet-stream"
                    )

            except Exception as e:
                st.error(f"Error processing document: {e}")
