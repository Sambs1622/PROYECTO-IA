import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import pandas as pd
import pyttsx3
import threading
import os
import re
import queue
import sounddevice as sd
import vosk
import json
import difflib
import unicodedata
from pathlib import Path
from datetime import datetime

# --- Configuración de Base de Datos ---
EXCEL_PATH = "DATOS TPM.xlsx"
SHEET_NAME = "SEGUIMIENTO TPM"

class DatabaseManager:
    def __init__(self, path):
        self.path = path
        self.df = None
        self.load_data()

    def load_data(self):
        try:
            # Primero ver las hojas disponibles
            xl = pd.ExcelFile(self.path)
            sheets = xl.sheet_names
            
            # Buscar la mejor coincidencia para SEGUIMIENTO TPM
            target = SHEET_NAME.upper()
            best_match = difflib.get_close_matches(target, [s.upper() for s in sheets], n=1, cutoff=0.5)
            
            final_sheet = sheets[0] # Default
            if best_match:
                # Encontrar el nombre original con el case correcto
                for s in sheets:
                    if s.upper() == best_match[0]:
                        final_sheet = s
                        break
            
            print(f"Cargando hoja: {final_sheet}")
            self.df = pd.read_excel(self.path, sheet_name=final_sheet)
            
            # Limpiar nombres de columnas de forma ROBUSTA
            def clean_col(name):
                n = str(name).strip().upper()
                n = "".join(c for c in unicodedata.normalize('NFD', n) if unicodedata.category(c) != 'Mn')
                return n

            self.df.columns = [clean_col(c) for c in self.df.columns]
            print(f"Columnas detectadas en {final_sheet}: {list(self.df.columns)}")
            
            # Validar columnas críticas
            if 'MAQUINA' not in self.df.columns:
                # Intentar mapear si hay algo parecido
                similares = difflib.get_close_matches('MAQUINA', self.df.columns, n=1)
                if similares:
                    self.df.rename(columns={similares[0]: 'MAQUINA'}, inplace=True)
            
            return True
        except Exception as e:
            print(f"Error cargando Excel: {e}")
            return False

    def query(self, text):
        if self.df is None: return "Error: Base de datos no cargada.", None
        
        text = text.lower().strip()
        
        # --- Listas de ayuda para entendimiento ---
        # Usamos los nombres normalizados (sin acentos)
        maquinas_reales = self.df['MAQUINA'].astype(str).unique().tolist()
        tecnicos_reales = self.df['TECNICO ENCARGADO'].astype(str).unique().tolist()
        tecnicos_reales = [t for t in tecnicos_reales if str(t).lower() != 'nan']
        reportadores_reales = self.df['NOMBRE DE QUIEN REPORTA'].astype(str).unique().tolist()
        reportadores_reales = [r for r in reportadores_reales if str(r).lower() not in ['nan', 'nombre de quien reporta']]
        col_tpm = self.df.columns[0] # Primera columna (#TPM)
        # 1. DETECCIÓN DE ENTIDADES EN EL TEXTO
        # A. Máquina
        mejor_maquina = None
        max_ratio = 0
        maquinas_ordenadas = sorted([str(m).upper() for m in maquinas_reales], key=len, reverse=True)
        for maq in maquinas_ordenadas:
            if str(maq) == "NAN": continue
            if maq.lower() in text:
                mejor_maquina = maq
                break
            ratio = difflib.SequenceMatcher(None, text, maq.lower()).ratio()
            if ratio > max_ratio and ratio > 0.4:
                max_ratio = ratio
                mejor_maquina = maq

        # B. Técnico
        mejor_tecnico = None
        for tec in [str(t).upper() for t in tecnicos_reales]:
            if tec.lower() in text:
                mejor_tecnico = tec
                break

        # C. Reportador
        reportadores_encontrados = []
        for rep in reportadores_reales:
            rep_upper = str(rep).upper()
            rep_lower = rep_upper.lower()
            
            # Si el nombre es muy corto, evitar falsos positivos
            if len(rep_lower.strip(".")) < 3:
                word = rep_lower.replace(".", "")
                pattern = rf'\b{re.escape(word)}\b'
                if re.search(pattern, text):
                    reportadores_encontrados.append(rep_upper)
                continue
                
            # Nombre completo
            if rep_lower in text:
                reportadores_encontrados.append(rep_upper)
                continue
            
            # Buscar por partes individuales (ej: "lucas", "triana")
            parts = [p.replace(".", "").lower() for p in rep_upper.split()]
            parts = [p for p in parts if len(p) >= 3]
            if parts and any(p in text for p in parts):
                reportadores_encontrados.append(rep_upper)
        if reportadores_encontrados:
            reportadores_encontrados = list(dict.fromkeys(reportadores_encontrados))

        # 2. BÚSQUEDA POR ID DE TPM (Ej: "TPM 352")
        match_tpm = re.search(r'tpm\s*(\d+)', text)
        if match_tpm:
            id_tpm = match_tpm.group(1)
            # Buscar en la primera columna
            res = self.df[self.df[col_tpm].astype(str).str.contains(id_tpm, na=False)]
            if len(res) > 0:
                return f"Mostrando el registro TPM número {id_tpm}.", res
            return f"No encontré ningún registro con el número TPM {id_tpm}.", None

        # 3. RESET / VER TODO
        if any(w in text for w in ["todo", "limpiar", "quitar filtro", "mostrar base"]):
            return "Aquí tienes la base de datos completa.", self.df

        # 4. PREGUNTAS DE CANTIDAD / ESTADÍSTICAS / TOTALES (con o sin filtros)
        if any(w in text for w in ["cuántos", "cuántas", "cuantos", "cuantas", "total", "cantidad", "resumen", "estadística", "general"]):
            # Determinar el DataFrame base para la estadística
            target_df = self.df
            sujeto = "la base de datos completa"
            
            if mejor_maquina:
                target_df = self.df[self.df['MAQUINA'].astype(str).str.upper() == mejor_maquina]
                sujeto = f"la {mejor_maquina}"
            elif mejor_tecnico:
                target_df = self.df[self.df['TECNICO ENCARGADO'].astype(str).str.upper() == mejor_tecnico]
                sujeto = f"el técnico {mejor_tecnico}"
            elif reportadores_encontrados:
                nombres_str = " o ".join(reportadores_encontrados)
                target_df = self.df[self.df['NOMBRE DE QUIEN REPORTA'].astype(str).str.upper().isin(reportadores_encontrados)]
                sujeto = f"el reportador {nombres_str}"

            total = len(target_df)
            abiertos_df = target_df[target_df['ESTADO'].str.contains('ABIERTA|PENDIENTE', case=False, na=False)]
            abiertos = len(abiertos_df)
            cerrados_df = target_df[target_df['ESTADO'].str.contains('CERRADA|CERRADO', case=False, na=False)]
            cerrados = len(cerrados_df)
            
            if any(w in text for w in ["cerrado", "cerrada", "cerrados", "cerradas"]):
                return f"Para {sujeto}, hay actualmente {cerrados} casos cerrados.", cerrados_df
            elif any(w in text for w in ["abierto", "abierta", "abiertos", "abiertas"]):
                return f"Para {sujeto}, hay actualmente {abiertos} casos abiertos.", abiertos_df
            
            return (f"Para {sujeto}, hay un total de {total} registros. "
                    f"De ellos, {abiertos} están abiertos y {cerrados} cerrados."), target_df

        # 5. FILTRADO SIMPLE (Si no preguntaron cantidad, pero sí mencionan una entidad)
        if mejor_maquina:
            res = self.df[self.df['MAQUINA'].astype(str).str.upper() == mejor_maquina]
            return f"Mostrando los {len(res)} registros para la {mejor_maquina}.", res
            
        if mejor_tecnico:
            res = self.df[self.df['TECNICO ENCARGADO'].astype(str).str.upper() == mejor_tecnico]
            return f"Filtrando intervenciones del técnico {mejor_tecnico}.", res
            
        if reportadores_encontrados:
            res = self.df[self.df['NOMBRE DE QUIEN REPORTA'].astype(str).str.upper().isin(reportadores_encontrados)]
            nombres_str = " o ".join(reportadores_encontrados)
            return f"Filtrando registros reportados por {nombres_str}.", res

        return ("No estoy segura de qué filtrar. Intenta con: 'Mantenimientos Selladora 3' o 'Ver todo'.", None)

class ARIAApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ARIA - Asistente TPM Local")
        self.root.geometry("600x500")
        self.root.configure(bg="#1e1e2e")
        
        self.db = DatabaseManager(EXCEL_PATH)
        self.engine = None
        self.is_listening = False
        self.audio_queue = queue.Queue()
        
        # Inicializar Vosk (Modelo en español)
        try:
            # Esto descargará el modelo automáticamente si no existe (requiere internet la primera vez)
            self.model = vosk.Model(lang="es")
            self.recognizer = vosk.KaldiRecognizer(self.model, 16000)
        except Exception as e:
            print(f"Error inicializando Vosk: {e}")
            self.model = None

        # Estilo
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TLabel", background="#1e1e2e", foreground="white", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10, "bold"))

        # UI Components
        self.header = tk.Label(root, text="ARIA: Asistente TPM Offline", bg="#1e1e2e", fg="#89dceb", font=("Segoe UI", 16, "bold"))
        self.header.pack(pady=15)

        self.chat_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=60, height=15, bg="#313244", fg="white", font=("Segoe UI", 10), bd=0)
        self.chat_area.pack(padx=20, pady=10)
        self.chat_area.config(state=tk.DISABLED)

        self.input_frame = tk.Frame(root, bg="#1e1e2e")
        self.input_frame.pack(fill=tk.X, padx=20, pady=10)

        self.user_input = tk.Entry(self.input_frame, font=("Segoe UI", 11), bg="#45475a", fg="white", insertbackground="white", bd=1)
        self.user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)
        self.user_input.bind("<Return>", lambda e: self.process_input())

        self.mic_btn = tk.Button(self.input_frame, text="🎤", command=self.toggle_voice, bg="#f38ba8", fg="#1e1e2e", font=("Segoe UI", 12, "bold"), bd=0, padx=10)
        self.mic_btn.pack(side=tk.RIGHT, padx=5)

        self.send_btn = tk.Button(self.input_frame, text="Enviar", command=self.process_input, bg="#89b4fa", fg="#1e1e2e", activebackground="#b4befe", font=("Segoe UI", 10, "bold"), bd=0, padx=15)
        self.send_btn.pack(side=tk.RIGHT, padx=5)

        # --- Visualizador de Datos (Tabla Permanente) ---
        self.table_container = tk.LabelFrame(root, text=" Vista de Base de Datos (Filtro Automático) ", bg="#1e1e2e", fg="#a6e3a1", font=("Segoe UI", 9, "bold"))
        self.table_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)

        # Scrollbars
        self.tree_xscroll = tk.Scrollbar(self.table_container, orient=tk.HORIZONTAL)
        self.tree_xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree_yscroll = tk.Scrollbar(self.table_container, orient=tk.VERTICAL)
        self.tree_yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree = ttk.Treeview(self.table_container, 
                                 xscrollcommand=self.tree_xscroll.set, 
                                 yscrollcommand=self.tree_yscroll.set, 
                                 selectmode="browse")
        self.tree.pack(fill=tk.BOTH, expand=True)
        
        self.tree_xscroll.config(command=self.tree.xview)
        self.tree_yscroll.config(command=self.tree.yview)

        self.status_lbl = tk.Label(root, text=f"Total: {len(self.db.df) if self.db.df is not None else 0} registros. Pregunta algo para filtrar.", bg="#1e1e2e", fg="#a6adc8", font=("Segoe UI", 8))
        self.status_lbl.pack(pady=5)

        self.load_table_data() # Carga inicial completa
        self.say("Hola, soy ARIA. La base de datos está cargada. Pregúntame por cualquier máquina y filtraré los datos para ti.")

    def log(self, text, sender="ARIA"):
        self.chat_area.config(state=tk.NORMAL)
        self.chat_area.insert(tk.END, f"{sender}: {text}\n")
        self.chat_area.insert(tk.END, "-"*40 + "\n")
        self.chat_area.config(state=tk.DISABLED)
        self.chat_area.see(tk.END)
        self.root.update_idletasks() # Forzar actualización visual

    def say(self, text):
        self.log(text)
        threading.Thread(target=self._speak, args=(text,), daemon=True).start()

    def _speak(self, text):
        try:
            import pythoncom
            pythoncom.CoInitialize()
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            print(f"Error TTS: {e}")
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    # ─── Visualización de Tabla ─────────────────────────────────────────────
    def load_table_data(self, filtered_df=None):
        if self.db.df is None: return
        
        # Usar el dataframe filtrado o el completo
        df_to_show = filtered_df if filtered_df is not None else self.db.df
        
        # Configurar columnas (solo la primera vez o si cambian)
        self.tree["columns"] = list(df_to_show.columns)
        self.tree["show"] = "headings"
        
        for col in df_to_show.columns:
            self.tree.heading(col, text=col)
            # Ajustar ancho de columna
            self.tree.column(col, width=120, anchor="w")
            
        # Limpiar y cargar todos los registros
        for i in self.tree.get_children():
            self.tree.delete(i)
            
        for _, row in df_to_show.iterrows():
            # Convertir todos los valores a string para evitar errores en Treeview
            vals = [str(v) if pd.notna(v) else "" for v in row.values]
            self.tree.insert("", tk.END, values=vals)

        # Actualizar contador
        self.status_lbl.config(text=f"Mostrando {len(df_to_show)} de {len(self.db.df)} registros.")

    # ─── Control de Voz (Vosk) ──────────────────────────────────────────────
    def toggle_voice(self):
        if not self.model:
            messagebox.showwarning("Voz Offline", "El modelo de voz no está listo o no se pudo descargar.")
            return

        if self.is_listening:
            self.stop_listening()
        else:
            self.start_listening()

    def start_listening(self):
        self.is_listening = True
        self.mic_btn.config(bg="#a6e3a1", text="🛑") # Verde mientras escucha
        self.status_lbl.config(text="Escuchando... habla ahora.")
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def stop_listening(self):
        self.is_listening = False
        self.mic_btn.config(bg="#f38ba8", text="🎤")
        self.status_lbl.config(text=f"Base de datos: {EXCEL_PATH} lista.")

    def _listen_loop(self):
        def callback(indata, frames, time, status):
            if status: print(status)
            self.audio_queue.put(bytes(indata))

        try:
            with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype='int16',
                                  channels=1, callback=callback):
                while self.is_listening:
                    data = self.audio_queue.get()
                    if self.recognizer.AcceptWaveform(data):
                        result = json.loads(self.recognizer.Result())
                        text = result.get("text", "")
                        if text:
                            self.root.after(0, self.process_voice_text, text)
                            break # Detener tras la primera instrucción finalizada
        except Exception as e:
            print(f"Error en loop de audio: {e}")
            self.root.after(0, self.stop_listening)

    def process_voice_text(self, text):
        self.stop_listening()
        self.user_input.insert(0, text)
        self.process_input()

    # ─── Procesamiento de Comandos ──────────────────────────────────────────
    def process_input(self):
        query = self.user_input.get()
        if not query: return
        
        self.log(query, "Tú")
        self.user_input.delete(0, tk.END)
        
        response, filtered_df = self.db.query(query)
        self.say(response)
        
        if filtered_df is not None:
            self.load_table_data(filtered_df)

if __name__ == "__main__":
    if not os.path.exists(EXCEL_PATH):
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Error", f"No se encontró el archivo {EXCEL_PATH} en la carpeta actual.")
    else:
        root = tk.Tk()
        app = ARIAApp(root)
        root.mainloop()
