"""Render a fictional Miami-Dade-style TRIM notice PDF for trying the OCR connector.

    python scripts/make_sample_trim.py   # writes samples/sample_trim_notice.pdf
"""

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parents[1] / "samples/sample_trim_notice.pdf"
AUTHORITIES = [  # (name, last year's rate, this year's proposed rate)
    ("Miami-Dade School Board", 5.6000, 5.5480),
    ("State and Other (Children's Trust, Everglades)", 0.5010, 0.4980),
    ("Miami-Dade County", 4.5740, 4.5740),
    ("Unincorporated Municipal Service Area", 1.9090, 1.9090),
    ("Library District", 0.2812, 0.2812),
    ("Fire Rescue District", 2.3965, 2.3965),
    ("Debt Service (County and Fire)", 0.4980, 0.4683),
    ("South Florida Water Management District", 0.2301, 0.2250),
    ("Florida Inland Navigation District", 0.0288, 0.0288),
]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUT), pagesize=letter)
    w, h = letter
    c.setFont("Helvetica-Bold", 9)
    c.drawString(0.6 * inch, h - 0.5 * inch, "SAMPLE - FICTIONAL DATA FOR SOFTWARE TESTING - NOT AN OFFICIAL NOTICE")
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(w / 2, h - 0.9 * inch, "NOTICE OF PROPOSED PROPERTY TAXES")
    c.setFont("Helvetica", 10)
    c.drawCentredString(w / 2, h - 1.1 * inch, "MIAMI-DADE COUNTY TAXING AUTHORITIES - DO NOT PAY - THIS IS NOT A BILL")
    y = h - 1.5 * inch
    for line in ["Folio: 30-4019-001-0100", "Property Address: 1200 MOCKINGBIRD ST, MIAMI, FL 33155",
                 "Owner: JORDAN SAMPLE", "Mailing date: August 24, 2026", "Tax year: 2026"]:
        c.drawString(0.6 * inch, y, line)
        y -= 14
    y -= 8
    c.setFont("Helvetica-Bold", 9)
    cols = [0.6, 4.2, 5.4, 6.6]
    for x, t in zip(cols, ["Taxing Authority", "Last Year Rate", "Rolled-back Rate", "Proposed Rate 2026"]):
        c.drawString(x * inch, y, t)
    c.setFont("Helvetica", 9)
    for name, last, new in AUTHORITIES:
        y -= 13
        for x, t in zip(cols, [name, f"{last:.4f}", f"{new * 0.97:.4f}", f"{new:.4f}"]):
            c.drawString(x * inch, y, t)
    y -= 15
    c.setFont("Helvetica-Bold", 9)
    c.drawString(cols[0] * inch, y, "Total")
    c.drawString(cols[3] * inch, y, f"{sum(a[2] for a in AUTHORITIES):.4f}")
    y -= 28
    c.drawString(0.6 * inch, y, "Property Values and Exemptions")
    c.drawString(4.2 * inch, y, "Last Year (2025)")
    c.drawString(5.6 * inch, y, "This Year (2026)")
    c.setFont("Helvetica", 9)
    for label, last, this in [("Market Value", "640,000", "655,000"),
                              ("Assessed Value", "610,000", "655,000"),
                              ("Homestead Exemption", "0", "25,000"),
                              ("Additional Homestead (non-school)", "0", "25,000"),
                              ("Taxable Value (non-school)", "610,000", "605,000"),
                              ("Taxable Value (school)", "610,000", "630,000")]:
        y -= 13
        c.drawString(0.6 * inch, y, label)
        c.drawRightString(5.2 * inch, y, last)
        c.drawRightString(6.6 * inch, y, this)
    y -= 30
    c.setFont("Helvetica", 9)
    for line in [
        "If you feel that the market value of your property is inaccurate or does not reflect fair market value,",
        "or if you are entitled to an exemption or classification that is not reflected above, contact the",
        "Miami-Dade Property Appraiser. If the Property Appraiser's office is unable to resolve the matter, you",
        "may file a petition for adjustment with the Value Adjustment Board. Petition forms are available from",
        "the Clerk of the Board and must be filed ON OR BEFORE September 18, 2026.",
    ]:
        c.drawString(0.6 * inch, y, line)
        y -= 12
    c.save()
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
