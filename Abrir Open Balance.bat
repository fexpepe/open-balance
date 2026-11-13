@echo off
rem Duplo clique para abrir o painel. Feche esta janela para desligar.
cd /d "%~dp0"
title Open Balance
python --version >nul 2>nul
if errorlevel 1 goto py
python app.py
if errorlevel 1 pause
exit /b

:py
py -3 --version >nul 2>nul
if errorlevel 1 goto sem_python
py -3 app.py
if errorlevel 1 pause
exit /b

:sem_python
echo Python nao encontrado.
echo Instale em https://www.python.org/downloads/ marcando "Add python.exe to PATH" e abra de novo.
pause
