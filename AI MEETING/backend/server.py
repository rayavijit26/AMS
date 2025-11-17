import os
import uuid
import subprocess
import time
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from openai import OpenAI
import math
import wave
import contextlib
import logging
import random

logging.basicConfig(level=logging.INFO)
load_dotenv()

# -------------------------------
# Config
# -------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing in .env")

client = OpenAI(api_key=OPENAI_API_KEY)

app = Flask(__name__)
CORS(app)

AUDIO_DIR = os.path.join(os.path.dirname(__file__), "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

latest_transcript = ""

# -------------------------------
# Helpers
# -------------------------------
def make_filename(prefix="meeting", ext="webm"):
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    uid = uuid.uuid4().hex[:8]
    return f"{prefix}_{ts}_{uid}.{ext}"

def get_wav_duration(path):
    with contextlib.closing(wave.open(path,'r')) as f:
        frames = f.getnframes()
        rate = f.getframerate()
        return frames / float(rate)

def split_wav(wav_path, chunk_length=60):
    """Split WAV into chunks (seconds). Returns list of chunk paths."""
    duration = get_wav_duration(wav_path)
    chunks = []
    if duration <= chunk_length:
        return [wav_path]
    
    base = wav_path.replace(".wav","")
    total_chunks = math.ceil(duration / chunk_length)
    
    for i in range(total_chunks):
        chunk_path = f"{base}_chunk{i}.wav"
        start = i * chunk_length
        subprocess.run([
            "ffmpeg", "-y", "-i", wav_path,
            "-ss", str(start),
            "-t", str(chunk_length),
            "-ar", "16000", "-ac", "1",
            chunk_path
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        chunks.append(chunk_path)
    
    return chunks

def transcribe_chunk(wav_path, retries=5):
    """Transcribe single WAV chunk with exponential backoff + jitter for 429 errors."""
    delay = 1
    for attempt in range(retries):
        try:
            with open(wav_path, "rb") as f:
                resp = client.audio.transcriptions.create(
                    model="whisper-1",  # <-- 🔴 MODIFIED: Was "gpt-4o-mini-transcribe"
                    file=f
                )
            return resp.text
        except Exception as e:
            if "429" in str(e):
                jitter = random.uniform(0, 1)
                sleep_time = delay + jitter
                logging.warning(f"Rate limit hit. Retry {attempt+1}/{retries} in {sleep_time:.1f}s")
                time.sleep(sleep_time)
                delay *= 2
            else:
                raise e
    raise Exception("Failed transcription after retries due to rate limit")

def summarize_text(text):
    """Summarize transcript into 5 bullets + action items."""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You summarize meetings professionally."},
            {"role": "user", "content": f"Summarize in 5 bullet points and action items:\n\n{text}"}
        ]
    )
    return resp.choices[0].message.content.strip()

# -------------------------------
# Routes
# -------------------------------
@app.route("/audio/<path:filename>")
def serve_audio(filename):
    return send_from_directory(AUDIO_DIR, filename)

@app.route("/upload", methods=["POST"])
def upload_audio():
    global latest_transcript

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]

    # Save original WEBM
    webm_name = make_filename(ext="webm")
    webm_path = os.path.join(AUDIO_DIR, webm_name)
    file.save(webm_path)

    # Convert to WAV
    wav_name = webm_name.replace(".webm", ".wav")
    wav_path = os.path.join(AUDIO_DIR, wav_name)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", webm_path, "-ar", "16000", "-ac", "1", wav_path],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except Exception as e:
        return jsonify({"error": "ffmpeg conversion failed", "details": str(e)}), 500

    # Split WAV if long
    try:
        chunks = split_wav(wav_path, chunk_length=60)  # 60 sec chunks
    except Exception as e:
        return jsonify({"error": "Failed to split audio", "details": str(e)}), 500

    # Transcribe all chunks
    transcript = ""
    for i, chunk in enumerate(chunks):
        try:
            text = transcribe_chunk(chunk)
            transcript += text + " "
        except Exception as e:
            return jsonify({"error": f"Transcription failed on chunk {i}", "details": str(e)}), 500
        finally:
            if chunk != wav_path:  # Keep original WAV
                os.remove(chunk)  # delete chunk after processing

    latest_transcript = transcript.strip()

    # Summarize
    try:
        summary = summarize_text(latest_transcript)
    except Exception as e:
        return jsonify({"error": "Summary generation failed", "details": str(e)}), 500

    return jsonify({
        "status": "success",
        "summary": summary,
        "transcript": latest_transcript,
        "webm_url": request.url_root + "audio/" + webm_name,
        "wav_url": request.url_root + "audio/" + wav_name
    })

@app.route("/chat", methods=["POST"])
def chat():
    global latest_transcript
    data = request.get_json() or {}
    question = data.get("question", "").strip()

    if not latest_transcript:
        return jsonify({"answer": "No transcript available yet."})

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You answer based on the meeting transcript."},
            {"role": "user", "content": f"Transcript:\n{latest_transcript}\n\nQuestion: {question}"}
        ]
    )
    return jsonify({"answer": resp.choices[0].message.content.strip()})

# -------------------------------
if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", 5000))
    app.run(host=host, port=port, debug=False)