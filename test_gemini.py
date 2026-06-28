"""Test minimal de l'appel API Google Gemini."""
import os, sys

# Fixer l'encodage stdout pour eviter les crashs
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.config import load_dotenv

load_dotenv()
key = os.environ.get("GEMINI_API_KEY")

if not key:
    print("[ERREUR] GEMINI_API_KEY non trouvee dans .env")
    print("  Verifie que ton .env contient : GEMINI_API_KEY=ta_cle")
    sys.exit(1)

# Masquer la cle pour la securite
print(f"[OK] Cle trouvee : {key[:10]}... ({len(key)} caracteres)")

from google import genai
from google.genai import types

client = genai.Client(api_key=key)
print("[OK] Client Gemini cree.")
print("[...] Appel Gemini en cours...")

try:
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents="Dis bonjour en francais en une phrase courte.",
        config=types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=100,
        ),
    )
    print()
    print("=" * 50)
    print("REPONSE GEMINI :")
    print("=" * 50)
    print(response.text)
    print("=" * 50)
    print("[OK] SUCCES -- L'API Gemini fonctionne !")
except Exception as e:
    print(f"[ERREUR] Echec : {e}")
    sys.exit(1)
