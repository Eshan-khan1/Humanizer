@echo off
setlocal EnableExtensions
title Humanizer — Setup models
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

if exist "models\humanizer-3b\gguf\Modelfile" (
  echo Creating humanizer-grammar / humanizer-writing from fine-tuned 3B Modelfile...
  pushd "models\humanizer-3b\gguf"
  ollama create humanizer-grammar -f Modelfile
  if exist Modelfile.writing (
    ollama create humanizer-writing -f Modelfile.writing
  ) else (
    ollama create humanizer-writing -f Modelfile
  )
  popd
) else if exist "models\humanizer-grammar\gguf\Modelfile" (
  echo Creating humanizer-grammar from local Modelfile...
  ollama create humanizer-grammar -f "models\humanizer-grammar\gguf\Modelfile"
  if exist "models\humanizer-grammar\gguf\Modelfile.writing" (
    ollama create humanizer-writing -f "models\humanizer-grammar\gguf\Modelfile.writing"
  )
) else (
  echo Pulling base models from Ollama Hub...
  ollama pull qwen2.5:0.5b
  ollama cp qwen2.5:0.5b humanizer-grammar
  ollama pull qwen2.5:3b-instruct
  ollama cp qwen2.5:3b-instruct humanizer-writing
)

echo.
echo Installed models:
ollama list
echo.
echo Done. Start the server with: start_server.bat
endlocal
exit /b 0
