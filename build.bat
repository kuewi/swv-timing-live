@echo off
REM Build SWV_LiveRanking.exe (Windows). Logo-Dateien im selben Ordner ablegen.
cd /d "%~dp0"

echo Installiere Module ...
python -m pip install --upgrade pyserial pyinstaller
if errorlevel 1 (
    echo.
    echo FEHLER: pyserial oder PyInstaller konnte nicht installiert werden. Internetverbindung pruefen.
    pause
    exit /b 1
)
REM Optional: Startlisten, Excel-Export und QR-Code funktionieren auch ohne diese Module
python -m pip install --upgrade "xlrd>=2.0.1" openpyxl

echo Pruefe Module ...
python -c "import serial, PyInstaller; print('Pflichtmodule vorhanden')"
if errorlevel 1 (
    echo.
    echo FEHLER: pyserial oder PyInstaller fehlt. Die .exe wird nicht gebaut.
    pause
    exit /b 1
)

set DATA=
if exist swv_logo.png set DATA=%DATA% --add-data "swv_logo.png;."
if exist logo.png set DATA=%DATA% --add-data "logo.png;."
set ICON=--icon assets\swv_logo.ico
set DATA=%DATA% --add-data "assets;assets"

python -m pip install --upgrade pillow
python tools\make_version_file.py version_info.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed --name SWV_LiveRanking ^
    --version-file version_info.txt --hidden-import xlrd --hidden-import openpyxl --hidden-import PIL.ImageGrab ^
    %ICON% %DATA% swv_live_ranking.py
if errorlevel 1 (
    echo.
    echo FEHLER: PyInstaller konnte die .exe nicht bauen.
    pause
    exit /b 1
)

echo.
echo Fertig: dist\SWV_LiveRanking.exe
pause
