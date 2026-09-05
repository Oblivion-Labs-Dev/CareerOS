import asyncio
from pathlib import Path
from app.services.application_assistant.resume_diff_service import (
    generate_role_tailoring_diff,
    render_tailored_resume_pdf,
)

async def main():
    job = {
        "id": "job_meta_staff",
        "title": "Staff Software Engineer - AI Agent Infrastructure",
        "company": "Meta",
        "description": "Architect high-performance distributed systems and AI agent infrastructure at global scale.",
    }
    profile = {
        "firstName": "Akshay",
        "lastName": "Borse",
    }

    out_dir = Path("apps/web/public/resumes")
    out_dir.mkdir(parents=True, exist_ok=True)

    for mode in ["off", "honest", "aggressive"]:
        print(f"Generating resume for mode: {mode}...")
        diff_data = await generate_role_tailoring_diff(job, profile, mode=mode)
        pdf_bytes = render_tailored_resume_pdf(diff_data, profile)
        dest_path = out_dir / f"Akshay_Borse_Resume_{mode.upper()}.pdf"
        dest_path.write_bytes(pdf_bytes)
        print(f"Wrote {len(pdf_bytes)} bytes to {dest_path}")

if __name__ == "__main__":
    asyncio.run(main())
