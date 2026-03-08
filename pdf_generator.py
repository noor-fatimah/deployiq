# pdf_generator.py — DeployIQ
# Fix #6: accepts either a file path (str) OR an io.BytesIO buffer as output target

import io
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    ListFlowable, ListItem, Table, TableStyle
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors


def _fmt(value, as_pct=True):
    if value is None:
        return "N/A"
    if as_pct:
        return f"{value:.2%}"
    return f"{value:.4f}"


def _risk_color(level):
    mapping = {
        "LOW":    colors.HexColor("#22c55e"),
        "MEDIUM": colors.HexColor("#f59e0b"),
        "HIGH":   colors.HexColor("#ef4444"),
    }
    return mapping.get(level, colors.grey)


def generate_pdf(metrics, risk_data, output=None):
    """
    Generate a PDF report.
    output: str (file path) | io.BytesIO | None (returns BytesIO)
    """
    if output is None:
        output = io.BytesIO()

    doc = SimpleDocTemplate(
        output,
        rightMargin=0.75 * inch, leftMargin=0.75 * inch,
        topMargin=0.75 * inch,   bottomMargin=0.75 * inch,
    )
    elements = []
    styles   = getSampleStyleSheet()

    task_type  = metrics.get("task_type", "classification")
    risk_level = risk_data.get("risk_level", "UNKNOWN")
    from datetime import datetime, timezone
    report_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Title ──────────────────────────────────────────────────────────────────
    elements.append(Paragraph("<b>DeployIQ</b>", styles["Title"]))
    elements.append(Spacer(1, 0.05 * inch))
    elements.append(Paragraph("AI Model Deployment Risk Assessment Report", styles["Heading2"]))
    elements.append(Paragraph(f"<i>Generated: {report_ts}</i>", styles["Normal"]))
    elements.append(Spacer(1, 0.25 * inch))

    # ── Column detection notice ────────────────────────────────────────────────
    method = metrics.get("column_detection_method", "")
    if method and method != "alias match":
        notice = (
            f"<i>Auto-detected columns — Label: <b>{metrics.get('label_column')}</b>, "
            f"Prediction: <b>{metrics.get('prediction_column')}</b> "
            f"(method: {method})</i>"
        )
        elements.append(Paragraph(notice, styles["Normal"]))
        elements.append(Spacer(1, 0.15 * inch))

    # ── Executive Summary ──────────────────────────────────────────────────────
    elements.append(Paragraph("<b>1. Executive Summary</b>", styles["Heading2"]))
    elements.append(Spacer(1, 0.1 * inch))

    if task_type == "regression":
        summary_rows = [
            ["Metric",       "Value"],
            ["R² Score",     _fmt(metrics.get("r2"), as_pct=False)],
            ["MAE",          _fmt(metrics.get("mae"), as_pct=False)],
            ["MSE",          _fmt(metrics.get("mse"), as_pct=False)],
            ["RMSE",         _fmt(metrics.get("rmse"), as_pct=False)],
            ["Dataset Size", str(metrics.get("dataset_size", "N/A"))],
        ]
    else:
        summary_rows = [
            ["Metric",       "Value"],
            ["Accuracy",     _fmt(metrics.get("accuracy"))],
            ["Precision",    _fmt(metrics.get("precision"))],
            ["Recall",       _fmt(metrics.get("recall"))],
            ["F1 Score",     _fmt(metrics.get("f1_score"))],
            ["ROC-AUC",      _fmt(metrics.get("roc_auc")) if metrics.get("roc_auc") is not None else "N/A"],
            ["Dataset Size", str(metrics.get("dataset_size", "N/A"))],
        ]

    t = Table(summary_rows, colWidths=[3 * inch, 3 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#1e293b")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
        ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("FONTSIZE",      (0, 0), (-1, -1), 10),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 0.3 * inch))

    # ── Risk Badge ─────────────────────────────────────────────────────────────
    elements.append(Paragraph("<b>Deployment Risk Level</b>", styles["Heading3"]))
    badge_style = ParagraphStyle(
        "badge", parent=styles["Normal"],
        fontSize=16, textColor=_risk_color(risk_level), fontName="Helvetica-Bold",
    )
    elements.append(Paragraph(f"● {risk_level} RISK", badge_style))
    elements.append(Spacer(1, 0.1 * inch))
    elements.append(Paragraph(risk_data.get("recommendation", ""), styles["Normal"]))
    elements.append(Spacer(1, 0.3 * inch))

    # ── Certification Status ───────────────────────────────────────────────────
    elements.append(Paragraph("<b>Deployment Certification Status</b>", styles["Heading3"]))
    status_map = {
        "LOW":    "✔ Approved for Pilot Deployment",
        "MEDIUM": "⚠ Requires Further Validation Before Deployment",
        "HIGH":   "✖ High Risk — Not Deployment Ready",
    }
    elements.append(Paragraph(status_map.get(risk_level, "⚠ Status Unknown"), styles["Normal"]))
    elements.append(Spacer(1, 0.3 * inch))

    # ── AI Insights ────────────────────────────────────────────────────────────
    elements.append(Paragraph("<b>2. AI Assistant Insights</b>", styles["Heading2"]))
    elements.append(Spacer(1, 0.1 * inch))
    explanation = risk_data.get("explanation", [])
    if explanation:
        elements.append(ListFlowable([
            ListItem(Paragraph(p, styles["Normal"])) for p in explanation
        ]))
    else:
        elements.append(Paragraph("No additional insights available.", styles["Normal"]))
    elements.append(Spacer(1, 0.3 * inch))

    # ── Dataset Overview ───────────────────────────────────────────────────────
    elements.append(Paragraph("<b>3. Dataset Overview</b>", styles["Heading2"]))
    elements.append(Spacer(1, 0.1 * inch))
    elements.append(Paragraph(
        f"Total Samples: {metrics.get('dataset_size', 'N/A')} &nbsp;|&nbsp; "
        f"Task Type: {task_type.title()} &nbsp;|&nbsp; "
        f"Label Column: <i>{metrics.get('label_column', 'N/A')}</i> &nbsp;|&nbsp; "
        f"Prediction Column: <i>{metrics.get('prediction_column', 'N/A')}</i>",
        styles["Normal"],
    ))
    elements.append(Spacer(1, 0.3 * inch))

    # ── Risk Flags ─────────────────────────────────────────────────────────────
    elements.append(Paragraph("<b>4. Risk Flags Detected</b>", styles["Heading2"]))
    elements.append(Spacer(1, 0.1 * inch))
    risks = risk_data.get("risks", [])
    if risks:
        elements.append(ListFlowable([
            ListItem(Paragraph(f"⚠ {r}", styles["Normal"])) for r in risks
        ]))
    else:
        elements.append(Paragraph("✔ No major risk flags detected.", styles["Normal"]))
    elements.append(Spacer(1, 0.4 * inch))

    # ── Footer ─────────────────────────────────────────────────────────────────
    elements.append(Paragraph(
        "<i>Powered by DeployIQ — AI Model Deployment Risk Validator</i>",
        styles["Normal"],
    ))

    doc.build(elements)
    return output
