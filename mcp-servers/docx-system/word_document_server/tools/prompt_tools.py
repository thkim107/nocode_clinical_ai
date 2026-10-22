"""
Prompt retrieval tools for Word Document Server.
Provides system prompts and guidelines for document generation.
"""
import os
from typing import Optional

# Base directory for prompt files
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "documents")


def _read_prompt_file(filename: str) -> str:
    """Read a prompt file from the documents directory.

    Args:
        filename: Name of the prompt file

    Returns:
        Content of the prompt file or error message
    """
    filepath = os.path.join(PROMPTS_DIR, filename)

    if not os.path.exists(filepath):
        return f"Prompt file not found: {filename}"

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Failed to read prompt file: {str(e)}"


async def get_tripod_ai_guideline(study_type: Optional[str] = None) -> str:
    """Get the TRIPOD+AI guideline for prediction model research report generation.

    This guideline provides a comprehensive framework for writing reports on AI/ML-based
    prediction models following the TRIPOD+AI (Transparent Reporting of a multivariable
    prediction model for Individual Prognosis Or Diagnosis + AI) checklist.

    Args:
        study_type: Optional filter for study type.
                   Use 'D' for development studies only,
                   'E' for evaluation studies only,
                   or None for full guideline (default).

    Returns:
        The TRIPOD+AI guideline prompt text, optionally filtered by study type.
        The guideline includes:
        - Document structure (Title, Abstract, Introduction, Methods, Results, Discussion)
        - All 27 TRIPOD+AI checklist items with detailed instructions
        - Handling instructions for missing information or non-applicable sections
        - DOCX formatting guidelines using MCP tools
        - Quality checklist for final review
    """
    content = _read_prompt_file("tripod_ai_system_prompt.txt")

    if study_type and study_type.upper() in ['D', 'E']:
        # Add study type specific note at the beginning
        study_type_note = f"""
## Study Type Filter Applied: {study_type.upper()}

**Note:** This guideline is being used for a {'Development' if study_type.upper() == 'D' else 'Evaluation'} study.
- Items marked with **[{study_type.upper()}]** or **[D;E]** are applicable
- Items marked with **[{'E' if study_type.upper() == 'D' else 'D'}]** only can be skipped

---

"""
        content = study_type_note + content

    return content


