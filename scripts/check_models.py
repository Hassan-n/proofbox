import os, time
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

client = OpenAI(
    api_key=os.environ["VULTR_INFERENCE_KEY"],
    base_url="https://api.vultrinference.com/v1"
)

def extract_text(msg):
    # Fallback if a reasoning model puts text in reasoning_content
    content = (msg.content or "").strip()
    if not content and hasattr(msg, "reasoning_content") and msg.reasoning_content:
        return f"[FROM REASONING]: {msg.reasoning_content.strip()[-100:]}"
    return content

text_roles = {
    "router": "deepseek-v4.1-flash-1017",
    "extractor": "qwen3.8-27b",
    "analyst_coder": "deepseek-v4.1-flash-1017",
    "writer": "glm-5.3",
}

for role, model in text_roles.items():
    t0 = time.time()
    r = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "/no_think Output valid JSON only."},
            {"role": "user", "content": 'Reply with only valid JSON: {"status": "ok"}'}
        ],
        max_tokens=512,
        temperature=0
    )
    print(f"[OK] {role} ({model}) - {time.time()-t0:.2f}s -> {extract_text(r.choices[0].message)}")

TINY_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
for v_model in ["mimo-v2.6-pro", "nemotron-3-nano-omni-30b-a3b-reasoning", "glm-5.3"]:
    t0 = time.time()
    try:
        r = client.chat.completions.create(
            model=v_model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image in 3 words."},
                    {"type": "image_url", "image_url": {"url": TINY_PNG}}
                ]
            }],
            max_tokens=512
        )
        print(f"[VISION] {v_model} ({time.time()-t0:.2f}s) -> {extract_text(r.choices[0].message)}")
    except Exception as e:
        print(f"[VISION FAIL] {v_model} -> {e}")