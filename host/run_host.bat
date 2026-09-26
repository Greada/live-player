@echo off
rem LivePlayer native messaging host launcher.
rem Runs the script with the trusted Python (pythonw.exe) so that no
rem self-built exe is needed (Smart App Control blocks unsigned exes).
setlocal
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%"
"%HERE%.venv\Scripts\pythonw.exe" -m liveplayer %*
endlocal
