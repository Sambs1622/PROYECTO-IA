@echo off
REM ============================================================
REM  ARIA - Asistente de Voz TPM
REM  Script de arranque automático
REM ============================================================

echo.
echo  ========================================
echo   ARIA - Asistente de Voz TPM
echo  ========================================
echo.

REM Verificar que existe el archivo .env
if not exist ".env" (
    echo  [ERROR] No se encontro el archivo .env
    echo  Por favor copia .env.example a .env y completa las API keys
    echo.
    echo  Instrucciones:
    echo  1. Copia .env.example a .env
    echo  2. Abre .env y agrega tus API keys
    echo  3. Vuelve a ejecutar este script
    echo.
    pause
    exit /b 1
)

echo  [OK] Archivo .env encontrado
echo.

REM Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python no encontrado. Instala Python 3.11+
    pause
    exit /b 1
)

echo  [OK] Python disponible
echo.

REM Instalar dependencias si es necesario
echo  Verificando dependencias...
pip install -r requirements.txt -q
echo  [OK] Dependencias verificadas
echo.

REM Iniciar el Servidor FastAPI (tokens + frontend)
echo  Iniciando servidor web en http://localhost:8080 ...
start "Servidor TPM" python server.py

REM Esperar 2 segundos para que el servidor arranque
timeout /t 2 /nobreak >nul

REM Iniciar el Agente LiveKit
echo  Iniciando agente de voz ARIA...
echo  (Presiona Ctrl+C para detener)
echo.
start "Agente ARIA" python agent.py dev

REM Esperar 3 segundos y abrir el navegador
timeout /t 3 /nobreak >nul
echo  Abriendo interfaz en el navegador...
start http://localhost:8080

echo.
echo  ========================================
echo   Sistema iniciado correctamente!
echo   Abre http://localhost:8080 si no se abrio
echo  ========================================
echo.
pause
