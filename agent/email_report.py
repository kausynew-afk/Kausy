"""Email report — generates HTML report file + sends via SMTP or saves for workflow."""

from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from .models import ApplicationRecord

logger = logging.getLogger(__name__)


class EmailReporter:
    """Generates a styled HTML report and optionally sends via SMTP."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        auto = config.get("automation", {})
        self._recipient = auto.get("email_recipient", "")
        self._smtp_user = os.environ.get("SMTP_USER", os.environ.get("GMAIL_USER", ""))
        self._smtp_pass = os.environ.get("SMTP_PASSWORD", os.environ.get("GMAIL_APP_PASSWORD", ""))
        self._smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
        self._smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        self._output_dir = Path(config.get("logging", {}).get("output_directory", "output"))

    def send_report(
        self,
        records: list[ApplicationRecord],
        run_id: str,
        stats: dict[str, Any],
    ) -> bool:
        html = self._render_html(records, run_id, stats)

        report_path = self._output_dir / "email_report.html"
        report_path.write_text(html, encoding="utf-8")
        logger.info("Email HTML report saved to %s", report_path)

        if not self._recipient:
            logger.info("Email: no recipient configured, skipping send")
            return False
        if not self._smtp_user or not self._smtp_pass:
            logger.info(
                "Email: SMTP credentials not set (set SMTP_USER + SMTP_PASSWORD "
                "or GMAIL_USER + GMAIL_APP_PASSWORD). Report saved to %s", report_path,
            )
            return False

        try:
            msg = self._build_email(records, run_id, stats, html)
            self._attach_resumes(msg, records)

            with smtplib.SMTP(self._smtp_server, self._smtp_port) as server:
                server.starttls()
                server.login(self._smtp_user, self._smtp_pass)
                server.send_message(msg)

            logger.info("Email report sent to %s via %s", self._recipient, self._smtp_server)
            return True
        except Exception as e:
            logger.error("Email send failed: %s. Report still saved to %s", e, report_path)
            return False

    def _build_email(
        self,
        records: list[ApplicationRecord],
        run_id: str,
        stats: dict[str, Any],
        html: str,
    ) -> MIMEMultipart:
        msg = MIMEMultipart("mixed")
        msg["From"] = self._smtp_user
        msg["To"] = self._recipient
        msg["Subject"] = (
            f"Job Agent Report — {datetime.now().strftime('%Y-%m-%d')} | "
            f"{stats.get('applied', 0)} Applied, "
            f"{stats.get('skipped', 0)} Skipped"
        )
        msg.attach(MIMEText(html, "html", "utf-8"))
        return msg

    def _attach_resumes(
        self, msg: MIMEMultipart, records: list[ApplicationRecord]
    ) -> None:
        attached = 0
        for rec in records:
            if rec.status != "logged" or not rec.resume_path:
                continue
            path = Path(rec.resume_path)
            if not path.exists():
                continue
            try:
                data = path.read_bytes()
                part = MIMEApplication(data, Name=rec.resume_filename or path.name)
                part["Content-Disposition"] = (
                    f'attachment; filename="{rec.resume_filename or path.name}"'
                )
                msg.attach(part)
                attached += 1
            except Exception as e:
                logger.warning("Could not attach %s: %s", path, e)

        logger.info("Email: attached %d tailored resume(s)", attached)

    def _render_html(
        self,
        records: list[ApplicationRecord],
        run_id: str,
        stats: dict[str, Any],
    ) -> str:
        applied = [r for r in records if r.status == "logged"]
        skipped = [r for r in records if r.status == "skipped"]
        errors = [r for r in records if r.status == "error"]
        date_str = datetime.now().strftime("%B %d, %Y  %H:%M")

        applied_rows = ""
        for i, r in enumerate(applied, 1):
            code = r.job.job_code or "NA"
            applied_rows += f"""
            <tr>
                <td>{i}</td>
                <td>{code}</td>
                <td><strong>{r.job.company}</strong></td>
                <td>{r.job.title}</td>
                <td>{r.job.platform}</td>
                <td>{r.job.location}</td>
                <td>{r.ats_score:.1f}%</td>
                <td><a href="{r.job.url}">View</a></td>
                <td>{r.resume_filename}</td>
            </tr>"""

        skipped_rows = ""
        for i, r in enumerate(skipped, 1):
            code = r.job.job_code or "NA"
            skipped_rows += f"""
            <tr>
                <td>{i}</td>
                <td>{code}</td>
                <td>{r.job.company}</td>
                <td>{r.job.title}</td>
                <td>{r.job.platform}</td>
                <td>{r.ats_score:.1f}%</td>
                <td>{r.notes[:80]}</td>
            </tr>"""

        error_rows = ""
        for i, r in enumerate(errors, 1):
            error_rows += f"""
            <tr>
                <td>{i}</td>
                <td>{r.job.company}</td>
                <td>{r.job.title}</td>
                <td>{r.notes[:80]}</td>
            </tr>"""

        return f"""<!DOCTYPE html>
