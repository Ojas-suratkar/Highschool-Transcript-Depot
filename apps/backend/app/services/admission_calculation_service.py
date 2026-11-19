from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, Union


AgKey = Literal["a", "b", "c", "d1", "d2", "d", "e", "f", "g"]
ScienceTarget = Literal["d1", "d2", "science-flex", "science-extra"]
ManualAgTarget = Union[AgKey, Literal["removed"]]
BasicGrade = Literal["A", "B", "C", "D", "F"]
GpaBucketKey = Literal["cumulative", "math", "english", "science"]


DEFAULT_AG_REQUIREMENTS: Dict[AgKey, int] = {
    "a": 4,
    "b": 8,
    "c": 6,
    "d1": 2,
    "d2": 2,
    "d": 4,
    "e": 4,
    "f": 2,
    "g": 2,
}


AG_LABELS: Dict[AgKey, str] = {
    "a": "History / Social Science (A)",
    "b": "English (B)",
    "c": "Mathematics (C)",
    "d1": "Bio (D1)",
    "d2": "Phys (D2)",
    "d": "Laboratory Science (D) = D1 + D2",
    "e": "Language Other Than English (E)",
    "f": "Visual & Performing Arts (F)",
    "g": "College-Preparatory Elective (G)",
}


DEFAULT_GRADE_POINTS: Dict[BasicGrade, float] = {
    "A": 4,
    "B": 3,
    "C": 2,
    "D": 1,
    "F": 0,
}


BASIC_GRADES: List[BasicGrade] = ["A", "B", "C", "D", "F"]
VALID_AG_LETTERS = {"a", "b", "c", "d", "d1", "d2", "e", "f", "g"}
PASSING_NON_GPA_GRADES = {"P", "PASS", "CR", "CREDIT"}

# CSULB First-Time Freshman index weights (from the CSULB audit document).
# CSULB Index = Cumulative GPA*200 + English GPA*500 + Math GPA*500
# STEM Index  = Math GPA*600 + Science GPA*600
# The thresholds these indexes are compared against come from the institution
# criteria (csulb_threshold / non_resident_csulb_threshold / stem_index_threshold).
CSULB_INDEX_CUMULATIVE_WEIGHT = 200
CSULB_INDEX_ENGLISH_WEIGHT = 500
CSULB_INDEX_MATH_WEIGHT = 500
STEM_INDEX_MATH_WEIGHT = 600
STEM_INDEX_SCIENCE_WEIGHT = 600


@dataclass
class ManualAgMapping:
    course_id: str
    target_ag: ManualAgTarget


@dataclass
class AdmissionCalculationConfig:
    ag_required: Dict[AgKey, int] = field(
        default_factory=lambda: DEFAULT_AG_REQUIREMENTS.copy()
    )
    grade_points: Dict[BasicGrade, float] = field(
        default_factory=lambda: DEFAULT_GRADE_POINTS.copy()
    )
    honors_bonus_points: float = 1
    honors_max_semesters: int = 8
    honors_max_10th_grade_semesters: int = 2
    csulb_score_multiplier: int = 800
    # CSULB First-Time Freshman Final Audit minimums (Clear Admit).
    california_resident_min_gpa: float = 2.5
    non_resident_min_gpa: float = 3.0
    csulb_threshold: int = 3200            # CA-resident CSULB Index minimum
    non_resident_csulb_threshold: int = 3500  # Non-resident CSULB Index minimum
    stem_index_threshold: int = 3600       # STEM Index minimum (STEM majors)
    stem_threshold: int = 0                # legacy field, retained for compatibility
    # Optional HS-graduation term gate, e.g. "Spring 2026". None = no gate.
    graduation_required_by: Optional[str] = None
    # HS grade levels considered, fully driven by the institution criteria.
    # ag_hs_grades             -> A-G counting (default 8-12)
    # gpa_hs_grades            -> subject GPAs: English/Math/Science (CSU: 9-12)
    # gpa_cumulative_hs_grades -> cumulative GPA / CSULB Index (CSU: 10-12)
    ag_hs_grades: List[int] = field(default_factory=lambda: [8, 9, 10, 11, 12])
    gpa_hs_grades: List[int] = field(default_factory=lambda: [9, 10, 11, 12])
    gpa_cumulative_hs_grades: List[int] = field(default_factory=lambda: [10, 11, 12])

    # --- Strict handbook A-G rule toggles (default False = current behavior) ---
    # Each is surfaced on the Institutional Criteria page and stored in the term's
    # rule_config; defaulting False means enabling them is always a deliberate act
    # and existing decisions never move until an admin flips the switch.
    strict_c_math_slots: bool = False        # Alg1 / Geometry / Alg2-or-Stats slots
    strict_a_history_anchor: bool = False     # U.S. History (or +Am Gov) anchor
    strict_f_same_discipline: bool = False    # 1 full year of ONE VPA discipline


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def lower_text(value: Any) -> str:
    return clean_text(value).lower()


def contains_any(text: str, terms: List[str]) -> bool:
    return any(term in text for term in terms)


