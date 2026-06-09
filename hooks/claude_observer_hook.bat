@echo off
REM Claude Code Observer - Hook entry point
REM Usage: claude_observer_hook.bat <event_name>
REM Reads JSON from stdin, passes to Node.js helper

setlocal

set "EVENT_NAME=%~1"
if "%EVENT_NAME%"=="" (
    echo Usage: claude_observer_hook.bat event_name >&2
    exit /b 1
)

REM Debug logging - remove this block after confirming hooks work
set "LOGFILE=%USERPROFILE%\.claude-observer\hook_debug.log"
echo [%date% %time%] Hook called: %EVENT_NAME% >> "%LOGFILE%"

REM Find Node.js
where node >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo Node.js not found in PATH >&2
    echo [%date% %time%] ERROR: Node.js not found >> "%LOGFILE%"
    exit /b 1
)

REM Save stdin to temp file (batch can't pipe stdin reliably to node)
set "TMPFILE=%TEMP%\claude_observer_hook_%RANDOM%.json"
findstr /s .* > "%TMPFILE%"

REM Log stdin size for debugging
for %%A in ("%TMPFILE%") do echo [%date% %time%] stdin size: %%~zA bytes >> "%LOGFILE%"

REM Get helper script path (same directory as this bat file)
set "HELPER=%~dp0claude_observer_helper.js"

REM Run helper
node "%HELPER%" "%EVENT_NAME%" < "%TMPFILE%" 2>> "%LOGFILE%"
echo [%date% %time%] node exit: %ERRORLEVEL% >> "%LOGFILE%"

REM Cleanup
del "%TMPFILE%" >nul 2>nul

exit /b 0
