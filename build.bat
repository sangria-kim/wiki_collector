@echo off
rem Build WikiCollector.exe on Windows. Output: dist\WikiCollector.exe
rem config.json is created next to the exe on first run.
cd /d "%~dp0"

python -m pip install --upgrade tkinterdnd2 pyinstaller || goto :error
python test_wiki_collector.py || goto :error

rem --collect-all tkinterdnd2 bundles the native tkdnd library needed for drag and drop.
python -m PyInstaller --noconfirm --onefile --windowed --name WikiCollector --collect-all tkinterdnd2 wiki_collector.py || goto :error

echo.
echo Build OK: dist\WikiCollector.exe
exit /b 0

:error
echo.
echo Build FAILED
exit /b 1
