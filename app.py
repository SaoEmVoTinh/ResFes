"""
app.py
Flask backend — AR Learning Assistant
Pipeline: image upload → Groq LLaMA 4 Scout (vision) → JSON response
"""

import os
import base64
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

from vision_module import analyze_image

load_dotenv()

app = Flask(__name__, static_folder="static")
CORS(app)


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    """
    Expects JSON:
    {
        "image":   "<base64 encoded image>",
        "subject": "Math",             (optional)
        "note":    "I don't get this"  (optional)
    }

    Returns JSON:
    {
        "extracted_text": "...",
        "hint":           "...",
        "subject":        "Math"
    }
    """

    data = request.get_json()

    if not data or "image" not in data:
        return jsonify({"error": "No image provided."}), 400

    subject       = data.get("subject", "")
    user_question = data.get("note", "")

    # ── Decode base64 image ───────────────────────────────────────────────────
    try:
        raw = data["image"]
        if "," in raw:
            raw = raw.split(",")[1]
        image_bytes = base64.b64decode(raw)
    except Exception as e:
        return jsonify({"error": f"Image decode failed: {str(e)}"}), 400

    # ── Groq vision ───────────────────────────────────────────────────────────
    try:
        result = analyze_image(
            image_bytes=image_bytes,
            subject=subject,
            user_question=user_question
        )
    except Exception as e:
        return jsonify({"error": f"Groq vision failed: {str(e)}"}), 500

    return jsonify({
        "extracted_text": result["extracted_text"],
        "hint":           result["hint"],
        "subject":        subject
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "model":  "meta-llama/llama-4-scout-17b-16e-instruct"
    })


if __name__ == "__main__":
    print("Starting AR Learning Assistant...")
    print("Open http://localhost:5000 in your browser")
    app.run(debug=True, port=5000)
