import os
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app import models

def get_db_url():
    return os.environ.get("DATABASE_URL") or input("Enter DATABASE_URL: ")

async def delete_all():
    db_url = get_db_url()
    engine = create_async_engine(db_url, echo=True)
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as session:
        try:
            await session.execute(models.Course_details.__table__.delete())
            await session.execute(models.Students.__table__.delete())
            await session.execute(models.ExtractionFileDetails.__table__.delete())
            await session.commit()
            # Reset primary key sequences
            from sqlalchemy import text
            await session.execute(text("ALTER SEQUENCE course_details_id_seq RESTART WITH 1;"))
            await session.execute(text("ALTER SEQUENCE student_details_id_seq RESTART WITH 1;"))
            await session.execute(text("ALTER SEQUENCE extraction_file_details_id_seq RESTART WITH 1;"))
            await session.commit()
            print("All data deleted and sequences reset for course_details, student_details, extraction_file_details.")
        except Exception as e:
            print(f"Error deleting data: {e}")

if __name__ == "__main__":
    asyncio.run(delete_all())
