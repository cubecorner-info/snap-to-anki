import io
import time
import random
import hashlib
from pydantic import BaseModel

import streamlit as st
import genanki
from google import genai
from google.genai import types
from google.genai.errors import APIError

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

# ------------------------------------------------------------------------------
# 1. Page Configuration & Minimalist CSS UI
# ------------------------------------------------------------------------------
st.set_page_config(page_title="Snap to Anki", page_icon="✦", layout="centered")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    .stApp {
        background: linear-gradient(135deg, #f5f6f8 0%, #e9ecef 100%);
        color: #2b2d42;
    }

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

    div[data-testid="stVerticalBlock"] > div, .stTabs [data-baseweb="tab-list"] {
        border-radius: 12px;
    }

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

    input, textarea, [data-baseweb="select"] {
        background-color: #ffffff !important;
        border: 1px solid #dcdfe6 !important;
        border-radius: 10px !important;
        color: #2b2d42 !important;
    }

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

# ------------------------------------------------------------------------------
# 2. Inputs & Secrets
# ------------------------------------------------------------------------------
api_key = st.secrets.get("GEMINI_API_KEY", None)
if not api_key:
    api_key = st.sidebar.text_input("Enter Gemini API Key", type="password")

deck_name = st.text_input("Deck Name", value="My Study Deck")
target_cards = st.slider("Target Number of Cards", min_value=5, max_value=50, value=25, step=5)

input_tab1, input_tab2 = st.tabs(["📁 Upload File/PDF", "📷 Snap Photo"])
uploaded_file = None
input_source = None

with input_tab1:
    file_upload = st.file_uploader("Upload Notes (PDF, JPG, PNG)", type=["pdf", "png", "jpg", "jpeg"])
    if file_upload:
        uploaded_file = file_upload
        input_source = "upload"

with input_tab2:
    camera_photo = st.camera_input("Take a photo of your notes")
    if camera_photo:
        uploaded_file = camera_photo
        input_source = "camera"

CANDIDATE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]

class Flashcard(BaseModel):
    front: str
    back: str

PROMPT_TEMPLATE = """
You are an exhaustive Anki flashcard creator following the Minimum Information Principle.
Analyze the provided notes thoroughly and create at least {num_cards} distinct flashcards.

CRITICAL EXTRACTION RULES:
1. EXHAUSTIVE COVERAGE: Do not summarize. Extract every formula, definition, rule, date, step, and nuance.
2. ATOMIC FACT PRINCIPLE: One single question and one specific answer per card.
   - Never list multiple items on the back.
   - If a concept has multiple parts or steps, make separate cards for each part/step.
3. QUESTION TYPES TO GENERATE:
   - "What is..." / "Define..." (Key terminology)
   - "Why..." / "How does X cause Y?" (Mechanisms & relationships)
   - "What is the formula for...?" (Math / Science)
   - "What is the difference between X and Y?" (Contrast cards)

NOTES:
{content}
"""

# ------------------------------------------------------------------------------
# 3. Helper Functions
# ------------------------------------------------------------------------------
def extract_pdf_pages(file_bytes: bytes) -> list[str]:
    if fitz is None:
        raise RuntimeError("pymupdf is not installed. Run: pip install pymupdf")
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages = [page.get_text() for page in doc]
    doc.close()
    return pages

def chunk_pages(pages: list[str], max_chars: int = 6000) -> list[str]:
    chunks, current, size = [], [], 0
    for p in pages:
        if size + len(p) > max_chars and current:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(p)
        size += len(p)
    if current:
        chunks.append("\n".join(current))
    return chunks

def generate_with_fallback_and_retry(client, contents, num_cards):
    last_error = None
    for model_name in CANDIDATE_MODELS:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=list[Flashcard],
                    ),
                )
                cards = [c.model_dump() for c in response.parsed]
                return cards, model_name
            except APIError as e:
                last_error = e
                if getattr(e, "code", None) in (503, 429) and attempt < 2:
                    wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                    time.sleep(wait_time)
                    continue
                break
            except Exception as e:
                last_error = e
                break
    raise RuntimeError(
        f"All available Gemini models are currently unavailable. "
        f"Please wait 1-2 minutes and try again. (Last error: {last_error})"
    )

def stable_id(seed: str) -> int:
    return int(hashlib.sha256(seed.encode()).hexdigest(), 16) % (1 << 31)

