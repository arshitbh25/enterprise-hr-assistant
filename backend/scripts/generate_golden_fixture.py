"""Regenerates tests/evaluation/fixtures/sample_hr_policy.pdf.

This fixture backs the entire golden evaluation set
(tests/evaluation/golden_qa.py) and threshold calibration
(scripts/calibrate_threshold.py). The version of this file replaced by
this script had every page cut off mid-word/mid-sentence (a defect in
however the PDF was originally produced, not in our own ingestion
pipeline - confirmed by extracting the committed PDF directly with
PyMuPDF, bypassing the chunker entirely). That silently starved several
ANSWERABLE_CASES questions (e.g. "Can I carry forward my earned
leave?") of the very fact they ask about, which only surfaced once a
real LLM (rather than FakeLLMService's verbatim-echo double) was asked
to reason over the truncated source text and correctly refused.

Each of the five pages below is a complete paragraph, written to:
- Fully answer every ANSWERABLE_CASES question for that topic.
- Deliberately omit the specific fact each TOPICALLY_ADJACENT
  adversarial case asks about (e.g. Leave Policy covers casual/earned
  leave only, never maternity/sick leave) so that adversarial tier
  still has a genuine "not in this document" answer, not just an
  absent-by-accident one.
- Preserve the exact numbers the hand-written groundedness examples in
  scripts/calibrate_threshold.py's _GROUNDEDNESS_EXAMPLES reference
  (twelve/fifteen days leave, sixty-day managerial notice, etc.), so
  those examples remain valid without also needing an edit.

Usage (from backend/):
    python scripts/generate_golden_fixture.py
"""

from pathlib import Path

import fitz

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "evaluation"
    / "fixtures"
    / "sample_hr_policy.pdf"
)

_PAGES: list[tuple[str, str]] = [
    (
        "Leave Policy",
        "Employees are entitled to twelve days of casual leave and fifteen days "
        "of earned leave per calendar year. Casual leave must be availed within "
        "the same calendar year and cannot be carried forward; any unused "
        "casual leave lapses at year end. Earned leave, however, may be "
        "carried forward to the following calendar year up to a maximum of "
        "thirty accumulated days. Employees must submit leave requests to "
        "their manager through the HR portal at least two working days in "
        "advance, except in cases of medical emergency.",
    ),
    (
        "Dress Code",
        "Employees are expected to dress in business casual attire during "
        "regular office hours, including collared shirts, closed-toe shoes, "
        "and neat, professional clothing. On Fridays, employees may wear "
        "smart casual attire, including jeans and sneakers, provided "
        "clothing remains neat and appropriate for the workplace. Formal "
        "business attire, including suits or equivalent professional wear, "
        "is required whenever an employee is attending an in-person or "
        "video client meeting, regardless of the day of the week. Employees "
        "are expected to exercise good judgment in maintaining a "
        "professional appearance at all times.",
    ),
    (
        "Travel and Reimbursement",
        "Employees traveling for business purposes may claim reimbursement "
        "for economy-class airfare, hotel accommodation, and reasonable "
        "meal expenses incurred during the trip. All reimbursement claims "
        "must be submitted through the expense portal within fourteen days "
        "of the employee's return from travel, along with original "
        "receipts. Alcohol expenses are not reimbursable under any "
        "circumstances, even when incurred during a business dinner with "
        "clients. Claims submitted after the fourteen-day window may be "
        "rejected at the discretion of the finance department.",
    ),
    (
        "Notice Period",
        "Employees resigning from their position are required to serve a "
        "notice period of sixty days for managerial roles and thirty days "
        "for all other regular employees. The notice period begins on the "
        "date the resignation letter is formally accepted by HR. If an "
        "employee does not serve the full notice period, the company will "
        "deduct an amount equal to the employee's basic salary for the "
        "number of days short from the employee's final settlement, in "
        "lieu of notice. Exceptions may be granted at management's "
        "discretion on a case-by-case basis.",
    ),
    (
        "Code of Conduct",
        "All employees are expected to maintain a professional and "
        "respectful workplace free from harassment, discrimination, and "
        "retaliation of any kind. Any employee who experiences or witnesses "
        "workplace harassment should report the incident to their HR "
        "business partner or the designated Internal Complaints Committee "
        "as soon as possible. The company maintains a strict zero-tolerance "
        "policy toward harassment of any form, and all reported incidents "
        "will be investigated promptly and confidentially.",
    ),
]


def main() -> None:
    doc = fitz.open()
    for title, body in _PAGES:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), title, fontsize=18, fontname="helv")
        page.insert_textbox(
            fitz.Rect(72, 100, 540, 400),
            body,
            fontsize=11,
            fontname="helv",
        )
    doc.save(_FIXTURE_PATH)
    doc.close()
    print(f"wrote {_FIXTURE_PATH}")


if __name__ == "__main__":
    main()
