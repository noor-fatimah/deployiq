# saas_admin.py — DeployIQ SaaS Admin Dashboard
# Mount this into saas_main.py OR run standalone

import os
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from saas_database import get_all_users, get_saas_stats

router = APIRouter(prefix="/admin")

ADMIN_KEY = os.getenv("ADMIN_KEY", "")


def require_admin(request: Request):
    key = request.headers.get("X-Admin-Key") or request.query_params.get("key")
    if ADMIN_KEY and key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.get("", response_class=HTMLResponse)
async def admin_dashboard(request: Request, _=Depends(require_admin)):
    stats = await get_saas_stats()
    users = await get_all_users(limit=50)

    rows = ""
    for u in users:
        plan_badge = (
            '<span style="background:#166534;color:#86efac;padding:2px 10px;border-radius:100px;font-size:11px;">PAID</span>'
            if u["plan"] == "paid" else
            '<span style="background:#1e3a5c;color:#38bdf8;padding:2px 10px;border-radius:100px;font-size:11px;">TRIAL</span>'
        )
        rows += f"""
        <tr>
          <td>{u['email']}</td>
          <td>{plan_badge}</td>
          <td>{u['reports_used']}</td>
          <td>{u['trial_end_date'].strftime('%Y-%m-%d') if u['trial_end_date'] else 'N/A'}</td>
          <td>{u['created_at'].strftime('%Y-%m-%d %H:%M') if u['created_at'] else 'N/A'}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"><title>DeployIQ Admin</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Inter:wght@400;500&display=swap" rel="stylesheet">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#060d1a; color:#f1f5f9; font-family:'Inter',sans-serif; padding:40px; }}
  h1 {{ font-family:'Syne',sans-serif; font-size:28px; font-weight:800; margin-bottom:8px; }}
  h1 span:first-child {{ color:#38bdf8; }}
  .stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:16px; margin:32px 0; }}
  .stat {{ background:#0d1f35; border:1px solid #1a3a5c; border-radius:12px; padding:20px; }}
  .stat-num {{ font-family:'Syne',sans-serif; font-size:32px; font-weight:800; color:#38bdf8; }}
  .stat-label {{ color:#64748b; font-size:13px; margin-top:4px; }}
  table {{ width:100%; border-collapse:collapse; background:#0d1f35; border:1px solid #1a3a5c; border-radius:12px; overflow:hidden; }}
  th {{ background:#1a3a5c; color:#94a3b8; font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:1px; padding:12px 16px; text-align:left; }}
  td {{ padding:12px 16px; border-bottom:1px solid #0f2545; color:#94a3b8; font-size:14px; }}
  tr:last-child td {{ border-bottom:none; }}
  tr:hover td {{ background:rgba(56,189,248,0.03); }}
  .section-title {{ font-family:'Syne',sans-serif; font-size:20px; font-weight:700; margin-bottom:16px; }}
</style>
</head>
<body>
  <h1><span>Deploy</span>IQ Admin</h1>
  <p style="color:#64748b;font-size:14px;">Usage statistics and user management</p>

  <div class="stats">
    <div class="stat">
      <div class="stat-num">{stats['total_users']}</div>
      <div class="stat-label">Total Users</div>
    </div>
    <div class="stat">
      <div class="stat-num">{stats['trial_users']}</div>
      <div class="stat-label">Trial Users</div>
    </div>
    <div class="stat">
      <div class="stat-num" style="color:#22c55e;">{stats['paid_users']}</div>
      <div class="stat-label">Paid Users</div>
    </div>
    <div class="stat">
      <div class="stat-num">{stats['signups_today']}</div>
      <div class="stat-label">Signups Today</div>
    </div>
    <div class="stat">
      <div class="stat-num">{stats['total_reports']}</div>
      <div class="stat-label">Total Reports</div>
    </div>
    <div class="stat">
      <div class="stat-num" style="color:#22c55e;">{stats['conversion_rate']}</div>
      <div class="stat-label">Conversion Rate</div>
    </div>
  </div>

  <div class="section-title">Recent Users (last 50)</div>
  <table>
    <thead>
      <tr>
        <th>Email</th><th>Plan</th><th>Reports Used</th><th>Trial Ends</th><th>Joined</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>"""
