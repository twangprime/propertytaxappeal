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


# ---- Miami-Dade layout ------------------------------------------------------------------
# Mirrors the real notice: the printed form and the filled-in values are drawn separately, so
# a plain text-stream read separates labels from numbers (the reader must rebuild rows).
OUT_MD = Path(__file__).resolve().parents[1] / "samples/sample_trim_notice_miami_dade.pdf"
MD_ROWS = [  # section, name, last taxable, last rate, current taxable, rolled-back rate, proposed rate
    ("MIAMI-DADE COUNTY:", "Countywide", 590000, 4.5740, 605000, 4.3301, 4.5740),
    (None, "Fire Rescue", 590000, 2.3965, 605000, 2.2644, 2.3965),
    ("PUBLIC SCHOOLS:", "By State Law", 615000, 3.2510, 630000, 3.1210, 3.2510),
    (None, "By Local Board", 615000, 2.2480, 630000, 2.1181, 2.2480),
    ("MUNICIPAL:", "Unincorp Area", 590000, 1.9090, 605000, 1.7983, 1.9090),
    ("VOTER APPROVED DEBT PAYMENTS:", "County Debt", 590000, 0.4171, 605000, 0.3937, 0.3937),
    (None, "School Debt", 615000, 0.1340, 630000, 0.1240, 0.1240),
]


def main_miami_dade() -> None:
    c = canvas.Canvas(str(OUT_MD), pagesize=letter)
    w, h = letter
    x = [0.4, 2.3, 2.95, 3.6, 4.4, 5.05, 5.75, 6.45, 7.15]
    # Pass 1: the printed form (labels only).
    c.setFont("Helvetica-Bold", 7)
    c.drawString(0.4 * inch, h - 0.35 * inch, "SAMPLE - FICTIONAL DATA FOR SOFTWARE TESTING - NOT AN OFFICIAL NOTICE")
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(w / 2, h - 0.6 * inch, "NOTICE OF PROPOSED PROPERTY TAXES AND")
    c.drawCentredString(w / 2, h - 0.75 * inch, "MIAMI-DADE COUNTY TAXING AUTHORITIES")
    c.setFont("Helvetica", 6)
    for xi, label in zip(x[1:], ["Last Year's Taxable Value", "Tax Rate", "Taxes", "Current Taxable Value",
                                 "Tax Rate", "Taxes", "Tax Rate", "Taxes"]):
        c.drawString(xi * inch, h - 2.0 * inch, label)
    c.drawString(x[0] * inch, h - 2.0 * inch, "TAXING AUTHORITY")
    c.drawString(1.5 * inch, h - 5.9 * inch, "MARKET VALUE")
    c.drawString(3.3 * inch, h - 5.9 * inch, "ASSESSED VALUE - School Levy")
    c.drawString(5.3 * inch, h - 5.9 * inch, "ASSESSED VALUE - Non-School Levy")
    c.drawString(0.4 * inch, h - 6.05 * inch, "PRIOR VALUE (2025)")
    c.drawString(0.4 * inch, h - 6.2 * inch, "CURRENT VALUE (2026)")
    c.drawString(0.4 * inch, h - 6.7 * inch, "If the Property Appraiser is unable to resolve the matter, you may file a "
                                             "petition with the Value Adjustment Board. Petitions must be filed on or before")
    # Pass 2: the filled-in values.
    c.setFont("Helvetica-Bold", 7)
    c.drawString(4.3 * inch, h - 1.1 * inch, "FOLIO: 30-4019-001-0100")
    c.drawString(4.3 * inch, h - 1.25 * inch, "PROPERTY ADDRESS: 1200 MOCKINGBIRD ST")
    c.drawString(6.9 * inch, h - 1.1 * inch, "2026")
    y = h - 2.2 * inch
    for section, name, last_tv, last_rate, cur_tv, rb_rate, rate in MD_ROWS:
        if section:
            c.drawString(x[0] * inch, y, section)
            y -= 11
        vals = [name, f"{last_tv:,}", f"{last_rate:.4f}", f"{last_tv * last_rate / 1000:,.2f}", f"{cur_tv:,}",
                f"{rb_rate:.4f}", f"{cur_tv * rb_rate / 1000:,.2f}", f"{rate:.4f}", f"{cur_tv * rate / 1000:,.2f}"]
        for xi, v in zip(x, vals):
            c.drawString(xi * inch, y, v)
        y -= 11
    for row_y, vals in [(h - 6.05 * inch, ["640,000", "610,000", "610,000"]),
                        (h - 6.2 * inch, ["705,000", "655,000", "655,000"])]:
        for xi, v in zip([1.6, 3.6, 5.6], vals):
            c.drawString(xi * inch, row_y, v)
    c.drawString(0.4 * inch, h - 6.85 * inch, "SEP. 18, 2026")
    c.save()
    print(f"wrote {OUT_MD}")


if __name__ == "__main__":
    main_miami_dade()
