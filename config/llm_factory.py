import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()  # REQUIRED

def get_llm(temperature=0):
    provider = os.getenv("LLM_PROVIDER", "openai").lower()

    if provider == "gemini":
        model = os.getenv("GEMINI_MODEL")
        key = os.getenv("GEMINI_API_KEY")

        if not model or not key:
            raise RuntimeError("GEMINI_MODEL or GEMINI_API_KEY missing")

        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=key,
            temperature=temperature
        )

    # OpenAI fallback
    model = os.getenv("OPENAI_MODEL")
    key = os.getenv("OPENAI_API_KEY")

    if not model or not key:
        raise RuntimeError("OPENAI_MODEL or OPENAI_API_KEY missing")

    return ChatOpenAI(
        model=model,
        api_key=key,
        temperature=temperature
    )