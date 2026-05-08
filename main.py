@app.post("/generate-pdf")
def generate_pdf(request: PDFRequest):
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch

        print(f"project_location: {request.project_location}")
        print(f"conducted_by: {request.conducted_by}")
        print(f"hirarc_rows type: {type(request.hirarc_rows)}")
        print(f"hirarc_rows preview: {str(request.hirarc_rows)[:300]}")

        # ROBUST PARSING - handles all formats
        rows = []
        raw = request.hirarc_rows

        if isinstance(raw, list):
            rows = raw
        elif isinstance(raw, str):
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

        # Convert all rows safely to dict
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

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=0.5*inch, rightMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch)
        elements = []
        styles = getSampleStyleSheet()

        elements.append(Paragraph("HIRARC REPORT", styles['Title']))
        elements.append(Paragraph(f"Project: {request.project_location} | Conducted By: {request.conducted_by}", styles['Normal']))
        elements.append(Spacer(1, 0.2*inch))

        headers = ['No', 'Activity', 'Hazard', 'Sev', 'Occ', 'RPN', 'Controls']
        data = [headers]
        for i, row in enumerate(rows):
            data.append([
                str(row.get('sn', i+1)),
                str(row.get('activity', ''))[:40],
                str(row.get('hazard', ''))[:40],
                str(row.get('initial_severity', '')),
                str(row.get('initial_occurrence', '')),
                str(row.get('initial_rpn', '')),
                str(row.get('existing_controls', ''))[:50],
            ])

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

    except Exception as e:
        print(f"PDF Error: {str(e)}")
        return {"status": "error", "message": str(e)}
