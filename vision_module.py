"""
vision_module.py
Sends images directly to Groq (LLaMA 4 Scout — multimodal).
Handles text, math, diagrams — everything in one call.
No local model needed.
"""

import os
import base64
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an AI learning assistant for high school students.

Your strict rules:
1. NEVER give direct answers or solutions.
2. NEVER solve the problem for the student.
3. Guide with Socratic questions only — ask what they already know,
   what formula might apply, or what the first step could be.
4. Keep responses concise: 3 to 5 sentences maximum.
5. Be warm, encouraging, and curious in tone.
6. If the image contains a diagram or formula, ask the student
   what they think it represents before explaining anything.
7. If a subject is provided, tailor your questions to that subject's
   typical problem-solving approach.

Your only goal: help students THINK, not just get answers."""


def encode_image(image_bytes: bytes) -> str:
    """Convert raw image bytes to base64 string."""
    return base64.b64encode(image_bytes).decode("utf-8")


def analyze_image(image_bytes: bytes, subject: str = "", user_question: str = "") -> dict:
    """
    Send image to Groq LLaMA 4 Scout and return:
    - extracted_text : what Groq read from the image
    - hint           : Socratic guidance for the student

    Args:
        image_bytes   : raw image bytes from upload
        subject       : subject selected by student (e.g. "Math")
        user_question : optional extra question from student

    Returns:
        { "extracted_text": "...", "hint": "..." }
    """

    b64 = encode_image(image_bytes)

    # Build text prompt
    parts = []
    if subject:
        parts.append(f"Subject: {subject}")
    if user_question:
        parts.append(f"Student's question: {user_question}")
    parts.append(
        "First, briefly describe what content you see in this image "
        "(text, formulas, diagrams). Then provide your Socratic guidance."
    )
    text_prompt = "\n".join(parts)

    response = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}"
                        }
                    },
                    {
                        "type": "text",
                        "text": text_prompt
                    }
                ]
            }
        ],
        temperature=0.7,
        max_tokens=400,
    )

    full_response = response.choices[0].message.content.strip()

    # Split response into extracted content + hint
    # Groq describes the image first, then gives the hint
    lines = full_response.split("\n")
    extracted_text = lines[0] if lines else ""
    hint           = "\n".join(lines[1:]).strip() if len(lines) > 1 else full_response

    return {
        "extracted_text": extracted_text,
        "hint":           hint,
        "full_response":  full_response
    }


# ── Quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python vision_module.py path/to/image.jpg")
        sys.exit(1)

    with open(sys.argv[1], "rb") as f:
        image_bytes = f.read()

    print("Sending to Groq vision...")
    result = analyze_image(
        image_bytes=image_bytes,
        subject="Math",
        user_question="I don't understand this"
    )

    print("\n── Result ───────────────────────────────────────────────")
    print(f"Extracted : {result['extracted_text']}")
    print(f"\nHint      :\n{result['hint']}")
