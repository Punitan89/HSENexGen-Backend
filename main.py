from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
import os

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

@app.get("/")
def read_root():
    return {"status": "HSE NexGen Backend Running"}

@app.post("/generate-hirarc")
def generate_hirarc(request: HIRARCRequest):
    prompt = f"""You are a certified HSE professional trained in Malaysian 
occupational safety standards (OSHA 1994, FMA 1967, BOWEC 1986).

Generate a complete HIRARC table for the following work:

Project/Location: {request.project_location}
Conducted By: {request.conducted_by}
Work Description: {request.work_description}

Return ONLY a JSON array with this exact structure, no other text:
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
Risk levels: 1-4 LOW, 5-9 MEDIUM, 10-16 HIGH, 17-25 EXTREME."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    import json
    response_text = message.content[0].text
    hirarc_data = json.loads(response_text)
    
    return {
        "status": "success",
        "project_location": request.project_location,
        "conducted_by": request.conducted_by,
        "hirarc_rows": hirarc_data
    }
