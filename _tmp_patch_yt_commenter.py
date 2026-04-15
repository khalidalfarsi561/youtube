from pathlib import Path

p = Path("yt_commenter.py")
s = p.read_text(encoding="utf-8")

if "from dotenv import load_dotenv" not in s:
    s = s.replace(
        "import urllib.request\nfrom playwright.async_api import async_playwright\n",
        "import urllib.request\nfrom dotenv import load_dotenv\nfrom pathlib import Path\nfrom playwright.async_api import async_playwright\n",
    )

s = s.replace("import google.genai as genai\n", "import google.generativeai as genai\n")

old_block = """def generate_comment(title: str) -> str:\n    api_key = os.getenv(\"GEMINI_API_KEY\")\n    if not api_key:\n        raise RuntimeError(\"GEMINI_API_KEY is not set.\")\n    genai.configure(api_key=api_key)\n"""
new_block = """def generate_comment(title: str) -> str:\n    load_dotenv()\n    api_key = os.getenv(\"GEMINI_API_KEY\")\n    if not api_key:\n        env_path = Path(\".env\")\n        if env_path.exists():\n            for line in env_path.read_text(encoding=\"utf-8\").splitlines():\n                if line.startswith(\"GEMINI_API_KEY=\"):\n                    api_key = line.split(\"=\", 1)[1].strip()\n                    if api_key:\n                        os.environ[\"GEMINI_API_KEY\"] = api_key\n                        break\n    if not api_key:\n        raise RuntimeError(\"GEMINI_API_KEY is not set. Add it to .env or the environment.\")\n    genai.configure(api_key=api_key)\n"""
if old_block in s:
    s = s.replace(old_block, new_block)

p.write_text(s, encoding="utf-8")
print("patched yt_commenter.py")
