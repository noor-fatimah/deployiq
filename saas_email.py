# saas_email.py — DeployIQ SaaS Email System
# Uses SMTP (Gmail or custom) — set env vars to configure

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

logger = logging.getLogger(__name__)

# ── SMTP Config ────────────────────────────────────────────────────────────────
SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", 587))
SMTP_USER     = os.getenv("SMTP_USER", "")           # your Gmail address
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")       # Gmail App Password
FROM_EMAIL    = os.getenv("FROM_EMAIL", SMTP_USER)
FROM_NAME     = os.getenv("FROM_NAME", "DeployIQ")
FRONTEND_URL  = os.getenv("FRONTEND_URL", "http://localhost:8001")


def _send_email(to_email: str, subject: str, html_body: str):
    """Core SMTP send function."""
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning(f"SMTP not configured — would send to {to_email}: {subject}")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"]      = to_email

    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, to_email, msg.as_string())
        logger.info(f"Email sent → {to_email} | {subject}")
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")


# ── Shared CSS/Layout ──────────────────────────────────────────────────────────
def _email_wrapper(content: str) -> str:
    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DeployIQ</title>
</head>
<body style="margin:0;padding:0;background:#0f172a;font-family:'Segoe UI',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0f172a;padding:40px 20px;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

      <!-- Header -->
      <tr>
        <td style="background:linear-gradient(135deg,#1e293b,#0f172a);border-radius:16px 16px 0 0;padding:32px 40px;border-bottom:1px solid #1e3a5f;">
          <table width="100%"><tr>
            <td>
              <span style="color:#38bdf8;font-size:24px;font-weight:800;letter-spacing:-0.5px;">Deploy</span><span style="color:#ffffff;font-size:24px;font-weight:800;">IQ</span>
              <span style="display:block;color:#64748b;font-size:12px;margin-top:2px;letter-spacing:2px;text-transform:uppercase;">AI Model Risk Validator</span>
            </td>
            <td align="right">
              <span style="background:#1e3a5f;color:#38bdf8;padding:6px 14px;border-radius:20px;font-size:12px;font-weight:600;">Deployment Intelligence</span>
            </td>
          </tr></table>
        </td>
      </tr>

      <!-- Body -->
      <tr>
        <td style="background:#1e293b;padding:40px;border-radius:0 0 16px 16px;">
          {content}
          <!-- Footer -->
          <table width="100%" style="margin-top:40px;border-top:1px solid #334155;padding-top:24px;">
            <tr>
              <td style="color:#475569;font-size:12px;text-align:center;line-height:1.6;">
                © {datetime.now().year} DeployIQ · AI Model Deployment Risk Validator<br>
                <a href="{FRONTEND_URL}/unsubscribe" style="color:#475569;">Unsubscribe</a> · 
                <a href="{FRONTEND_URL}" style="color:#475569;">Website</a>
              </td>
            </tr>
          </table>
        </td>
      </tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""


def _cta_button(url: str, text: str, color: str = "#38bdf8") -> str:
    return f"""
<table width="100%" style="margin:24px 0;">
  <tr><td align="center">
    <a href="{url}" style="background:{color};color:#0f172a;padding:14px 32px;border-radius:8px;font-weight:700;font-size:16px;text-decoration:none;display:inline-block;letter-spacing:0.3px;">
      {text} →
    </a>
  </td></tr>
</table>"""


# ── Email Templates ────────────────────────────────────────────────────────────

