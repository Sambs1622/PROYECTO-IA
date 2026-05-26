"""
agent.py
Agente ARIA — Asistente de Voz TPM con LiveKit Agents v1.5+
Pipeline: STT (Deepgram español) → LLM (Gemini) → TTS (OpenAI)
"""

import asyncio
import logging
import os
from typing import Annotated

from dotenv import load_dotenv

from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    function_tool,
    RunContext,
)
from livekit.protocol import message_models
from livekit.plugins import deepgram, google, openai, silero

from tpm_knowledge import TPMKnowledgeBase

# ─── Configuración ────────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EXCEL_PATH = os.path.join(os.path.dirname(__file__), "DATOS TPM.xlsx")

# Carga la base de datos al inicio (una sola vez, en memoria)
logger.info("Iniciando base de conocimiento TPM...")
knowledge_base = TPMKnowledgeBase(EXCEL_PATH)
logger.info(f"Base de conocimiento lista: {knowledge_base.stats['total_registros']} registros.")


# ─── Herramientas del Agente (Tools) ─────────────────────────────────────────

@function_tool
async def consultar_maquina(
    ctx: RunContext,
    maquina: Annotated[str, "Nombre de la máquina a consultar. Ejemplos: 'SELLADORA 3', 'EXTRUSORA 1', 'IMPRESORA', 'MEZCLADORA'"],
) -> str:
    """
    Consulta todos los mantenimientos de una máquina específica.
    Retorna estadísticas, tipos de falla y últimos casos registrados.
    Usa esta herramienta cuando pregunten por una máquina en particular.
    """
    logger.info(f"[Tool] consultar_maquina: {maquina}")
    return knowledge_base.query_by_machine(maquina)


@function_tool
async def consultar_tecnico(
    ctx: RunContext,
    tecnico: Annotated[str, "Nombre o apellido del técnico. Ejemplos: 'ORTEGA', 'BAUTISTA', 'FLOREZ', 'DUARTE', 'SILVA'"],
) -> str:
    """
    Consulta las intervenciones de un técnico de mantenimiento específico.
    Retorna cuántos casos atendió, qué máquinas y cuántos están abiertos.
    Usa esta herramienta cuando pregunten por un técnico específico.
    """
    logger.info(f"[Tool] consultar_tecnico: {tecnico}")
    return knowledge_base.query_by_technician(tecnico)


@function_tool
async def obtener_casos_abiertos(ctx: RunContext) -> str:
    """
    Retorna todos los casos de mantenimiento actualmente ABIERTOS (pendientes de solución).
    Usa esta herramienta cuando pregunten por casos pendientes, sin resolver o abiertos.
    """
    logger.info("[Tool] obtener_casos_abiertos")
    return knowledge_base.get_open_cases()


@function_tool
async def obtener_estadisticas(ctx: RunContext) -> str:
    """
    Retorna estadísticas generales de toda la base de datos TPM: totales por estado,
    máquinas con más fallas y técnicos más activos.
    Usa esta herramienta para preguntas generales como cuántos mantenimientos hay,
    cuál máquina falla más, o cuál técnico atiende más casos.
    """
    logger.info("[Tool] obtener_estadisticas")
    return knowledge_base.get_statistics()


@function_tool
async def buscar_descripcion(
    ctx: RunContext,
    palabra_clave: Annotated[str, "Palabra o frase a buscar en descripciones, acciones y repuestos. Ejemplos: 'teflon', 'cuchilla', 'motor', 'rodamiento'"],
) -> str:
    """
    Busca registros cuya descripción del problema, acción tomada o repuestos
    contengan una palabra clave específica.
    Usa esta herramienta cuando pregunten por un componente, tipo de problema o repuesto específico.
    """
    logger.info(f"[Tool] buscar_descripcion: {palabra_clave}")
    return knowledge_base.search_by_description(palabra_clave)


@function_tool
async def consultar_por_fechas(
    ctx: RunContext,
    fecha_inicio: Annotated[str, "Fecha de inicio del rango en formato DD/MM/YYYY o YYYY-MM-DD"],
    fecha_fin: Annotated[str, "Fecha de fin del rango en formato DD/MM/YYYY o YYYY-MM-DD"],
) -> str:
    """
    Filtra mantenimientos en un rango de fechas específico.
    Usa esta herramienta cuando pregunten por mantenimientos en un mes, trimestre o período.
    """
    logger.info(f"[Tool] consultar_por_fechas: {fecha_inicio} a {fecha_fin}")
    return knowledge_base.query_by_date_range(fecha_inicio, fecha_fin)


# ─── Clase del Agente ARIA ────────────────────────────────────────────────────