def number_or_zero(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0
        return float(value)
    except (TypeError, ValueError):
        return 0


def non_negative_number(value: Any) -> float:
    return max(number_or_zero(value), 0)


def clean_count(value: Any) -> Union[int, float]:
    number = non_negative_number(value)

    if float(number).is_integer():
        return int(number)

    return number


def format_number(value: Any) -> str:
    number = number_or_zero(value)

    if float(number).is_integer():
        return str(int(number))

    return f"{number:.3f}".rstrip("0").rstrip(".")


def parse_grade_level(value: Any) -> Optional[int]:
    text = clean_text(value)

    if not text:
        return None

    try:
        numeric = float(text)

        if numeric.is_integer():
            grade_level = int(numeric)

            if 6 <= grade_level <= 12:
                return grade_level
    except (TypeError, ValueError):
        pass

    lowered = text.lower()

    for candidate in [12, 11, 10, 9, 8, 7, 6]:
        if re.search(rf"\b{candidate}(?:st|nd|rd|th)?\b", lowered):
            return candidate

    return None


def normalize_letter_grade(grade: Any) -> str:
    value = clean_text(grade).upper()

    if value.startswith("A"):
        return "A"
    if value.startswith("B"):
        return "B"
    if value.startswith("C"):
        return "C"
    if value.startswith("D"):
        return "D"
    if value.startswith("F"):
        return "F"

    try:
        numeric = float(value)

        if numeric >= 90:
            return "A"
        if numeric >= 80:
            return "B"
        if numeric >= 70:
            return "C"
        if numeric >= 60:
            return "D"
        return "F"
    except ValueError:
        return ""


def is_c_or_better(grade: Any) -> bool:
    return normalize_letter_grade(grade) in {"A", "B", "C"}


def is_pass_or_credit_grade(grade: Any) -> bool:
    return clean_text(grade).upper() in PASSING_NON_GPA_GRADES


# ---------------------------------------------------------------------------
# Course field accessors
# ---------------------------------------------------------------------------

def get_course_id(course: Dict[str, Any]) -> str:
    return clean_text(
        course.get("id")
        or course.get("course_id")
        or course.get("crs_id")
        or course.get("uc_doorway_course_id")
    )


def get_course_key(course: Dict[str, Any], index: int) -> str:
    crs_id = clean_text(course.get("crs_id") or course.get("id") or "course")
    name = clean_text(course.get("name") or "unknown")
    grade = clean_text(
        course.get("letter_grade")
        or course.get("grade")
        or course.get("crs_letter_grade")
        or ""
    )
    credits = clean_text(
        course.get("crs_credit_completed")
        or course.get("credits_completed")
        or course.get("credits")
        or ""
    )
    year = clean_text(course.get("year") or "")
    month = clean_text(course.get("month") or "")

    return f"{crs_id}__{name}__{grade}__{credits}__{year}__{month}__row_{index}"


def is_row_level_course_key(value: str) -> bool:
    return "__row_" in clean_text(value)


def get_legacy_course_key(course: Dict[str, Any], index: int) -> str:
    explicit_id = clean_text(course.get("id"))

    if explicit_id:
        return explicit_id

    crs_id = clean_text(course.get("crs_id") or "course")
    name = clean_text(course.get("name") or "unknown")

    return f"{crs_id}-{name}-{index}"


def get_course_lookup_keys(course: Dict[str, Any], index: int) -> List[str]:
    keys = [
        get_course_key(course, index),
        get_legacy_course_key(course, index),
        get_course_id(course),
        clean_text(course.get("id")),
        clean_text(course.get("course_id")),
        clean_text(course.get("crs_id")),
        clean_text(course.get("uc_doorway_course_id")),
    ]

    return [key for key in keys if key]


def get_course_name(course: Dict[str, Any]) -> str:
    mapped = course.get("mapped_uc_course") or {}

    return clean_text(
        course.get("name")
        or course.get("crs_description")
        or mapped.get("crs_description")
        or "Unknown Course"
    )


def get_course_grade(course: Dict[str, Any]) -> str:
    for field_name in ["letter_grade", "grade", "crs_letter_grade"]:
        value = clean_text(course.get(field_name))

        if value:
            return value.upper()

    crs_grade = clean_text(course.get("crs_grade"))

    if crs_grade and parse_grade_level(crs_grade) is None:
        return crs_grade.upper()

    return ""


def get_course_credits(course: Dict[str, Any]) -> float:
    return number_or_zero(
        course.get("crs_credit_completed")
        or course.get("credits_completed")
        or course.get("credits")
    )


def get_course_semesters(course: Dict[str, Any]) -> int:
    # Transcript rows are semester rows in this app.
    # Zero-credit rows are still attempts unless repeat cleanup excludes them.
    credits = get_course_credits(course)

    if credits > 0:
        return 1

    if get_course_name(course) or get_course_grade(course):
        return 1

    return 0


def get_grade_level(course: Dict[str, Any]) -> Optional[int]:
    possible_values = [
        course.get("grade_level"),
        course.get("gradeLevel"),
        course.get("hs_grade"),
        course.get("hsGrade"),
        course.get("HS Grade"),
        course.get("crs_grade"),
    ]

    for value in possible_values:
        grade_level = parse_grade_level(value)

        if grade_level is not None:
            return grade_level

    return None


def get_mapped_course(course: Dict[str, Any]) -> Dict[str, Any]:
    return course.get("mapped_uc_course") or {}


def get_combined_course_text(course: Dict[str, Any]) -> str:
    mapped = get_mapped_course(course)
    parts = [
        course.get("name"),
        course.get("standardizedDescription"),
        course.get("standardized_code"),
        course.get("standardized_description"),
        mapped.get("crs_description"),
        mapped.get("crs_ag_category_letter"),
        mapped.get("crs_ag_category_description"),
        mapped.get("crs_discipline"),
        mapped.get("crs_transcript_abbrevs"),
        mapped.get("crs_local_codes"),
    ]

    return lower_text(" ".join(clean_text(part) for part in parts if part is not None))


def get_original_ag_letter(course: Dict[str, Any]) -> str:
    mapped = get_mapped_course(course)
    possible_values = [
        mapped.get("crs_ag_category_letter"),
        course.get("ag"),
        course.get("a_g"),
        course.get("ag_code"),
        course.get("agCode"),
        course.get("standardizedCode"),
        course.get("standardized_code"),
    ]

    for value in possible_values:
        letter = lower_text(value).replace(" ", "")

        if letter in VALID_AG_LETTERS:
            return letter

    return ""


def get_course_discipline_text(course: Dict[str, Any]) -> str:
    mapped = get_mapped_course(course)

    return lower_text(
        " ".join(
            [
                clean_text(mapped.get("crs_discipline")),
                clean_text(mapped.get("crs_ag_category_description")),
                clean_text(mapped.get("crs_description")),
                clean_text(course.get("standardizedDescription")),
                clean_text(course.get("standardized_description")),
                clean_text(course.get("name")),
            ]
        )
    )


def get_uc_discipline(course: Dict[str, Any]) -> str:
    """The exact UC Doorways discipline (only), normalized for matching against the
    fixed discipline vocabulary used by the strict A-G rules. Empty if unmapped."""
    return lower_text(get_mapped_course(course).get("crs_discipline"))


# ---------------------------------------------------------------------------
# Fixed UC Doorways discipline vocabulary (the strict A-G rules key off these).
# These are the exact `crs_discipline` values UC Doorways emits; matching is
# case-insensitive. Institution overrides can be supplied via rule_config later.
# ---------------------------------------------------------------------------

# C — Math: three ordered slots + wildcards that fill any one empty slot.
MATH_SLOT_1_DISCIPLINES = {"algebra i", "mathematics i"}
MATH_SLOT_2_DISCIPLINES = {"geometry", "mathematics ii"}
MATH_SLOT_3_DISCIPLINES = {
    "algebra ii", "mathematics iii", "statistics", "algebra ii / trigonometry",
}
MATH_WILDCARD_DISCIPLINES = {
    "pre-calculus", "calculus", "other advanced mathematics", "additional math",
}

# A — History: the U.S. History anchor (+ American Government half).
HISTORY_US_DISCIPLINES = {"u.s. history"}
HISTORY_GOV_DISCIPLINES = {"civics / american government"}

# F — VPA: the 1-year-same-discipline set.
VPA_DISCIPLINES = {"visual arts", "music", "theater", "dance", "interdisciplinary arts"}


def is_valid_ag_course(course: Dict[str, Any]) -> bool:
    # Non-academic courses (flagged by a configured transcript code, e.g. '*')
    # never count toward A-G.
    if course.get("_non_academic"):
        return False

    # A-G completion rule: A/B/C grades count. P/CR can count for completion.
    # D/F do not satisfy A-G completion.
    raw_grade = get_course_grade(course)

    if not raw_grade:
        return False

    if is_pass_or_credit_grade(raw_grade):
        return True

    return normalize_letter_grade(raw_grade) in {"A", "B", "C"}


def get_course_id_prefix(course: Dict[str, Any]) -> str:
    raw = clean_text(course.get("crs_id") or course.get("course_id") or "")
    raw = raw.replace("-", " ").strip()

    for part in raw.split():
        letters = "".join(ch for ch in part if ch.isalpha())

        if letters:
            return letters.upper()

    return ""


def get_school_key_from_text(value: Any) -> str:
    text = lower_text(value)
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip()

    if "lbusd" in text or "long beach" in text:
        return "lbusd"

    if "st anthony" in text or "saint anthony" in text:
        return "st_anthony"

    if "mayfair" in text:
        return "mayfair"

    return ""


def get_student_school_key(student: Dict[str, Any]) -> str:
    possible_values = [
        student.get("school"),
        student.get("school_name"),
        student.get("schoolName"),
        student.get("format"),
        student.get("transcript_format"),
        student.get("transcriptFormat"),
    ]

    for value in possible_values:
        school_key = get_school_key_from_text(value)

        if school_key:
            return school_key

    return ""


def get_standardized_honors_value(course: Dict[str, Any]) -> str:
    mapped = get_mapped_course(course)

    possible_values = [
        course.get("honors"),
        course.get("Honors"),
        course.get("crs_honors"),
        course.get("standardized_honors"),
        course.get("standardizedHonors"),
        mapped.get("honors"),
        mapped.get("Honors"),
        mapped.get("crs_honors"),
    ]

    yes_values = {
        "yes",
        "y",
        "true",
        "1",
        "honors",
        "h",
        "ap",
        "advanced placement",
    }

    no_values = {
        "no",
        "n",
        "false",
        "0",
        "none",
        "regular",
        "college prep",
        "college-prep",
    }

    for value in possible_values:
        text = lower_text(value)

        if not text:
            continue

        if text in yes_values:
            return "yes"

        if text in no_values:
            return "no"

    return ""


def get_raw_course_id_for_honors(course: Dict[str, Any]) -> str:
    return clean_text(
        course.get("crs_id")
        or course.get("course_id")
        or course.get("uc_doorway_course_id")
        or course.get("id")
    )


def course_id_starts_with_ap_or_hp(course: Dict[str, Any]) -> bool:
    raw = get_raw_course_id_for_honors(course).upper().strip()
    normalized = raw.replace("-", " ").strip()
    prefix = get_course_id_prefix(course)

    return (
        normalized.startswith("AP")
        or normalized.startswith("HP")
        or prefix in {"AP", "HP"}
        or prefix.startswith("AP")
        or prefix.startswith("HP")
    )


def course_id_has_plus_sign(course: Dict[str, Any]) -> bool:
    return "+" in get_raw_course_id_for_honors(course)


def _code_matches_course_id(code: str, position: str, raw_id: str) -> bool:
    """Does a transcript code (e.g. '*', '+', 'HP') appear on this course ID at
    the configured position? Markers are matched against the raw ID's tokens."""
    code = (code or "").strip().lower()
    raw = (raw_id or "").strip().lower()
    if not code or not raw:
        return False
    pos = (position or "prefix").strip().lower()
    # Symbol markers (*, +) can appear anywhere in the visible ID token.
    if code in {"*", "+"}:
        if pos == "suffix":
            return raw.rstrip().endswith(code)
        if pos == "prefix":
            return raw.lstrip().startswith(code) or raw.split()[0] == code or raw.startswith(code)
        return code in raw
    # Letter markers (P, HP, N, ...) are matched as whole leading/trailing tokens.
    tokens = raw.replace("-", " ").split()
    if not tokens:
        return False
    if pos == "suffix":
        return tokens[-1] == code
    if pos == "either":
        return code in tokens
    return tokens[0] == code


def apply_transcript_codes(
    courses: List[Dict[str, Any]],
    institution_codes: Optional[List[Dict[str, Any]]],
) -> None:
    """Annotate each course with the meaning of any configured transcript code
    found on its course ID. Sets `_non_academic` (excluded from A-G when the
    code affects A-G) and `_honors_from_code`. Mutates courses in place.

    This makes the user's Transcript Codes page actually drive the calculation
    (e.g. '*' = non-academic, '+' = honors) instead of relying on hardcoded
    heuristics.
    """
    if not institution_codes:
        return

    def _norm_school(v: Any) -> str:
        # Normalize separators so "mayfair_high_school" matches "Mayfair High School".
        return lower_text(v).replace("_", " ").replace("-", " ").strip()

    for course in courses:
        raw_id = get_raw_course_id_for_honors(course)
        if not raw_id:
            continue
        course_school = _norm_school(
            course.get("crs_hs") or course.get("school") or course.get("school_name")
        )
        for code in institution_codes:
            code_school = _norm_school(code.get("school_name"))
            # A code with no school applies to all; otherwise it must match.
            if code_school and course_school and code_school not in course_school and course_school not in code_school:
                continue
            if not _code_matches_course_id(code.get("code", ""), code.get("position", "prefix"), raw_id):
                continue
            meaning = lower_text(code.get("meaning"))
            if meaning == "non_academic":
                if code.get("affects_ag", True):
                    course["_non_academic"] = True
            elif meaning in {"honors", "ap", "college_prep"}:
                if meaning == "honors" or meaning == "ap":
                    course["_honors_from_code"] = True


def is_honors_or_ap_course(course: Dict[str, Any], school_key: str = "") -> bool:
    """
    Honors/AP logic by school:

    LBUSD / St. Anthony:
    1. First check standardized Honors column.
    2. If Honors = Yes, count as honors.
    3. If Honors = No/blank, then count as honors only if course ID starts AP or HP.

    Mayfair:
    Keep existing logic, plus count as honors if course ID contains '+'.
    """
    school_key = clean_text(school_key)
    standardized_honors = get_standardized_honors_value(course)

    # A configured transcript code (e.g. '+' = honors) marks this course honors.
    if course.get("_honors_from_code"):
        return True

    if school_key in {"lbusd", "st_anthony"}:
        if standardized_honors == "yes":
            return True

        return course_id_starts_with_ap_or_hp(course)

    name = lower_text(course.get("name"))
    mapped = get_mapped_course(course)
    honors = lower_text(mapped.get("crs_honors"))
    course_prefix = get_course_id_prefix(course)

    existing_honors_logic = (
        course_prefix in {"H", "HP", "AP"}
        or course_prefix.startswith("HP")
        or course_prefix.startswith("AP")
        or name.startswith("ap ")
        or name.startswith("honors ")
        or " ap " in f" {name} "
        or "(ap" in name
        or "honors" in name
        or "(h)" in name
        or honors
        in {
            "true",
            "yes",
            "y",
            "1",
            "honors",
            "ap",
            "advanced placement",
        }
    )

    if school_key == "mayfair":
        return existing_honors_logic or course_id_has_plus_sign(course)

    return existing_honors_logic


# ---------------------------------------------------------------------------
# Science classification
# ---------------------------------------------------------------------------

def get_science_target_from_text(text: str) -> Optional[ScienceTarget]:
    text = lower_text(text)

    # Bio / life science should win first, even if the course name has PLTW.
    if any(
        word in text
        for word in [
            "biology",
            "biological",
            "life science",
            "life sciences",
            "bio ",
            "bio lvng",
            "biomedical",
            "medical biology",
            "human body systems",
            "medical interventions",
            "biomedical innovation",
            "environmental science",
            "anatomy",
            "physiology",
        ]
    ):
        return "d1"

    if any(
        word in text
        for word in [
            "physics",
            "physical science",
            "physical sciences",
            "chemistry",
            "chem ",
            "medical chemistry",
            "earth science",
            "earth",
            "geology",
            "astronomy",
        ]
    ):
        return "d2"

    if any(
        word in text
        for word in [
            "computer science",
            "computer sci",
            "engineering",
            "manufacturing",
            "aerospace engineering",
            "principles of engineering",
            "engineering design",
            "applied science",
        ]
    ):
        return "science-extra"

    if any(
        word in text
        for word in [
            "interdisciplinary science",
            "integrated science",
            "lab science",
            "laboratory science",
            "forensic science",
        ]
    ):
        return "science-flex"

    return None


def classify_course_for_ag(
    course: Dict[str, Any],
) -> Optional[Union[AgKey, ScienceTarget]]:
    original_letter = get_original_ag_letter(course)
    discipline_text = get_course_discipline_text(course)
    science_from_discipline = get_science_target_from_text(discipline_text)

    if original_letter == "a":
        return "a"
    if original_letter == "b":
        return "b"
    if original_letter == "c":
        return "c"
    # CSULB rule: Computer Science / Engineering cannot satisfy Area D1 or D2 — it
    # can only count as a 3rd year of science. Enforce this even when UC Doorways
    # labeled the course d1/d2.
    if original_letter in ("d1", "d2", "d") and science_from_discipline == "science-extra":
        return "science-extra"
    if original_letter == "d1":
        return "d1"
    if original_letter == "d2":
        return "d2"
    if original_letter == "d":
        return science_from_discipline or "science-flex"
    if original_letter == "e":
        return "e"
    if original_letter == "f":
        return "f"
    if original_letter == "g":
        return "g"

    return None


# ---------------------------------------------------------------------------
# Manual mapping helpers
# ---------------------------------------------------------------------------

def make_manual_mapping_lookup(
    manual_mappings: Optional[List[ManualAgMapping]],
) -> Dict[str, ManualAgTarget]:
    manual_mappings = manual_mappings or []
    lookup: Dict[str, ManualAgTarget] = {}

    for mapping in manual_mappings:
        if isinstance(mapping, dict):
            raw_course_id = mapping.get("course_id")
            raw_target = mapping.get("target_ag")
        else:
            raw_course_id = mapping.course_id
            raw_target = mapping.target_ag

        course_id = clean_text(raw_course_id)
        target = lower_text(raw_target)

        if not course_id:
            continue

        if target == "removed":
            lookup[course_id] = "removed"
            continue

        if target in VALID_AG_LETTERS:
            lookup[course_id] = target  # type: ignore[assignment]

    return lookup


def manual_map_uses_row_keys(manual_map: Dict[str, ManualAgTarget]) -> bool:
    return any(is_row_level_course_key(key) for key in manual_map.keys())


def get_manual_target_for_course(
    course: Dict[str, Any],
    index: int,
    manual_map: Dict[str, ManualAgTarget],
) -> Optional[ManualAgTarget]:
    row_key = get_course_key(course, index)

    if row_key in manual_map:
        return manual_map[row_key]

    # If frontend sends row-level keys, never fall back to crs_id.
    if manual_map_uses_row_keys(manual_map):
        return None

    for key in get_course_lookup_keys(course, index):
        if key in manual_map:
            return manual_map[key]

    return None


# ---------------------------------------------------------------------------
# Repeat detection helpers
# ---------------------------------------------------------------------------

def normalize_subject_group_name(course: Dict[str, Any]) -> str:
    name = lower_text(get_course_name(course))

    remove_words = [
        "apex",
        "credit recovery",
        "credit recov",
        "recovery",
        "repeated",
        "repeat",
        "semester",
        "fall",
        "spring",
    ]

    for word in remove_words:
        name = re.sub(rf"\b{re.escape(word)}\b", " ", name)

    name = re.sub(r"[^a-z0-9]+", " ", name)
    name = " ".join(name.split())

    return name


def is_repeat_course(course: Dict[str, Any]) -> bool:
    prefix = get_course_id_prefix(course)
    name = lower_text(get_course_name(course))
    status = lower_text(course.get("mapping_status"))
    course_type = lower_text(course.get("course_type"))

    return (
        prefix in {"R", "PR"}
        or prefix.startswith("R")
        or prefix.startswith("PR")
        or "repeat" in name
        or "repeated" in name
        or "repeat" in status
        or "repeat" in course_type
    )


def _grade_sort_key(normalized: str) -> int:
    order = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0, "": -1}
    return order.get(normalized, -1)


