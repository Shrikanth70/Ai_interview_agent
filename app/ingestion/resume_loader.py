import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    """Extracts raw text from a PDF file using pdfplumber with pypdf fallback."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    text_parts: list[str] = []

    # Try pdfplumber first
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        if text_parts:
            return "\n\n".join(text_parts)
    except Exception:
        # Fall back to pypdf if pdfplumber fails or is unavailable
        pass

    try:
        import pypdf

        reader = pypdf.PdfReader(str(pdf_path))
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        if text_parts:
            return "\n\n".join(text_parts)
    except Exception as e:
        raise RuntimeError(f"Failed to extract text from PDF '{pdf_path}': {e}") from e

    return "\n\n".join(text_parts)


def clean_resume_text(raw_text: str) -> str:
    """Cleans extracted resume text by normalizing whitespace, line breaks, and bullet characters."""
    if not raw_text:
        return ""

    # Normalize carriage returns
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")

    # Normalize unicode bullets
    text = re.sub(r"[\u2022\u2023\u25E6\u2043\u2219]", "-", text)

    # Normalize multiple blank lines (keep at most two newlines)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Clean leading/trailing line whitespace
    lines = [line.strip() for line in text.split("\n")]
    cleaned_text = "\n".join(lines).strip()
    return cleaned_text


def parse_resume_sections(cleaned_text: str) -> Dict[str, str]:
    """Lightweight section identifier dividing resume into logical categories."""
    section_patterns = {
        "experience": re.compile(
            r"^(experience|work history|employment|work experience|professional experience)",
            re.IGNORECASE,
        ),
        "education": re.compile(
            r"^(education|academic background|academics|qualifications)",
            re.IGNORECASE,
        ),
        "projects": re.compile(
            r"^(projects|personal projects|technical projects|key projects)",
            re.IGNORECASE,
        ),
        "skills": re.compile(
            r"^(skills|technical skills|technologies|core competencies|core skills|key skills|primary skills|technical competencies|tools & technologies|tools and technologies)",
            re.IGNORECASE,
        ),
        "summary": re.compile(
            r"^(summary|professional summary|about me|profile|objective)",
            re.IGNORECASE,
        ),
    }

    lines = cleaned_text.split("\n")
    sections: Dict[str, list[str]] = {
        "header": [],
        "summary": [],
        "experience": [],
        "projects": [],
        "skills": [],
        "education": [],
        "other": [],
    }

    current_section = "header"

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Check if line looks like a header (short length, matches pattern)
        header_candidate = re.sub(r"[:\-\#\*]", "", stripped).strip()
        matched = False
        if len(header_candidate.split()) <= 4:
            for sec_name, pattern in section_patterns.items():
                if pattern.match(header_candidate):
                    current_section = sec_name
                    matched = True
                    break

        if not matched:
            sections[current_section].append(stripped)

    # Consolidate sections to text
    return {k: "\n".join(v).strip() for k, v in sections.items() if v}


def load_resume(source: str | Path) -> Dict[str, Any]:
    """Loads and processes a resume from a file path (.txt, .md, .pdf) or direct text string.

    Returns:
        dict with keys:
            - full_text: cleaned string
            - sections: dict of identified sections
            - char_count: int length
            - line_count: int lines
    """
    raw_text = ""
    source_str = str(source).strip()

    # Determine if source is an existing file
    potential_path = Path(source_str)
    if potential_path.is_file():
        suffix = potential_path.suffix.lower()
        if suffix == ".pdf":
            raw_text = extract_text_from_pdf(potential_path)
        else:
            with open(potential_path, "r", encoding="utf-8", errors="replace") as f:
                raw_text = f.read()
    else:
        # Source is raw text passed directly
        raw_text = source_str

    if not raw_text.strip():
        raise ValueError("Resume source text is empty or could not be extracted.")

    cleaned = clean_resume_text(raw_text)
    sections = parse_resume_sections(cleaned)

    return {
        "full_text": cleaned,
        "sections": sections,
        "char_count": len(cleaned),
        "line_count": len(cleaned.splitlines()),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.ingestion.resume_loader <path_or_text>")
        sys.exit(1)

    input_arg = sys.argv[1]
    try:
        result = load_resume(input_arg)
        print(json.dumps(result, indent=2))
    except Exception as err:
        print(f"Error loading resume: {err}", file=sys.stderr)
        sys.exit(1)