class ARIAAgent(Agent):
    """
    ARIA — Asistente de Reconocimiento Industrial Autónomo
    Especialista en consultas de mantenimiento TPM.
    """

    def __init__(self):
        super().__init__(
            instructions=f"""Eres ARIA, un asistente experto en mantenimiento industrial TPM (Total Productive Maintenance).
Trabajas para una empresa de manufactura y tienes acceso completo a la base de datos de órdenes de mantenimiento.

{knowledge_base.get_system_context()}

COMPORTAMIENTO:
- Responde SIEMPRE en español, de forma clara, directa y profesional
- Cuando el usuario haga una pregunta sobre datos, SIEMPRE usa las herramientas disponibles para consultar la base de datos exacta
- Da respuestas concisas (2-4 oraciones para respuestas de voz), no hagas listas largas a menos que sea necesario
- Si no entiendes la pregunta, pide aclaración de forma amable
- Puedes mantener una conversación natural sobre mantenimiento industrial
- Cuando mentions números, exprésalos de forma natural para voz (no uses formatos complejos)

CAPACIDADES (usa las herramientas disponibles):
- Consultar mantenimientos por máquina específica → usa consultar_maquina
- Consultar por técnico → usa consultar_tecnico  
- Ver casos abiertos/pendientes → usa obtener_casos_abiertos
- Estadísticas generales → usa obtener_estadisticas
- Buscar por componente o repuesto → usa buscar_descripcion
- Filtrar por rango de fechas → usa consultar_por_fechas

SALUDO INICIAL:
Preséntate brevemente como ARIA y menciona que tienes acceso a {knowledge_base.stats['total_registros']} registros de mantenimiento.
""",
            stt=deepgram.STT(language="es", model="nova-2-general"),
            llm=google.LLM(model="gemini-2.0-flash"),
            tts=openai.TTS(voice="alloy"),
            vad=silero.VAD.load(),
            tools=[
                consultar_maquina,
                consultar_tecnico,
                obtener_casos_abiertos,
                obtener_estadisticas,
                buscar_descripcion,
                consultar_por_fechas,
            ],
        )
        self.llm = google.LLM(model="gemini-2.0-flash")
        self.fnc_ctx = self._tools 
        self.chat_ctx = openai.ChatContext().append(role="system", text=self._instructions)

    async def on_enter(self) -> None:
        """Se llama cuando el agente entra al room y está listo."""
        await self.session.say(
            f"Hola, soy ARIA, tu asistente de mantenimiento TPM. "
            f"Tengo acceso a {knowledge_base.stats['total_registros']} órdenes de mantenimiento. "
            f"¿En qué puedo ayudarte?",
            allow_interruptions=True,
        )


# ─── Punto de entrada del agente ──────────────────────────────────────────────

async def entrypoint(ctx: JobContext):
    """Función principal del worker LiveKit."""
    logger.info(f"Nueva sesión iniciada. Room: {ctx.room.name}")

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    session = AgentSession()
    agent = ARIAAgent()

    await session.start(
        agent=agent,
        room=ctx.room,
    )

    # ─── Manejo de Comandos de Texto (Chat) ──────────────────────────────────
    @ctx.room.on("data_received")
    def on_data_received(data_received: message_models.DataPacket):
        if data_received.topic == "chat":
            text = data_received.data.decode("utf-8")
            logger.info(f"Comando de texto recibido: {text}")
            
            asyncio.create_task(process_text_command(ctx, agent, text))

async def process_text_command(ctx: JobContext, agent: ARIAAgent, text: str):
    """
    Procesa un comando de texto usando el mismo LLM y herramientas que la voz.
    """
    try:
        # Usar el LLM del agente para procesar el texto
        # Nota: Usamos el chat del LLM directamente
        chat_ctx = agent.chat_ctx.copy()
        chat_ctx.append(role="user", text=text)

        # Crear un stream para procesar con herramientas
        stream = agent.llm.chat(
            chat_ctx=chat_ctx,
            fnc_ctx=agent.fnc_ctx, # Esto contiene las herramientas (tools)
        )

        full_response = ""
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                full_response += chunk.choices[0].delta.content

        if full_response:
            logger.info(f"Respuesta de texto generada: {full_response}")
            # Enviar la respuesta de vuelta al frontend
            await ctx.room.local_participant.publish_data(
                full_response.encode("utf-8"),
                topic="chat-response"
            )
            
            # También podemos hacer que el agente lo DIGA si queremos, 
            # pero el usuario pidió "ver los datos", así que texto es primordial.
            # await agent.say(full_response) 

    except Exception as e:
        logger.error(f"Error procesando comando de texto: {e}")
        await ctx.room.local_participant.publish_data(
            f"Lo siento, hubo un error al procesar tu solicitud: {str(e)}".encode("utf-8"),
            topic="chat-response"
        )


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="aria-tpm",
        )
    )
