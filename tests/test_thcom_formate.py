"""THCOM08-Zeilen aus fremden Quellen (skiFFS, Chrono-Cross, ullr) und Sonderformate."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import swv_live_ranking as m
ok = []
def check(name, cond): ok.append(bool(cond)); print(("OK  " if cond else "FEHLER ") + name)
P = m.parse_thcom
i = P("TN         1  1        4.30700   365")
check("ohne Stunden und Minuten (Synchro 00:00)", i["kind"] == "time" and i["tod"] == 4.307 and i["seq"] == 1 and i["day"] == 365)
i = P("TN    1    3  1     12:34.50000  6994")
check("ohne Stunden", i["kind"] == "time" and i["tod"] == 754.5 and i["nr"] == 1)
i = P("TN    2    2 M1 19:30:58.41200  6994\t06B3")
check("normal mit Prüfsumme", i["kind"] == "time" and i["manual"] and i["ch"] == 1 and i["day"] == 6994)
i = P("TN         1 04 15:41:10.50000  9822")
check("TM550 ohne Nummer", i["nr"] == 0 and i["ch"] == 4)
i = P("TN 0012 0001 01 10:15:30.12300 06570")
check("skiFFS: Nullen aufgefüllt", i["nr"] == 12 and i["seq"] == 1 and i["ch"] == 1)
i = P("TN    5    7 01 10:00:00.00000")
check("ohne Tag", i["kind"] == "time" and i["day"] > 9000)
i = P("RR 0001 0012    00:01:23.45600 06570")
check("RR mit angehängtem Tag", i["kind"] == "result" and i["nr"] == 12 and abs(i["secs"] - 83.456) < 1e-6)
check("RR normal", P("RR    0    1           2.47700")["secs"] == 2.477)
check("IR benannt", P("IR 1    0012    00:00:41.20000")["label"] == "Zwischenzeit")
check("DR benannt", P("DR 0012 0013    00:00:00.41200")["kind"] == "note")
i = P("TN 0013 0003 04 00:00:00.00000 -0003")
check("Statuszeile kein Impuls", i["kind"] == "note")
check("Eingang 12", P("TN    1    1 12  9:05:01.00000  6994")["ch"] == 12)
i = P("TC           04 23:00:46.34000  9793")
check("TC ohne Zählnummer benannt, kein Impuls", i["kind"] == "note" and "ohne Zuordnung" in i["label"])
import time as _t
lt = _t.localtime(); tod = lt.tm_hour * 3600 + lt.tm_min * 60
today = m.day_from_pc(tod)
check("Tag vom PC", today == int(m.local_abs() // 86400))
check("Mitternacht: Uhrzeit 12 h+ voraus = Vortag", m.day_from_pc((tod + 13 * 3600) % 86400) in (today - 1, today))
print(f"{sum(ok)}/{len(ok)} OK"); sys.exit(0 if all(ok) else 1)
