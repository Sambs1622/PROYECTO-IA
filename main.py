import subprocess
import sys
import os

def main():
    print("\nIniciando ARIA Local (Offline)...")
    
    # Simplemente lanzamos el script local de Tkinter
    # No necesitamos servidores ni .env
    try:
        subprocess.run([sys.executable, "local_aria.py"])
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error al iniciar ARIA: {e}")

if __name__ == "__main__":
    main()