def send_trial_started_email(
    email: str,
    access_url: str,
    trial_end_date,
    is_resend: bool = False,
    is_forever: bool = False,
):
    subject = "🚀 Your DeployIQ Access is Ready" if not is_resend else "🔗 Your DeployIQ Access Link"
    exp_str = trial_end_date.strftime("%B %d, %Y") if trial_end_date else "7 days from now"

    plan_note = ""
    if is_forever:
        plan_note = f"""
<div style="background:#0c2340;border:1px solid #1e4a7a;border-radius:10px;padding:16px;margin:20px 0;">
  <p style="color:#38bdf8;font-size:14px;margin:0;font-weight:600;">⚡ Forever Plan</p>
  <p style="color:#94a3b8;font-size:13px;margin:8px 0 0;">Complete your payment to activate unlimited access.</p>
</div>"""

    content = f"""
<h1 style="color:#f1f5f9;font-size:26px;font-weight:700;margin:0 0 8px;">
  {"Welcome back!" if is_resend else "Your trial has started! 🎉"}
</h1>
<p style="color:#94a3b8;font-size:15px;line-height:1.7;margin:0 0 24px;">
  {"Here's your access link:" if is_resend else "You're all set. Click below to start analyzing your AI models:"}
</p>

{plan_note}

<div style="background:#0c1929;border:1px solid #1e3a5f;border-radius:10px;padding:20px;margin:20px 0;">
  <p style="color:#64748b;font-size:12px;margin:0 0 8px;text-transform:uppercase;letter-spacing:1px;">Your Trial Details</p>
  <table width="100%">
    <tr>
      <td style="color:#94a3b8;font-size:14px;padding:4px 0;">Trial expires</td>
      <td style="color:#f1f5f9;font-size:14px;font-weight:600;text-align:right;">{exp_str}</td>
    </tr>
    <tr>
      <td style="color:#94a3b8;font-size:14px;padding:4px 0;">Reports included</td>
      <td style="color:#f1f5f9;font-size:14px;font-weight:600;text-align:right;">2 free reports</td>
    </tr>
    <tr>
      <td style="color:#94a3b8;font-size:14px;padding:4px 0;">Card required</td>
      <td style="color:#22c55e;font-size:14px;font-weight:600;text-align:right;">❌ No card needed</td>
    </tr>
  </table>
</div>

{_cta_button(access_url, "Open DeployIQ")}

<p style="color:#64748b;font-size:13px;line-height:1.6;">
  <strong style="color:#94a3b8;">How it works:</strong><br>
  1. Click the button above to open your dashboard<br>
  2. Upload a CSV with your model's predictions<br>
  3. Get instant risk assessment + PDF report<br>
  4. Upgrade anytime for unlimited reports
</p>

<p style="color:#475569;font-size:12px;margin-top:24px;">
  This link is unique to your account. Please don't share it.<br>
  Link expires with your trial on {exp_str}.
</p>"""

    _send_email(email, subject, _email_wrapper(content))


def send_trial_expired_email(email: str, checkout_url: str):
    subject = "⏰ Your DeployIQ Trial Has Ended"
    content = f"""
<h1 style="color:#f1f5f9;font-size:26px;font-weight:700;margin:0 0 8px;">
  Your Trial Has Expired
</h1>
<p style="color:#94a3b8;font-size:15px;line-height:1.7;margin:0 0 24px;">
  Your 7-day free trial has ended. Upgrade now to continue validating your AI models 
  and generating risk assessment reports.
</p>

<div style="background:#1a0a0a;border:1px solid #7f1d1d;border-radius:10px;padding:20px;margin:20px 0;">
  <p style="color:#fca5a5;font-size:14px;font-weight:600;margin:0 0 8px;">🔒 Access Blocked</p>
  <p style="color:#94a3b8;font-size:13px;margin:0;">
    Your reports are paused until you upgrade. All your data is safe.
  </p>
</div>

<div style="background:#0c2340;border:1px solid #1e4a7a;border-radius:10px;padding:20px;margin:20px 0;">
  <p style="color:#38bdf8;font-size:18px;font-weight:700;margin:0 0 4px;">Forever Plan — $29.99</p>
  <p style="color:#64748b;font-size:13px;margin:0 0 12px;">One-time payment. Unlimited access forever.</p>
  <table width="100%">
    <tr><td style="color:#94a3b8;font-size:13px;padding:3px 0;">✅ Unlimited reports per day</td></tr>
    <tr><td style="color:#94a3b8;font-size:13px;padding:3px 0;">✅ PDF risk assessment reports</td></tr>
    <tr><td style="color:#94a3b8;font-size:13px;padding:3px 0;">✅ CSV, Excel, PDF, Word support</td></tr>
    <tr><td style="color:#94a3b8;font-size:13px;padding:3px 0;">✅ No recurring fees ever</td></tr>
  </table>
</div>

{_cta_button(checkout_url, "Upgrade Now — $29.99", "#22c55e")}

<p style="color:#64748b;font-size:13px;line-height:1.6;text-align:center;">
  Secure checkout powered by Lemon Squeezy 🍋<br>
  30-day money-back guarantee
</p>"""

    _send_email(email, subject, _email_wrapper(content))


