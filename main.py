from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import anthropic
import os
import json
import re
import io
import base64

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = anthropic.Anthropic(api_key=os.environ.get("CLAUDE_API_KEY"))

class HIRARCRequest(BaseModel):
    project_location: str
    conducted_by: str
    work_description: str

class PDFRequest(BaseModel):
    project_location: str
    conducted_by: str
    hirarc_rows: list

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

[
  {{
    "sn": 1,
    "activity": "activity name",
    "conditions": "R",
    "hazard": "hazard description",
    "risk_impact": "potential impact",
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

Generate at least 5 rows covering all major activities and hazards.
RPN = severity x occurrence.
Risk levels: 1-4 LOW, 5-9 MEDIUM, 10-16 HIGH, 17-25 EXTREME.
Legal references must cite actual Malaysian laws and standards."""

        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4000,
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

        return {
            "status": "success",
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
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=0.5*inch, rightMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch)
        elements = []
        styles = getSampleStyleSheet()

        elements.append(Paragraph("HIRARC REPORT", styles['Title']))
        elements.append(Paragraph(f"Project: {request.project_location} | Conducted By: {request.conducted_by}", styles['Normal']))
        elements.append(Spacer(1, 0.2*inch))

        headers = ['No', 'Activity', 'Hazard', 'Sev', 'Occ', 'RPN', 'Controls']
        data = [headers]
        for i, row in enumerate(request.hirarc_rows):
            if isinstance(row, dict):
                data.append([
                    str(row.get('sn', i+1)),
                    str(row.get('activity', ''))[:40],
                    str(row.get('hazard', ''))[:40],
                    str(row.get('initial_severity', '')),
                    str(row.get('initial_occurrence', '')),
                    str(row.get('initial_rpn', '')),
                    str(row.get('existing_controls', ''))[:50],
                ])
            else:
                data.append([str(i+1), str(row)[:40], '', '', '', '', ''])

        table = Table(data, colWidths=[0.4*inch, 2*inch, 2*inch, 0.4*inch, 0.4*inch, 0.4*inch, 2.5*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.green),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTSIZE', (0,0), (-1,-1), 7),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.lightgrey]),
        ]))
        elements.append(table)
        doc.build(elements)
        buffer.seek(0)

pdf_base64 = base64.b64encode(buffer.read()).decode('utf-8')
data_url = f"data:application/pdf;base64,{pdf_base64}"
return {"status": "success", "pdf_url": data_url}