def build_deck(deck_name: str, cards: list[dict]) -> bytes:
    model_id = stable_id(deck_name + "_model")
    deck_id = stable_id(deck_name + "_deck")

    anki_model = genanki.Model(
        model_id,
        "Mobile QA Model",
        fields=[{"name": "Question"}, {"name": "Answer"}],
        templates=[{
            "name": "Card 1",
            "qfmt": '<div style="font-family: system-ui, sans-serif; font-size: 1.2rem; text-align: center; padding: 20px;">{{Question}}</div>',
            "afmt": '{{FrontSide}}<hr id="answer"><div style="font-family: system-ui, sans-serif; font-size: 1.1rem; color: #166534; text-align: center; padding: 20px;">{{Answer}}</div>',
        }],
    )

    deck = genanki.Deck(deck_id, deck_name)
    for card in cards:
        front = card.get("front", "").strip()
        back = card.get("back", "").strip()
        if not front or not back:
            continue
        deck.add_note(genanki.Note(model=anki_model, fields=[front, back]))

    buffer = io.BytesIO()
    genanki.Package(deck).write_to_file(buffer)  # accepts a file-like object, not just a path
    buffer.seek(0)
    return buffer.getvalue()

# ------------------------------------------------------------------------------
# 4. App Action Logic
# ------------------------------------------------------------------------------
if st.button("Generate Flashcard Deck", type="primary"):
    if not api_key:
        st.error("Please provide a Gemini API Key.")
    elif not uploaded_file:
        st.warning("Please upload a file or take a photo first.")
    elif not deck_name.strip():
        st.warning("Please enter a deck name.")
    else:
        with st.spinner("Analyzing notes and compiling Anki deck..."):
            try:
                client = genai.Client(api_key=api_key)
                file_bytes = uploaded_file.getvalue()
                mime_type = getattr(uploaded_file, "type", None)

                all_cards = []
                used_models = set()

                file_name = getattr(uploaded_file, "name", "photo.jpg") or "photo.jpg"
                is_pdf = input_source == "upload" and (
                    mime_type == "application/pdf"
                    or file_name.lower().endswith(".pdf")
                )

                if is_pdf:
                    pages = extract_pdf_pages(file_bytes)
                    chunks = chunk_pages(pages)
                    cards_per_chunk = max(3, target_cards // max(1, len(chunks)))

                    progress = st.progress(0.0, text=f"Processing 0/{len(chunks)} sections...")
                    for i, chunk in enumerate(chunks):
                        prompt = PROMPT_TEMPLATE.format(num_cards=cards_per_chunk, content=chunk)
                        cards, used_model = generate_with_fallback_and_retry(
                            client, [prompt], cards_per_chunk
                        )
                        all_cards.extend(cards)
                        used_models.add(used_model)
                        progress.progress((i + 1) / len(chunks), text=f"Processing {i + 1}/{len(chunks)} sections...")
                    progress.empty()
                else:
                    if not mime_type:
                        ext = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else "jpg"
                        mime_type = {
                            "jpg": "image/jpeg",
                            "jpeg": "image/jpeg",
                            "png": "image/png",
                            "webp": "image/webp",
                        }.get(ext, "image/jpeg")

                    prompt = PROMPT_TEMPLATE.format(
                        num_cards=target_cards,
                        content="[Notes provided as an image attachment.]",
                    )
                    contents = [
                        types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                        prompt,
                    ]
                    all_cards, used_model = generate_with_fallback_and_retry(
                        client, contents, target_cards
                    )
                    used_models.add(used_model)

                if not all_cards:
                    st.warning("No flashcards could be extracted. Please check document clarity.")
                else:
                    apkg_data = build_deck(deck_name, all_cards)
                    model_label = ", ".join(sorted(used_models))
                    st.success(f"Generated {len(all_cards)} flashcards using {model_label}!")
                    
                    with st.expander("👁️ Preview Extracted Cards", expanded=False):
                        for idx, c in enumerate(all_cards, 1):
                            st.markdown(f"**Q{idx}:** {c.get('front')}")
                            st.markdown(f"**A{idx}:** {c.get('back')}")
                            st.divider()

                    st.download_button(
                        label="📥 Download .apkg Deck",
                        data=apkg_data,
                        file_name=f"{deck_name.replace(' ', '_')}.apkg",
                        mime="application/octet-stream",
                    )

            except Exception as e:
                st.error(f"Error: {e}")
