"""Schreibt die Versionsinfo fuer PyInstaller (--version-file) aus APP_VERSION in swv_live_ranking.py.
Damit stehen Version und Name in den Dateieigenschaften der .exe."""
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(HERE, "swv_live_ranking.py"), encoding="utf-8").read()
ver = re.search(r'^APP_VERSION = "([0-9.]+)"', src, re.M).group(1)
parts = [int(x) for x in ver.split(".")] + [0] * 4
t = tuple(parts[:4])
out = sys.argv[1] if len(sys.argv) > 1 else "version_info.txt"
text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040704b0', [
      StringStruct('CompanyName', 'Stefan Küng'),
      StringStruct('FileDescription', 'SWV Live-Ranking für TAG Heuer CP 545'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', 'SWV_LiveRanking'),
      StringStruct('LegalCopyright', 'MIT-Lizenz'),
      StringStruct('OriginalFilename', 'SWV_LiveRanking.exe'),
      StringStruct('ProductName', 'SWV Live-Ranking'),
      StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [0x0407, 1200])])
  ]
)
"""
open(out, "w", encoding="utf-8").write(text)
print(f"Versionsinfo {ver} -> {out}")