def is_completed_attempt(course: Dict[str, Any]) -> bool:
    grade = get_course_grade(course)
    normalized = normalize_letter_grade(grade)

    if normalized in {"A", "B", "C", "D", "F"} and get_course_credits(course) > 0:
        return True

    if is_pass_or_credit_grade(grade) and get_course_credits(course) > 0:
        return True

    return False


def is_zero_credit_deficiency(course: Dict[str, Any]) -> bool:
    grade = normalize_letter_grade(get_course_grade(course))
    return get_course_credits(course) <= 0 and grade in {"D", "F"}


def build_gpa_repeat_exclusion_keys_for_bucket(
    indexed_courses: List[Tuple[int, Dict[str, Any]]],
) -> set[str]:
    # IMPORTANT: This receives only courses eligible for the specific GPA bucket.
    # This prevents 9th-grade rows from excluding 10th-12th cumulative rows.
    grouped: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}

    for original_index, course in indexed_courses:
        key = normalize_subject_group_name(course)

        if not key:
            continue

        grouped.setdefault(key, []).append((original_index, course))

    excluded: set[str] = set()

    for _, items in grouped.items():
        if len(items) < 2:
            continue

        has_explicit_repeat = any(is_repeat_course(course) for _, course in items)
        has_zero_credit_deficiency = any(
            is_zero_credit_deficiency(course) for _, course in items
        )
        has_completed_attempt = any(is_completed_attempt(course) for _, course in items)

        if not (
            has_explicit_repeat
            or (has_zero_credit_deficiency and has_completed_attempt)
        ):
            continue

        gpa_grade_items: List[Tuple[int, Dict[str, Any], str]] = []

        for original_index, course in items:
            normalized = normalize_letter_grade(get_course_grade(course))

            if normalized in {"A", "B", "C", "D", "F"}:
                gpa_grade_items.append((original_index, course, normalized))

        if not gpa_grade_items:
            continue

        best_grade_value = max(
            _grade_sort_key(normalized) for _, _, normalized in gpa_grade_items
        )

        best_candidates = [
            (original_index, course, normalized)
            for original_index, course, normalized in gpa_grade_items
            if _grade_sort_key(normalized) == best_grade_value
        ]

        kept_index, kept_course, _ = next(
            (
                (original_index, course, normalized)
                for original_index, course, normalized in best_candidates
                if get_course_credits(course) > 0
            ),
            best_candidates[0],
        )

        kept_key = get_course_key(kept_course, kept_index)

        for original_index, course, _ in gpa_grade_items:
            course_key = get_course_key(course, original_index)

            if course_key != kept_key:
                excluded.add(course_key)

    return excluded


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def add_subject_count(
    subject_counts: Dict[str, Dict[str, int]],
    subject_entries: Dict[str, List[Dict[str, Any]]],
    category: str,
    subject_name: str,
    semesters: int,
    original_ag: Optional[str] = None,
    final_ag: Optional[str] = None,
    moved_from: Optional[str] = None,
) -> None:
    if category not in subject_counts:
        subject_counts[category] = {}

    if category not in subject_entries:
        subject_entries[category] = []

    label = subject_name

    if moved_from and final_ag:
        label = f"{subject_name} ({moved_from.upper()} -> {final_ag.upper()})"
    elif original_ag:
        label = f"{subject_name} ({original_ag.upper()})"

    subject_counts[category][label] = subject_counts[category].get(label, 0) + semesters

    existing = next(
        (
            item
            for item in subject_entries[category]
            if item["name"] == subject_name
            and item.get("original_ag") == original_ag
            and item.get("final_ag") == final_ag
            and item.get("moved_from") == moved_from
        ),
        None,
    )

    if existing:
        existing["count"] += semesters
        existing["label"] = label
    else:
        subject_entries[category].append(
            {
                "name": subject_name,
                "count": semesters,
                "original_ag": original_ag,
                "final_ag": final_ag or category,
                "moved_from": moved_from,
                "label": label,
            }
        )


def merge_subject_counts(*items: Dict[str, int]) -> Dict[str, int]:
    merged: Dict[str, int] = {}

    for item in items:
        for subject, count in item.items():
            merged[subject] = merged.get(subject, 0) + count

    return merged


