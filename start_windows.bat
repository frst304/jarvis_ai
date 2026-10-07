@echo off
title J.A.R.V.I.S.
cd /d "%~dp0"
if not exist .venv (
  echo Installation de JARVIS (premiere fois, 1 a 2 minutes)...
  python -m venv .venv || (echo Python 3.10+ requis : https://www.python.org/downloads/ & pause & exit /b)
  .venv\Scripts\python -m pip install --upgrade pip >nul
  .venv\Scripts\pip install -r requirements.txt
)
if not exist .env copy .env.example .env >nul
.venv\Scripts\python run.py
pause
