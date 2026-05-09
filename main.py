from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Union, Optional
import anthropic
import os
import json
import io
import base64
from datetime import datetime
from supabase import create_client, Client

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = anthropic.Anthropic(api_key=os.environ.get("CLAUDE_API_KEY"))

# ✅ SUPABASE CLIENT
supabase: Client = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_KEY")
)

# ✅ MEMORY STORE
last_hirarc_store = {}

class HIRARCRequest(BaseModel):
    project_location: str
    conducted_by: str
    work_description: str
    user_id: Optional[str] = None

class PDFRequest(BaseModel):
    project_location: Optional[str] = ""
    conducted_by: Optional[str] = ""
    hirarc_rows: Union[list, str] = ""

@app.get("/")
def read_root():
    return {"status": "HSE NexGen Backend Running"}

@app.post("/generate-hirarc")
def generate_hirarc(request: HIRARCRequest):
    try:
        prompt = f"""You are a certified HSE professional trained in Malaysian occupational safety standards (OSHA 1994, FMA 1967, BOWEC 1986).

IMPORTANT LANGUAGE RULE:
- Detect the language used in the work description below
- If Bahasa Malaysia respond entirely in Bahasa Malaysia
- If English respond entirely in English
- If Mandarin respond entirely in Mandarin
- Always match the input language for ALL fields in the output

Generate a complete HIRARC table for the following work:
Project/Location: {request.project_location}
Conducted By: {request.conducted_by}
Work Description: {request.work_description}

CRITICAL: Return ONLY a raw JSON array. No markdown. No backticks. No ```json. No explanation. Start your response with [ and end with ].

ROW COUNT RULES:
- Simple work (1-2 activities): generate 8-10 rows
- Medium work (3-5 activities): generate 10-15 rows
- Complex/large scope work (6+ activities or big project): generate 15-20 rows
- Cover ALL major activities and hazards — do NOT stop early!
- Every activity must have at least 1-2 hazards identified

[
  {{
    "sn": 1,
    "activity": "activity name",
    "conditions": "R",
    "hazard": "hazard description",
    "risk_impact": "potential impact on people or environment",
    "initial_severity": 3,
    "initial_occurrence": 3,
    "initial_rpn": 9,
    "existing_controls": "control measures",
    "legal_references": "OSHA 1994, FMA 1967",
    "legality": "Y",
    "residual_severity": 2,
    "residual_occurrence": 2,
    "residual_rpn": 4,
    "additional_controls": "additional measures",
    "responsible_person": "Site Supervisor"
  }}
]

RPN = severity x occurrence.
Risk levels: 1-4 LOW, 5-9 MEDIUM, 10-16 HIGH, 17-25 EXTREME.
Legal references must cite actual Malaysian laws and standards."""

        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = message.content[0].text.strip()
        print(f"Raw AI response: {response_text[:200]}")

        if not response_text:
            return {"status": "error", "message": "Empty response from AI model"}

        if '```' in response_text:
            response_text = response_text.split('```')[1]
            if response_text.startswith('json'):
                response_text = response_text[4:]
        response_text = response_text.strip()

        start = response_text.find('[')
        end = response_text.rfind(']') + 1
        if start != -1 and end > start:
            response_text = response_text[start:end]

        print(f"Cleaned response: {response_text[:200]}")
        hirarc_data = json.loads(response_text)

        # ✅ SAVE TO MEMORY STORE
        last_hirarc_store["rows"] = hirarc_data
        last_hirarc_store["project_location"] = request.project_location
        last_hirarc_store["conducted_by"] = request.conducted_by
        print(f"Stored {len(hirarc_data)} rows in memory")

        # ✅ SAVE TO SUPABASE
        hirarc_record = {
            "location": request.project_location,
            "conducted_by": request.conducted_by,
            "date_conducted": datetime.now().strftime("%Y-%m-%d"),
            "status": "draft",
            "ai_generated": True,
            "raw_content": hirarc_data,
        }

        if request.user_id:
            hirarc_record["created_by"] = request.user_id

        result = supabase.table("hirarc_records").insert(hirarc_record).execute()
        hirarc_id = result.data[0]["id"]
        print(f"Saved to hirarc_records with id: {hirarc_id}")

        # ✅ SAVE ROWS TO hirarc_rows
        rows_to_insert = []
        for row in hirarc_data:
            rows_to_insert.append({
                "hirarc_id": hirarc_id,
                "sn": row.get("sn", 0),
                "activity": row.get("activity", ""),
                "conditions": row.get("conditions", "R"),
                "hazard": row.get("hazard", ""),
                "risk_impact": row.get("risk_impact", ""),
                "initial_severity": row.get("initial_severity", 0),
                "initial_occurrence": row.get("initial_occurrence", 0),
                "initial_rpn": row.get("initial_rpn", 0),
                "existing_controls": row.get("existing_controls", ""),
                "legal_references": row.get("legal_references", ""),
                "legality": row.get("legality", "Y"),
                "residual_severity": row.get("residual_severity", 0),
                "residual_occurrence": row.get("residual_occurrence", 0),
                "residual_rpn": row.get("residual_rpn", 0),
                "additional_controls": row.get("additional_controls", ""),
                "responsible_person": row.get("responsible_person", ""),
            })

        supabase.table("hirarc_rows").insert(rows_to_insert).execute()
        print(f"Saved {len(rows_to_insert)} rows to hirarc_rows")

        return {
            "status": "success",
            "hirarc_id": hirarc_id,
            "project_location": request.project_location,
            "conducted_by": request.conducted_by,
            "hirarc_rows": hirarc_data
        }

    except json.JSONDecodeError as e:
        return {"status": "error", "message": f"JSON parse error: {str(e)}"}
    except Exception as e:
        return {"status": "error", "message": f"Error: {str(e)}"}

