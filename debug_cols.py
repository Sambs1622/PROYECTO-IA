import pandas as pd
import unicodedata

def clean_col(name):
    n = str(name).strip().upper()
    # Normalize and remove marks (accents)
    normalized = unicodedata.normalize('NFD', n)
    cleaned = "".join(c for c in normalized if unicodedata.category(c) != 'Mn')
    return cleaned

try:
    df = pd.read_excel('DATOS TPM.xlsx')
    original = list(df.columns)
    cleaned = [clean_col(c) for c in original]
    
    print("--- ORIGINAL ---")
    print(original)
    print("--- CLEANED ---")
    print(cleaned)
    
    # Check if 'MAQUINA' is in cleaned
    if 'MAQUINA' in cleaned:
        print("OK: MAQUINA found.")
    else:
        print("ERROR: MAQUINA NOT FOUND.")
        # Try to find something similar
        import difflib
        matches = difflib.get_close_matches('MAQUINA', cleaned)
        print(f"Closest matches: {matches}")

except Exception as e:
    print(f"FAILED: {e}")
