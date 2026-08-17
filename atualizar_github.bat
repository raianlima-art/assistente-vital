@echo off
title Enviar para o GitHub
color 0A

echo ==================================================
echo       SISTEMA VITAL - ATUALIZACAO NO GITHUB
echo ==================================================
echo.

:: Solicita a mensagem do commit para o usuario
set /p mensagem="Digite o que voce alterou (ou aperte Enter para enviar com mensagem padrao): "

:: Se o usuario nao digitar nada, usa uma mensagem padrao com a data e hora
if "%mensagem%"=="" set mensagem=Atualizacao automatica do sistema

echo.
echo [1/3] Adicionando os arquivos alterados...
git add .

echo.
echo [2/3] Salvando as alteracoes (Commit)...
git commit -m "%mensagem%"

echo.
echo [3/3] Enviando para a nuvem (Push)...
git push origin main

echo.
echo ==================================================
echo     CONCLUIDO! O STREAMLIT JA VAI ATUALIZAR.
echo ==================================================
pause