#!/usr/bin/env python3
"""Run this to see all models available on your Gemini API key."""
import os
import sys
from google import genai

if not os.environ.get("GEMINI_API_KEY"):
    sys.exit("Error: GEMINI_API_KEY not set.")

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

print("\nAvailable Gemini models that support generateContent:\n")
for m in client.models.list():
    if "generateContent" in (m.supported_actions or []):
        print(f"  {m.name}")
print()