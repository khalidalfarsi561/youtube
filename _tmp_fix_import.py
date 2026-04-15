from pathlib import Path

p = Path("yt_commenter.py")
s = p.read_text(encoding="utf-8")
s = s.replace("import google.generativeai as genai\n", "import google.genai as genai\n")
p.write_text(s, encoding="utf-8")
print("patched")
