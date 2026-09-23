import io
import os
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
# 1. Page Configuration & Claude Dark Mode CSS UI
# ------------------------------------------------------------------------------
st.set_page_config(page_title="Snap to Anki", page_icon="✦", layout="centered")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Söhne:wght@400;500;600&family=Inter:wght@300;400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,400;1,6..72,400&display=swap');
    
    /* Overall Page Background & Text Base */
    .stApp {
        background-color: #0d0d0e !important;
        color: #e3e3e8 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
    }

    /* Claude-Style Serif Header */
    .claude-header {
        font-family: 'Newsreader', Georgia, serif;
        font-size: 2.6rem;
        font-weight: 400;
        text-align: center;
        color: #f0ede6;
        letter-spacing: -0.5px;
        margin-top: 1rem;
        margin-bottom: 0.3rem;
    }

    .claude-sub {
        font-family: 'Inter', sans-serif;
        font-size: 0.95rem;
        text-align: center;
        color: #9a9ab0;
        font-weight: 400;
        margin-bottom: 2.5rem;
    }

    /* Input Labels and Form Controls */
    label, div[data-testid="stMarkdownContainer"] p {
        color: #c5c5d0 !important;
        font-size: 0.92rem !important;
    }

    /* Input Fields (Text Inputs, Sliders) */
    input[type="text"], input[type="password"] {
        background-color: #16161a !important;
        border: 1px solid #2a2a35 !important;
        border-radius: 8px !important;
        color: #f0ede6 !important;
        padding: 0.5rem 0.8rem !important;
    }

    input[type="text"]:focus, input[type="password"]:focus {
        border-color: #5b21b6 !important; /* Muted Dark Violet */
        box-shadow: 0 0 0 1px #5b21b6 !important;
    }

    /* File Uploader & Camera Area */
    div[data-testid="stFileUploader"], div[data-testid="stCameraInput"] {
        background-color: #121216 !important;
        border: 1px dashed #2e2e3d !important;
        border-radius: 12px !important;
        padding: 1rem !important;
    }

    /* Custom Tabs Styling */
    .stTabs [data-baseweb="tab-list"] {
        background-color: #121216 !important;
        border-radius: 10px !important;
        padding: 4px !important;
        gap: 4px !important;
        border: 1px solid #22222d !important;
    }

    .stTabs [data-baseweb="tab"] {
        color: #8e8e9f !important;
        border-radius: 6px !important;
        border: none !important;
        padding: 8px 16px !important;
    }

    .stTabs [aria-selected="true"] {
        background-color: #1e1b2e !important; /* Deep Violet Tint */
        color: #e2d9f3 !important;
        font-weight: 500 !important;
    }

    /* Main Action Button - Deep Wine Red Accent */
    .stButton>button[kind="primary"] {
        background: linear-gradient(180deg, #721c24 0%, #4a1217 100%) !important;
        color: #f8d7da !important;
        font-weight: 500 !important;
        border: 1px solid #842029 !important;
        border-radius: 8px !important;
        padding: 0.65rem 2rem !important;
        transition: all 0.2s ease !important;
        width: 100%;
        margin-top: 1rem;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4) !important;
    }

    .stButton>button[kind="primary"]:hover {
        background: linear-gradient(180deg, #842029 0%, #5c161d 100%) !important;
        border-color: #a71d2a !important;
        color: #ffffff !important;
        transform: translateY(-1px);
    }

    /* Secondary / Download Buttons - Dark Violet Accent */
    div[data-testid="stDownloadButton"] > button {
        background: linear-gradient(180deg, #3b154c 0%, #240d30 100%) !important;
        color: #ebd3f8 !important;
        border: 1px solid #582373 !important;
        border-radius: 8px !important;
        width: 100%;
    }

    div[data-testid="stDownloadButton"] > button:hover {
        background: linear-gradient(180deg, #4c1d63 0%, #321243 100%) !important;
        border-color: #732e96 !important;
        color: #ffffff !important;
    }

    /* Expander Container */
    .streamlit-expanderHeader {
        background-color: #141419 !important;
        border: 1px solid #242430 !important;
        border-radius: 8px !important;
        color: #c5c5d0 !important;
    }

    /* Sidebar Fixes */
    section[data-testid="stSidebar"] {
        background-color: #09090b !important;
        border-right: 1px solid #1f1f28 !important;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 class="claude-header">Snap Notes to Anki</h1>', unsafe_allow_html=True)
st.markdown('<p class="claude-sub">Transform your study material into minimal, structured flashcard decks.</p>', unsafe_allow_html=True)

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
    "gemini-3.6-flash",
    "gemini-3.0-flash",
    "gemini-2.5-flash",
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
            "qfmt": '<div style="font-family: system-ui, sans-serif; font-size: 1.1rem; text-align: center; color: #f0ede6; padding: 20px;">{{Question}}</div>',
            "afmt": '{{FrontSide}}<hr id="answer" style="border-color: #2e2e3d;"><div style="font-family: system-ui, sans-serif; font-size: 1.05rem; color: #a3e635; text-align: center; padding: 20px;">{{Answer}}</div>',
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
    genanki.Package(deck).write_to_buffer(buffer)
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