def merge_subject_entries(*items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []

    for item in items:
        merged.extend(item)

    return merged


def resolve_science_flex_target(
    counts: Dict[str, int],
    config: AdmissionCalculationConfig,
) -> Literal["d1", "d2"]:
    d1_needed = max(config.ag_required["d1"] - counts["d1"], 0)
    d2_needed = max(config.ag_required["d2"] - counts["d2"], 0)

    if d1_needed >= d2_needed:
        return "d1"

    return "d2"


def get_display_original_ag(original_letter: str, final_category: str) -> str:
    if final_category == "d_extra":
        if original_letter in {"", "d"}:
            return "d"
        return original_letter

    if original_letter == "d" and final_category in {"d1", "d2"}:
        return final_category

    return original_letter or final_category


def get_display_final_ag(final_category: str) -> str:
    if final_category == "d_extra":
        return "d"

    return final_category


def get_display_moved_from(original_letter: str, final_category: str) -> Optional[str]:
    if not original_letter:
        return None

    display_final = get_display_final_ag(final_category)

    if original_letter == display_final:
        return None

    if original_letter == "d" and final_category in {"d1", "d2", "d_extra"}:
        return None

    return original_letter


# ---------------------------------------------------------------------------
# A-G validation helpers
# ---------------------------------------------------------------------------

def get_lote_level(course: Dict[str, Any]) -> Optional[int]:
    text = get_course_discipline_text(course)
    match = re.search(r"lote\s*level\s*(\d+)", text, re.IGNORECASE)

    if match:
        return int(match.group(1))

    return None


ESL_HINTS = (
    "english as a second language",
    "english as second language",
    "english language development",
    "e.s.l",
    " esl",
    "esl ",
    " eld ",
)
NATIVE_SPEAKER_HINTS = (
    "native speaker",
    "for native",
    "heritage speaker",
    "heritage language",
)


def _lote_course_text(course: Dict[str, Any]) -> str:
    return f" {lower_text(get_course_name(course))} {get_course_discipline_text(course)} "


def apply_lote_validation(
    counts: Dict[str, int],
    courses: List[Dict[str, Any]],
    config: AdmissionCalculationConfig,
    manual_map: Dict[str, ManualAgTarget],
) -> None:
    max_lote_level = 0
    esl_satisfies_lote = False
    native_speaker_full_year = False

    for index, course in enumerate(courses):
        if get_manual_target_for_course(course, index, manual_map) == "removed":
            continue

        text = _lote_course_text(course)

        # ESL: regardless of level, ESL taken after age 10 in a U.S. school satisfies
        # the 2-year LOTE requirement. (HS ESL is after age 10.) Does NOT require the
        # course to be A-G approved. Requires a passing grade.
        if is_passing_for_validation(course) and any(h in text for h in ESL_HINTS):
            esl_satisfies_lote = True

        # "Native Speakers" full-year course (e.g. Spanish for Native Speakers)
        # validates the LOTE sequence.
        if is_passing_for_validation(course) and any(h in text for h in NATIVE_SPEAKER_HINTS):
            native_speaker_full_year = True

        if not is_valid_ag_course(course):
            continue

        if get_subject_category_for_completion(course, index, manual_map) != "e":
            continue

        level = get_lote_level(course)
        if level:
            max_lote_level = max(max_lote_level, level)

    # Level 2+, ESL, or a Native Speakers course satisfies the E (LOTE) requirement.
    if max_lote_level >= 2 or esl_satisfies_lote or native_speaker_full_year:
        counts["e"] = max(counts["e"], config.ag_required["e"])


# Disciplines (as named on UC Doorways) that count as "Advanced Mathematics" —
# a passing one validates the entire 3-year (C) high-school math requirement.
ADVANCED_MATH_DISCIPLINE_HINTS = (
    "advanced mathematics",
    "advanced math",
    "pre-calculus",
    "precalculus",
    "pre calculus",
    "calculus",
    "trigonometry",
    "mathematical reasoning",  # e.g. MRWC
    "mathematical analysis",
)


def is_passing_for_validation(course: Dict[str, Any]) -> bool:
    """A course validates only with a C- or better, or a Pass/Credit grade."""
    grade = get_course_grade(course)
    return is_c_or_better(grade) or is_pass_or_credit_grade(grade)


def apply_math_validation(
    counts: Dict[str, int],
    courses: List[Dict[str, Any]],
    config: AdmissionCalculationConfig,
    manual_map: Dict[str, ManualAgTarget],
) -> None:
    """Advanced Mathematics validation (CSULB FTFY rule): a passing course whose
    UC Doorways discipline is Advanced Mathematics (Pre-Calculus, Calculus,
    Trigonometry, MRWC, etc., where Algebra 2 is the prerequisite) validates the
    entire 3-year (C) requirement for grade deficiency or subject omission.

    NOTE: Statistics is intentionally NOT handled here — it validates Algebra I/II
    but not Geometry, which needs per-course Algebra/Geometry granularity the
    current year-counts don't carry. Left for a follow-up so we never over-credit.
    """
    required_c = config.ag_required.get("c", 0)
    if required_c <= 0 or counts["c"] >= required_c:
        return

    for index, course in enumerate(courses):
        if get_manual_target_for_course(course, index, manual_map) == "removed":
            continue
        if not is_valid_ag_course(course):
            continue
        if get_subject_category_for_completion(course, index, manual_map) != "c":
            continue
        if not is_passing_for_validation(course):
            continue

        discipline = get_course_discipline_text(course)
        if any(hint in discipline for hint in ADVANCED_MATH_DISCIPLINE_HINTS):
            counts["c"] = max(counts["c"], required_c)
            return


def _year_sequence_area(course: Dict[str, Any]) -> Optional[str]:
    """Return the year-sequence-validatable area for a course: 'c' (Math),
    'd2_chem' (Chemistry only — not all physical science), 'e' (LOTE), else None."""
    cls = classify_course_for_ag(course)
    if cls == "c":
        return "c"
    if cls == "e":
        return "e"
    if cls == "d2":
        text = f"{get_course_discipline_text(course)} {lower_text(get_course_name(course))}"
        if "chemistry" in text or "chem" in text:
            return "d2_chem"
    return None


def apply_year_sequence_validation(
    counts: Dict[str, int],
    courses: List[Dict[str, Any]],
    config: AdmissionCalculationConfig,
    manual_map: Dict[str, ManualAgTarget],
) -> None:
    """Year-sequence validation (CSULB FTFY): a Pass/Credit or C- or better in the
    2nd semester of a yearlong course validates the full year — so a failed/weak
    1st semester of the SAME course still counts — in Chemistry, Math, and LOTE.

    A failed (D/F) semester normally does not count toward A-G; here we credit it
    back when a later semester of the same course (same title + year) passes.
    """
    from collections import defaultdict

    groups: Dict[Tuple[str, Any, str], List[Tuple[int, Dict[str, Any]]]] = defaultdict(list)
    for index, course in enumerate(courses):
        if get_manual_target_for_course(course, index, manual_map) == "removed":
            continue
        area = _year_sequence_area(course)
        if not area:
            continue
        name = normalize_subject_group_name(course)
        if not name:
            continue
        month = course.get("month")
        groups[(name, course.get("year"), area)].append((month if month is not None else 0, course))

    for (name, year, area), items in groups.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda t: t[0])
        later_course = items[-1][1]
        earlier_courses = [c for _, c in items[:-1]]

        # The 2nd (later) semester must pass for the year to validate.
        if not is_passing_for_validation(later_course):
            continue

        # Credit each earlier semester of the SAME course that was failed (D/F) and
        # therefore did not already count.
        failed_earlier = [
            c for c in earlier_courses
            if get_course_grade(c) and not is_valid_ag_course(c)
        ]
        if not failed_earlier:
            continue

        count_key = "d2" if area == "d2_chem" else area
        counts[count_key] = counts[count_key] + len(failed_earlier)


def apply_g_surplus(counts: Dict[str, int], config: AdmissionCalculationConfig) -> None:
    d_actual = counts["d1"] + counts["d2"] + counts["d_extra"]

    surplus = (
        max(counts["a"] - config.ag_required["a"], 0)
        + max(counts["b"] - config.ag_required["b"], 0)
        + max(counts["c"] - config.ag_required["c"], 0)
        + max(d_actual - config.ag_required["d"], 0)
        + max(counts["e"] - config.ag_required["e"], 0)
        + max(counts["f"] - config.ag_required["f"], 0)
    )

    g_needed = max(config.ag_required["g"] - counts["g"], 0)
    counts["g"] += min(g_needed, surplus)


# ---------------------------------------------------------------------------
# G substitution helper
# ---------------------------------------------------------------------------

def get_g_substitution_target_if_deficient(
    course: Dict[str, Any],
    counts: Dict[str, int],
    config: AdmissionCalculationConfig,
) -> Optional[Literal["a", "d1", "d2"]]:
    """
    A G course should stay G by default.

    It may move only when it can fix a real remaining deficiency:
    - G -> A only if A is deficient and the course is history/social science-like.
    - G -> D1 only if D1 is deficient and the course is bio/life science-like.
    - G -> D2 only if D2 is deficient and the course is physical science-like.
    """
    text = get_course_discipline_text(course)

    a_deficit = max(config.ag_required["a"] - counts["a"], 0)
    d1_deficit = max(config.ag_required["d1"] - counts["d1"], 0)
    d2_deficit = max(config.ag_required["d2"] - counts["d2"], 0)

    if a_deficit > 0 and any(
        word in text
        for word in [
            "history / social science",
            "history/social science",
            "u.s. history",
            "us history",
            "world history",
            "civics",
            "american government",
            "government",
            "social science",
        ]
    ):
        return "a"

    science_target = get_science_target_from_text(text)

    if science_target == "d1" and d1_deficit > 0:
        return "d1"

    if science_target == "d2" and d2_deficit > 0:
        return "d2"

    if science_target in {"science-flex", "science-extra"}:
        if d1_deficit > 0 and d1_deficit >= d2_deficit:
            return "d1"

        if d2_deficit > 0:
            return "d2"

    return None


# ---------------------------------------------------------------------------
# A-G completion helpers
# ---------------------------------------------------------------------------

def get_subject_category_for_completion(
    course: Dict[str, Any],
    index: int,
    manual_map: Dict[str, ManualAgTarget],
) -> Optional[str]:
    manual_target = get_manual_target_for_course(course, index, manual_map)

    if manual_target == "removed":
        return None

    if manual_target:
        return "d_extra" if manual_target == "d" else manual_target

    category = classify_course_for_ag(course)

    if category == "science-extra":
        return "d_extra"

    if category in {"science-flex", "d"}:
        return "d"

    return category


# ---------------------------------------------------------------------------
# Strict handbook A-G evaluators (each gated by a config toggle; all key off the
# fixed UC Doorways discipline vocabulary, never the raw transcript course name).
# ---------------------------------------------------------------------------

def evaluate_math_slots(
    courses: List[Dict[str, Any]],
    manual_map: Dict[str, ManualAgTarget],
) -> Dict[str, Any]:
    """Strict C: three ordered math slots, each satisfied by 1 year (2 sems) of a
    matching discipline. Wildcards (Pre-Calc/Calculus/Other Advanced/Additional
    Math) fill any ONE empty slot — a single advanced course fills one slot, not
    all three. Computer Science / unmapped C courses fill no named slot."""
    slot_sems = {1: 0, 2: 0, 3: 0}
    wildcard_sems = 0
    for index, course in enumerate(courses):
        if get_manual_target_for_course(course, index, manual_map) == "removed":
            continue
        if not is_valid_ag_course(course):
            continue
        if get_subject_category_for_completion(course, index, manual_map) != "c":
            continue
        disc = get_uc_discipline(course)
        sems = get_course_semesters(course)
        if disc in MATH_SLOT_1_DISCIPLINES:
            slot_sems[1] += sems
        elif disc in MATH_SLOT_2_DISCIPLINES:
            slot_sems[2] += sems
        elif disc in MATH_SLOT_3_DISCIPLINES:
            slot_sems[3] += sems
        elif disc in MATH_WILDCARD_DISCIPLINES:
            wildcard_sems += sems

    filled = {s: slot_sems[s] >= 2 for s in (1, 2, 3)}
    remaining_wild = wildcard_sems
    for s in (1, 2, 3):
        if not filled[s] and remaining_wild >= 2:
            filled[s] = True
            remaining_wild -= 2

    slot_names = {
        1: "Algebra I / Math I",
        2: "Geometry / Math II",
        3: "Algebra II / Math III / Statistics",
    }
    missing = [slot_names[s] for s in (1, 2, 3) if not filled[s]]
    return {"filled_slots": sum(1 for s in (1, 2, 3) if filled[s]), "missing": missing}


def evaluate_history_anchor(
    courses: List[Dict[str, Any]],
    manual_map: Dict[str, ManualAgTarget],
) -> Dict[str, Any]:
    """Strict A: the 2-year requirement must include a U.S. History year — either
    2 sems of U.S. History, or 1 sem U.S. History + 1 sem American Government."""
    us_sems = gov_sems = 0
    for index, course in enumerate(courses):
        if get_manual_target_for_course(course, index, manual_map) == "removed":
            continue
        if not is_valid_ag_course(course):
            continue
        if get_subject_category_for_completion(course, index, manual_map) != "a":
            continue
        disc = get_uc_discipline(course)
        sems = get_course_semesters(course)
        if disc in HISTORY_US_DISCIPLINES:
            us_sems += sems
        elif disc in HISTORY_GOV_DISCIPLINES:
            gov_sems += sems
    anchor_ok = us_sems >= 2 or (us_sems >= 1 and gov_sems >= 1)
    return {"anchor_ok": anchor_ok, "us_sems": us_sems, "gov_sems": gov_sems}


