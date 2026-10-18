"""
Input validation for HarborClaim's claim submission form.

Separate from main.py's check_claim() on purpose: check_claim() asks "is this claim
*complete* enough to reach an adjuster" (missing fields are a valid, expected outcome,
not an error). This module asks "is this *input* well-formed at all" (a policy ID of
10,000 characters, an incident date in the year 3026, or a .exe upload are never valid,
regardless of completeness). Completeness is a business state; malformed input is a
rejected request. Keeping them separate means check_claim() -- the graded minimum --
never has to know about file types or string-length limits.
"""

from datetime import date, datetime

POLICY_ID_MAX_LENGTH = 40
DESCRIPTION_MAX_LENGTH = 5000
EARLIEST_INCIDENT_DATE = date(2000, 1, 1)
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_FILES = 10
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".jpg", ".jpeg", ".png", ".zip", ".doc", ".docx"}

# Hints only: main.py's completeness rule (any non-empty document list) decides
# readiness, so a missing police report on an auto claim never blocks submission.
CLAIM_TYPES = {
    "auto": ("Auto", "Attach a police report if you have one, plus photos of the damage."),
    "property": ("Property", "Attach a repair estimate and photos of the damage."),
    "health": ("Health / injury", "Attach treatment notes or a medical bill."),
    "theft": ("Theft", "Attach the police report number and any proof of ownership."),
    "liability": ("Liability", "Attach anything showing what happened and who was involved."),
    "other": ("Other", "Attach whatever documents support the claim."),
}
DEFAULT_CLAIM_TYPE = "other"


def normalize_claim_type(claim_type: str) -> str:
    """Blank means "other", so older clients and scripts that never send the field still work."""
    return claim_type.strip().lower() or DEFAULT_CLAIM_TYPE


def validate_claim_type(claim_type: str) -> list[str]:
    if claim_type not in CLAIM_TYPES:
        return [f"Claim type isn't recognized (choose one of: {', '.join(CLAIM_TYPES)})."]
    return []


def validate_claim_fields(policy_id: str, incident_date: str, description: str) -> list[str]:
    """Checks the three text fields for malformed (not just missing) input.

    Blank fields are intentionally NOT an error here -- that's check_claim()'s job,
    and reporting it twice (once as a validation error, once as NEEDS_INFORMATION)
    would be confusing. This only rejects input that's actively wrong.
    """
    errors = []

    if len(policy_id) > POLICY_ID_MAX_LENGTH:
        errors.append(f"Policy ID is too long (max {POLICY_ID_MAX_LENGTH} characters).")

    if incident_date.strip():
        try:
            parsed = datetime.strptime(incident_date, "%Y-%m-%d").date()
        except ValueError:
            errors.append("Incident date isn't a valid date.")
        else:
            if parsed > date.today():
                errors.append("Incident date can't be in the future.")
            elif parsed < EARLIEST_INCIDENT_DATE:
                errors.append(f"Incident date can't be before {EARLIEST_INCIDENT_DATE.isoformat()}.")

    if len(description) > DESCRIPTION_MAX_LENGTH:
        errors.append(f"Description is too long (max {DESCRIPTION_MAX_LENGTH} characters).")

    return errors


def validate_files(filenames_and_sizes: list[tuple[str, int]]) -> list[str]:
    """Checks uploaded files for type and size -- not content. A renamed .exe with a
    .pdf extension would still pass; this is a basic filter, not a security boundary.
    """
    errors = []

    if len(filenames_and_sizes) > MAX_FILES:
        errors.append(f"Too many files (max {MAX_FILES} per claim).")

    for filename, size_bytes in filenames_and_sizes:
        suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if suffix not in ALLOWED_EXTENSIONS:
            errors.append(f"{filename}: file type not allowed (allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}).")
        if size_bytes > MAX_FILE_SIZE_BYTES:
            errors.append(f"{filename}: file is too large (max {MAX_FILE_SIZE_BYTES // (1024*1024)} MB).")

    return errors