<html>
<head>
<style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
    .container {{ max-width: 900px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
    .header {{ background: linear-gradient(135deg, #1a73e8, #4285f4); color: white; padding: 24px 32px; }}
    .header h1 {{ margin: 0; font-size: 22px; }}
    .header p {{ margin: 6px 0 0; opacity: 0.9; font-size: 14px; }}
    .stats {{ display: flex; padding: 20px 32px; gap: 20px; border-bottom: 1px solid #e0e0e0; }}
    .stat-box {{ flex: 1; text-align: center; padding: 12px; border-radius: 8px; }}
    .stat-box.applied {{ background: #e8f5e9; color: #2e7d32; }}
    .stat-box.skipped {{ background: #fff3e0; color: #e65100; }}
    .stat-box.errors {{ background: #fce4ec; color: #c62828; }}
    .stat-box.total {{ background: #e3f2fd; color: #1565c0; }}
    .stat-num {{ font-size: 28px; font-weight: bold; }}
    .stat-label {{ font-size: 12px; text-transform: uppercase; margin-top: 4px; }}
    .section {{ padding: 20px 32px; }}
    .section h2 {{ color: #333; font-size: 18px; border-bottom: 2px solid #1a73e8; padding-bottom: 8px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th {{ background: #f8f9fa; padding: 10px 8px; text-align: left; border-bottom: 2px solid #ddd; color: #555; font-size: 11px; text-transform: uppercase; }}
    td {{ padding: 10px 8px; border-bottom: 1px solid #eee; }}
    tr:hover {{ background: #f8f9fa; }}
    a {{ color: #1a73e8; text-decoration: none; }}
    .footer {{ padding: 16px 32px; background: #f8f9fa; text-align: center; font-size: 12px; color: #888; }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>Job Application Agent — Daily Report</h1>
        <p>{date_str} &nbsp;|&nbsp; Run ID: {run_id}</p>
    </div>
    <div class="stats">
        <div class="stat-box total"><div class="stat-num">{stats.get('processed', 0)}</div><div class="stat-label">Processed</div></div>
        <div class="stat-box applied"><div class="stat-num">{stats.get('applied', 0)}</div><div class="stat-label">Applied</div></div>
        <div class="stat-box skipped"><div class="stat-num">{stats.get('skipped', 0)}</div><div class="stat-label">Skipped</div></div>
        <div class="stat-box errors"><div class="stat-num">{stats.get('errors', 0)}</div><div class="stat-label">Errors</div></div>
    </div>
    {"" if not applied else f'''
    <div class="section">
        <h2>Applied Jobs ({len(applied)})</h2>
        <p>Tailored resumes are attached to this email.</p>
        <table>
            <tr><th>#</th><th>Code</th><th>Company</th><th>Position</th><th>Platform</th><th>Location</th><th>ATS</th><th>Link</th><th>Resume</th></tr>
            {applied_rows}
        </table>
    </div>'''}
    {"" if not skipped else f'''
    <div class="section">
        <h2>Skipped Jobs ({len(skipped)})</h2>
        <table>
            <tr><th>#</th><th>Code</th><th>Company</th><th>Position</th><th>Platform</th><th>ATS</th><th>Reason</th></tr>
            {skipped_rows}
        </table>
    </div>'''}
    {"" if not errors else f'''
    <div class="section">
        <h2>Errors ({len(errors)})</h2>
        <table>
            <tr><th>#</th><th>Company</th><th>Position</th><th>Error</th></tr>
            {error_rows}
        </table>
    </div>'''}
    <div class="footer">
        Automated by Job Application Agent &nbsp;|&nbsp;
        <a href="https://github.com/kausynew-afk/Kausy">View on GitHub</a>
    </div>
</div>
</body>
</html>"""
