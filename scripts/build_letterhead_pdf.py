#!/usr/bin/env python3
"""Letterhead HTML -> PDF builder.

Renders a letterhead HTML document (repeating thead/tfoot page chrome) to PDF
via headless Chromium, then fixes the last-page footer position: with
table-footer-group pagination, the footer on the FINAL page sits directly
under the last line of content instead of at the page bottom. This script
measures the gap on the rendered PDF and injects a spacer so the footer sits
at the same height on every page, then re-renders.

Usage: python3 build_letterhead_pdf.py input.html output.pdf
Requires: Chromium at CHROMIUM (env or default), poppler-utils (pdftotext).
The HTML must contain the closing sequence '</div>\n</td></tr></tbody></table>'
(end of .wrap inside the page table) — the spacer is injected there.
"""
import os, re, subprocess, sys, tempfile

CHROMIUM = os.environ.get("CHROMIUM", "/opt/pw-browsers/chromium")
FOOTER_TOKEN = os.environ.get("FOOTER_TOKEN", "<YOUR_FOOTER_TOKEN>")  # a short string that appears in the page footer
SAFETY_PX = 8                        # keep a hair above perfect to avoid spill
CLOSE_SEQ = "</div>\n</td></tr></tbody></table>"
MARKER = "<!--LASTPAGE-SPACER-->"

def render(html_path, pdf_path):
    subprocess.run([CHROMIUM, "--headless", "--disable-gpu", "--no-sandbox",
                    f"--print-to-pdf={pdf_path}", "--no-pdf-header-footer",
                    "--virtual-time-budget=8000", f"file://{os.path.abspath(html_path)}"],
                   check=True, capture_output=True)

def footer_tops(pdf_path):
    """Per page, the y (pt, from page top) of the lowest FOOTER_TOKEN word."""
    xml = subprocess.run(["pdftotext", "-bbox", pdf_path, "-"],
                         check=True, capture_output=True, text=True).stdout
    pages = re.split(r'<page\s', xml)[1:]
    tops = []
    for p in pages:
        ys = [float(m.group(1)) for m in re.finditer(
            r'<word[^>]*yMin="([\d.]+)"[^>]*>[^<]*' + re.escape(FOOTER_TOKEN), p)]
        tops.append(max(ys) if ys else None)
    return tops

def page_count(pdf_path):
    out = subprocess.run(["pdfinfo", pdf_path], check=True, capture_output=True, text=True).stdout
    return int(re.search(r"Pages:\s+(\d+)", out).group(1))

def inject_spacer(src_html, spacer_px):
    s = open(src_html).read()
    spacer = f'{MARKER}<div style="height:{spacer_px}px;"></div>\n'
    if MARKER in s:
        s = re.sub(re.escape(MARKER) + r'<div style="height:\d+px;"></div>\n?', spacer, s)
    else:
        s = s.replace(CLOSE_SEQ, spacer + CLOSE_SEQ, 1)
    tmp = src_html + ".spaced.html"
    open(tmp, "w").write(s)
    return tmp

def build(html_path, out_pdf):
    render(html_path, out_pdf)
    n = page_count(out_pdf)
    tops = footer_tops(out_pdf)
    if n < 2 or tops[0] is None or tops[-1] is None:
        print(f"{out_pdf}: {n} page(s), no adjustment possible/needed"); return
    gap_pt = tops[0] - tops[-1]
    if gap_pt < 6:
        print(f"{out_pdf}: footer already within {gap_pt:.1f}pt of page bottom"); return
    spacer_px = max(0, int(gap_pt * 96 / 72) - SAFETY_PX)
    for attempt in range(3):
        tmp = inject_spacer(html_path, spacer_px)
        render(tmp, out_pdf)
        if page_count(out_pdf) == n:
            t2 = footer_tops(out_pdf)
            print(f"{out_pdf}: fixed. footer gap {gap_pt:.0f}pt -> {t2[0]-t2[-1]:.0f}pt (spacer {spacer_px}px)")
            os.remove(tmp); return
        spacer_px -= 40   # spilled to a new page; back off
    os.remove(tmp)
    print(f"{out_pdf}: WARNING could not fit spacer without adding a page; left unadjusted")
    render(html_path, out_pdf)

if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
