@echo off
REM Abre la interfaz grafica usando el entorno virtual del proyecto.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\pythonw.exe" main.py %*
) else (
    echo No existe .venv. Crealo con:  py -3.11 -m venv .venv
    echo y luego:  .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
)
