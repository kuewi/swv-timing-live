"""PDF aus docs/handbuch/*.md: SWV_Live-Ranking_Benutzerhandbuch.pdf und SWV_Live-Ranking_Training.pdf.
Nur bei «update Doku» laufen lassen, nach tools/doku_screenshots.py.
Braucht: python-markdown, Google Chrome oder Chromium (headless), pypdf, reportlab."""
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata

import markdown
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "handbuch")
VERSION = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', open(os.path.join(ROOT, "swv_live_ranking.py"),
                    encoding="utf-8").read(), re.M).group(1)
DOCS = (("benutzerhandbuch.md", f"SWV_Live-Ranking_Benutzerhandbuch_v{VERSION}.pdf", "Benutzerhandbuch"),
        ("training.md", f"SWV_Live-Ranking_Training_v{VERSION}.pdf", "Training"))
REPO = "https://github.com/kuewi/swv-timing-live/blob/main/"

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
body { font-family: "Inter", "Segoe UI", "DejaVu Sans", sans-serif; font-size: 10.5pt; line-height: 1.45;
       color: #1d1d1f; }
h1 { font-size: 24pt; margin: 0 0 4mm 0; color: #0b5fbf; }
h2 { font-size: 15pt; margin: 9mm 0 3mm 0; padding-bottom: 1.5mm; border-bottom: 1.5px solid #0b5fbf;
     color: #0b5fbf; break-after: avoid; }
h2.neu { break-before: page; margin-top: 0; }
h3 { font-size: 12pt; margin: 6mm 0 2mm 0; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
table { border-collapse: collapse; width: 100%; margin: 2mm 0 4mm 0; font-size: 9.5pt; break-inside: auto; }
tr { break-inside: avoid; }
th { background: #e8eef7; text-align: left; }
th, td { border: 1px solid #c8ced8; padding: 1.4mm 2mm; vertical-align: top; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 9pt; background: #f1f2f4; padding: 0 1mm;
       border-radius: 1mm; }
img { max-width: 100%; max-height: 100mm; display: block; margin: 2mm auto 1mm auto; border: 1px solid #c8ced8;
      border-radius: 2mm; break-inside: avoid; }
p.bild { text-align: center; font-size: 8.5pt; color: #666; margin: 0 0 4mm 0; break-before: avoid; }
a { color: #0b5fbf; text-decoration: none; }
.titel { height: 245mm; display: flex; flex-direction: column; justify-content: center; break-after: page; }
.titel .logo { max-height: 22mm; border: none; margin: 0 0 10mm 0; }
.titel h1 { font-size: 34pt; }
.titel .unter { font-size: 14pt; color: #444; }
.titel .stand { margin-top: 20mm; font-size: 10pt; color: #666; }
"""


def slug(text):
    """Anker wie GitHub: klein, Satzzeichen weg, Leerzeichen zu Bindestrich, Umlaute bleiben."""
    text = re.sub(r"<[^>]+>", "", text).strip().lower()
    text = "".join(c for c in text if c.isalnum() or c in " -_" or unicodedata.category(c) == "Mn")
    return text.replace(" ", "-")


def to_html(md_name, title):
    src = open(os.path.join(DOC, md_name), encoding="utf-8").read()
    # Titelzeile und Stand kommen aufs Deckblatt
    lines = src.split("\n")
    head = lines[0].lstrip("# ").strip()
    stand = next((ln for ln in lines[1:6] if ln.startswith("Stand:")), "")
    body = "\n".join(ln for ln in lines[1:] if ln != stand)
    html = markdown.markdown(body, extensions=["tables", "toc", "sane_lists"],
                             extension_configs={"toc": {"slugify": lambda v, _s: slug(v)}})
    # Links auf die andere Datei zeigen auf das PDF, Links auf andere Repo-Dateien auf GitHub
    for md, pdf, _t in DOCS:
        html = html.replace(f'href="{md}', f'href="{pdf}')
    html = re.sub(r'href="(\.\./[^"#]+)', lambda m: 'href="' + REPO + os.path.normpath(
        os.path.join("docs/handbuch", m.group(1))).replace(os.sep, "/"), html)
    # Bildunterschrift aus dem Alt-Text
    html = re.sub(r'<p><img alt="([^"]*)" src="([^"]+)" ?/?></p>',
                  r'<img alt="\1" src="\2"><p class="bild">\1</p>', html)
    # jedes Hauptkapitel ab Kapitel 2 auf neuer Seite (Benutzerhandbuch), im Training jede Stufe
    first = [True]

    def h2(m):
        if first[0]:
            first[0] = False
            return m.group(0)
        return m.group(0).replace("<h2", '<h2 class="neu"', 1)
    html = re.sub(r"<h2[^>]*>", h2, html)
    logo = os.path.join(ROOT, "assets", "swv_logo.svg")
    cover = (f'<div class="titel">' + (f'<img class="logo" src="file://{logo}">' if logo else "") +
             f'<h1>{head}</h1><div class="unter">Speakerbildschirm für den Schweizer Wasserfahrverband</div>'
             f'<div class="stand">Software-Revision v{VERSION}<br>{stand}<br>Aktuelle Fassung: github.com/kuewi/swv-timing-live › docs/handbuch'
             f'</div></div>')
    return (f'<!DOCTYPE html><html lang="de"><head><meta charset="utf-8"><title>{head}</title>'
            f'<style>{CSS}</style></head><body>{cover}{html}</body></html>')


def find_chrome():
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        path = shutil.which(name)
        if path:
            return path
    sys.exit("Chrome/Chromium fehlt")


def number_pages(path, title):
    reader = PdfReader(path)
    writer = PdfWriter()
    total = len(reader.pages)
    for i, page in enumerate(reader.pages):
        if i:
            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=A4)
            c.setFont("Helvetica", 8)
            c.setFillGray(0.45)
            c.drawString(16 * 72 / 25.4, 10 * 72 / 25.4, f"SWV Live-Ranking v{VERSION} · {title}")
            c.drawRightString(A4[0] - 16 * 72 / 25.4, 10 * 72 / 25.4, f"Seite {i + 1} von {total}")
            c.save()
            buf.seek(0)
            page.merge_page(PdfReader(buf).pages[0])
        writer.add_page(page)
    writer.add_metadata({"/Title": f"SWV Live-Ranking {title} v{VERSION}", "/Author": "SWV Live-Ranking"})
    with open(path, "wb") as fh:
        writer.write(fh)


def main():
    chrome = find_chrome()
    for name in os.listdir(DOC):  # alte Fassungen entfernen
        if name.startswith("SWV_Live-Ranking_") and name.endswith(".pdf"):
            os.remove(os.path.join(DOC, name))
    tmp = tempfile.mkdtemp()
    for md, pdf, title in DOCS:
        html_path = os.path.join(DOC, f"_{md}.html")  # neben bilder/, damit relative Pfade stimmen
        open(html_path, "w", encoding="utf-8").write(to_html(md, title))
        out = os.path.join(DOC, pdf)
        subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--allow-file-access-from-files",
                        f"--user-data-dir={tmp}", "--no-pdf-header-footer", f"--print-to-pdf={out}",
                        "file://" + html_path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.remove(html_path)
        number_pages(out, title)
        print(out, len(PdfReader(out).pages), "Seiten")
    shutil.rmtree(tmp, ignore_errors=True)
    # Links im README und in der Uebersicht auf die neuen Dateinamen
    for path in (os.path.join(ROOT, "README.md"), os.path.join(DOC, "README.md")):
        text = open(path, encoding="utf-8").read()
        for _md, pdf, title in DOCS:
            text = re.sub(r"SWV_Live-Ranking_" + title + r"(?:_v[0-9.]+)?\.pdf", pdf, text)
        text = re.sub(r"Stand: App v[0-9.]+", f"Stand: App v{VERSION}", text)
        open(path, "w", encoding="utf-8").write(text)


if __name__ == "__main__":
    main()
