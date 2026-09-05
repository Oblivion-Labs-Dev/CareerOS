import json
import os
import sys
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

# Add apps/api to path
sys.path.insert(0, os.path.abspath("apps/api"))
from app.db.store import session_scope, get_kv
from app.services.application_assistant.resume_diff_service import generate_role_tailoring_diff

def create_resume_pdf(output_path: str, diff_data: dict, candidate_info: dict):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    
    styles = getSampleStyleSheet()
    
    # Custom Palette
    PRIMARY = colors.HexColor("#0f172a") # Slate 900
    ACCENT = colors.HexColor("#0284c7")  # Sky 600
    MUTED = colors.HexColor("#64748b")   # Slate 500
    MODE_COLORS = {
        "off": colors.HexColor("#475569"),
        "honest": colors.HexColor("#0d9488"),
        "aggressive": colors.HexColor("#e11d48")
    }
    
    mode = diff_data.get("mode", "honest")
    badge_color = MODE_COLORS.get(mode, ACCENT)
    
    # Styles
    name_style = ParagraphStyle(
        'CandidateName',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=PRIMARY
    )
    
    contact_style = ParagraphStyle(
        'ContactLine',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        textColor=MUTED
    )
    
    section_title_style = ParagraphStyle(
        'SectionTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10.5,
        leading=13,
        textColor=PRIMARY,
        spaceAfter=3
    )
    
    job_header_left = ParagraphStyle(
        'JobHeaderLeft',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9.5,
        leading=12,
        textColor=PRIMARY
    )
    
    job_header_right = ParagraphStyle(
        'JobHeaderRight',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=8.5,
        leading=12,
        alignment=2, # Right align
        textColor=MUTED
    )
    
    bullet_style = ParagraphStyle(
        'BulletItem',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#1e293b")
    )
    
    meta_tag_style = ParagraphStyle(
        'MetaTag',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=badge_color
    )
    
    elements = []
    
    # Header Section
    full_name = f"{candidate_info.get('firstName', 'Akshay')} {candidate_info.get('lastName', 'Borse')}".strip()
    contact_parts = [
        candidate_info.get("location", "Auburn, WA"),
        candidate_info.get("email", "amsborse@gmail.com"),
        candidate_info.get("phone", "(425) 336-9852"),
        "linkedin.com/in/amsborse",
        "github.com/amsborse"
    ]
    contact_str = "  •  ".join([p for p in contact_parts if p])
    
    # Mode Watermark / Header badge
    mode_labels = {
        "off": "TSENTA RESTRUCTURE: OFF (Original Unaltered Bullets)",
        "honest": "TSENTA RESTRUCTURE: HONEST (Role-Realigned & Grounded)",
        "aggressive": "TSENTA RESTRUCTURE: AGGRESSIVE (Max Metric Inflation & Callbacks)"
    }
    mode_tag = f"<b>{mode_labels.get(mode, mode.upper())}</b>  |  Target: {diff_data.get('title')} @ {diff_data.get('company')}  |  Match Score: {diff_data.get('matchScore')}%"
    
    header_table = Table([
        [Paragraph(f"<b>{full_name}</b>", name_style), Paragraph(mode_tag, meta_tag_style)],
        [Paragraph(contact_str, contact_style), ""]
    ], colWidths=[330, 210])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 1),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 6))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY, spaceAfter=8, spaceBefore=2))
    
    # Summary Section
    elements.append(Paragraph("PROFESSIONAL SUMMARY", section_title_style))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=MUTED, spaceAfter=4, spaceBefore=0))
    if mode == "off":
        summary_text = (
            "Senior Software Engineer with 7+ years of experience in distributed systems, backend architectures, "
            "and cloud services. Proven record of building high-scale services at Microsoft and Amazon."
        )
    elif mode == "honest":
        summary_text = (
            f"Senior Software Engineer with 7+ years of proven expertise delivering high-performance distributed systems, "
            f"cloud-native architectures, and production AI pipelines. Specifically tailored for the {diff_data.get('title')} role "
            f"at {diff_data.get('company')}, leveraging robust microservice orchestration, high availability, and modern full-stack workflows."
        )
    else: # aggressive
        summary_text = (
            f"Staff / Principal Software Architect with 7+ years scaling mission-critical distributed infrastructures, "
            f"enterprise LLM orchestration clusters, and hyper-throughput platforms servicing 50M+ daily users. Track record of driving $10M+ ARR "
            f"impact and $1.2M in annual cloud efficiency savings. Primed to spearhead technical roadmaps for {diff_data.get('company')}'s {diff_data.get('title')} team."
        )
    elements.append(Paragraph(summary_text, bullet_style))
    elements.append(Spacer(1, 8))
    
    # Work Experience Section
    elements.append(Paragraph("PROFESSIONAL EXPERIENCE", section_title_style))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=MUTED, spaceAfter=6, spaceBefore=0))
    
    # 1. Primary Current Role (Microsoft) - Where tailored bullets live!
    exp_table_msft = Table([
        [Paragraph("<b>Microsoft</b>  —  Senior Software Engineer", job_header_left), Paragraph("09/2025 – Present  |  Redmond, WA", job_header_right)]
    ], colWidths=[380, 160])
    exp_table_msft.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 1),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(exp_table_msft)
    elements.append(Spacer(1, 3))
    
    # Bullets from diff_data
    for b in diff_data.get("bulletDiffs", []):
        bullet_content = b.get("tailored") or b.get("original") or ""
        elements.append(Paragraph(f"• &nbsp; {bullet_content}", bullet_style))
        elements.append(Spacer(1, 2.5))
        
    elements.append(Spacer(1, 6))
    
    # 2. Amazon Role
    exp_table_amzn = Table([
        [Paragraph("<b>Amazon</b>  —  Software Development Engineer II", job_header_left), Paragraph("08/2019 – 08/2025  |  Seattle, WA", job_header_right)]
    ], colWidths=[380, 160])
    exp_table_amzn.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 1),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(exp_table_amzn)
    elements.append(Spacer(1, 3))
    
    amzn_bullets = [
        "Architected and deployed high-throughput tier-1 payment and checkout microservices serving millions of transactions with 99.999% SLA.",
        "Built distributed event-driven data streaming pipelines utilizing AWS Kinesis, Lambda, DynamoDB, and ECS.",
        "Mentored junior and mid-level engineers, instituted automated unit/integration test standards raising code coverage from 72% to 94%."
    ]
    for b in amzn_bullets:
        elements.append(Paragraph(f"• &nbsp; {b}", bullet_style))
        elements.append(Spacer(1, 2.5))
        
    elements.append(Spacer(1, 6))
    
    # Technical Skills Section
    elements.append(Paragraph("TECHNICAL SKILLS & COMPETENCIES", section_title_style))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=MUTED, spaceAfter=4, spaceBefore=0))
    
    skills_table = Table([
        [Paragraph("<b>Languages:</b>", bullet_style), Paragraph("Python, TypeScript, JavaScript, Go, Java, SQL, C++", bullet_style)],
        [Paragraph("<b>Frameworks:</b>", bullet_style), Paragraph("FastAPI, Next.js, React, Node.js, Flask, TailwindCSS", bullet_style)],
        [Paragraph("<b>Cloud & Infra:</b>", bullet_style), Paragraph("AWS (Lambda, ECS, DynamoDB, S3), Azure, Docker, Kubernetes, Terraform, CI/CD", bullet_style)],
        [Paragraph("<b>AI & Data:</b>", bullet_style), Paragraph("RAG, Vector DBs (Chroma, Pinecone), LangChain, Ollama, Qwen, Fine-Tuning", bullet_style)],
    ], colWidths=[85, 455])
    skills_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 1),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(skills_table)
    elements.append(Spacer(1, 6))
    
    # Education Section
    elements.append(Paragraph("EDUCATION", section_title_style))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=MUTED, spaceAfter=4, spaceBefore=0))
    edu_table = Table([
        [Paragraph("<b>Master of Science in Computer Science</b>  —  San Jose State University", job_header_left), Paragraph("San Jose, CA", job_header_right)]
    ], colWidths=[380, 160])
    edu_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(edu_table)
    
    doc.build(elements)
    print(f"Generated PDF: {output_path} ({os.path.getsize(output_path)} bytes)")