def evaluate_vpa_same_discipline(
    courses: List[Dict[str, Any]],
    manual_map: Dict[str, ManualAgTarget],
) -> Dict[str, Any]:
    """Strict F: the 1-year requirement must be 2 semesters of a SINGLE VPA
    discipline (not 1 sem music + 1 sem art)."""
    from collections import defaultdict

    disc_sems: Dict[str, int] = defaultdict(int)
    for index, course in enumerate(courses):
        if get_manual_target_for_course(course, index, manual_map) == "removed":
            continue
        if not is_valid_ag_course(course):
            continue
        if get_subject_category_for_completion(course, index, manual_map) != "f":
            continue
        disc = get_uc_discipline(course)
        if disc:
            disc_sems[disc] += get_course_semesters(course)
    return {"max_same_semesters": max(disc_sems.values(), default=0)}


def compute_strict_overrides(
    courses: List[Dict[str, Any]],
    config: AdmissionCalculationConfig,
    manual_map: Dict[str, ManualAgTarget],
) -> Dict[str, Dict[str, Any]]:
    """Per-area actual/deficit overrides for whichever strict toggles are on.
    Returns {} when all toggles are off (so default behavior is untouched)."""
    overrides: Dict[str, Dict[str, Any]] = {}

    if config.strict_c_math_slots:
        m = evaluate_math_slots(courses, manual_map)
        req_c = config.ag_required.get("c", 0)
        actual_c = min(m["filled_slots"] * 2, req_c)
        overrides["c"] = {
            "actual": actual_c,
            "def": max(req_c - actual_c, 0),
            "note": ("Missing math slot(s): " + ", ".join(m["missing"])) if m["missing"] else None,
        }

    if config.strict_a_history_anchor:
        a = evaluate_history_anchor(courses, manual_map)
        if not a["anchor_ok"]:
            overrides["a"] = {
                "def_floor": 2,
                "note": (
                    "Missing U.S. History requirement: needs 2 sems U.S. History, "
                    "or 1 sem U.S. History + 1 sem American Government."
                ),
            }

    if config.strict_f_same_discipline:
        f = evaluate_vpa_same_discipline(courses, manual_map)
        req_f = config.ag_required.get("f", 0)
        actual_f = min(f["max_same_semesters"], req_f)
        overrides["f"] = {
            "actual": actual_f,
            "def": max(req_f - actual_f, 0),
            "note": None if actual_f >= req_f else (
                "VPA year must be a single discipline (2 semesters of the same art)."
            ),
        }

    return overrides


# ---------------------------------------------------------------------------
# A-G review builder
# ---------------------------------------------------------------------------

def build_ag_review(
    courses: List[Dict[str, Any]],
    config: Optional[AdmissionCalculationConfig] = None,
    manual_mappings: Optional[List[ManualAgMapping]] = None,
) -> Dict[str, Any]:
    config = config or AdmissionCalculationConfig()
    manual_map = make_manual_mapping_lookup(manual_mappings)
    # A-G counting honors the institution's configured HS grade levels.
    allowed_ag_grades = set(config.ag_hs_grades or [8, 9, 10, 11, 12])

    counts: Dict[str, int] = {
        "a": 0,
        "b": 0,
        "c": 0,
        "d1": 0,
        "d2": 0,
        "d_extra": 0,
        "e": 0,
        "f": 0,
        "g": 0,
    }

    subject_counts: Dict[str, Dict[str, int]] = {
        "a": {},
        "b": {},
        "c": {},
        "d1": {},
        "d2": {},
        "d_extra": {},
        "e": {},
        "f": {},
        "g": {},
    }

    subject_entries: Dict[str, List[Dict[str, Any]]] = {
        "a": [],
        "b": [],
        "c": [],
        "d1": [],
        "d2": [],
        "d_extra": [],
        "e": [],
        "f": [],
        "g": [],
    }

    course_assignments: List[Dict[str, Any]] = []
    pending_g_courses: List[Tuple[int, Dict[str, Any], Dict[str, Any], int, str]] = []

    for index, course in enumerate(courses):
        course_key = get_course_key(course, index)
        course_id = get_course_id(course)
        subject_name = get_course_name(course)
        original_letter = get_original_ag_letter(course)
        manual_target = get_manual_target_for_course(course, index, manual_map)

        assignment_record = {
            "course_key": course_key,
            "course_id": course_id,
            "course_index": index,
            "course_name": subject_name,
            "year": course.get("year"),
            "month": course.get("month"),
            "grade": get_course_grade(course),
            "credits": (
                course.get("crs_credit_completed")
                or course.get("credits_completed")
                or course.get("credits")
            ),
            "original_ag": original_letter,
            "final_ag": None,
            "removed": False,
            "manual": manual_target is not None,
            "moved_from": None,
            "counted": False,
            "grade_level": get_grade_level(course),
        }

        if manual_target == "removed":
            assignment_record["removed"] = True
            course_assignments.append(assignment_record)
            continue

        # Restrict A-G counting to the institution's configured HS grade levels.
        # A course whose grade level is set but not selected is shown but not
        # counted (fully config-driven from the Institutional Criteria page).
        grade_level = assignment_record["grade_level"]
        if grade_level is not None and grade_level not in allowed_ag_grades:
            assignment_record["reason"] = "grade level not considered for A-G"
            course_assignments.append(assignment_record)
            continue

        if not is_valid_ag_course(course):
            course_assignments.append(assignment_record)
            continue

        semesters = get_course_semesters(course)

        if semesters <= 0:
            course_assignments.append(assignment_record)
            continue

        if manual_target and manual_target != "removed":
            target: Union[AgKey, str] = manual_target

            if target == "d":
                target = "d_extra"

            counts[target] += semesters

            display_original = get_display_original_ag(original_letter, target)
            display_final = get_display_final_ag(target)
            display_moved_from = get_display_moved_from(original_letter, target)

            add_subject_count(
                subject_counts,
                subject_entries,
                target,
                subject_name,
                semesters,
                original_ag=display_original,
                final_ag=display_final,
                moved_from=display_moved_from,
            )

            assignment_record["final_ag"] = display_final
            assignment_record["counted"] = True
            assignment_record["original_ag"] = display_original
            assignment_record["moved_from"] = display_moved_from

            course_assignments.append(assignment_record)
            continue

        if not original_letter:
            assignment_record["reason"] = "not official A-G course"
            course_assignments.append(assignment_record)
            continue

        category = classify_course_for_ag(course)

        if not category:
            course_assignments.append(assignment_record)
            continue

        # G courses are processed after all normal/native courses are counted.
        # This prevents a G course from moving to A/D1/D2 too early.
        if category == "g":
            pending_g_courses.append(
                (index, course, assignment_record, semesters, subject_name)
            )
            course_assignments.append(assignment_record)
            continue

        if category == "science-extra":
            category = "d_extra"
        elif category in {"science-flex", "d"}:
            category = resolve_science_flex_target(counts, config)

        counts[category] += semesters

        display_original = get_display_original_ag(original_letter, category)
        display_final = get_display_final_ag(category)
        display_moved_from = get_display_moved_from(original_letter, category)

        add_subject_count(
            subject_counts,
            subject_entries,
            category,
            subject_name,
            semesters,
            original_ag=display_original,
            final_ag=display_final,
            moved_from=display_moved_from,
        )

        assignment_record["original_ag"] = display_original
        assignment_record["final_ag"] = display_final
        assignment_record["moved_from"] = display_moved_from
        assignment_record["counted"] = True

        course_assignments.append(assignment_record)

    # Now process G courses only if they fix a remaining A, D1, or D2 deficiency.
    for index, course, assignment_record, semesters, subject_name in pending_g_courses:
        target = get_g_substitution_target_if_deficient(
            course=course,
            counts=counts,
            config=config,
        )

        if target:
            counts[target] += semesters

            add_subject_count(
                subject_counts,
                subject_entries,
                target,
                subject_name,
                semesters,
                original_ag="g",
                final_ag=target,
                moved_from="g",
            )

            assignment_record["original_ag"] = "g"
            assignment_record["final_ag"] = target
            assignment_record["moved_from"] = "g"
            assignment_record["counted"] = True
        else:
            counts["g"] += semesters

            add_subject_count(
                subject_counts,
                subject_entries,
                "g",
                subject_name,
                semesters,
                original_ag="g",
                final_ag="g",
            )

            assignment_record["original_ag"] = "g"
            assignment_record["final_ag"] = "g"
            assignment_record["moved_from"] = None
            assignment_record["counted"] = True

    apply_lote_validation(counts, courses, config, manual_map)
    apply_math_validation(counts, courses, config, manual_map)
    apply_year_sequence_validation(counts, courses, config, manual_map)
    apply_g_surplus(counts, config)

    # Strict handbook overrides (only for toggles that are on; {} otherwise).
    strict_overrides = compute_strict_overrides(courses, config, manual_map)

    d_actual = counts["d1"] + counts["d2"] + counts["d_extra"]
    d_subject_counts = merge_subject_counts(
        subject_counts["d1"],
        subject_counts["d2"],
        subject_counts["d_extra"],
    )
    d_subject_entries = merge_subject_entries(
        subject_entries["d1"],
        subject_entries["d2"],
        subject_entries["d_extra"],
    )

    rows = []

    for key in ["a", "b", "c", "d1", "d2", "d", "e", "f", "g"]:
        if key == "d":
            actual = d_actual
            row_subject_counts = d_subject_counts
            row_subject_entries = d_subject_entries
        else:
            actual = counts[key]
            row_subject_counts = subject_counts[key]
            row_subject_entries = subject_entries[key]

        required = config.ag_required[key]

        if key == "d":
            d1_def = max(config.ag_required["d1"] - counts["d1"], 0)
            d2_def = max(config.ag_required["d2"] - counts["d2"], 0)
            deficit = d1_def + d2_def
        else:
            deficit = max(required - actual, 0)

        # Apply a strict-rule override for this area (a/c/f) when its toggle is on.
        strict_note = None
        ov = strict_overrides.get(key)
        if ov:
            if "actual" in ov:
                actual = ov["actual"]
            if "def" in ov:
                deficit = ov["def"]
            if "def_floor" in ov:
                deficit = max(deficit, ov["def_floor"])
            strict_note = ov.get("note")

        rows.append(
            {
                "key": key,
                "label": AG_LABELS[key],
                "required": required,
                "actual": actual,
                "def": deficit,
                "subject_counts": row_subject_counts,
                "subjects": row_subject_entries,
                "strict_note": strict_note,
            }
        )

    total_rows = [row for row in rows if row["key"] not in {"d1", "d2"}]

    return {
        "rows": rows,
        "totals": {
            "required": sum(
                config.ag_required[key] for key in ["a", "b", "c", "d", "e", "f", "g"]
            ),
            "actual": sum(row["actual"] for row in total_rows),
            "def": sum(row["def"] for row in total_rows),
        },
        "manual_mappings": [
            {
                "course_id": (
                    mapping.course_id
                    if not isinstance(mapping, dict)
                    else mapping.get("course_id")
                ),
                "target_ag": (
                    mapping.target_ag
                    if not isinstance(mapping, dict)
                    else mapping.get("target_ag")
                ),
            }
            for mapping in (manual_mappings or [])
        ],
        "course_assignments": course_assignments,
    }


