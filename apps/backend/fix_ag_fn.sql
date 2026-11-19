CREATE OR REPLACE FUNCTION compute_student_ag_summary(p_student_id BIGINT)
RETURNS VOID
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_gpa_extracted   DOUBLE PRECISION;
    v_year_intake     TEXT;
    v_a_calc          DOUBLE PRECISION := 0;
    v_b_calc          DOUBLE PRECISION := 0;
    v_c_calc          DOUBLE PRECISION := 0;
    v_d1_calc         DOUBLE PRECISION := 0;
    v_d2_calc         DOUBLE PRECISION := 0;
    v_d_calc          DOUBLE PRECISION := 0;
    v_e_calc          DOUBLE PRECISION := 0;
    v_f_calc          DOUBLE PRECISION := 0;
    v_g_calc          DOUBLE PRECISION := 0;
    v_gpa_cumulative  DOUBLE PRECISION;
    v_gpa_english     DOUBLE PRECISION;
    v_gpa_math        DOUBLE PRECISION;
    v_gpa_science     DOUBLE PRECISION;
    v_stem_score      DOUBLE PRECISION;
    v_csulb_score     DOUBLE PRECISION;
BEGIN
    SELECT sd.hs_total_gpa_course, ef.year_intake
    INTO v_gpa_extracted, v_year_intake
    FROM student_details sd
    LEFT JOIN extraction_file_details ef ON ef.id = sd.source_file
    WHERE sd.id = p_student_id;

    WITH raw AS (
        SELECT
            CASE LOWER(uc.crs_ag_category_letter)
                WHEN 'd' THEN
                    CASE
                        WHEN LOWER(uc.crs_discipline) LIKE '%biology%'
                          OR LOWER(uc.crs_discipline) LIKE '%life science%'
                            THEN 'D1'
                        WHEN LOWER(uc.crs_discipline) IN (
                                'chemistry', 'physics',
                                'earth and space sciences',
                                'engineering', 'computer science')
                          OR LOWER(uc.crs_discipline) LIKE 'chemistry/%'
                          OR LOWER(uc.crs_discipline) LIKE 'physics/%'
                            THEN 'D2'
                        WHEN LOWER(COALESCE(uc.crs_description, cd.crs_description, ''))
                             ~ '(biochem|biophys)'
                            THEN 'D2'
                        WHEN LOWER(COALESCE(uc.crs_description, cd.crs_description, ''))
                             ~ '(\mbiol|\banatomy|\bphysiol|\bmarine|\becolog|\bbotan|\bzoolog|\bgenetic|\bmicrobiol|life science|\borganism|\bagri|\bbiotech|\bneurosci|\bpatholog|\bimmunol)'
                            THEN 'D1'
                        WHEN LOWER(COALESCE(uc.crs_description, cd.crs_description, ''))
                             ~ '(\bchem|\bphysics|\bearth\M|\bgeolog|\bgeosci|\bastro|\bocean|\bmeteor|\benviron|engineering|computer sci|\belectric|\bthermo|\bnuclear|\bquantum)'
                            THEN 'D2'
                        ELSE 'D'
                    END
                WHEN 'a' THEN 'A'
                WHEN 'b' THEN 'B'
                WHEN 'c' THEN 'C'
                WHEN 'e' THEN 'E'
                WHEN 'f' THEN 'F'
                WHEN 'g' THEN 'G'
                ELSE NULL
            END AS ag_key,
            CASE UPPER(TRIM(COALESCE(cd.crs_letter_grade, '')))
                WHEN 'A+' THEN 4.0  WHEN 'A'  THEN 4.0
                WHEN 'A-' THEN 3.7
                WHEN 'B+' THEN 3.3  WHEN 'B'  THEN 3.0
                WHEN 'B-' THEN 2.7
                WHEN 'C+' THEN 2.3  WHEN 'C'  THEN 2.0
                WHEN 'C-' THEN 1.7
                WHEN 'D'  THEN 1.0
                WHEN 'F'  THEN 0.0
                ELSE NULL
            END AS grade_pts,
            (
                cd.crs_letter_grade IS NOT NULL
                AND cd.crs_letter_grade <> ''
                AND UPPER(TRIM(cd.crs_letter_grade)) NOT LIKE 'D%'
                AND UPPER(TRIM(cd.crs_letter_grade)) NOT LIKE 'F%'
                AND UPPER(TRIM(cd.crs_letter_grade)) IN
                    ('A','A+','A-','B','B+','B-','C','C+','C-')
            ) AS valid_for_ag_count,
            cd.crs_grade AS hs_grade
        FROM course_details cd
        JOIN course_detail_mapping_uc_doorway_courses m ON m.course_details_id = cd.id
        JOIN uc_doorway_courses uc ON uc.id = m.uc_doorway_courses_id
        WHERE cd.s_id = p_student_id
          AND uc.crs_ag_category_letter IS NOT NULL
    ),
    agg AS (
        SELECT
            ag_key,
            SUM(CASE WHEN valid_for_ag_count THEN 1 ELSE 0 END)::DOUBLE PRECISION AS cnt,
            SUM(CASE WHEN (hs_grade IS NULL OR hs_grade IN (10,11,12))
                     THEN grade_pts ELSE NULL END)                                  AS cum_sum_pts,
            COUNT(CASE WHEN (hs_grade IS NULL OR hs_grade IN (10,11,12))
                        AND grade_pts IS NOT NULL THEN 1 END)::DOUBLE PRECISION     AS cum_grade_cnt,
            SUM(CASE WHEN (hs_grade IS NULL OR hs_grade IN (9,10,11,12))
                     THEN grade_pts ELSE NULL END)                                  AS sub_sum_pts,
            COUNT(CASE WHEN (hs_grade IS NULL OR hs_grade IN (9,10,11,12))
                        AND grade_pts IS NOT NULL THEN 1 END)::DOUBLE PRECISION     AS sub_grade_cnt
        FROM raw
        WHERE ag_key IS NOT NULL
        GROUP BY ag_key
    )
    SELECT
        COALESCE(SUM(cnt) FILTER (WHERE ag_key = 'A'), 0),
        COALESCE(SUM(cnt) FILTER (WHERE ag_key = 'B'), 0),
        COALESCE(SUM(cnt) FILTER (WHERE ag_key = 'C'), 0),
        COALESCE(SUM(cnt) FILTER (WHERE ag_key = 'D1'), 0),
        COALESCE(SUM(cnt) FILTER (WHERE ag_key = 'D2'), 0),
        COALESCE(SUM(cnt) FILTER (WHERE ag_key IN ('D','D1','D2')), 0),
        COALESCE(SUM(cnt) FILTER (WHERE ag_key = 'E'), 0),
        COALESCE(SUM(cnt) FILTER (WHERE ag_key = 'F'), 0),
        COALESCE(SUM(cnt) FILTER (WHERE ag_key = 'G'), 0),
        CASE WHEN SUM(cum_grade_cnt) > 0
             THEN ROUND(CAST(SUM(cum_sum_pts) / SUM(cum_grade_cnt) AS NUMERIC), 3)::DOUBLE PRECISION
             ELSE NULL END,
        CASE WHEN SUM(sub_grade_cnt) FILTER (WHERE ag_key = 'B') > 0
             THEN ROUND(CAST(SUM(sub_sum_pts) FILTER (WHERE ag_key = 'B') /
                             SUM(sub_grade_cnt) FILTER (WHERE ag_key = 'B') AS NUMERIC), 3)::DOUBLE PRECISION
             ELSE NULL END,
        CASE WHEN SUM(sub_grade_cnt) FILTER (WHERE ag_key = 'C') > 0
             THEN ROUND(CAST(SUM(sub_sum_pts) FILTER (WHERE ag_key = 'C') /
                             SUM(sub_grade_cnt) FILTER (WHERE ag_key = 'C') AS NUMERIC), 3)::DOUBLE PRECISION
             ELSE NULL END,
        CASE WHEN SUM(sub_grade_cnt) FILTER (WHERE ag_key IN ('D','D1','D2')) > 0
             THEN ROUND(CAST(SUM(sub_sum_pts)   FILTER (WHERE ag_key IN ('D','D1','D2')) /
                             SUM(sub_grade_cnt) FILTER (WHERE ag_key IN ('D','D1','D2')) AS NUMERIC), 3)::DOUBLE PRECISION
             ELSE NULL END
    INTO
        v_a_calc, v_b_calc, v_c_calc, v_d1_calc, v_d2_calc, v_d_calc,
        v_e_calc, v_f_calc, v_g_calc,
        v_gpa_cumulative, v_gpa_english, v_gpa_math, v_gpa_science
    FROM agg;

    v_csulb_score := CASE WHEN v_gpa_cumulative IS NOT NULL
                          THEN ROUND(v_gpa_cumulative * 800)
                          ELSE NULL END;
    v_stem_score  := CASE WHEN v_gpa_math IS NOT NULL AND v_gpa_science IS NOT NULL
                          THEN ROUND(CAST((v_gpa_math + v_gpa_science) / 2 AS NUMERIC), 3)::DOUBLE PRECISION
                          ELSE NULL END;

    -- INSERT: only fill calc columns. Override columns stay NULL until user presses Confirm Edit.
    INSERT INTO student_ag_summary (
        student_id,
        a_calc, b_calc, c_calc, d1_calc, d2_calc, d_calc, e_calc, f_calc, g_calc,
        gpa_extracted, gpa_cumulative, gpa_english, gpa_math, gpa_science,
        stem_score, csulb_score,
        year_intake, updated_at
    ) VALUES (
        p_student_id,
        v_a_calc, v_b_calc, v_c_calc, v_d1_calc, v_d2_calc, v_d_calc,
        v_e_calc, v_f_calc, v_g_calc,
        v_gpa_extracted, v_gpa_cumulative, v_gpa_english, v_gpa_math, v_gpa_science,
        v_stem_score, v_csulb_score,
        v_year_intake, NOW()
    )
    ON CONFLICT (student_id) DO UPDATE SET
        -- Update calc columns only; never touch override columns on recompute
        a_calc         = EXCLUDED.a_calc,
        b_calc         = EXCLUDED.b_calc,
        c_calc         = EXCLUDED.c_calc,
        d1_calc        = EXCLUDED.d1_calc,
        d2_calc        = EXCLUDED.d2_calc,
        d_calc         = EXCLUDED.d_calc,
        e_calc         = EXCLUDED.e_calc,
        f_calc         = EXCLUDED.f_calc,
        g_calc         = EXCLUDED.g_calc,
        gpa_extracted  = EXCLUDED.gpa_extracted,
        gpa_cumulative = EXCLUDED.gpa_cumulative,
        gpa_english    = EXCLUDED.gpa_english,
        gpa_math       = EXCLUDED.gpa_math,
        gpa_science    = EXCLUDED.gpa_science,
        stem_score     = EXCLUDED.stem_score,
        csulb_score    = EXCLUDED.csulb_score,
        year_intake    = COALESCE(EXCLUDED.year_intake, student_ag_summary.year_intake),
        updated_at     = EXCLUDED.updated_at;
END;
$fn$;
