"""Generate a synthetic US high-school transcript PDF (real text layer) so the
full pipeline can be tested end-to-end with no external file. Printed totals are
kept consistent with the course rows, so a correct extraction reconciles."""
from __future__ import annotations

import os

import fitz

GRADE_POINTS = {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0, "F": 0.0}

COURSES = [
    ("Fall 2022 (Grade 10)", "P 2986", "Honors Algebra II", "A", 5.0),
    ("Fall 2022 (Grade 10)", "P 1104", "English 10", "B", 5.0),
    ("Fall 2022 (Grade 10)", "P 3320", "Biology", "A", 5.0),
    ("Fall 2022 (Grade 10)", "P 5540", "World History", "B", 5.0),
    ("Spring 2023 (Grade 10)", "P 2987", "Honors Algebra II", "A", 5.0),
    ("Spring 2023 (Grade 10)", "P 1105", "English 10", "A", 5.0),
    ("Spring 2023 (Grade 10)", "P 3321", "Biology", "B", 5.0),
    ("Spring 2023 (Grade 10)", "P 7110", "Spanish II", "C", 5.0),
]


def _totals() -> tuple[float, float]:
    total_credits = sum(c[4] for c in COURSES)
    pts = sum(GRADE_POINTS[c[3]] * c[4] for c in COURSES)
    gpa = round(pts / total_credits, 2)
    return total_credits, gpa


def generate(out_path: str) -> str:
    total_credits, gpa = _totals()
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)  # US Letter

    def line(x: float, y: float, text: str, size: float = 10, bold: bool = False):
        page.insert_text((x, y), text, fontsize=size,
                         fontname="hebo" if bold else "helv")

    line(60, 60, "LAKESIDE HIGH SCHOOL", 16, bold=True)
    line(60, 78, "1200 Beach Blvd, Long Beach, CA 90815", 9)
    line(60, 92, "Official Academic Transcript", 9)

    line(60, 122, "Student: Jordan A. Rivera", 11, bold=True)
    line(60, 138, "Student ID: 100482       DOB: 03/14/2007       Grade: 11", 9)

    y = 175
    line(60, y, "Term", 9, bold=True)
    line(180, y, "Course ID", 9, bold=True)
    line(250, y, "Course Title", 9, bold=True)
    line(440, y, "Mark", 9, bold=True)
    line(490, y, "Credits", 9, bold=True)
    y += 6
    page.draw_line((60, y), (552, y))
    y += 16

    last_term = None
    for term, cid, title, grade, credits in COURSES:
        if term != last_term:
            line(60, y, term, 9, bold=True)
            last_term = term
        line(180, y, cid, 9)
        line(250, y, title, 9)
        line(445, y, grade, 9)
        line(495, y, f"{credits:.2f}", 9)
        y += 16

    y += 10
    page.draw_line((60, y), (552, y))
    y += 20
    line(60, y, "CUMULATIVE SUMMARY", 10, bold=True)
    y += 18
    line(60, y, f"Total Credits Earned: {total_credits:.2f}", 10)
    y += 16
    line(60, y, f"Cumulative GPA: {gpa:.2f}", 10)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    doc.save(out_path)
    doc.close()
    return out_path
