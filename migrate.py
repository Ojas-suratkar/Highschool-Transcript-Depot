from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/transcripts"

# =========================
# SOURCE TABLE CONFIG
# =========================
OLD_TABLE = "uc_doorway_courses"
OLD_ID_COL = "id"
OLD_INST_COL = "hs_id"
OLD_YEAR_COL = "crs_academic_year"
OLD_CODES_COL = "crs_local_codes"
OLD_ABBREV_COL = "crs_transcript_abbrevs"

# =========================
# TARGET SEARCH TABLE CONFIG
# =========================
NEW_TABLE = "uc_doorway_courses_search_index"
NEW_FK_COL = "crs_id"
NEW_INST_FK_COL = "hs_id"
NEW_YEAR_COL = "crs_academic_year"
NEW_TYPE_COL = "search_type"
NEW_VALUE_COL = "search_value"

# =========================
# TUNING
# =========================
SOURCE_PAGE_SIZE = 2000
INSERT_BATCH_SIZE = 5000
PROGRESS_EVERY_SOURCE_ROWS = 10000


def split_pipe_values(value):
    if value is None:
        return []
    return [item.strip() for item in str(value).split("|") if item and item.strip()]





def flush_batch(conn, insert_sql, batch, total_attempted):
    if not batch:
        return total_attempted

    conn.execute(insert_sql, batch)
    total_attempted += len(batch)
    print(f"Inserted so far: {total_attempted}")
    batch.clear()
    return total_attempted


def fetch_source_page(conn, last_id, page_size):
    page_sql = text(f"""
        SELECT
            {OLD_ID_COL} AS course_id,
            {OLD_INST_COL} AS institution_id,
            {OLD_YEAR_COL} AS crs_academic_year,
            {OLD_CODES_COL} AS local_codes,
            {OLD_ABBREV_COL} AS abbreviations
        FROM {OLD_TABLE}
        WHERE {OLD_ID_COL} > :last_id
        ORDER BY {OLD_ID_COL}
        LIMIT :page_size
    """)
    return conn.execute(
        page_sql,
        {"last_id": last_id, "page_size": page_size}
    ).mappings().all()




def load_data_phase(engine):
    print("=== DATA LOAD ===")

    insert_sql = text(f"""
        INSERT INTO {NEW_TABLE} (
            {NEW_FK_COL},
            {NEW_INST_FK_COL},
            {NEW_YEAR_COL},
            {NEW_TYPE_COL},
            {NEW_VALUE_COL}
        )
        VALUES (
            :{NEW_FK_COL},
            :{NEW_INST_FK_COL},
            :{NEW_YEAR_COL},
            :{NEW_TYPE_COL},
            :{NEW_VALUE_COL}
        )
        ON CONFLICT (
            {NEW_FK_COL},
            {NEW_INST_FK_COL},
            {NEW_YEAR_COL},
            {NEW_TYPE_COL},
            {NEW_VALUE_COL}
        ) DO NOTHING
    """)

    last_id = 0
    source_row_count = 0
    total_attempted = 0
    batch = []

    with engine.begin() as conn:
        while True:
            rows = fetch_source_page(conn, last_id, SOURCE_PAGE_SIZE)
            if not rows:
                break

            for row in rows:
                source_row_count += 1

                course_id = row["course_id"]
                institution_id = row["institution_id"]
                year_value = row["crs_academic_year"]

                for code in split_pipe_values(row["local_codes"]):
                    batch.append({
                        NEW_FK_COL: course_id,
                        NEW_INST_FK_COL: institution_id,
                        NEW_YEAR_COL: year_value,
                        NEW_TYPE_COL: "crs_local_codes",
                        NEW_VALUE_COL: code,
                    })

                for abbr in split_pipe_values(row["abbreviations"]):
                    batch.append({
                        NEW_FK_COL: course_id,
                        NEW_INST_FK_COL: institution_id,
                        NEW_YEAR_COL: year_value,
                        NEW_TYPE_COL: "crs_transcript_abbrevs",
                        NEW_VALUE_COL: abbr,
                    })

                if len(batch) >= INSERT_BATCH_SIZE:
                    total_attempted = flush_batch(conn, insert_sql, batch, total_attempted)

            last_id = rows[-1]["course_id"]

            if source_row_count % PROGRESS_EVERY_SOURCE_ROWS == 0:
                print(f"Processed rows: {source_row_count}")

        total_attempted = flush_batch(conn, insert_sql, batch, total_attempted)

    print("=== DONE ===")
    print(f"Total processed source rows: {source_row_count}")
    print(f"Total inserted search rows: {total_attempted}")


def main():
    engine = create_engine(DATABASE_URL, echo=False)
    load_data_phase(engine)


if __name__ == "__main__":
    main()