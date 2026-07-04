import os
import json
from pathlib import Path

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parent.parent

PROGRESS_PATH = DEFAULT_PROJECT_ROOT / "agent_progress.json"
REQUEST_PATH = DEFAULT_PROJECT_ROOT / "gemini_query_prompt.md"


def check_if_stuck(consecutive_failure_threshold: int = 3) -> bool:
    """Checks agent_progress.json to determine if the local LLM is looping."""
    if not PROGRESS_PATH.exists():
        return False

    try:
        progress = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        failures = progress.get("metadata", {}).get("consecutive_failures", 0)
        return failures >= consecutive_failure_threshold
    except Exception:
        return False


def assemble_escalation_payload(
    stuck_module: str, error_message: str, code_snippet: str
) -> str:
    prompt = f"""### SYSTEM ESCALATION: DEVELOPER ASSISTANCE REQUEST
The automated coding agent has encountered a persistent error during implementation.

**Failing Module:** `{stuck_module}`
**Error Output / Stack Trace:**
```text
{error_message}
```

**Current Implementation Code:**
```python
{code_snippet}
```

**Task Spec Context:**
Review the ASR Spec rules regarding `{stuck_module}`. 

**Instruction:**
Identify the exact bug causing this failure and provide a corrected, complete implementation of the code snippet above. Keep your response brief and direct.
"""
    return prompt


def escalate_to_gemini(prompt: str) -> str | None:
    print("\\n" + "=" * 60)
    print("⚠️  STUCK ALERT: The local agent has encountered repeating failures.")
    print("Proposed Question for Gemini:")
    print("-" * 60)
    print(prompt)
    print("-" * 60)

    REQUEST_PATH.write_text(prompt, encoding="utf-8")
    print(f"📝 Prompt saved to: {REQUEST_PATH}")

    user_input = (
        input("\\nDo you approve sending this query to Gemini API? (y/n): ")
        .strip()
        .lower()
    )

    if user_input != "y":
        print(
            "❌ Request cancelled by user. You can manually copy the prompt from gemini_query_prompt.md."
        )
        return None

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("⚠️  GEMINI_API_KEY environment variable not found.")
        print(
            "Please resolve manually using the prompt saved in gemini_query_prompt.md, then paste the solution."
        )
        return None

    try:
        print("🚀 Sending approved request to Gemini...")
        import google.generativeai as genai  # type: ignore

        genai.configure(api_key=api_key)

        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)

        print("\\n✅ Response Received from Gemini:")
        print(response.text)
        return response.text
    except Exception as e:
        print(f"❌ Error communicating with Gemini API: {e}")
        return None
