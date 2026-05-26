#!/usr/bin/env python3
"""
Daily Activity Report Generator — Jennifer White Insurance Agency
Calls the AZ Analyst API and emails an HTML report via Gmail SMTP.

Usage:
    python3 daily-report.py

Environment variables:
    ANALYST_API_URL    Base URL for the analyst API (default: https://jwhitezaps.atoaz.com/api/analysis)
    ANALYST_API_KEY    API key for authentication
    GMAIL_FROM         Sender Gmail address (default: chad@jenniferwhiteagency.com)
    GMAIL_APP_PASSWORD App password for Gmail SMTP
    REPORT_TO          Recipient email (default: chad@jenniferwhiteagency.com)
    REPORT_DATE        Override date YYYY-MM-DD (default: today Pacific)
    DRY_RUN            If set to "1", print HTML to stdout instead of sending
"""

import json
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib import request as urllib_request
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("ANALYST_API_URL", "https://jwhitezaps.atoaz.com/api/analysis")
API_KEY = os.environ.get("ANALYST_API_KEY", "")
GMAIL_FROM = os.environ.get("GMAIL_FROM", "chad@jenniferwhiteagency.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
REPORT_TO = os.environ.get("REPORT_TO", "chad@jenniferwhiteagency.com")
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pacific_today() -> str:
    if override := os.environ.get("REPORT_DATE"):
        return override
    pt = ZoneInfo("America/Los_Angeles")
    return datetime.now(tz=pt).strftime("%Y-%m-%d")


def pacific_today_display(date_str: str) -> str:
    """Format date string for display, e.g. 'Monday, May 26 2026'."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%A, %B %-d %Y")
    except Exception:
        return date_str


def api_get(path: str) -> dict | None:
    url = BASE_URL + path
    req = urllib_request.Request(url, headers={"X-API-Key": API_KEY})
    try:
        with urllib_request.urlopen(req, timeout=45) as r:
            return json.loads(r.read())
    except HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"[ERROR] HTTP {e.code} for {path}: {body[:300]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[ERROR] {path}: {e}", file=sys.stderr)
        return None


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def safe(d: dict, *keys, default="—"):
    """Safely traverse nested dict."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, None)
        if cur is None:
            return default
    return cur


# ---------------------------------------------------------------------------
# Fetch data
# ---------------------------------------------------------------------------

def fetch_all(date_var: str) -> dict:
    print(f"[INFO] Fetching data for {date_var}...", file=sys.stderr)

    team = api_get(f"/team-performance?date_from={date_var}&date_to={date_var}")
    funnel = api_get(
        f"/funnel-performance?date_from={date_var}&date_to={date_var}"
        "&group_by=producer&summary_only=false"
    )
    quality = api_get("/data-quality?days=7")
    quotes = api_get(
        f"/quote-analysis?date_from={date_var}&date_to={date_var}&summary_only=true"
    )

    return {"team": team, "funnel": funnel, "quality": quality, "quotes": quotes}


# ---------------------------------------------------------------------------
# Report analysis helpers
# ---------------------------------------------------------------------------

def coaching_flags(producers: list, funnel_groups: list) -> list:
    """Identify producers needing coaching attention."""
    flags = []

    # Build funnel lookup by producer name (funnel group_key is producer name)
    funnel_map = {}
    for g in funnel_groups or []:
        key = g.get("group_key", "")
        funnel_map[key] = g.get("metrics", {})

    for p in producers:
        name = p.get("name", "Unknown")
        total = p.get("total", 0)
        if total < 2:
            continue  # Skip producers with very few leads today

        expired = p.get("expired", 0)
        quoted = p.get("quoted", 0)
        won = p.get("won", 0)
        lost = p.get("lost", 0)
        new_leads = p.get("new", 0)
        decided = won + lost

        # High expiration rate
        if total > 0 and expired / total >= 0.35:
            flags.append({
                "producer": name,
                "issue": "High expiration rate",
                "detail": f"{expired}/{total} leads expired ({pct(expired/total)})",
                "severity": "warning",
            })

        # Zero quotes on a reasonable number of leads
        if total >= 5 and quoted == 0 and won == 0:
            flags.append({
                "producer": name,
                "issue": "No leads quoted today",
                "detail": f"{total} leads worked, 0 quoted",
                "severity": "warning",
            })

        # Very high loss rate
        if decided >= 3 and lost / decided >= 0.70:
            flags.append({
                "producer": name,
                "issue": "High loss rate",
                "detail": f"{lost}/{decided} decided leads lost ({pct(lost/decided)})",
                "severity": "alert",
            })

        # Lots of new unworked leads
        if new_leads >= 8:
            flags.append({
                "producer": name,
                "issue": "High new lead backlog",
                "detail": f"{new_leads} uncontacted new leads",
                "severity": "info",
            })

    return flags


def build_action_items(data: dict, flags: list) -> list:
    """Generate 2-3 specific, data-driven action items."""
    actions = []

    team_totals = safe(data["team"], "team_totals", default={})
    quality = data["quality"] or {}
    health_score = quality.get("health_score_pct", "N/A")
    issues = quality.get("issues", {})
    quote_summary = safe(data["quotes"], "summary", default={})
    producers = safe(data["team"], "producers", default=[])

    # 1. Data quality issues
    stuck_count = safe(issues, "stuck_in_new_14_plus_days", "count", default=0)
    quoted_wrong_count = safe(issues, "quoted_but_wrong_status", "count", default=0)
    if isinstance(stuck_count, int) and stuck_count > 5:
        actions.append(
            f"<strong>{stuck_count} leads have been stuck in NEW status for 14+ days</strong> — "
            "assign or contact these leads today to prevent expiration."
        )
    if isinstance(quoted_wrong_count, int) and quoted_wrong_count > 3:
        actions.append(
            f"<strong>{quoted_wrong_count} quoted leads still show NEW/CONTACTED status</strong> — "
            "producers need to update AgencyZoom status after quoting."
        )

    # 2. Bundle rate
    total_q = quote_summary.get("total", 0)
    bundled_q = quote_summary.get("bundled", 0)
    if total_q > 0:
        bundle_rate = bundled_q / total_q
        if bundle_rate < 0.30:
            actions.append(
                f"<strong>Bundle rate is only {pct(bundle_rate)}</strong> — "
                "remind team to present multi-line options on every quote to improve retention and premium."
            )

    # 3. Coaching flags
    alert_producers = [f["producer"] for f in flags if f["severity"] == "alert"]
    if alert_producers:
        actions.append(
            f"<strong>Priority coaching: {', '.join(set(alert_producers))}</strong> — "
            "these producers have high loss rates and need a sales process review."
        )

    # 4. High expiry overall
    total_leads = team_totals.get("total_leads", 0)
    team_expired = sum(p.get("expired", 0) for p in producers)
    if total_leads > 0 and team_expired > 0 and team_expired / total_leads >= 0.25:
        actions.append(
            f"<strong>Team expiration rate is {pct(team_expired/total_leads)}</strong> — "
            "review follow-up cadence; consider implementing a re-engagement sequence for aging leads."
        )

    # 5. Fallback if nothing flagged
    if not actions:
        won = team_totals.get("won", 0)
        if won > 0:
            actions.append(
                f"Strong day with {won} policies written. "
                "Keep momentum by contacting new leads within 24 hours of assignment."
            )
        else:
            actions.append(
                "Focus on quoted leads today — following up quickly after quotes significantly improves close rates."
            )

    return actions[:3]  # Cap at 3


# ---------------------------------------------------------------------------
# HTML report builder
# ---------------------------------------------------------------------------

CSS = """
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
         background: #f4f6f9; margin: 0; padding: 20px; color: #1a1a2e; }
  .container { max-width: 780px; margin: 0 auto; background: #fff;
               border-radius: 10px; overflow: hidden;
               box-shadow: 0 2px 12px rgba(0,0,0,0.10); }
  .header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #fff; padding: 28px 32px; }
  .header h1 { margin: 0 0 4px; font-size: 22px; font-weight: 700; }
  .header p  { margin: 0; font-size: 14px; opacity: 0.75; }
  .body { padding: 28px 32px; }
  h2 { font-size: 15px; font-weight: 700; text-transform: uppercase;
       letter-spacing: 0.05em; color: #1a1a2e; margin: 28px 0 12px;
       border-bottom: 2px solid #e8ecf2; padding-bottom: 6px; }
  h2:first-child { margin-top: 0; }
  .stat-row { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
  .stat { flex: 1; min-width: 100px; background: #f4f6f9; border-radius: 8px;
          padding: 14px 16px; text-align: center; }
  .stat .val { font-size: 28px; font-weight: 700; color: #1a1a2e; line-height: 1; }
  .stat .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
               color: #6b7280; margin-top: 4px; }
  .stat.green .val { color: #059669; }
  .stat.red   .val { color: #dc2626; }
  .stat.blue  .val { color: #2563eb; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { background: #f4f6f9; text-align: left; padding: 8px 10px;
       font-weight: 600; color: #6b7280; font-size: 11px;
       text-transform: uppercase; letter-spacing: 0.04em; }
  td { padding: 8px 10px; border-bottom: 1px solid #f0f0f0; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #fafafa; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
           font-size: 11px; font-weight: 600; }
  .badge.warn { background: #fef3c7; color: #92400e; }
  .badge.alert { background: #fee2e2; color: #991b1b; }
  .badge.info  { background: #dbeafe; color: #1e40af; }
  .flag-row { display: flex; align-items: flex-start; gap: 10px;
              padding: 10px 0; border-bottom: 1px solid #f0f0f0; }
  .flag-row:last-child { border-bottom: none; }
  .flag-icon { font-size: 18px; flex-shrink: 0; }
  .flag-text strong { display: block; font-size: 13px; }
  .flag-text span { font-size: 12px; color: #6b7280; }
  .action-list { list-style: none; padding: 0; margin: 0; }
  .action-list li { display: flex; align-items: flex-start; gap: 10px;
                    padding: 10px 0; border-bottom: 1px solid #f0f0f0;
                    font-size: 13px; line-height: 1.5; }
  .action-list li:last-child { border-bottom: none; }
  .action-num { background: #1a1a2e; color: #fff; border-radius: 50%;
                width: 22px; height: 22px; display: flex; align-items: center;
                justify-content: center; font-size: 11px; font-weight: 700;
                flex-shrink: 0; margin-top: 1px; }
  .quality-bar { background: #e8ecf2; border-radius: 6px; height: 12px;
                 overflow: hidden; margin-top: 6px; }
  .quality-fill { height: 100%; border-radius: 6px; }
  .no-data { color: #9ca3af; font-style: italic; font-size: 13px; padding: 12px 0; }
  .footer { background: #f4f6f9; padding: 16px 32px; font-size: 11px;
            color: #9ca3af; text-align: center; }
"""


def _rank_medal(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")


def build_html(data: dict, date_var: str) -> str:
    date_display = pacific_today_display(date_var)

    # -----------------------------------------------------------------------
    # 1. Team Summary
    # -----------------------------------------------------------------------
    tt = safe(data["team"], "team_totals", default={})
    if isinstance(tt, str):
        tt = {}

    producers_raw = safe(data["team"], "producers", default=[])
    if not isinstance(producers_raw, list):
        producers_raw = []

    total_leads = tt.get("total_leads", 0)
    team_won = tt.get("won", 0)
    team_lost = tt.get("lost", 0)
    team_new = tt.get("new", 0)
    team_close_pct = tt.get("close_rate_pct", "—")
    team_expired = sum(p.get("expired", 0) for p in producers_raw)
    team_quoted = sum(p.get("quoted", 0) for p in producers_raw)

    stat_row = f"""
    <div class="stat-row">
      <div class="stat">
        <div class="val">{total_leads}</div>
        <div class="lbl">Leads Worked</div>
      </div>
      <div class="stat green">
        <div class="val">{team_won}</div>
        <div class="lbl">Won</div>
      </div>
      <div class="stat red">
        <div class="val">{team_lost}</div>
        <div class="lbl">Lost</div>
      </div>
      <div class="stat">
        <div class="val">{team_quoted}</div>
        <div class="lbl">Quoted</div>
      </div>
      <div class="stat">
        <div class="val">{team_expired}</div>
        <div class="lbl">Expired</div>
      </div>
      <div class="stat blue">
        <div class="val">{team_close_pct}</div>
        <div class="lbl">Close Rate</div>
      </div>
    </div>"""

    # -----------------------------------------------------------------------
    # 2. Producer Leaderboard
    # -----------------------------------------------------------------------
    if producers_raw:
        rows = ""
        for i, p in enumerate(producers_raw, 1):
            name = p.get("name", "Unknown")
            won = p.get("won", 0)
            lost = p.get("lost", 0)
            quoted = p.get("quoted", 0)
            expired = p.get("expired", 0)
            total = p.get("total", 0)
            close_pct = p.get("close_rate_pct", "—")
            medal = _rank_medal(i)
            rows += f"""
            <tr>
              <td>{medal} {name}</td>
              <td style="text-align:center">{total}</td>
              <td style="text-align:center">{quoted}</td>
              <td style="text-align:center;color:#059669;font-weight:600">{won}</td>
              <td style="text-align:center;color:#dc2626">{lost}</td>
              <td style="text-align:center;color:#d97706">{expired}</td>
              <td style="text-align:center;font-weight:700">{close_pct}</td>
            </tr>"""
        leaderboard_html = f"""
        <table>
          <tr>
            <th>Producer</th><th style="text-align:center">Leads</th>
            <th style="text-align:center">Quoted</th>
            <th style="text-align:center">Won</th>
            <th style="text-align:center">Lost</th>
            <th style="text-align:center">Expired</th>
            <th style="text-align:center">Close Rate</th>
          </tr>
          {rows}
        </table>
        <p style="font-size:11px;color:#9ca3af;margin-top:8px">
          ℹ️ Quoted = leads with quote records or quote_date set (AgencyZoom rarely sets QUOTED status automatically).
          Close rate = Won ÷ (Won + Lost).
        </p>"""
    else:
        leaderboard_html = '<p class="no-data">No producer data for this date.</p>'

    # -----------------------------------------------------------------------
    # 3. Quoting Activity
    # -----------------------------------------------------------------------
    qs = safe(data["quotes"], "summary", default={})
    if isinstance(qs, str):
        qs = {}

    q_total = qs.get("total", 0)
    q_bundled = qs.get("bundled", 0)
    q_mono = qs.get("mono_line", 0)
    bundle_rate_str = pct(q_bundled / q_total) if q_total > 0 else "N/A"

    carriers = qs.get("by_carrier", []) or []
    products = qs.get("by_product", []) or []

    carrier_rows = "".join(
        f"<tr><td>{c.get('name','—')}</td>"
        f"<td style='text-align:center'>{c.get('count',0)}</td>"
        f"<td style='text-align:center'>"
        f"{pct(c.get('count',0)/q_total) if q_total>0 else '—'}</td></tr>"
        for c in carriers[:6]
    )
    product_rows = "".join(
        f"<tr><td>{pr.get('name','—')}</td>"
        f"<td style='text-align:center'>{pr.get('count',0)}</td></tr>"
        for pr in products[:6]
    )

    if q_total > 0:
        quoting_html = f"""
        <div class="stat-row">
          <div class="stat">
            <div class="val">{q_total}</div>
            <div class="lbl">Quoted Leads</div>
          </div>
          <div class="stat green">
            <div class="val">{q_bundled}</div>
            <div class="lbl">Bundled</div>
          </div>
          <div class="stat">
            <div class="val">{q_mono}</div>
            <div class="lbl">Mono-Line</div>
          </div>
          <div class="stat blue">
            <div class="val">{bundle_rate_str}</div>
            <div class="lbl">Bundle Rate</div>
          </div>
        </div>
        <div style="display:flex;gap:24px;margin-top:16px">
          <div style="flex:1">
            <p style="font-size:12px;font-weight:600;text-transform:uppercase;
                      letter-spacing:.04em;color:#6b7280;margin:0 0 8px">Top Carriers</p>
            <table>
              <tr><th>Carrier</th><th style="text-align:center">Quotes</th>
                  <th style="text-align:center">Share</th></tr>
              {carrier_rows or '<tr><td colspan="3" class="no-data">No carrier data</td></tr>'}
            </table>
          </div>
          <div style="flex:1">
            <p style="font-size:12px;font-weight:600;text-transform:uppercase;
                      letter-spacing:.04em;color:#6b7280;margin:0 0 8px">Top Products</p>
            <table>
              <tr><th>Product</th><th style="text-align:center">Quotes</th></tr>
              {product_rows or '<tr><td colspan="2" class="no-data">No product data</td></tr>'}
            </table>
          </div>
        </div>"""
    else:
        quoting_html = '<p class="no-data">No quotes recorded for this date.</p>'

    # -----------------------------------------------------------------------
    # 4. Coaching Flags
    # -----------------------------------------------------------------------
    funnel_groups = safe(data["funnel"], "groups", default=[])
    if not isinstance(funnel_groups, list):
        funnel_groups = []

    flags = coaching_flags(producers_raw, funnel_groups)

    if flags:
        severity_icon = {"warning": "⚠️", "alert": "🚨", "info": "ℹ️"}
        severity_label = {"warning": "warn", "alert": "alert", "info": "info"}
        flag_items = "".join(
            f"""<div class="flag-row">
              <div class="flag-icon">{severity_icon.get(f['severity'],'⚠️')}</div>
              <div class="flag-text">
                <strong>
                  <span class="badge {severity_label.get(f['severity'],'warn')}">
                    {f['severity'].upper()}
                  </span>
                  &nbsp;{f['producer']} — {f['issue']}
                </strong>
                <span>{f['detail']}</span>
              </div>
            </div>"""
            for f in flags
        )
        coaching_html = flag_items
    else:
        coaching_html = '<p class="no-data">✅ No coaching flags today — all producers are within normal ranges.</p>'

    # -----------------------------------------------------------------------
    # 5. Data Quality
    # -----------------------------------------------------------------------
    qual = data["quality"] or {}
    health_score_str = qual.get("health_score_pct", "N/A")
    total_scanned = qual.get("total_leads_scanned", 0)
    total_issues_count = qual.get("total_issues", 0)
    issues_map = qual.get("issues", {})

    try:
        health_pct_val = int(health_score_str.replace("%", ""))
    except Exception:
        health_pct_val = 0

    health_color = (
        "#059669" if health_pct_val >= 85
        else "#d97706" if health_pct_val >= 70
        else "#dc2626"
    )

    issue_rows = ""
    severity_order = {"high": 0, "medium": 1, "low": 2}
    sorted_issues = sorted(
        issues_map.items(),
        key=lambda kv: severity_order.get(kv[1].get("severity", "low"), 9)
    )
    for key, val in sorted_issues:
        count = val.get("count", 0)
        if count == 0:
            continue
        sev = val.get("severity", "low")
        desc = val.get("description", key.replace("_", " ").title())
        sev_color = {"high": "#dc2626", "medium": "#d97706", "low": "#6b7280"}.get(sev, "#6b7280")
        issue_rows += f"""<tr>
          <td>{desc}</td>
          <td style="text-align:center;font-weight:600;color:{sev_color}">{count}</td>
          <td style="text-align:center">
            <span class="badge {'alert' if sev=='high' else 'warn' if sev=='medium' else 'info'}">
              {sev.upper()}
            </span>
          </td>
        </tr>"""

    quality_html = f"""
    <div style="display:flex;align-items:center;gap:20px;margin-bottom:16px">
      <div style="flex:1">
        <div style="font-size:13px;color:#6b7280">Health Score
          <span style="font-size:22px;font-weight:700;color:{health_color};margin-left:8px">
            {health_score_str}
          </span>
          <span style="font-size:12px;color:#9ca3af"> ({total_issues_count} issues across {total_scanned} leads, last 7 days)</span>
        </div>
        <div class="quality-bar">
          <div class="quality-fill" style="width:{health_pct_val}%;background:{health_color}"></div>
        </div>
      </div>
    </div>
    {"<table><tr><th>Issue</th><th style='text-align:center'>Count</th><th style='text-align:center'>Severity</th></tr>" + issue_rows + "</table>" if issue_rows else '<p class="no-data">✅ No data quality issues detected.</p>'}
    """

    # -----------------------------------------------------------------------
    # 6. Action Items
    # -----------------------------------------------------------------------
    actions = build_action_items(data, flags)
    action_items_html = "<ul class='action-list'>" + "".join(
        f"<li><div class='action-num'>{i}</div><div>{a}</div></li>"
        for i, a in enumerate(actions, 1)
    ) + "</ul>"

    # -----------------------------------------------------------------------
    # Assemble full HTML
    # -----------------------------------------------------------------------
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Activity Report — {date_var}</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>📊 Daily Activity Report</h1>
    <p>Jennifer White Insurance Agency &nbsp;·&nbsp; {date_display}</p>
  </div>
  <div class="body">

    <h2>1. Team Summary</h2>
    {stat_row}

    <h2>2. Producer Leaderboard</h2>
    {leaderboard_html}

    <h2>3. Quoting Activity</h2>
    {quoting_html}

    <h2>4. Coaching Flags</h2>
    {coaching_html}

    <h2>5. Data Quality (Last 7 Days)</h2>
    {quality_html}

    <h2>6. Action Items</h2>
    {action_items_html}

  </div>
  <div class="footer">
    Generated {datetime.now(ZoneInfo('America/Los_Angeles')).strftime('%Y-%m-%d %I:%M %p PT')}
    &nbsp;·&nbsp; JWhiteZaps AZ Analyst Service
    &nbsp;·&nbsp; Data from AgencyZoom (synced cache + live API)
  </div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Email sender
# ---------------------------------------------------------------------------

def send_email(html: str, subject: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_FROM
    msg["To"] = REPORT_TO
    msg.attach(MIMEText(html, "html"))

    print(f"[INFO] Sending email to {REPORT_TO}...", file=sys.stderr)
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(GMAIL_FROM, GMAIL_APP_PASSWORD)
        server.send_message(msg)
    print("[INFO] Email sent successfully.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not API_KEY:
        print("[ERROR] ANALYST_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    date_var = pacific_today()
    data = fetch_all(date_var)

    if not any(data.values()):
        print("[ERROR] All API calls failed. Check API key and connectivity.", file=sys.stderr)
        sys.exit(1)

    html = build_html(data, date_var)
    subject = f"Daily Activity Report — {date_var}"

    if DRY_RUN:
        print(html)
        return

    if not GMAIL_APP_PASSWORD:
        print("[WARN] GMAIL_APP_PASSWORD not set — printing HTML to stdout instead.", file=sys.stderr)
        print(html)
        return

    send_email(html, subject)
    print(f"[INFO] Daily report for {date_var} sent to {REPORT_TO}", file=sys.stderr)


if __name__ == "__main__":
    main()