@app.post("/generate-pdf")
def generate_pdf(request: PDFRequest):
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch

        print(f"project_location received: {request.project_location}")
        print(f"conducted_by received: {request.conducted_by}")
        print(f"hirarc_rows received: {str(request.hirarc_rows)[:100]}")

        proj = request.project_location
        if not proj or proj.strip() == "" or proj == "[project_location]":
            proj = last_hirarc_store.get("project_location", "HSE NexGen Project")

        cond = request.conducted_by
        if not cond or cond.strip() == "" or cond == "[conducted_by]":
            cond = last_hirarc_store.get("conducted_by", "HSE Officer")

        rows = []
        raw = request.hirarc_rows

        if isinstance(raw, list) and len(raw) > 0:
            rows = raw
        elif isinstance(raw, str):
            if raw and raw != "[hirarc_rows]" and raw.strip() != "":
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        rows = parsed
                    elif isinstance(parsed, str):
                        parsed2 = json.loads(parsed)
                        if isinstance(parsed2, list):
                            rows = parsed2
                except:
                    rows = []

        if len(rows) == 0:
            rows = last_hirarc_store.get("rows", [])
            print(f"Using stored rows: {len(rows)}")

        clean_rows = []
        for row in rows:
            if isinstance(row, dict):
                clean_rows.append(row)
            elif isinstance(row, str):
                try:
                    clean_rows.append(json.loads(row))
                except:
                    pass

        rows = clean_rows
        print(f"Final rows count: {len(rows)}")

        today = datetime.now().strftime("%d/%m/%Y")

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                                leftMargin=0.5*inch, rightMargin=0.5*inch,
                                topMargin=0.5*inch, bottomMargin=0.5*inch)
        elements = []
        styles = getSampleStyleSheet()

        cell_style = ParagraphStyle('cell', fontSize=7, leading=9, wordWrap='CJK')
        header_style = ParagraphStyle('header', fontSize=7, leading=9,
                                      textColor=colors.white, fontName='Helvetica-Bold')
        label_style = ParagraphStyle('label', fontSize=7, leading=9,
                                     fontName='Helvetica-Bold')
        value_style = ParagraphStyle('value', fontSize=7, leading=9)

        gray = colors.Color(0.85, 0.85, 0.85)

        elements.append(Paragraph(
            "HAZARD IDENTIFICATION, RISK ASSESSMENT AND RISK CONTROL (HIRARC)",
            styles['Title']))
        elements.append(Spacer(1, 0.1*inch))

        header_data = [
            [Paragraph("Company & Package No :", label_style), "",
             Paragraph("HIRARC No :", label_style), ""],
            [Paragraph("Process / Location :", label_style),
             Paragraph(proj, value_style), "", ""],
            [Paragraph("Conducted by :", label_style),
             Paragraph(cond, value_style),
             Paragraph("Reviewed by :", label_style), ""],
            [Paragraph("Date Conducted :", label_style),
             Paragraph(today, value_style),
             Paragraph("Last Review Date :", label_style),
             Paragraph(today, value_style)],
            [Paragraph("Approved by :", label_style), "",
             Paragraph("Next Review Date :", label_style), ""],
        ]

        header_table = Table(header_data,
                             colWidths=[1.8*inch, 3.5*inch, 1.8*inch, 2.0*inch])
        header_table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('BACKGROUND', (0,0), (0,-1), gray),
            ('BACKGROUND', (2,0), (2,-1), gray),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 4),
            ('RIGHTPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 0.15*inch))

        headers = ['No', 'Activity', 'Hazard', 'Risk Impact',
                   'Sev', 'Occ', 'RPN', 'Controls']
        data = [[Paragraph(h, header_style) for h in headers]]

        for i, row in enumerate(rows):
            data.append([
                Paragraph(str(row.get('sn', i+1)), cell_style),
                Paragraph(str(row.get('activity', '')), cell_style),
                Paragraph(str(row.get('hazard', '')), cell_style),
                Paragraph(str(row.get('risk_impact', '')), cell_style),
                Paragraph(str(row.get('initial_severity', '')), cell_style),
                Paragraph(str(row.get('initial_occurrence', '')), cell_style),
                Paragraph(str(row.get('initial_rpn', '')), cell_style),
                Paragraph(str(row.get('existing_controls', '')), cell_style),
            ])

        table = Table(data, colWidths=[
            0.3*inch, 1.7*inch, 1.7*inch, 1.5*inch,
            0.35*inch, 0.35*inch, 0.35*inch, 2.1*inch
        ])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.green),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.lightgrey]),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 4),
            ('RIGHTPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        elements.append(table)
        doc.build(elements)
        buffer.seek(0)
        pdf_base64 = base64.b64encode(buffer.read()).decode('utf-8')
        data_url = f"data:application/pdf;base64,{pdf_base64}"
        return {"status": "success", "pdf_url": data_url}

    except Exception as e:
        print(f"PDF Error: {str(e)}")
        return {"status": "error", "message": str(e)}
