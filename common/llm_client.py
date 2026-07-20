import os
import time
import json
import requests
from typing import Type, Tuple, Dict, Any, Optional
from pydantic import BaseModel, ValidationError

# Load .env manually if it exists in current working directory or parent
def _load_env():
    for env_path in [".env", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")]:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip("'\""))

_load_env()

def _generate_structured_gemini(
    system_prompt: str,
    user_prompt: str,
    schema: Type[BaseModel],
    temperature: float = 0.0
) -> Tuple[BaseModel, Dict[str, Any]]:
    """
    Structured generation implementation using Google Gemini API (google-genai SDK).
    """
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing. Please set GEMINI_API_KEY.")

    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    client = genai.Client(api_key=api_key)

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=temperature,
        response_mime_type="application/json",
        response_schema=schema,
    )

    current_user_prompt = user_prompt
    validation_attempts = 0
    max_validation_attempts = 2
    last_error = ""

    prompt_tokens = 0
    completion_tokens = 0
    total_latency_ms = 0.0

    while validation_attempts < max_validation_attempts:
        validation_attempts += 1

        # Handle rate limiting with exponential backoff (1s, 2s, 4s)
        backoff_delays = [1.0, 2.0, 4.0]
        response = None
        rate_limit_attempts = 0

        while True:
            start_time = time.perf_counter()
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=current_user_prompt,
                    config=config,
                )
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                total_latency_ms += elapsed_ms
                break
            except Exception as e:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                total_latency_ms += elapsed_ms
                err_str = str(e).lower()
                is_rate_limit = any(kw in err_str for kw in ["429", "resource_exhausted", "quota", "rate limit", "too many requests"])

                if is_rate_limit and rate_limit_attempts < len(backoff_delays):
                    delay = backoff_delays[rate_limit_attempts]
                    rate_limit_attempts += 1
                    print(f"[GEMINI_RATE_LIMIT] 429 hit. Retrying in {delay}s (attempt {rate_limit_attempts})...")
                    time.sleep(delay)
                else:
                    raise e

        # Extract usage token counts from usage_metadata
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            prompt_tokens += getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            completion_tokens += getattr(response.usage_metadata, "candidates_token_count", 0) or 0

        # Try parsing response object or text into schema
        try:
            if hasattr(response, "parsed") and response.parsed is not None:
                validated_data = response.parsed
                # If parsed is a dict, convert via schema
                if isinstance(validated_data, dict):
                    validated_data = schema.model_validate(validated_data)
            else:
                raw_text = getattr(response, "text", "") or ""
                validated_data = schema.model_validate_json(raw_text)

            metadata = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": total_latency_ms,
                "local_inference": False,
                "model": model_name
            }
            return validated_data, metadata

        except (ValidationError, json.JSONDecodeError, AttributeError) as err:
            last_error = str(err)
            print(f"[GEMINI_VALIDATION_RETRY] Validation failed on attempt {validation_attempts}: {last_error}")
            current_user_prompt = (
                f"{user_prompt}\n\n"
                f"Warning: Your previous response failed validation with error: {last_error}. "
                f"Please ensure output strictly matches the required JSON schema."
            )

    raise ValueError(f"Gemini structured generation failed Pydantic validation after {max_validation_attempts} attempts. Last error: {last_error}")


def _generate_structured_ollama(
    system_prompt: str,
    user_prompt: str,
    schema: Type[BaseModel],
    temperature: float = 0.0
) -> Tuple[BaseModel, Dict[str, Any]]:
    """
    Swappable Ollama provider stub / implementation.
    """
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
    url = f"{host}/api/chat"

    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    instructions = (
        f"\n\nYou MUST return a JSON object matching this schema:\n"
        f"{schema_json}\n"
        f"Do not include any introductory or concluding text, markdown code blocks, or formatting. "
        f"Return ONLY valid raw JSON."
    )

    current_user_prompt = user_prompt + instructions
    attempts = 0
    max_attempts = 2
    last_error = ""

    prompt_tokens = 0
    completion_tokens = 0
    total_latency_ms = 0.0

    while attempts < max_attempts:
        attempts += 1
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": current_user_prompt}
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature}
        }

        start_time = time.perf_counter()
        try:
            response = requests.post(url, json=payload, timeout=90)
            response.raise_for_status()
            res_data = response.json()
        except Exception as e:
            total_latency_ms += (time.perf_counter() - start_time) * 1000.0
            last_error = f"Ollama API request failed: {e}"
            if attempts < max_attempts:
                time.sleep(2.0)
                continue
            raise RuntimeError(f"Ollama API request failed after {max_attempts} attempts. Last error: {e}")

        total_latency_ms += (time.perf_counter() - start_time) * 1000.0
        prompt_tokens += res_data.get("prompt_eval_count", 0)
        completion_tokens += res_data.get("eval_count", 0)
        content = res_data.get("message", {}).get("content", "").strip()

        try:
            validated_data = schema.model_validate_json(content)
            metadata = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": total_latency_ms,
                "local_inference": True,
                "model": model
            }
            return validated_data, metadata
        except (ValidationError, json.JSONDecodeError) as err:
            last_error = str(err)
            current_user_prompt = (
                f"{user_prompt}\n\n"
                f"Warning: Your last attempt failed validation: {last_error}\n"
                f"Correct the JSON and return ONLY valid raw JSON."
            )

    raise ValueError(f"Ollama structured generation failed validation after {max_attempts} attempts. Error: {last_error}")


def generate_structured(
    system_prompt: str,
    user_prompt: str,
    schema: Type[BaseModel],
    temperature: float = 0.0
) -> Tuple[BaseModel, Dict[str, Any]]:
    """
    Single unified LLM abstraction interface used by extraction, canonicalization, and Q&A layer.
    Provider is selectable via environment variable LLM_PROVIDER ('gemini' | 'ollama').
    Defaults to 'gemini'.
    """
    provider = os.environ.get("LLM_PROVIDER", "gemini").lower()
    if provider == "gemini":
        return _generate_structured_gemini(system_prompt, user_prompt, schema, temperature)
    elif provider == "ollama":
        return _generate_structured_ollama(system_prompt, user_prompt, schema, temperature)
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER '{provider}'. Supported providers: 'gemini', 'ollama'.")
