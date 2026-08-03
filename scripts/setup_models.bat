@echo off
setlocal EnableExtensions
title Thoth — Setup models
cd /d "%~dp0.."

where ollama >nul 2>&1
if errorlevel 1 (
  echo ERROR: Install Ollama from https://ollama.com and reopen this window.
  exit /b 1
)

curl -sf http://127.0.0.1:11434/api/tags >nul 2>&1
if errorlevel 1 (
  echo ERROR: Ollama is not running. Open the Ollama app from the Start menu, wait a few seconds, then try again.
  exit /b 1
)

if exist "models\thoth-3b\gguf\Modelfile" (
  echo Creating thoth-grammar / thoth-writing from fine-tuned 3B Modelfile...
  pushd "models\thoth-3b\gguf"
  ollama create thoth-grammar -f Modelfile
  if exist Modelfile.writing (
    ollama create thoth-writing -f Modelfile.writing
  ) else (
    ollama create thoth-writing -f Modelfile
  )
  popd
) else if exist "models\thoth-grammar\gguf\Modelfile" (
  echo Creating thoth-grammar from local Modelfile...
  ollama create thoth-grammar -f "models\thoth-grammar\gguf\Modelfile"
  if exist "models\thoth-grammar\gguf\Modelfile.writing" (
    ollama create thoth-writing -f "models\thoth-grammar\gguf\Modelfile.writing"
  )
) else (
  echo Pulling base models from Ollama Hub...
  ollama pull qwen2.5:0.5b
  ollama cp qwen2.5:0.5b thoth-grammar
  ollama pull qwen2.5:3b-instruct
  ollama cp qwen2.5:3b-instruct thoth-writing
)

echo.
echo Installed models:
ollama list
echo.
echo Done. Start the server with: start_server.bat
endlocal
exit /b 0