# ---------------------------------------------------------------------------
# GPA helpers
# ---------------------------------------------------------------------------

def get_official_ag_category_for_gpa(course: Dict[str, Any]) -> Optional[str]:
    original_letter = get_original_ag_letter(course)

    if original_letter in {"a", "b", "c", "e", "f", "g"}:
        return original_letter

    if original_letter in {"d", "d1", "d2"}:
        return "d"

    return None


def get_subject_category_for_gpa(
    course: Dict[str, Any],
    index: int,
    manual_map: Dict[str, ManualAgTarget],
) -> Optional[str]:
    manual_target = get_manual_target_for_course(course, index, manual_map)

    if manual_target == "removed":
        return None

    if manual_target:
        if manual_target in {"d", "d1", "d2"}:
            return "d"
        return manual_target

    return get_official_ag_category_for_gpa(course)


def is_ag_eligible_for_gpa(
    course: Dict[str, Any],
    index: int,
    manual_map: Dict[str, ManualAgTarget],
) -> bool:
    return get_subject_category_for_gpa(course, index, manual_map) is not None


def is_grade_level_allowed(course: Dict[str, Any], allowed: List[int]) -> bool:
    grade_level = get_grade_level(course)

    if grade_level is None:
        return True

    return grade_level in allowed


# ---------------------------------------------------------------------------
# GPA bucket builder
# ---------------------------------------------------------------------------

def build_gpa_bucket(
    label: str,
    courses: List[Dict[str, Any]],
    include_course: Callable[[Dict[str, Any], int], bool],
    config: AdmissionCalculationConfig,
    manual_map: Dict[str, ManualAgTarget],
    school_key: str = "",
) -> Dict[str, Any]:
    grade_counts: Dict[BasicGrade, Union[int, float]] = {
        "A": 0,
        "B": 0,
        "C": 0,
        "D": 0,
        "F": 0,
    }

    bucket_repeat_candidates = [
        (index, course)
        for index, course in enumerate(courses)
        if get_manual_target_for_course(course, index, manual_map) != "removed"
        and include_course(course, index)
    ]

    excluded_repeat_keys = build_gpa_repeat_exclusion_keys_for_bucket(
        bucket_repeat_candidates
    )

    honors_count: Union[int, float] = 0
    honors_bonus_semesters_used = 0
    honors_bonus_10th_semesters_used = 0
    total_semesters: Union[int, float] = 0
    total_points = 0.0
    included_courses: List[Dict[str, Any]] = []

    for index, course in enumerate(courses):
        course_key = get_course_key(course, index)

        if course_key in excluded_repeat_keys:
            continue

        if get_manual_target_for_course(course, index, manual_map) == "removed":
            continue

        if not include_course(course, index):
            continue

        grade = get_course_grade(course)

        # P/CR can satisfy A-G completion but does not enter GPA.
        if is_pass_or_credit_grade(grade):
            continue

        normalized = normalize_letter_grade(grade)

        if normalized not in config.grade_points:
            continue

        weight = get_gpa_course_weight(course)
        semesters = int(weight["grade_entries"])
        honors_semester_cap_for_course = int(weight["honors_entry_cap"])
        is_college_course = bool(weight["college_course"])

        if semesters <= 0:
            continue

        base_points = config.grade_points[normalized]
        honors_semesters_for_course = 0
        grade_level = get_grade_level(course)
        honors_allowed_for_grade = grade_level is None or grade_level in {10, 11, 12}
        honors_grade_is_valid = is_c_or_better(grade)
        is_honors_course = is_honors_or_ap_course(course, school_key)
        eligible_for_honors_weight = is_honors_course or is_college_course

        if (
            eligible_for_honors_weight
            and honors_grade_is_valid
            and honors_allowed_for_grade
            and honors_bonus_semesters_used < config.honors_max_semesters
        ):
            available_total_honors = config.honors_max_semesters - honors_bonus_semesters_used

            if grade_level == 10:
                available_10th_honors = (
                    config.honors_max_10th_grade_semesters
                    - honors_bonus_10th_semesters_used
                )
                honors_semesters_for_course = min(
                    honors_semester_cap_for_course,
                    available_total_honors,
                    max(available_10th_honors, 0),
                )
                honors_bonus_10th_semesters_used += honors_semesters_for_course
            else:
                honors_semesters_for_course = min(
                    honors_semester_cap_for_course,
                    available_total_honors,
                )

            honors_bonus_semesters_used += honors_semesters_for_course

        grade_counts[normalized] += semesters
        honors_count += honors_semesters_for_course
        total_semesters += semesters
        total_points += (base_points * semesters) + (
            config.honors_bonus_points * honors_semesters_for_course
        )

        included_courses.append(
            {
                "course_key": course_key,
                "course_id": get_course_id(course),
                "course_index": index,
                "course_name": get_course_name(course),
                "year": course.get("year"),
                "month": course.get("month"),
                "grade": grade,
                "normalized_grade": normalized,
                "grade_level": grade_level,
                "semesters": semesters,
                "subject_category": get_subject_category_for_gpa(
                    course,
                    index,
                    manual_map,
                ),
                "honors": eligible_for_honors_weight,
                "college_course": is_college_course,
                "honors_semesters_used": honors_semesters_for_course,
                "points": round(
                    (base_points * semesters)
                    + (config.honors_bonus_points * honors_semesters_for_course),
                    3,
                ),
            }
        )

    gpa = round(total_points / total_semesters, 3) if total_semesters > 0 else None

    return {
        "label": label,
        "grade_counts": grade_counts,
        "grade_points": config.grade_points,
        "honors_count": honors_count,
        "honors_bonus_points": config.honors_bonus_points,
        "honors_max_semesters": config.honors_max_semesters,
        "honors_max_10th_grade_semesters": config.honors_max_10th_grade_semesters,
        "total_semesters": total_semesters,
        "total_points": round(total_points, 3),
        "gpa": gpa,
        "included_courses": included_courses,
        "manual_edit": False,
    }

def is_qualifying_3plus_unit_college_course(course: Dict[str, Any]) -> bool:
    if get_course_credits(course) < 3:
        return False

    mapped = get_mapped_course(course)
    text = lower_text(
        " ".join(
            clean_text(value)
            for value in [
                course.get("course_type"),
                course.get("course_category"),
                course.get("source"),
                course.get("crs_hs"),
                course.get("school"),
                course.get("school_name"),
                mapped.get("crs_environment"),
                mapped.get("crs_description"),
                mapped.get("crs_ag_category_description"),
                mapped.get("crs_discipline"),
            ]
            if value is not None
        )
    )

    if "college prep" in text:
        return False

    return contains_any(
        text,
        [
            "college",
            "community college",
            "dual enrollment",
            "dual-enrollment",
            "concurrent enrollment",
        ],
    )


def get_gpa_course_weight(course: Dict[str, Any]) -> Dict[str, Union[int, bool]]:
    is_college_course = is_qualifying_3plus_unit_college_course(course)

    if is_college_course:
        return {
            "grade_entries": 2,
            "honors_entry_cap": 1,
            "college_course": True,
        }

    semesters = get_course_semesters(course)

    return {
        "grade_entries": semesters,
        "honors_entry_cap": semesters,
        "college_course": False,
    }

# ---------------------------------------------------------------------------
# GPA manual edit helpers
# ---------------------------------------------------------------------------

