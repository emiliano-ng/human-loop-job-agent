"""
Provider-agnostic on purpose. This tool is meant to run repeatedly for
months of job searching, not once, so cost and availability matter more
than which backend it hits.

Default: Ollama running locally (free, unlimited, no API key). Swap
providers by changing three env vars, nothing else in the codebase needs
to change, since every option here speaks the same OpenAI-compatible chat
API.

Example configs (set these in .env):

  # Ollama (local, free, default)
  LLM_BASE_URL=http://localhost:11434/v1
  LLM_API_KEY=ollama          # any non-empty string, Ollama ignores it
  LLM_MODEL=llama3.1:8b       # or whatever you've pulled: `ollama pull llama3.1:8b`

  # Groq (free tier, cloud, fast, good if local inference feels slow/unreliable for JSON)
  LLM_BASE_URL=https://api.groq.com/openai/v1
  LLM_API_KEY=<your groq key>
  LLM_MODEL=llama-3.1-8b-instant

  # OpenAI (cheap, very reliable JSON mode, needs billing set up)
  LLM_BASE_URL=https://api.openai.com/v1
  LLM_API_KEY=<your openai key>
  LLM_MODEL=gpt-4o-mini

  # Nebius Token Factory (if you want Nemotron specifically, or already pay for it elsewhere)
  LLM_BASE_URL=https://api.studio.nebius.com/v1/
  LLM_API_KEY=<your nebius key>
  LLM_MODEL=nvidia/Llama-3_1-Nemotron-70B-Instruct-HF
"""

import os
import json
from openai import OpenAI

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "ollama")
LLM_MODEL = os.environ.get("LLM_MODEL", "llama3.1:8b")

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
    return _client


def json_completion(system_prompt: str, user_prompt: str, model: str | None = None) -> dict:
    """Calls the model and asks for JSON-only output, then parses it."""
    client = get_client()
    response = client.chat.completions.create(
        model=model or LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )
    raw = response.choices[0].message.content.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)
