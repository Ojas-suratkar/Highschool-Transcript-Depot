"""Map final_course_details to UC doorway courses (validated layer)

Adds a DB trigger that maps each final_course_details row (the validated,
reconciled output) to a UC doorway course and links the mapping via
final_course_details_id — which the frontend A-G / GPA tabs join on directly.

Previously only course_details (raw Document AI) was mapped, linked via
course_details_id, so the validated rows shown in the UI had no UC mapping
unless a fragile document_ai_course_detail_id fallback happened to resolve.

Mirrors the 16-step logic of map_course_on_insert() but reads from
final_course_details and writes final_course_details_id.

Revision ID: zz_final_course_mapping_trigger
Revises: c3ccf2bea1dc
Create Date: 2026-06-08
"""

from alembic import op

revision = "zz_final_course_mapping_trigger"
down_revision = "c3ccf2bea1dc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE OR REPLACE FUNCTION map_final_course_on_insert()
RETURNS TRIGGER AS $$
DECLARE
    v_school_name  TEXT;
    v_school_ids   BIGINT[];
    v_school_found BOOLEAN := FALSE;
    v_course_code  TEXT;
    v_year_a       TEXT;
    v_year_b       TEXT;
    v_uc_id        BIGINT := NULL;
    v_status       TEXT;
    v_code_ids     BIGINT[];
