import asyncio
import logging

from sqlmodel import Session,select
from database import engine
from models import Job,Thumbnail
from services.openai_service import generate_thumbnail
from services.imagekit_service import upload_file

logger  =  logging.getLogger(__name__)

STYLES = {
    "bold_dramatic":(
        "Create a bold, dramatic youtube thumbnail with high contrast,"
        "Cinematic lighting, dark moody background, and powerful composition,"
        "The person's face should be prominent with a dramatic expression."
    ),
    "clean_minimal":(
        "Create a clean, minimal Youtube thumbnail with bright lighting, "
        "white/light backgroud, modern professional aesthetic, plenty of "
        "whitespace, and sharp clean composition. The person should look "
        "approachable and professional."
    ),
    "vibrant_energetic":(
        "Create a vibrant, energetic Youtube thumbnail with coolorful gradiants,"
        "dynamic angels, eye-catching pop-art style colors, and energetic "
        "composition. the person should have an excited or engaging expression."
    )


}

STYLE_ORDER = ["bold_dramatic","clean_minimal","vibrant_energetic"]

async def generate_single_thumbnail(thumbnail_id:str,prompt:str,headshot_url:str):
    # db mark -> generating
    with Session(engine) as session:
        thumb = session.get(Thumbnail,thumbnail_id)
        thumb.status = "generating"
        style_name  = thumb.style_name
        session.add(thumb)
        session.commit()
    style_prompt = STYLES[style_name]
    # AI call

    try:
        image_byte = await generate_thumbnail(prompt,style_prompt,headshot_url)
        with Session(engine) as session:
            thumb = session.get(Thumbnail,thumbnail_id)
            job_id = thumb.job_id
        # upload this image

        url = upload_file(
            file_bytes=image_byte,
            file_name=f"{thumbnail_id}.png",
            folder_path=f"thumbnails/{job_id}/"
        ) 
        # db call save the url + mark uploaded
        with Session(engine) as session:
            thumb = session.get(Thumbnail,thumbnail_id)
            thumb.image_url = url
            thumb.status = "uploaded"
            session.add(thumb)
            session.commit()
        logger.info(f"Thumbnail {thumbnail_id} generated and uploaded successfully.")
    except Exception as e:
        logger.error(f"Error generating thumbnail {thumbnail_id}:{e}")
        with Session(engine) as session:
            thumb = session.get(Thumbnail,thumbnail_id)
            thumb.status = "error"
            thumb.error_message = str(e)[:500]
            session.add(thumb)
            session.commit()


async def process_job(job_id:str):
    # make job as processing
    # find all thumbnails for this job
    # start one worker for each thumbnail
    # wait for all worker to finish
    # mark job as complete or failed
    with Session(engine) as session:
        job = session.get(Job,job_id)
        job.status = "processing"
        prompt = job.prompt
        headshot_url = job.headshot_url
        session.add(job)
        session.commit()

        thumbnails = session.exec(
            select(Thumbnail).where(Thumbnail.job_id == job_id)
        ).all()

        thumbnails_ids = [t.id for t in thumbnails]

        tasks = [
            generate_single_thumbnail(tid,headshot_url,prompt)
            for tid in thumbnails_ids
        ]

        # run all thumbnail concurrently
        await asyncio.gather(*tasks,return_exceptions=True)

        with Session(engine) as session:
            thumbnails = session.exec(
            select(Thumbnail).where(Thumbnail.job_id == job_id)
            ).all()
            all_failed = all(t.status == "failed" for t in thumbnails)
            job = session.get(Job,job_id)
            job.status = "failed" if all_failed else "completed"
            session.add(job)
            session.commit()

