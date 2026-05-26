"""
tpm_knowledge.py
Motor de conocimiento para la base de datos de mantenimiento TPM.
Carga el Excel, calcula estadísticas y expone funciones de consulta para el LLM.
"""

import pandas as pd
from datetime import datetime, date
from typing import Optional
import os
import logging

logger = logging.getLogger(__name__)

# ─── Rutas ────────────────────────────────────────────────────────────────────
EXCEL_PATH = os.path.join(os.path.dirname(__file__), "DATOS TPM.xlsx")
SHEET_NAME = "SEGUIMIENTO TPM xlsx"

# Nombres de columna normalizados (posicionales)
COLS = [
    "tpm_num", "reportado_por", "hora_reporte", "fecha_reporte",
    "maquina", "tipo_falla", "descripcion", "hora_inicio",
    "hora_fin", "fecha_intervencion", "tipo_intervencion",
    "accion_tomada", "repuestos", "insumos", "tecnico",
    "estado", "tiempo_intervencion", "fecha_hora_inicio",
    "fecha_hora_fin", "tiempo_total"
]


class TPMKnowledgeBase:
    """
    Carga y gestiona los datos de mantenimiento TPM.
    Provee métodos de consulta estructurados para el agente de voz.
    """

    def __init__(self, excel_path: str = EXCEL_PATH, sheet_name: str = SHEET_NAME):
        logger.info(f"Cargando base de datos TPM desde: {excel_path}")
        self.df = self._load_data(excel_path, sheet_name)
        self.stats = self._compute_stats()
        logger.info(f"Base de datos cargada: {len(self.df)} registros válidos")

    # ──────────────────────────────────────────────────────────────────────────
    # CARGA Y LIMPIEZA
    # ──────────────────────────────────────────────────────────────────────────

    def _load_data(self, path: str, sheet: str) -> pd.DataFrame:
        """Carga el Excel y limpia los datos."""
        df = pd.read_excel(path, sheet_name=sheet, header=0)

        # Asignar nombres de columna limpios (primeras 20 columnas)
        num_cols = min(len(df.columns), len(COLS))
        col_map = {df.columns[i]: COLS[i] for i in range(num_cols)}
        df = df.rename(columns=col_map)

        # Conservar solo las columnas conocidas
        df = df[[c for c in COLS if c in df.columns]]

        # Filtrar filas de encabezado repetido y filas vacías
        df = df[pd.notna(df["tpm_num"])]
        df = df[~df["tpm_num"].astype(str).str.contains("TPM|#", na=False)]
        df = df[df["tpm_num"] != ""]

        # Convertir número TPM a entero donde sea posible
        df["tpm_num"] = pd.to_numeric(df["tpm_num"], errors="coerce")
        df = df[df["tpm_num"].notna()]

        # Limpiar strings
        for col in ["maquina", "tipo_falla", "estado", "tecnico", "tipo_intervencion"]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip().str.upper()

        # Normalizar estado
        df["estado"] = df["estado"].replace({
            "CERRADA": "CERRADA",
            "ABIERTA": "ABIERTA",
            "ANULADA": "ANULADA",
        })

        # Normalizar tipo de falla
        df["tipo_falla"] = df["tipo_falla"].replace({
            "PUNTUAL": "PUNTUAL",
            "REPETITIVA": "REPETITIVA",
            "REPETITIVO": "REPETITIVA",
        })

        # Fecha de reporte como datetime
        df["fecha_reporte"] = pd.to_datetime(df["fecha_reporte"], errors="coerce")

        return df.reset_index(drop=True)

    # ──────────────────────────────────────────────────────────────────────────
    # ESTADÍSTICAS GLOBALES
    # ──────────────────────────────────────────────────────────────────────────

    def _compute_stats(self) -> dict:
        """Calcula estadísticas globales de la base de datos."""
        df = self.df

        # Conteo por estado
        estado_counts = df["estado"].value_counts().to_dict()

        # Top máquinas
        top_maquinas = (
            df[~df["maquina"].isin(["NA", "OTRO", "NAN", "MÁQUINA", "MAQUINA"])]
            .groupby("maquina")
            .size()
            .sort_values(ascending=False)
            .head(15)
            .to_dict()
        )

        # Top técnicos
        top_tecnicos = (
            df[~df["tecnico"].isin(["NA", "NAN"])]
            .groupby("tecnico")
            .size()
            .sort_values(ascending=False)
            .head(10)
            .to_dict()
        )

        # Tipo de falla
        tipo_falla_counts = (
            df[~df["tipo_falla"].isin(["NA", "NAN", "TIPO FALLA"])]
            .groupby("tipo_falla")
            .size()
            .to_dict()
        )

        # Tipo de intervención
        tipo_intervencion = (
            df[~df["tipo_intervencion"].isin(["NA", "NAN"])]
            .groupby("tipo_intervencion")
            .size()
            .sort_values(ascending=False)
            .to_dict()
        )

        # Rango de fechas
        fechas_validas = df["fecha_reporte"].dropna()
        fecha_min = fechas_validas.min() if not fechas_validas.empty else None
        fecha_max = fechas_validas.max() if not fechas_validas.empty else None

        return {
            "total_registros": len(df),
            "estados": estado_counts,
            "top_maquinas": top_maquinas,
            "top_tecnicos": top_tecnicos,
            "tipo_falla": tipo_falla_counts,
            "tipo_intervencion": tipo_intervencion,
            "fecha_inicio": str(fecha_min.date()) if fecha_min else "desconocida",
            "fecha_fin": str(fecha_max.date()) if fecha_max else "desconocida",
        }

    # ──────────────────────────────────────────────────────────────────────────
    # CONTEXTO PARA EL LLM
    # ──────────────────────────────────────────────────────────────────────────

    def get_system_context(self) -> str:
        """
        Genera el texto de contexto que se inyecta en el system prompt del LLM.
        Incluye estadísticas clave y la estructura de datos disponible.
        """
        s = self.stats

        # Formatear top máquinas
        maquinas_str = "\n".join(
            f"  - {m}: {c} casos" for m, c in s["top_maquinas"].items()
        )

        # Formatear top técnicos
        tecnicos_str = "\n".join(
            f"  - {t}: {c} intervenciones" for t, c in s["top_tecnicos"].items()
        )

        # Formatear estados
        estados_str = ", ".join(
            f"{k}: {v}" for k, v in s["estados"].items()
        )

        # Formatear tipos de falla
        fallas_str = ", ".join(
            f"{k}: {v}" for k, v in s["tipo_falla"].items()
        )

        # Formatear tipos de intervención
        interv_str = ", ".join(
            f"{k}: {v}" for k, v in s["tipo_intervencion"].items()
        )

        return f"""
=== BASE DE DATOS DE MANTENIMIENTO TPM ===

RESUMEN GENERAL:
- Total de registros: {s['total_registros']} órdenes de mantenimiento
- Período cubierto: desde {s['fecha_inicio']} hasta {s['fecha_fin']}
- Estados: {estados_str}
- Tipos de falla: {fallas_str}
- Tipos de intervención: {interv_str}

MÁQUINAS CON MÁS INTERVENCIONES:
{maquinas_str}

TÉCNICOS CON MÁS INTERVENCIONES:
{tecnicos_str}

COLUMNAS DISPONIBLES EN LA BASE DE DATOS:
- #TPM: Número de orden de mantenimiento
- Reportado por: Nombre del operario que reportó
- Hora y fecha de reporte
- Máquina: Equipo intervenido
- Tipo de falla: PUNTUAL o REPETITIVA
- Descripción: Descripción del problema
- Hora inicio/fin de intervención
- Fecha de intervención
- Tipo de intervención: Mecánica, Eléctrica, etc.
- Acción tomada: Lo que se hizo para resolver
- Repuestos usados
- Insumos utilizados
- Técnico encargado
- Estado: ABIERTA, CERRADA o ANULADA

INSTRUCCIONES:
- Tienes acceso a funciones de consulta que puedes llamar para obtener datos específicos
- Cuando te pregunten por una máquina, usa la función consultar_maquina
- Cuando te pregunten por un técnico, usa consultar_tecnico
- Cuando necesites buscar por descripción, usa buscar_descripcion
- Para casos abiertos, usa obtener_casos_abiertos
- Para estadísticas generales, usa obtener_estadisticas
- Responde siempre en español, de forma clara y directa
"""

    # ──────────────────────────────────────────────────────────────────────────
    # FUNCIONES DE CONSULTA
    # ──────────────────────────────────────────────────────────────────────────

    def query_by_machine(self, maquina: str) -> str:
        """Retorna información de mantenimientos para una máquina específica."""
        df = self.df
        mascara = df["maquina"].str.contains(maquina.upper(), na=False, regex=False)
        resultado = df[mascara]

        if resultado.empty:
            # Búsqueda más flexible
            for m in df["maquina"].unique():
                if maquina.upper() in m or m in maquina.upper():
                    mascara = df["maquina"] == m
                    resultado = df[mascara]
                    break

        if resultado.empty:
            return f"No se encontraron registros para la máquina '{maquina}'. Máquinas disponibles: {', '.join(self.stats['top_maquinas'].keys())}"

        total = len(resultado)
        abiertos = len(resultado[resultado["estado"] == "ABIERTA"])
        cerrados = len(resultado[resultado["estado"] == "CERRADA"])

        # Tipo de falla breakdown
        fallas = resultado["tipo_falla"].value_counts().to_dict()
        fallas_str = ", ".join(f"{k}: {v}" for k, v in fallas.items() if k not in ["NA", "NAN"])

        # Últimos 5 registros
        ultimos = resultado.sort_values("tpm_num", ascending=False).head(5)
        ultimos_str = ""
        for _, row in ultimos.iterrows():
            fecha = str(row.get("fecha_reporte", ""))[:10] if pd.notna(row.get("fecha_reporte")) else "N/A"
            desc = str(row.get("descripcion", ""))[:80] if pd.notna(row.get("descripcion")) else "N/A"
            tecnico = str(row.get("tecnico", "N/A"))
            estado = str(row.get("estado", "N/A"))
            ultimos_str += f"\n  • TPM#{int(row['tpm_num'])} [{fecha}] {estado} - {desc} (Téc: {tecnico})"

        return f"""MÁQUINA: {maquina.upper()}
Total de mantenimientos: {total}
  - Cerrados: {cerrados} | Abiertos: {abiertos}
Tipos de falla: {fallas_str}
Últimos registros:{ultimos_str}"""

    def query_by_technician(self, tecnico: str) -> str:
        """Retorna información de intervenciones por un técnico específico."""
        df = self.df
        mascara = df["tecnico"].str.contains(tecnico.upper(), na=False, regex=False)
        resultado = df[mascara]

        if resultado.empty:
            return f"No se encontraron registros para el técnico '{tecnico}'. Técnicos disponibles: {', '.join(self.stats['top_tecnicos'].keys())}"

        total = len(resultado)
        abiertos = len(resultado[resultado["estado"] == "ABIERTA"])

        # Máquinas que atendió
        maquinas = resultado["maquina"].value_counts().head(5).to_dict()
        maquinas_str = ", ".join(f"{m}: {c}" for m, c in maquinas.items() if m not in ["NA", "NAN"])

        return f"""TÉCNICO: {tecnico.upper()}
Total de intervenciones: {total}
Casos abiertos pendientes: {abiertos}
Máquinas que más atiende: {maquinas_str}"""

    def get_open_cases(self) -> str:
        """Retorna los casos de mantenimiento actualmente abiertos."""
        df = self.df
        abiertos = df[df["estado"] == "ABIERTA"].sort_values("tpm_num", ascending=False)

        if abiertos.empty:
            return "No hay casos abiertos en este momento. ✅"

        total = len(abiertos)
        casos_str = ""
        for _, row in abiertos.head(10).iterrows():
            fecha = str(row.get("fecha_reporte", ""))[:10] if pd.notna(row.get("fecha_reporte")) else "N/A"
            maquina = str(row.get("maquina", "N/A"))
            desc = str(row.get("descripcion", ""))[:60] if pd.notna(row.get("descripcion")) else "N/A"
            tecnico = str(row.get("tecnico", "N/A"))
            casos_str += f"\n  • TPM#{int(row['tpm_num'])} - {maquina} [{fecha}] {desc} (Téc: {tecnico})"

        suffix = f"\n  ... y {total - 10} más." if total > 10 else ""
        return f"""CASOS ABIERTOS: {total} órdenes pendientes{casos_str}{suffix}"""

    def get_statistics(self) -> str:
        """Retorna estadísticas generales de la base de datos TPM."""
        s = self.stats

        maquinas_str = "\n".join(
            f"  {i+1}. {m}: {c} casos"
            for i, (m, c) in enumerate(s["top_maquinas"].items())
        )

        tecnicos_str = "\n".join(
            f"  {i+1}. {t}: {c} intervenciones"
            for i, (t, c) in enumerate(list(s["top_tecnicos"].items())[:5])
        )

        estados_str = "\n".join(
            f"  - {k}: {v}" for k, v in s["estados"].items()
        )

        fallas_str = ", ".join(
            f"{k}: {v}" for k, v in s["tipo_falla"].items()
        )

        return f"""ESTADÍSTICAS GENERALES TPM
Total de órdenes: {s['total_registros']}
Período: {s['fecha_inicio']} al {s['fecha_fin']}

Estados:
{estados_str}

Tipos de falla: {fallas_str}

Máquinas con más intervenciones:
{maquinas_str}

Técnicos más activos:
{tecnicos_str}"""

    def search_by_description(self, keyword: str) -> str:
        """Busca registros cuya descripción o acción tomada contenga la palabra clave."""
        df = self.df
        kw = keyword.upper()
        mascara = (
            df["descripcion"].astype(str).str.upper().str.contains(kw, na=False) |
            df["accion_tomada"].astype(str).str.upper().str.contains(kw, na=False) |
            df["repuestos"].astype(str).str.upper().str.contains(kw, na=False)
        )
        resultado = df[mascara]

        if resultado.empty:
            return f"No se encontraron registros que mencionen '{keyword}'."

        total = len(resultado)
        casos_str = ""
        for _, row in resultado.head(5).iterrows():
            fecha = str(row.get("fecha_reporte", ""))[:10] if pd.notna(row.get("fecha_reporte")) else "N/A"
            maquina = str(row.get("maquina", "N/A"))
            desc = str(row.get("descripcion", ""))[:70] if pd.notna(row.get("descripcion")) else "N/A"
            accion = str(row.get("accion_tomada", ""))[:70] if pd.notna(row.get("accion_tomada")) else "N/A"
            casos_str += f"\n  • TPM#{int(row['tpm_num'])} - {maquina} [{fecha}]\n    Problema: {desc}\n    Acción: {accion}"

        suffix = f"\n  ... y {total - 5} más." if total > 5 else ""
        return f"""Búsqueda: '{keyword}' — {total} resultado(s){casos_str}{suffix}"""

    def query_by_date_range(self, fecha_inicio: str, fecha_fin: str) -> str:
        """Filtra registros en un rango de fechas."""
        try:
            fi = pd.to_datetime(fecha_inicio, dayfirst=True)
            ff = pd.to_datetime(fecha_fin, dayfirst=True)
        except Exception:
            return f"Formato de fecha inválido. Use DD/MM/YYYY o YYYY-MM-DD."

        df = self.df
        mascara = (df["fecha_reporte"] >= fi) & (df["fecha_reporte"] <= ff)
        resultado = df[mascara]

        if resultado.empty:
            return f"No hay registros entre {fecha_inicio} y {fecha_fin}."

        total = len(resultado)
        abiertos = len(resultado[resultado["estado"] == "ABIERTA"])
        cerrados = len(resultado[resultado["estado"] == "CERRADA"])

        maquinas = resultado["maquina"].value_counts().head(5).to_dict()
        maquinas_str = ", ".join(f"{m}: {c}" for m, c in maquinas.items() if m not in ["NA", "NAN"])

        return f"""Período: {fecha_inicio} a {fecha_fin}
Total de órdenes: {total}
  - Cerradas: {cerrados} | Abiertas: {abiertos}
Máquinas más activas: {maquinas_str}"""


# ─── Test rápido ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    kb = TPMKnowledgeBase()
    print("=" * 60)
    print(kb.get_statistics())
    print("=" * 60)
    print(kb.get_open_cases())
    print("=" * 60)
    print(kb.query_by_machine("SELLADORA 3"))