BEGIN
    SELECT COALESCE(NULLIF(TRIM(sd.hs_name), ''), NULLIF(TRIM(NEW.crs_hs), ''))
    INTO v_school_name
    FROM student_details sd WHERE sd.id = NEW.s_id;
    IF v_school_name IS NULL THEN v_school_name := NULLIF(TRIM(NEW.crs_hs), ''); END IF;

    v_school_ids := ARRAY[]::BIGINT[];
    IF v_school_name IS NOT NULL AND v_school_name <> '' THEN
        SELECT ARRAY_AGG(id) INTO v_school_ids FROM uc_doorway_schools
        WHERE LOWER(TRIM(hs_name)) = LOWER(v_school_name);
        IF v_school_ids IS NULL OR array_length(v_school_ids, 1) IS NULL THEN
            SELECT ARRAY_AGG(id) INTO v_school_ids FROM uc_doorway_schools
            WHERE LOWER(TRIM(hs_name)) LIKE '%' || LOWER(v_school_name) || '%';
        END IF;
        IF v_school_ids IS NOT NULL AND array_length(v_school_ids, 1) > 0 THEN
            v_school_found := TRUE;
        ELSE
            v_school_ids := ARRAY[]::BIGINT[];
        END IF;
    END IF;

    IF NEW.crs_year IS NOT NULL THEN
        v_year_a := CONCAT(NEW.crs_year::TEXT, '-',
                           LPAD(((NEW.crs_year + 1) % 100)::TEXT, 2, '0'));
        v_year_b := CONCAT((NEW.crs_year - 1)::TEXT, '-',
                           LPAD((NEW.crs_year % 100)::TEXT, 2, '0'));
    END IF;

    IF NEW.crs_id IS NOT NULL AND TRIM(NEW.crs_id) <> '' THEN
        v_course_code := LOWER(REGEXP_REPLACE(TRIM(NEW.crs_id), '^[A-Za-z]+\\s+', ''));
    END IF;

    -- Step 1: local code + school + year + exact title/abbrev
    IF v_school_found AND v_course_code IS NOT NULL AND v_year_a IS NOT NULL THEN
        SELECT crs_id INTO v_uc_id
        FROM uc_doorway_courses_search_index si
        WHERE si.hs_id = ANY(v_school_ids)
          AND si.search_type = 'crs_local_codes'
          AND LOWER(si.search_value) = v_course_code
          AND si.crs_academic_year IN (v_year_a, v_year_b)
          AND LOWER((SELECT crs_description FROM uc_doorway_courses WHERE id = si.crs_id))
              = LOWER(NEW.crs_description)
        LIMIT 1;
        IF v_uc_id IS NOT NULL THEN v_status := 'matched_local_code_year_exact_title'; END IF;

        IF v_uc_id IS NULL THEN
            SELECT si.crs_id INTO v_uc_id
            FROM uc_doorway_courses_search_index si
            JOIN uc_doorway_courses_search_index sa ON sa.crs_id = si.crs_id
            WHERE si.hs_id = ANY(v_school_ids)
              AND si.search_type = 'crs_local_codes'
              AND LOWER(si.search_value) = v_course_code
              AND si.crs_academic_year IN (v_year_a, v_year_b)
              AND sa.search_type = 'crs_transcript_abbrevs'
              AND LOWER(sa.search_value) = LOWER(NEW.crs_description)
              AND sa.crs_academic_year IN (v_year_a, v_year_b)
            LIMIT 1;
            IF v_uc_id IS NOT NULL THEN v_status := 'matched_local_code_year_exact_title'; END IF;
        END IF;
    END IF;

    -- Step 2: local code + school + no year + exact title
    IF v_uc_id IS NULL AND v_school_found AND v_course_code IS NOT NULL THEN
        SELECT ARRAY_AGG(crs_id) INTO v_code_ids
        FROM uc_doorway_courses_search_index
        WHERE hs_id = ANY(v_school_ids)
          AND search_type = 'crs_local_codes'
          AND LOWER(search_value) = v_course_code;
        IF v_code_ids IS NOT NULL AND array_length(v_code_ids, 1) > 0 THEN
            SELECT id INTO v_uc_id FROM uc_doorway_courses
            WHERE id = ANY(v_code_ids) AND LOWER(crs_description) = LOWER(NEW.crs_description)
            LIMIT 1;
            IF v_uc_id IS NOT NULL THEN v_status := 'matched_local_code_exact_title'; END IF;
        END IF;
    END IF;

    -- Step 3: general code + no school + year + exact title
    IF v_uc_id IS NULL AND v_course_code IS NOT NULL AND v_year_a IS NOT NULL THEN
        SELECT crs_id INTO v_uc_id
        FROM uc_doorway_courses_search_index si
        WHERE si.search_type = 'crs_local_codes'
          AND LOWER(si.search_value) = v_course_code
          AND si.crs_academic_year IN (v_year_a, v_year_b)
          AND LOWER((SELECT crs_description FROM uc_doorway_courses WHERE id = si.crs_id))
              = LOWER(NEW.crs_description)
        LIMIT 1;
        IF v_uc_id IS NOT NULL THEN
            v_status := CASE
                WHEN v_school_name IS NULL OR v_school_name = '' THEN 'school_missing_mapped_with_general_codes_year'
                WHEN NOT v_school_found THEN 'school_not_found_mapped_with_general_codes_year'
                ELSE 'mapped_with_general_codes_year' END;
        END IF;
    END IF;

    -- Step 4: general code + no school + no year + exact title
    IF v_uc_id IS NULL AND v_course_code IS NOT NULL THEN
        SELECT ARRAY_AGG(crs_id) INTO v_code_ids
        FROM uc_doorway_courses_search_index
        WHERE search_type = 'crs_local_codes' AND LOWER(search_value) = v_course_code;
        IF v_code_ids IS NOT NULL AND array_length(v_code_ids, 1) > 0 THEN
            SELECT id INTO v_uc_id FROM uc_doorway_courses
            WHERE id = ANY(v_code_ids) AND LOWER(crs_description) = LOWER(NEW.crs_description)
            LIMIT 1;
            IF v_uc_id IS NOT NULL THEN
                v_status := CASE
                    WHEN v_school_name IS NULL OR v_school_name = '' THEN 'school_missing_mapped_with_general_codes'
                    WHEN NOT v_school_found THEN 'school_not_found_mapped_with_general_codes'
                    ELSE 'mapped_with_general_codes' END;
            END IF;
        END IF;
    END IF;

    -- Step 5: abbreviation + school + year
    IF v_uc_id IS NULL AND v_school_found AND NEW.crs_description IS NOT NULL AND v_year_a IS NOT NULL THEN
        SELECT crs_id INTO v_uc_id FROM uc_doorway_courses_search_index
        WHERE hs_id = ANY(v_school_ids)
          AND search_type = 'crs_transcript_abbrevs'
          AND LOWER(search_value) = LOWER(NEW.crs_description)
          AND crs_academic_year IN (v_year_a, v_year_b)
        LIMIT 1;
        IF v_uc_id IS NOT NULL THEN v_status := 'matched_abbrev_year'; END IF;
    END IF;

    -- Step 6: abbreviation + school + no year
    IF v_uc_id IS NULL AND v_school_found AND NEW.crs_description IS NOT NULL THEN
        SELECT crs_id INTO v_uc_id FROM uc_doorway_courses_search_index
        WHERE hs_id = ANY(v_school_ids)
          AND search_type = 'crs_transcript_abbrevs'
          AND LOWER(search_value) = LOWER(NEW.crs_description)
        LIMIT 1;
        IF v_uc_id IS NOT NULL THEN v_status := 'matched_abbrev'; END IF;
    END IF;

    -- Step 7: abbreviation + no school + year
    IF v_uc_id IS NULL AND NEW.crs_description IS NOT NULL AND v_year_a IS NOT NULL THEN
        SELECT crs_id INTO v_uc_id FROM uc_doorway_courses_search_index
        WHERE search_type = 'crs_transcript_abbrevs'
          AND LOWER(search_value) = LOWER(NEW.crs_description)
          AND crs_academic_year IN (v_year_a, v_year_b)
        LIMIT 1;
        IF v_uc_id IS NOT NULL THEN
            v_status := CASE
                WHEN v_school_name IS NULL OR v_school_name = '' THEN 'school_missing_matched_abbrev_year'
                WHEN NOT v_school_found THEN 'school_not_found_matched_abbrev_year'
                ELSE 'matched_abbrev_year_without_school' END;
        END IF;
    END IF;

    -- Step 8: abbreviation + no school + no year
    IF v_uc_id IS NULL AND NEW.crs_description IS NOT NULL THEN
        SELECT crs_id INTO v_uc_id FROM uc_doorway_courses_search_index
        WHERE search_type = 'crs_transcript_abbrevs'
          AND LOWER(search_value) = LOWER(NEW.crs_description)
        LIMIT 1;
        IF v_uc_id IS NOT NULL THEN
            v_status := CASE
                WHEN v_school_name IS NULL OR v_school_name = '' THEN 'school_missing_matched_abbrev'
                WHEN NOT v_school_found THEN 'school_not_found_matched_abbrev'
                ELSE 'matched_abbrev_without_school' END;
        END IF;
    END IF;

    -- Step 9: exact crs_description + school + year
    IF v_uc_id IS NULL AND v_school_found AND NEW.crs_description IS NOT NULL AND v_year_a IS NOT NULL THEN
        SELECT id INTO v_uc_id FROM uc_doorway_courses
        WHERE hs_id = ANY(v_school_ids)
          AND LOWER(crs_description) = LOWER(NEW.crs_description)
          AND crs_academic_year IN (v_year_a, v_year_b)
        LIMIT 1;
        IF v_uc_id IS NOT NULL THEN v_status := 'matched_exact_course_description_year'; END IF;
    END IF;

    -- Step 10: exact crs_description + school + no year
    IF v_uc_id IS NULL AND v_school_found AND NEW.crs_description IS NOT NULL THEN
        SELECT id INTO v_uc_id FROM uc_doorway_courses
        WHERE hs_id = ANY(v_school_ids) AND LOWER(crs_description) = LOWER(NEW.crs_description)
        LIMIT 1;
        IF v_uc_id IS NOT NULL THEN v_status := 'matched_exact_course_description'; END IF;
    END IF;

    -- Step 11: exact crs_description + no school + year
    IF v_uc_id IS NULL AND NEW.crs_description IS NOT NULL AND v_year_a IS NOT NULL THEN
        SELECT id INTO v_uc_id FROM uc_doorway_courses
        WHERE LOWER(crs_description) = LOWER(NEW.crs_description)
          AND crs_academic_year IN (v_year_a, v_year_b)
        LIMIT 1;
        IF v_uc_id IS NOT NULL THEN
            v_status := CASE
                WHEN v_school_name IS NULL OR v_school_name = '' THEN 'school_missing_matched_exact_course_description_year'
                WHEN NOT v_school_found THEN 'school_missing_matched_exact_course_description_year'
                ELSE 'matched_exact_course_description_year_without_school' END;
        END IF;
    END IF;

    -- Step 12: exact crs_description + no school + no year
    IF v_uc_id IS NULL AND NEW.crs_description IS NOT NULL THEN
        SELECT id INTO v_uc_id FROM uc_doorway_courses
        WHERE LOWER(crs_description) = LOWER(NEW.crs_description)
        LIMIT 1;
        IF v_uc_id IS NOT NULL THEN
            v_status := CASE
                WHEN v_school_name IS NULL OR v_school_name = '' THEN 'school_missing_matched_exact_course_description'
                WHEN NOT v_school_found THEN 'school_not_found_matched_exact_course_description'
                ELSE 'matched_exact_course_description_without_school' END;
        END IF;
    END IF;

    -- Step 13: normalized title + school + year
    IF v_uc_id IS NULL AND v_school_found AND NEW.crs_description IS NOT NULL AND v_year_a IS NOT NULL THEN
        SELECT id INTO v_uc_id FROM uc_doorway_courses
        WHERE hs_id = ANY(v_school_ids) AND crs_academic_year IN (v_year_a, v_year_b)
          AND canonical_title_key(crs_description) = canonical_title_key(NEW.crs_description)
        LIMIT 1;
        IF v_uc_id IS NULL THEN
            SELECT id INTO v_uc_id FROM uc_doorway_courses
            WHERE hs_id = ANY(v_school_ids) AND crs_academic_year IN (v_year_a, v_year_b)
              AND compact_title_key(crs_description) = compact_title_key(NEW.crs_description)
            LIMIT 1;
        END IF;
        IF v_uc_id IS NOT NULL THEN v_status := 'matched_normalized_title_sql_school_year'; END IF;
    END IF;

    -- Step 14: normalized title + school + no year
    IF v_uc_id IS NULL AND v_school_found AND NEW.crs_description IS NOT NULL THEN
        SELECT id INTO v_uc_id FROM uc_doorway_courses
        WHERE hs_id = ANY(v_school_ids)
          AND canonical_title_key(crs_description) = canonical_title_key(NEW.crs_description)
        LIMIT 1;
        IF v_uc_id IS NULL THEN
            SELECT id INTO v_uc_id FROM uc_doorway_courses
            WHERE hs_id = ANY(v_school_ids)
              AND compact_title_key(crs_description) = compact_title_key(NEW.crs_description)
            LIMIT 1;
        END IF;
        IF v_uc_id IS NOT NULL THEN v_status := 'matched_normalized_title_sql_school'; END IF;
    END IF;

    -- Step 15: normalized title + no school + year
    IF v_uc_id IS NULL AND NEW.crs_description IS NOT NULL AND v_year_a IS NOT NULL THEN
        SELECT id INTO v_uc_id FROM uc_doorway_courses
        WHERE crs_academic_year IN (v_year_a, v_year_b)
          AND canonical_title_key(crs_description) = canonical_title_key(NEW.crs_description)
        LIMIT 1;
        IF v_uc_id IS NULL THEN
            SELECT id INTO v_uc_id FROM uc_doorway_courses
            WHERE crs_academic_year IN (v_year_a, v_year_b)
              AND compact_title_key(crs_description) = compact_title_key(NEW.crs_description)
            LIMIT 1;
        END IF;
        IF v_uc_id IS NOT NULL THEN
            v_status := CASE
                WHEN v_school_name IS NULL OR v_school_name = '' THEN 'school_missing_matched_normalized_title_sql_year'
                WHEN NOT v_school_found THEN 'school_not_found_matched_normalized_title_sql_year'
                ELSE 'matched_normalized_title_sql_year_without_school' END;
        END IF;
    END IF;

    -- Step 16: normalized title + no school + no year
    IF v_uc_id IS NULL AND NEW.crs_description IS NOT NULL THEN
        SELECT id INTO v_uc_id FROM uc_doorway_courses
        WHERE canonical_title_key(crs_description) = canonical_title_key(NEW.crs_description)
        LIMIT 1;
        IF v_uc_id IS NULL THEN
            SELECT id INTO v_uc_id FROM uc_doorway_courses
            WHERE compact_title_key(crs_description) = compact_title_key(NEW.crs_description)
            LIMIT 1;
        END IF;
        IF v_uc_id IS NOT NULL THEN
            v_status := CASE
                WHEN v_school_name IS NULL OR v_school_name = '' THEN 'school_missing_matched_normalized_title_sql'
                WHEN NOT v_school_found THEN 'school_not_found_matched_normalized_title_sql'
                ELSE 'matched_normalized_title_sql_without_school' END;
        END IF;
    END IF;

    IF v_uc_id IS NULL THEN
        v_status := CASE
            WHEN v_school_name IS NULL OR v_school_name = '' THEN 'school_missing'
            WHEN NOT v_school_found THEN 'school_not_found'
            ELSE 'no_match' END;
    END IF;

    INSERT INTO course_detail_mapping_uc_doorway_courses
        (final_course_details_id, uc_doorway_courses_id, mapping_status, mapped_at)
    VALUES (NEW.id, v_uc_id, v_status, NOW())
    ON CONFLICT (final_course_details_id) DO UPDATE
        SET uc_doorway_courses_id = EXCLUDED.uc_doorway_courses_id,
            mapping_status        = EXCLUDED.mapping_status,
            mapped_at             = EXCLUDED.mapped_at;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
    """)

    op.execute("""
        DROP TRIGGER IF EXISTS final_course_mapping_after_insert ON final_course_details;
        CREATE TRIGGER final_course_mapping_after_insert
        AFTER INSERT ON final_course_details
        FOR EACH ROW EXECUTE FUNCTION map_final_course_on_insert();
    """)

    # Drop the raw-table trigger: mapping now runs on the validated final rows.
    # Keeping both would map every course twice during extraction (raw + final),
    # doubling latency. The validated rows are the ones the UI/admission logic use.
    op.execute("DROP TRIGGER IF EXISTS course_mapping_after_insert ON course_details;")

    # Backfill mapping links for existing final_course_details rows so already
    # extracted terms immediately show UC mappings in the A-G / GPA tabs.
    op.execute("""
        INSERT INTO course_detail_mapping_uc_doorway_courses
            (final_course_details_id, uc_doorway_courses_id, mapping_status, mapped_at)
        SELECT fcd.id, m.uc_doorway_courses_id, m.mapping_status, NOW()
        FROM final_course_details fcd
        JOIN course_detail_mapping_uc_doorway_courses m
             ON m.course_details_id = fcd.document_ai_course_detail_id
        WHERE fcd.document_ai_course_detail_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM course_detail_mapping_uc_doorway_courses x
            WHERE x.final_course_details_id = fcd.id
          )
        ON CONFLICT (final_course_details_id) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS final_course_mapping_after_insert ON final_course_details;")
    op.execute("DROP FUNCTION IF EXISTS map_final_course_on_insert();")
    # Restore the raw-table trigger
    op.execute("""
        DROP TRIGGER IF EXISTS course_mapping_after_insert ON course_details;
        CREATE TRIGGER course_mapping_after_insert
        AFTER INSERT ON course_details
        FOR EACH ROW EXECUTE FUNCTION map_course_on_insert();
    """)