def normalize_gpa_bucket_edits(
    gpa_bucket_edits: Optional[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    if not isinstance(gpa_bucket_edits, dict):
        return {}

    normalized: Dict[str, Dict[str, Any]] = {}

    for bucket_key in ["cumulative", "math", "english", "science"]:
        raw_edit = gpa_bucket_edits.get(bucket_key)

        if not isinstance(raw_edit, dict):
            continue

        grade_counts = raw_edit.get("grade_counts") or raw_edit.get("gradeCounts") or {}
        honors_count = raw_edit.get("honors_count")

        if honors_count is None:
            honors_count = raw_edit.get("honorsCount")

        normalized[bucket_key] = {
            "grade_counts": grade_counts if isinstance(grade_counts, dict) else {},
            "honors_count": honors_count,
        }

    return normalized


def apply_gpa_bucket_edit(
    bucket: Dict[str, Any],
    edit: Dict[str, Any],
    config: AdmissionCalculationConfig,
) -> Dict[str, Any]:
    grade_counts: Dict[BasicGrade, Union[int, float]] = {}
    current_grade_counts = bucket.get("grade_counts") or {}
    edited_grade_counts = edit.get("grade_counts") or {}

    for grade in BASIC_GRADES:
        if grade in edited_grade_counts:
            grade_counts[grade] = clean_count(edited_grade_counts.get(grade))
        else:
            grade_counts[grade] = clean_count(current_grade_counts.get(grade, 0))

    if edit.get("honors_count") is not None:
        honors_count: Union[int, float] = clean_count(edit.get("honors_count"))
    else:
        honors_count = clean_count(bucket.get("honors_count", 0))

    total_semesters = sum(
        number_or_zero(grade_counts.get(grade, 0)) for grade in BASIC_GRADES
    )

    honors_count = min(
        number_or_zero(honors_count),
        number_or_zero(total_semesters),
        number_or_zero(config.honors_max_semesters),
    )

    if float(honors_count).is_integer():
        honors_count = int(honors_count)

    grade_total = sum(
        number_or_zero(grade_counts.get(grade, 0)) * config.grade_points[grade]
        for grade in BASIC_GRADES
    )
    honors_total = number_or_zero(honors_count) * config.honors_bonus_points
    total_points = grade_total + honors_total
    gpa = round(total_points / total_semesters, 3) if total_semesters > 0 else None

    return {
        **bucket,
        "grade_counts": grade_counts,
        "grade_points": config.grade_points,
        "honors_count": honors_count,
        "honors_bonus_points": config.honors_bonus_points,
        "total_semesters": clean_count(total_semesters),
        "total_points": round(total_points, 3),
        "gpa": gpa,
        "manual_edit": True,
    }


def apply_gpa_bucket_edits(
    buckets: Dict[str, Dict[str, Any]],
    gpa_bucket_edits: Optional[Dict[str, Any]],
    config: AdmissionCalculationConfig,
) -> Dict[str, Dict[str, Any]]:
    normalized_edits = normalize_gpa_bucket_edits(gpa_bucket_edits)

    if not normalized_edits:
        return buckets

    updated_buckets: Dict[str, Dict[str, Any]] = {}

    for bucket_key, bucket in buckets.items():
        edit = normalized_edits.get(bucket_key)

        if edit:
            updated_buckets[bucket_key] = apply_gpa_bucket_edit(bucket, edit, config)
        else:
            updated_buckets[bucket_key] = bucket

    return updated_buckets


def build_score_summary_from_buckets(
    buckets: Dict[str, Dict[str, Any]],
    config: AdmissionCalculationConfig,
) -> Dict[str, Any]:
    cumulative_gpa = buckets.get("cumulative", {}).get("gpa")
    english_gpa = buckets.get("english", {}).get("gpa")
    math_gpa = buckets.get("math", {}).get("gpa")
    science_gpa = buckets.get("science", {}).get("gpa")

    # CSULB Index = Cumulative GPA*200 + English GPA*500 + Math GPA*500
    # (CSU First-Time Freshman GPA-only index). Missing subject GPAs count as 0.
    csulb_score = (
        round(
            number_or_zero(cumulative_gpa) * CSULB_INDEX_CUMULATIVE_WEIGHT
            + number_or_zero(english_gpa) * CSULB_INDEX_ENGLISH_WEIGHT
            + number_or_zero(math_gpa) * CSULB_INDEX_MATH_WEIGHT
        )
        if cumulative_gpa is not None
        else None
    )

    # STEM GPA is the average of the Math and Science GPAs (shown as "STEM Score").
    stem_score = (
        round(((number_or_zero(math_gpa) + number_or_zero(science_gpa)) / 2), 3)
        if math_gpa is not None and science_gpa is not None
        else None
    )

    # STEM Index = Math GPA*600 + Science GPA*600, compared against the STEM
    # Index minimum (default 3600) from the institution criteria.
    stem_index = (
        round(
            number_or_zero(math_gpa) * STEM_INDEX_MATH_WEIGHT
            + number_or_zero(science_gpa) * STEM_INDEX_SCIENCE_WEIGHT
        )
        if math_gpa is not None and science_gpa is not None
        else None
    )

    return {
        "csulb_score": csulb_score,
        "cumulative_gpa": cumulative_gpa,
        "english_gpa": english_gpa,
        "math_gpa": math_gpa,
        "science_gpa": science_gpa,
        "stem_score": stem_score,
        "stem_index": stem_index,
        "csulb_score_multiplier": config.csulb_score_multiplier,
        "california_resident_min_gpa": config.california_resident_min_gpa,
        "non_resident_min_gpa": config.non_resident_min_gpa,
        "csulb_threshold": config.csulb_threshold,
        "non_resident_csulb_threshold": config.non_resident_csulb_threshold,
        "stem_index_threshold": config.stem_index_threshold,
        "stem_threshold": config.stem_threshold,
    }


def build_gpa_calculation(
    courses: List[Dict[str, Any]],
    config: Optional[AdmissionCalculationConfig] = None,
    manual_mappings: Optional[List[ManualAgMapping]] = None,
    gpa_bucket_edits: Optional[Dict[str, Any]] = None,
    school_key: str = "",
) -> Dict[str, Any]:
    config = config or AdmissionCalculationConfig()
    manual_map = make_manual_mapping_lookup(manual_mappings)

    # Grade levels are taken straight from the institution criteria — the
    # cumulative GPA (CSULB Index) and the subject GPAs use their own selections.
    cumulative_grades = list(config.gpa_cumulative_hs_grades or [10, 11, 12])
    subject_grades = list(config.gpa_hs_grades or [9, 10, 11, 12])

    buckets = {
        "cumulative": build_gpa_bucket(
            "Cumulative GPA Calc",
            courses,
            lambda course, index: (
                is_grade_level_allowed(course, cumulative_grades)
                and is_ag_eligible_for_gpa(course, index, manual_map)
            ),
            config,
            manual_map,
            school_key,
        ),
        "math": build_gpa_bucket(
            "Math GPA Calc",
            courses,
            lambda course, index: (
                is_grade_level_allowed(course, subject_grades)
                and get_subject_category_for_gpa(course, index, manual_map) == "c"
            ),
            config,
            manual_map,
            school_key,
        ),
        "english": build_gpa_bucket(
            "English GPA Calc",
            courses,
            lambda course, index: (
                is_grade_level_allowed(course, subject_grades)
                and get_subject_category_for_gpa(course, index, manual_map) == "b"
            ),
            config,
            manual_map,
            school_key,
        ),
        "science": build_gpa_bucket(
            "Science GPA Calc",
            courses,
            lambda course, index: (
                is_grade_level_allowed(course, subject_grades)
                and get_subject_category_for_gpa(course, index, manual_map) == "d"
            ),
            config,
            manual_map,
            school_key,
        ),
    }

    buckets = apply_gpa_bucket_edits(buckets, gpa_bucket_edits, config)

    return {
        "buckets": buckets,
        "score_summary": build_score_summary_from_buckets(buckets, config),
        "gpa_bucket_edits": normalize_gpa_bucket_edits(gpa_bucket_edits),
    }


# ---------------------------------------------------------------------------
# Admission decision
# ---------------------------------------------------------------------------

def build_admission_decision(
    ag_review: Dict[str, Any],
    gpa_calculation: Dict[str, Any],
    config: AdmissionCalculationConfig,
) -> Dict[str, Any]:
    rows = ag_review.get("rows") or []
    row_by_key = {clean_text(row.get("key")): row for row in rows}

    required_decision_keys = ["a", "b", "c", "d", "e", "f"]
    ag_deficits = []

    for key in required_decision_keys:
        row = row_by_key.get(key)

        if not row:
            ag_deficits.append(
                {
                    "key": key,
                    "label": AG_LABELS[key],
                    "def": config.ag_required[key],
                }
            )
            continue

        deficit = number_or_zero(row.get("def"))

        if deficit > 0:
            ag_deficits.append(
                {
                    "key": key,
                    "label": row.get("label") or AG_LABELS[key],
                    "def": deficit,
                }
            )

    ag_satisfied = len(ag_deficits) == 0
    g_row = row_by_key.get("g")
    g_deficit = number_or_zero(g_row.get("def")) if g_row else 0

    score_summary = gpa_calculation.get("score_summary") or {}
    cumulative_gpa = score_summary.get("cumulative_gpa")
    minimum_gpa = config.california_resident_min_gpa

    if cumulative_gpa is None:
        minimum_gpa_satisfied = False
    else:
        minimum_gpa_satisfied = number_or_zero(cumulative_gpa) >= minimum_gpa

    decision = "admitted" if ag_satisfied and minimum_gpa_satisfied else "denied"
    reason_parts: List[str] = []

    if decision == "admitted":
        if g_deficit > 0:
            reason_parts.append("Admitted: Required A-F areas are satisfied.")
        else:
            reason_parts.append("Admitted: A-G requirements are satisfied.")

        reason_parts.append(
            f"Minimum GPA is achieved: cumulative GPA {format_number(cumulative_gpa)} "
            f"is at or above {format_number(minimum_gpa)}."
        )
    else:
        denial_reasons: List[str] = []

        if not ag_satisfied:
            deficit_text = "; ".join(
                f"{item['label']} deficit {format_number(item['def'])}"
                for item in ag_deficits
            )
            denial_reasons.append(
                f"A-G requirements are not satisfied: {deficit_text}."
            )

        if not minimum_gpa_satisfied:
            if cumulative_gpa is None:
                denial_reasons.append(
                    f"Minimum GPA is not satisfied because cumulative GPA is unavailable. "
                    f"Required minimum GPA is {format_number(minimum_gpa)}."
                )
            else:
                denial_reasons.append(
                    f"Minimum GPA is not satisfied: cumulative GPA "
                    f"{format_number(cumulative_gpa)} is below {format_number(minimum_gpa)}."
                )

        reason_parts.append("Denied: " + " ".join(denial_reasons))

    if g_deficit > 0:
        reason_parts.append(
            f"G missing: College-Preparatory Elective (G) deficit {format_number(g_deficit)}. "
            "G is optional for this decision."
        )

    return {
        "recommended_decision": decision,
        "ag_satisfied_ignoring_g": ag_satisfied,
        "minimum_gpa_satisfied": minimum_gpa_satisfied,
        "g_is_optional": True,
        "g_deficit_ignored": g_deficit,
        "ag_deficits_ignoring_g": ag_deficits,
        "cumulative_gpa": cumulative_gpa,
        "minimum_gpa_required": minimum_gpa,
        "reason": " ".join(reason_parts),
    }


# ---------------------------------------------------------------------------
# CSULB First-Time Freshman FINAL AUDIT decision (Outcome 1 / 2 / 3)
# ---------------------------------------------------------------------------
# The final audit needs three inputs that do NOT come from the transcript
# (they live in the CSU application system): residency, whether the student is a
# STEM major, and LBUSD "Promise to the Beach" recruitment eligibility. These are
# accepted as explicit parameters; when not supplied we fall back to transparent
# defaults (CA resident, non-STEM, LBUSD derived from the high-school name) and
# echo every assumption back in the result so a reviewer can see/override them.

CA_RESIDENCY_VALUES = {"california", "ca", "resident", "ca_resident", "in_state", "in-state"}

# All US state abbreviations (used to read residency from the student's address).
US_STATE_ABBREVIATIONS = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}


def resolve_residency(student: Dict[str, Any], residency: Optional[str]) -> str:
    """Return 'california' or 'non_resident'. An explicit value wins. Otherwise we
    read the state from the student's residential address: a CA signal -> california,
    a different US state -> non_resident, nothing detectable -> default california."""
    if residency:
        return "california" if lower_text(residency) in CA_RESIDENCY_VALUES else "non_resident"

    address = clean_text(student.get("address") or student.get("s_address"))
    if address:
        upper = address.upper()
        if "CALIFORNIA" in upper:
            return "california"
        # Prefer a 2-letter state code right before a ZIP, e.g. "Long Beach, CA 90808".
        zip_state = re.search(r"\b([A-Z]{2})\b[ ,]+\d{5}", upper)
        if zip_state and zip_state.group(1) in US_STATE_ABBREVIATIONS:
            return "california" if zip_state.group(1) == "CA" else "non_resident"
        # Otherwise any standalone CA token means California.
        if re.search(r"\bCA\b", upper):
            return "california"
        # A clearly-present different state means non-resident.
        for state in US_STATE_ABBREVIATIONS - {"CA"}:
            if re.search(rf"\b{state}\b", upper):
                return "non_resident"
    # Default: treat as CA resident (the overwhelming majority); reviewer can override.
    return "california"


def _parse_year_from_term(value: Any) -> Optional[int]:
    match = re.search(r"(19|20)\d{2}", clean_text(value))
    return int(match.group(0)) if match else None


def graduation_meets_requirement(student: Dict[str, Any], required_by: Optional[str]) -> bool:
    """True if the student graduates by the required term. If no gate is configured
    or the graduation date is unknown, do not block on it (return True)."""
    if not required_by:
        return True

    required_year = _parse_year_from_term(required_by)
    if required_year is None:
        return True

    grad = student.get("graduation_date") or student.get("hs_graduation_date")
    grad_year = getattr(grad, "year", None) or _parse_year_from_term(grad)
    if grad_year is None:
        return True  # unknown graduation date — don't fail the audit on missing data

    return grad_year <= required_year


def build_final_audit_decision(
    ag_review: Dict[str, Any],
    gpa_calculation: Dict[str, Any],
    student: Dict[str, Any],
    config: AdmissionCalculationConfig,
    *,
    residency: Optional[str] = None,
    is_stem_major: bool = False,
    lbusd_promise: Optional[bool] = None,
) -> Dict[str, Any]:
    """Apply the CSULB FTFY Final Audit and return one of:
      - clear_admit               (Outcome 1)
      - clear_admit_lbusd_promise (Outcome 2 — LBUSD Promise to the Beach)
      - failed_audit_rescinded    (Outcome 3)
    """
    residency_resolved = resolve_residency(student, residency)
    is_ca = residency_resolved == "california"

    # Reuse the A-F satisfaction logic (G is optional) from the standard decision.
    base = build_admission_decision(ag_review, gpa_calculation, config)
    ag_satisfied = bool(base.get("ag_satisfied_ignoring_g"))

    score = gpa_calculation.get("score_summary") or {}
    cumulative_gpa = score.get("cumulative_gpa")
    csulb_index = score.get("csulb_score")
    stem_index = score.get("stem_index")

    min_gpa = config.california_resident_min_gpa if is_ca else config.non_resident_min_gpa
    csulb_min = config.csulb_threshold if is_ca else config.non_resident_csulb_threshold

    gpa_ok = cumulative_gpa is not None and number_or_zero(cumulative_gpa) >= min_gpa
    csulb_index_ok = csulb_index is not None and number_or_zero(csulb_index) >= csulb_min
    # STEM Index is only required for STEM majors.
    stem_index_ok = (not is_stem_major) or (
        stem_index is not None and number_or_zero(stem_index) >= config.stem_index_threshold
    )
    graduation_ok = graduation_meets_requirement(student, config.graduation_required_by)

    # LBUSD Promise to the Beach eligibility: explicit flag, else derived from the HS.
    if lbusd_promise is None:
        lbusd_promise = get_student_school_key(student) == "lbusd"

    checks = {
        "ag_completion": ag_satisfied,
        "gpa_minimum": gpa_ok,
        "csulb_index": csulb_index_ok,
        "stem_index": stem_index_ok,
        "hs_graduation": graduation_ok,
    }

    reasons: List[str] = []

    if ag_satisfied and gpa_ok and csulb_index_ok and stem_index_ok and graduation_ok:
        # Outcome 1 — Clear Admit
        outcome = "clear_admit"
        student_status = "A"  # Admitted to the University
        label = "Clear Admit"
        reasons.append(
            f"Clear Admit: A-G satisfied, cumulative GPA {format_number(cumulative_gpa)} "
            f">= {format_number(min_gpa)}, CSULB Index {format_number(csulb_index)} >= {csulb_min}"
            + (f", STEM Index {format_number(stem_index)} >= {config.stem_index_threshold}" if is_stem_major else "")
            + f" ({'CA resident' if is_ca else 'non-resident'})."
        )
    elif is_ca and lbusd_promise and ag_satisfied and gpa_ok and graduation_ok:
        # Outcome 2 — Clear Admit, LBUSD Promise to the Beach (below CSULB Index but
        # meets all CSU minimums).
        outcome = "clear_admit_lbusd_promise"
        student_status = "A"  # Admitted to the University
        label = "Clear Admit — LBUSD Promise to the Beach"
        reasons.append(
            "Clear Admit (LBUSD Promise to the Beach): below the CSULB Index minimum but "
            f"meets all CSU minimums — A-G satisfied and cumulative GPA "
            f"{format_number(cumulative_gpa)} >= {format_number(min_gpa)}."
        )
    else:
        # Outcome 3 — Failed Audit, Rescinded
        outcome = "failed_audit_rescinded"
        student_status = "rescinded"
        label = "Failed Audit — Rescinded"
        if not ag_satisfied:
            reasons.append("A-G requirements are not satisfied.")
        if not gpa_ok:
            reasons.append(
                f"Cumulative GPA {format_number(cumulative_gpa)} is below the "
                f"{format_number(min_gpa)} minimum."
            )
        if not csulb_index_ok:
            reasons.append(
                f"CSULB Index {format_number(csulb_index)} is below the {csulb_min} minimum"
                + (" and LBUSD Promise to the Beach does not apply." if not lbusd_promise else ".")
            )
        if is_stem_major and not stem_index_ok:
            reasons.append(
                f"STEM Index {format_number(stem_index)} is below the "
                f"{config.stem_index_threshold} minimum."
            )
        if not graduation_ok:
            reasons.append(
                f"HS graduation does not meet the required term ({config.graduation_required_by})."
            )

    return {
        "outcome": outcome,
        "label": label,
        "student_status": student_status,
        "checks": checks,
        "reason": " ".join(reasons),
        # Inputs / assumptions echoed back so a reviewer can verify or override.
        "inputs": {
            "residency": residency_resolved,
            "residency_was_provided": residency is not None,
            "is_stem_major": is_stem_major,
            "lbusd_promise": bool(lbusd_promise),
            "applied_min_gpa": min_gpa,
            "applied_csulb_index_min": csulb_min,
            "stem_index_min": config.stem_index_threshold,
            "graduation_required_by": config.graduation_required_by,
        },
    }


# ---------------------------------------------------------------------------
# Top-level payload builder
# ---------------------------------------------------------------------------

def apply_institution_course_overrides(
    courses: List[Dict[str, Any]],
    overrides: Optional[List[Dict[str, Any]]],
) -> None:
    """Reassign a course's A-G category per the institution's overrides — matched
    by the UC Doorways course name (+ discipline when the override specifies one),
    falling back to the raw course name for user-added courses. Overrides UC
    Doorways. target_ag 'exclude' drops the course from A-G entirely."""
    if not overrides:
        return

    by_name_disc: Dict[Tuple[str, str], str] = {}
    by_name: Dict[str, str] = {}
    for o in overrides:
        name = lower_text(o.get("course_name"))
        if not name:
            continue
        target = lower_text(o.get("target_ag"))
        disc = lower_text(o.get("discipline"))
        if disc:
            by_name_disc[(name, disc)] = target
        else:
            by_name[name] = target

    for course in courses:
        mapped = get_mapped_course(course)
        cname = lower_text(mapped.get("crs_description")) or lower_text(course.get("name"))
        if not cname:
            continue
        target = by_name_disc.get((cname, get_uc_discipline(course))) or by_name.get(cname)
        if not target:
            continue
        if target in ("exclude", "remove", "removed", "none"):
            course["_non_academic"] = True
            continue
        if target in VALID_AG_LETTERS:
            m = course.get("mapped_uc_course")
            if not isinstance(m, dict):
                m = {}
                course["mapped_uc_course"] = m
            m["crs_ag_category_letter"] = target
            course["standardizedCode"] = target
            course["_ag_override"] = target


def build_admission_review_payload(
    student: Dict[str, Any],
    config: Optional[AdmissionCalculationConfig] = None,
    manual_mappings: Optional[List[ManualAgMapping]] = None,
    gpa_bucket_edits: Optional[Dict[str, Any]] = None,
    institution_codes: Optional[List[Dict[str, Any]]] = None,
    final_audit_inputs: Optional[Dict[str, Any]] = None,
    institution_course_overrides: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    courses = student.get("courses") or []
    config = config or AdmissionCalculationConfig()
    school_key = get_student_school_key(student)

    # Apply the institution's configured transcript codes (e.g. '*' = non-academic,
    # '+' = honors) so they actually drive A-G counting and honors detection.
    apply_transcript_codes(courses, institution_codes)

    # Institution course->A-G reassignments (override UC Doorways).
    apply_institution_course_overrides(courses, institution_course_overrides)

    ag_review = build_ag_review(
        courses=courses,
        config=config,
        manual_mappings=manual_mappings,
    )

    gpa_calculation = build_gpa_calculation(
        courses=courses,
        config=config,
        manual_mappings=manual_mappings,
        gpa_bucket_edits=gpa_bucket_edits,
        school_key=school_key,
    )

    admission_decision = build_admission_decision(
        ag_review=ag_review,
        gpa_calculation=gpa_calculation,
        config=config,
    )

    final_audit_inputs = final_audit_inputs or {}
    final_audit = build_final_audit_decision(
        ag_review=ag_review,
        gpa_calculation=gpa_calculation,
        student=student,
        config=config,
        residency=final_audit_inputs.get("residency"),
        is_stem_major=bool(final_audit_inputs.get("is_stem_major", False)),
        lbusd_promise=final_audit_inputs.get("lbusd_promise"),
    )

    # The recommended decision follows the comprehensive Final Audit (A-G, GPA,
    # CSULB/STEM Index, graduation, residency, LBUSD Promise) rather than the
    # simpler A-F + GPA pre-check. The pre-check result is kept for reference.
    audit_outcome = final_audit.get("outcome")
    admission_decision["precheck_decision"] = admission_decision.get("recommended_decision")
    admission_decision["recommended_decision"] = (
        "admitted"
        if audit_outcome in ("clear_admit", "clear_admit_lbusd_promise")
        else "denied"
    )
    admission_decision["recommended_from_final_audit"] = True
    if final_audit.get("reason"):
        admission_decision["reason"] = final_audit["reason"]

    return {
        "student": {
            "id": student.get("id") or student.get("db_id") or student.get("student_id"),
            "student_id": student.get("student_id") or student.get("studentId"),
            "student_name": student.get("student_name") or student.get("studentName"),
            "format": student.get("format"),
            "school_key": school_key,
        },
        "ag_review": ag_review,
        "gpa_calculation": gpa_calculation,
        "admission_decision": admission_decision,
        "final_audit": final_audit,
        "config": {
            "ag_required": config.ag_required,
            "grade_points": config.grade_points,
            "honors_bonus_points": config.honors_bonus_points,
            "honors_max_semesters": config.honors_max_semesters,
            "honors_max_10th_grade_semesters": config.honors_max_10th_grade_semesters,
            "csulb_score_multiplier": config.csulb_score_multiplier,
            "california_resident_min_gpa": config.california_resident_min_gpa,
            "non_resident_min_gpa": config.non_resident_min_gpa,
            "csulb_threshold": config.csulb_threshold,
            "non_resident_csulb_threshold": config.non_resident_csulb_threshold,
            "stem_index_threshold": config.stem_index_threshold,
            "stem_threshold": config.stem_threshold,
            "graduation_required_by": config.graduation_required_by,
        },
    }