def send_trial_reminder_email(email: str, access_url: str, checkout_url: str, days_left: int):
    subject = f"⚡ {days_left} Day{'s' if days_left != 1 else ''} Left in Your DeployIQ Trial"
    content = f"""
<h1 style="color:#f1f5f9;font-size:26px;font-weight:700;margin:0 0 8px;">
  {days_left} Day{'s' if days_left != 1 else ''} Left in Your Trial
</h1>
<p style="color:#94a3b8;font-size:15px;line-height:1.7;margin:0 0 24px;">
  Your free trial ends soon. Don't lose access to DeployIQ's AI model risk analysis.
</p>

<div style="background:#1a1200;border:1px solid #78350f;border-radius:10px;padding:20px;margin:20px 0;">
  <p style="color:#fcd34d;font-size:14px;font-weight:600;margin:0 0 8px;">⚠️ Trial Ending Soon</p>
  <p style="color:#94a3b8;font-size:13px;margin:0;">
    Upgrade now to keep generating unlimited risk reports without interruption.
  </p>
</div>

{_cta_button(access_url, "Continue Using DeployIQ")}

<p style="color:#64748b;font-size:13px;text-align:center;">or</p>

{_cta_button(checkout_url, "Upgrade to Forever Plan — $29.99", "#22c55e")}"""

    _send_email(email, subject, _email_wrapper(content))


def send_payment_success_email(email: str, access_url: str):
    subject = "🎉 Welcome to DeployIQ Forever — Payment Confirmed!"
    content = f"""
<div style="text-align:center;margin-bottom:32px;">
  <div style="font-size:64px;">🎉</div>
  <h1 style="color:#22c55e;font-size:28px;font-weight:700;margin:8px 0;">
    Payment Successful!
  </h1>
  <p style="color:#94a3b8;font-size:15px;">
    You now have <strong style="color:#f1f5f9;">unlimited access</strong> to DeployIQ — forever.
  </p>
</div>

<div style="background:#0c2a14;border:1px solid #166534;border-radius:10px;padding:20px;margin:20px 0;">
  <p style="color:#22c55e;font-size:14px;font-weight:600;margin:0 0 12px;">✅ Forever Plan Activated</p>
  <table width="100%">
    <tr><td style="color:#86efac;font-size:13px;padding:3px 0;">✅ Unlimited reports per day</td></tr>
    <tr><td style="color:#86efac;font-size:13px;padding:3px 0;">✅ All file formats supported</td></tr>
    <tr><td style="color:#86efac;font-size:13px;padding:3px 0;">✅ PDF risk assessment reports</td></tr>
    <tr><td style="color:#86efac;font-size:13px;padding:3px 0;">✅ No recurring fees — ever</td></tr>
  </table>
</div>

{_cta_button(access_url, "Open Your Dashboard Now", "#22c55e")}

<p style="color:#64748b;font-size:13px;text-align:center;line-height:1.6;">
  Thank you for your purchase! Your order confirmation has been sent separately.<br>
  Questions? Reply to this email.
</p>"""

    _send_email(email, subject, _email_wrapper(content))
