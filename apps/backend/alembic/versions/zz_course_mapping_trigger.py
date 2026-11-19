"""Add DB-level UC doorway mapping trigger on course_details

Revision ID: zz_course_mapping_trigger
Revises:
Create Date: 2026-05-17
"""

from alembic import op

revision = "zz_course_mapping_trigger"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Indexes to support the trigger's queries efficiently
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_si_type_lower_value_year
        ON uc_doorway_courses_search_index
        USING btree (search_type, lower(search_value), crs_academic_year);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_udc_canonical_year_only
        ON uc_doorway_courses
        USING btree (crs_academic_year, canonical_title_key(crs_description));
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_udc_canonical_only
        ON uc_doorway_courses
        USING btree (canonical_title_key(crs_description));
    """)

    # 16-step UC doorway mapping trigger — mirrors process_single_course() in Python
    op.execute("""
CREATE OR REPLACE FUNCTION map_course_on_insert()
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
        v_course_code := LOWER(REGEXP_REPLACE(TRIM(NEW.crs_id), '^[A-Za-z]+\s+', ''));
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
        (course_details_id, uc_doorway_courses_id, mapping_status, mapped_at)
    VALUES (NEW.id, v_uc_id, v_status, NOW())
    ON CONFLICT (course_details_id) DO UPDATE
        SET uc_doorway_courses_id = EXCLUDED.uc_doorway_courses_id,
            mapping_status        = EXCLUDED.mapping_status,
            mapped_at             = EXCLUDED.mapped_at;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
    """)

    op.execute("""
        DROP TRIGGER IF EXISTS course_mapping_after_insert ON course_details;
        CREATE TRIGGER course_mapping_after_insert
        AFTER INSERT ON course_details
        FOR EACH ROW EXECUTE FUNCTION map_course_on_insert();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS course_mapping_after_insert ON course_details;")
    op.execute("DROP FUNCTION IF EXISTS map_course_on_insert();")
    op.execute("DROP INDEX IF EXISTS idx_si_type_lower_value_year;")
    op.execute("DROP INDEX IF EXISTS idx_udc_canonical_year_only;")
    op.execute("DROP INDEX IF EXISTS idx_udc_canonical_only;")
