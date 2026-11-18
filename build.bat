@echo off
REM Build SWV_LiveRanking.exe (Windows). Logo-Dateien im selben Ordner ablegen.
cd /d "%~dp0"
python -m pip install --upgrade pyserial pyinstaller

set DATA=
if exist swv_logo.png set DATA=%DATA% --add-data "swv_logo.png;."
if exist logo.png set DATA=%DATA% --add-data "logo.png;."
set ICON=
if exist swv_logo.ico set ICON=--icon swv_logo.ico

python -m PyInstaller --noconfirm --clean --onefile --windowed --name SWV_LiveRanking %ICON% %DATA% swv_live_ranking.py

echo.
echo Fertig: dist\SWV_LiveRanking.exe
pause