async def main():
    import json
    with session_scope() as db:
        profile = get_kv(db, "profile") or {}
    
    # Fallback to applypilot-profile.json if empty
    if not profile:
        with open("apps/api/data/applypilot-profile.json", "r", encoding="utf-8") as f:
            profile = json.load(f)
            
    # Sample Target Job: Reddit - Software Engineer
    target_job = {
        "id": "job_reddit_swe",
        "company": "Reddit",
        "title": "Software Engineer",
        "description": "Build high-throughput distributed systems and backend infrastructure serving millions of daily active Redditors."
    }
    
    output_dir_public = "apps/web/public/resumes"
    output_dir_data = "apps/api/data/generated_resumes"
    os.makedirs(output_dir_public, exist_ok=True)
    os.makedirs(output_dir_data, exist_ok=True)
    
    modes = ["off", "honest", "aggressive"]
    generated_files = []
    
    for mode in modes:
        diff_data = await generate_role_tailoring_diff(target_job, profile, mode=mode)
        
        # Paths
        filename = f"Akshay_Borse_Resume_{mode.upper()}.pdf"
        pub_path = os.path.join(output_dir_public, filename)
        data_path = os.path.join(output_dir_data, filename)
        
        from app.services.application_assistant.resume_diff_service import render_tailored_resume_pdf
        pdf_bytes = render_tailored_resume_pdf(diff_data, profile)
        with open(pub_path, "wb") as f:
            f.write(pdf_bytes)
        with open(data_path, "wb") as f:
            f.write(pdf_bytes)
            
        generated_files.append({
            "mode": mode,
            "filename": filename,
            "webUrl": f"/resumes/{filename}",
            "diskPath": os.path.abspath(pub_path),
            "size": os.path.getsize(pub_path)
        })
        
    print("\nGeneration complete!")
    print(json.dumps(generated_files, indent=2))

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
