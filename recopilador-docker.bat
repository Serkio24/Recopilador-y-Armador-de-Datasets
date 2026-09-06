@echo off
REM Ejecuta el CLI dentro del contenedor. Equivalente a recopilador.bat, pero
REM sin ventana: la interfaz grafica se sigue abriendo con recopilador.bat.
REM
REM   recopilador-docker.bat --cli --tema "pesca artesanal" --n 50
REM   recopilador-docker.bat --analizar --exportar
REM   recopilador-docker.bat --exportar-csv --tema "pesca artesanal"
cd /d "%~dp0"
docker compose run --rm app %*
