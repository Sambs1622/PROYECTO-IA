"""
server.py
Servidor FastAPI que sirve el frontend y genera tokens LiveKit para los usuarios.
"""

import os
import uuid
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from dotenv import load_dotenv

import livekit.api as lk_api

# ─── Configuración ────────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LIVEKIT_URL    = os.getenv("LIVEKIT_URL", "wss://tu-proyecto.livekit.cloud")
LIVEKIT_API_KEY    = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")
SERVER_PORT    = int(os.getenv("SERVER_PORT", "8080"))
ROOM_NAME      = os.getenv("ROOM_NAME", "tpm-assistant")

FRONTEND_DIR = Path(__file__).parent / "frontend"

app = FastAPI(title="Asistente TPM - Token Server")


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/api/token")
async def get_token(user_id: str = None):
    """
    Genera un token de acceso LiveKit para que el usuario del frontend
    pueda unirse al room del asistente de voz.
    """
    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
        raise HTTPException(
            status_code=500,
            detail="LiveKit API keys no configuradas. Revisa el archivo .env"
        )

    identity = user_id or f"usuario-{uuid.uuid4().hex[:6]}"

    try:
        token = (
            lk_api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
            .with_identity(identity)
            .with_name("Usuario TPM")
            .with_grants(
                lk_api.VideoGrants(
                    room_join=True,
                    room=ROOM_NAME,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                )
            )
            .to_jwt()
        )

        logger.info(f"Token generado para: {identity} → room: {ROOM_NAME}")

        return JSONResponse({
            "token": token,
            "url": LIVEKIT_URL,
            "room": ROOM_NAME,
            "identity": identity,
        })

    except Exception as e:
        logger.error(f"Error generando token: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health():
    """Verificación de estado del servidor."""
    return {
        "status": "ok",
        "livekit_configured": bool(LIVEKIT_API_KEY and LIVEKIT_API_SECRET),
        "room": ROOM_NAME,
    }


# ─── Servir Frontend ──────────────────────────────────────────────────────────

@app.get("/")
async def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")

# Montar archivos estáticos del frontend
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Iniciando servidor en http://localhost:{SERVER_PORT}")
    logger.info(f"LiveKit URL: {LIVEKIT_URL}")
    logger.info(f"Room: {ROOM_NAME}")
    uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT, log_level="info")
