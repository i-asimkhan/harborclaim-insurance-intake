"""
Builds the two demo documents for a realistic, fictional auto claim (no new dependency: a
minimal hand-written PDF). Run: python sample_data/demo/make_demo_pdfs.py

Deliberate test: the repair estimate totals $3,486.40, but the claim description (in
DEMO_CLAIM.md) says $3,250.00, so the AI review should raise an amount difference.
"""

from pathlib import Path

HERE = Path(__file__).parent

POLICE = [
    ("B", "CITY OF BAYPORT POLICE DEPARTMENT (fictional, for classroom use)"),
    ("B", "Traffic Crash Report"),
    ("", ""),
    ("", "Report number: BPD-2026-118407"),
    ("", "Date of crash: 2026-10-27        Time: 5:42 PM"),
    ("", "Location: Harbor Avenue at Palm Street, Bayport"),
    ("", "Reporting officer: Ofc. R. Delgado, Badge 4471"),
    ("", ""),
    ("B", "Vehicle 1 (struck)"),
    ("", "Driver: Jordan Ellis    Policy on file: HC-AUTO-5318"),
    ("", "2021 Honda Civic, silver, plate JXR-4417"),
    ("", "Damage: rear bumper cover, trunk lid, left tail lamp"),
    ("", ""),
    ("B", "Vehicle 2 (striking)"),
    ("", "Driver: Sam Ortiz    2018 Ford F-150, blue, plate KLT-9023"),
    ("", "Damage: front bumper, minor"),
    ("", ""),
    ("B", "Narrative"),
    ("", "Vehicle 1 was stopped at a red light on Harbor Avenue when Vehicle 2 failed"),
    ("", "to stop and struck it from behind. No injuries were reported at the scene."),
    ("", "Both vehicles were drivable. Driver 2 was issued a citation for following"),
    ("", "too closely. Photos were taken by the officer."),
]

ESTIMATE = [
    ("B", "Bayshore Collision Center (fictional, for classroom use)"),
    ("B", "Repair Estimate"),
    ("", ""),
    ("", "Estimate number: BCC-77215        Date: 2026-10-29"),
    ("", "Customer: Jordan Ellis"),
    ("", "Vehicle: 2021 Honda Civic, plate JXR-4417"),
    ("", "Insurance: HarborClaim, policy HC-AUTO-5318"),
    ("", ""),
    ("B", "Parts"),
    ("", "Rear bumper cover (OEM)                       $612.00"),
    ("", "Trunk lid (OEM)                               $894.50"),
    ("", "Left tail lamp assembly                       $318.90"),
    ("", "Clips, brackets and hardware                   $86.00"),
    ("B", "Labor and paint"),
    ("", "Body labor, 14.5 hours at $62.00               $899.00"),
    ("", "Paint and materials                           $540.00"),
    ("", "Rear camera recalibration                     $136.00"),
    ("", ""),
    ("B", "Total estimate $3,486.40"),
    ("", ""),
    ("", "Estimate valid for 30 days. Hidden damage found during repair will be"),
    ("", "reported to the insurer before any additional work."),
]


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_pdf(path: Path, lines: list[tuple[str, str]]) -> None:
    ops, y = ["BT"], 760
    for style, text in lines:
        font, size = ("F2", 13) if style == "B" else ("F1", 11)
        ops.append(f"/{font} {size} Tf 1 0 0 1 60 {y} Tm ({_escape(text)}) Tj")
        y -= 20 if style == "B" else 16
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    path.write_bytes(bytes(out))


if __name__ == "__main__":
    write_pdf(HERE / "bayport_police_report.pdf", POLICE)
    write_pdf(HERE / "bayshore_repair_estimate.pdf", ESTIMATE)
    print("Wrote", HERE / "bayport_police_report.pdf", "and", HERE / "bayshore_repair_estimate.pdf")
