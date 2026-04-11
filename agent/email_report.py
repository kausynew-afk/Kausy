"""Email report — sends per-job emails + end-of-run summary via SMTP.

Rule 4: The agent MUST NOT submit job applications automatically.
Instead, for each valid job it sends an individual email containing
the job details, application link, match summary, and the tailored
PDF resume as an attachment.
"""

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

from .models import ApplicationRecord, ATSResult, JobListing

logger = logging.getLogger(__name__)


class EmailReporter:
    """Sends per-job emails with tailored PDF resumes + an end-of-run summary."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        auto = config.get("automation", {})
        self._recipient = auto.get("email_recipient", "")
        self._smtp_user = (
            os.environ.get("SMTP_USER", "").strip()
            or os.environ.get("GMAIL_USER", "").strip()
        )
        self._smtp_pass = (
            os.environ.get("SMTP_PASSWORD", "").strip()
            or os.environ.get("GMAIL_APP_PASSWORD", "").strip()
        )
        self._smtp_server = os.environ.get("SMTP_SERVER", "").strip() or "smtp.gmail.com"
        raw_port = os.environ.get("SMTP_PORT", "").strip()
        self._smtp_port = int(raw_port) if raw_port else 587
        self._output_dir = Path(config.get("logging", {}).get("output_directory", "output"))
        self._emails_sent = 0
        self._emails_failed = 0

    @property
    def can_send(self) -> bool:
        return bool(self._recipient and self._smtp_user and self._smtp_pass)

    # ── Per-job email (Rule 4) ───────────────────────────────────────────

    def send_job_email(
        self,
        job: JobListing,
        ats: ATSResult,
        resume_path: str,
        resume_filename: str,
        skip_reason: str = "",
    ) -> bool:
        """Send ONE email for ONE job with the tailored PDF resume attached.

        If skip_reason is provided, the email indicates the job was skipped
        but still includes the apply link and resume for manual review.
        Returns True if the email was sent successfully.
        """
        if not self.can_send:
            logger.info(
                "Email: credentials not configured, skipping per-job email for %s @ %s",
                job.title, job.company,
            )
            return False

        if skip_reason:
            subject = f"[Low Match] {job.company} - {job.title} (ATS {ats.overall_score:.0f}%)"
        else:
            subject = f"New Job Ready for Application - {job.company} - {job.title}"

        html = self._render_job_html(job, ats, resume_filename, skip_reason)

        msg = MIMEMultipart("mixed")
        msg["From"] = self._smtp_user
        msg["To"] = self._recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html", "utf-8"))

        pdf_path = Path(resume_path)
        if pdf_path.exists():
            try:
                data = pdf_path.read_bytes()
                subtype = "pdf" if pdf_path.suffix.lower() == ".pdf" else "octet-stream"
                part = MIMEApplication(data, _subtype=subtype, Name=resume_filename)
                part["Content-Disposition"] = f'attachment; filename="{resume_filename}"'
                msg.attach(part)
            except Exception as e:
                logger.warning("Could not attach %s: %s", pdf_path, e)
        else:
            logger.warning("Resume file not found for attachment: %s", resume_path)

        try:
            with smtplib.SMTP(self._smtp_server, self._smtp_port) as server:
                server.starttls()
                server.login(self._smtp_user, self._smtp_pass)
                server.send_message(msg)
            self._emails_sent += 1
            logger.info(
                "EMAIL SENT (%s): %s @ %s -> %s (resume: %s)",
                "skipped" if skip_reason else "matched",
                job.title, job.company, self._recipient, resume_filename,
            )
            return True
        except Exception as e:
            self._emails_failed += 1
            logger.error("Email send failed for %s @ %s: %s", job.title, job.company, e)
            return False

    # ── End-of-run summary email + HTML report ────────────────────────────

    def send_summary_report(
        self,
        records: list[ApplicationRecord],
        run_id: str,
        stats: dict[str, Any],
    ) -> bool:
        """Send end-of-run summary email and save HTML report to disk."""
        stats["emails_sent"] = self._emails_sent
        stats["emails_failed"] = self._emails_failed

        html = self._render_summary_html(records, run_id, stats)

        report_path = self._output_dir / "email_report.html"
        report_path.write_text(html, encoding="utf-8")
        logger.info("Email HTML summary report saved to %s", report_path)

        if not self.can_send:
            logger.info("Email: SMTP credentials not set. Report saved to %s", report_path)
            return False

        try:
            msg = MIMEMultipart("mixed")
            msg["From"] = self._smtp_user
            msg["To"] = self._recipient
            msg["Subject"] = (
                f"Job Agent Daily Summary - {datetime.now().strftime('%Y-%m-%d')} | "
                f"{stats.get('email_sent_count', 0)} Jobs Emailed, "
                f"{stats.get('skipped', 0)} Skipped"
            )
            msg.attach(MIMEText(html, "html", "utf-8"))

            self._attach_all_pdfs(msg, records)

            with smtplib.SMTP(self._smtp_server, self._smtp_port) as server:
                server.starttls()
                server.login(self._smtp_user, self._smtp_pass)
                server.send_message(msg)

            logger.info("Summary email sent to %s", self._recipient)
            return True
        except Exception as e:
            logger.error("Summary email failed: %s. Report saved to %s", e, report_path)
            return False

    # ── HTML renderers ────────────────────────────────────────────────────

    def _render_job_html(
        self, job: JobListing, ats: ATSResult, resume_filename: str,
        skip_reason: str = "",
    ) -> str:
        """Styled HTML body for a single-job email."""
        code = job.job_code or "NA"
        date_str = datetime.now().strftime("%B %d, %Y")

        matched = ", ".join(ats.technical_matches[:10]) or "N/A"
        missing = ", ".join(ats.technical_missing[:10]) or "None"

        if skip_reason:
            banner_bg = "linear-gradient(135deg, #e65100, #ff9800)"
            banner_title = "Job Found - Low ATS Match (Review Manually)"
            status_badge = (
                f'<div style="margin-top:12px;padding:8px 14px;background:#fff3e0;'
                f'border-left:4px solid #e65100;border-radius:4px;font-size:13px;color:#bf360c;">'
                f'<strong>Skipped Reason:</strong> {skip_reason}</div>'
            )
        else:
            banner_bg = "linear-gradient(135deg, #1a73e8, #4285f4)"
            banner_title = "New Job Ready for Application"
            status_badge = ""

        return f"""<!DOCTYPE html>
<html>
<head>
<style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
    .card {{ max-width: 680px; margin: 0 auto; background: white; border-radius: 10px;
             overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }}
    .banner {{ background: {banner_bg}; color: white; padding: 24px 28px; }}
    .banner h1 {{ margin: 0; font-size: 20px; }}
    .banner p {{ margin: 6px 0 0; opacity: 0.9; font-size: 13px; }}
    .body {{ padding: 24px 28px; color: #333; }}
    .field {{ margin-bottom: 12px; }}
    .label {{ font-size: 11px; text-transform: uppercase; color: #888; font-weight: 600; }}
    .value {{ font-size: 14px; margin-top: 2px; }}
    .score {{ display: inline-block; background: #e8f5e9; color: #2e7d32; font-weight: bold;
              padding: 4px 12px; border-radius: 14px; font-size: 14px; }}
    .apply-btn {{ display: inline-block; margin-top: 18px; padding: 12px 28px; background: #1a73e8;
                  color: white; text-decoration: none; border-radius: 6px; font-weight: 600;
                  font-size: 15px; }}
    .apply-btn:hover {{ background: #1557b0; }}
    .skills {{ font-size: 13px; margin-top: 8px; }}
    .skills span {{ display: inline-block; padding: 2px 8px; margin: 2px 3px; border-radius: 4px;
                    font-size: 11px; }}
    .match {{ background: #e8f5e9; color: #2e7d32; }}
    .gap {{ background: #fce4ec; color: #c62828; }}
    .footer {{ padding: 14px 28px; background: #f8f9fa; font-size: 11px; color: #999; text-align: center; }}
</style>
</head>
<body>
<div class="card">
    <div class="banner">
        <h1>{banner_title}</h1>
        <p>{date_str}</p>
    </div>
    <div class="body">
        {status_badge}
        <div class="field">
            <div class="label">Company</div>
            <div class="value"><strong>{job.company}</strong></div>
        </div>
        <div class="field">
            <div class="label">Position</div>
            <div class="value">{job.title}</div>
        </div>
        <div class="field">
            <div class="label">Job ID</div>
            <div class="value">{code}</div>
        </div>
        <div class="field">
            <div class="label">Location</div>
            <div class="value">{job.location}</div>
        </div>
        <div class="field">
            <div class="label">Platform</div>
            <div class="value">{job.platform.capitalize()}</div>
        </div>
        <div class="field">
            <div class="label">ATS Match Score</div>
            <div class="value"><span class="score">{ats.overall_score:.1f}%</span></div>
        </div>
        <div class="field">
            <div class="label">Why This Job Matches Your Profile</div>
            <div class="skills">
                <strong>Matched Skills:</strong><br>
                {"".join(f'<span class="match">{s}</span>' for s in ats.technical_matches[:10])}
            </div>
            <div class="skills" style="margin-top:6px">
                <strong>Skills to Highlight:</strong><br>
                {"".join(f'<span class="gap">{s}</span>' for s in ats.technical_missing[:8])}
            </div>
        </div>
        <div class="field">
            <div class="label">Customized Resume</div>
            <div class="value">{resume_filename} (attached)</div>
        </div>
        <div class="field">
            <div class="label">Resume Generated On</div>
            <div class="value">{date_str}</div>
        </div>
        <a class="apply-btn" href="{job.url}" target="_blank">Open Job &amp; Apply Now</a>
    </div>
    <div class="footer">
        Automated by Job Application Agent &middot; You are in full control of submissions
    </div>
</div>
</body>
</html>"""

    def _render_summary_html(
        self,
        records: list[ApplicationRecord],
        run_id: str,
        stats: dict[str, Any],
    ) -> str:
        """Styled HTML for the end-of-run summary email."""
        emailed = [r for r in records if r.status == "email_sent"]
        skipped = [r for r in records if r.status == "skipped"]
        errors = [r for r in records if r.status == "error"]
        date_str = datetime.now().strftime("%B %d, %Y  %H:%M")

        emailed_rows = ""
        for i, r in enumerate(emailed, 1):
            code = r.job.job_code or "NA"
            emailed_rows += f"""
            <tr>
                <td>{i}</td>
                <td>{code}</td>
                <td><strong>{r.job.company}</strong></td>
                <td>{r.job.title}</td>
                <td>{r.job.platform}</td>
                <td>{r.job.location}</td>
                <td>{r.ats_score:.1f}%</td>
                <td><a href="{r.job.url}">Apply</a></td>
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
                <td><a href="{r.job.url}">Apply</a></td>
                <td>{r.resume_filename or 'N/A'}</td>
                <td>{r.notes[:60]}</td>
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

        email_sent_count = stats.get("emails_sent", 0)
        email_failed = stats.get("emails_failed", 0)

        return f"""<!DOCTYPE html>
<html>
<head>
<style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
    .container {{ max-width: 900px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
    .header {{ background: linear-gradient(135deg, #1a73e8, #4285f4); color: white; padding: 24px 32px; }}
    .header h1 {{ margin: 0; font-size: 22px; }}
    .header p {{ margin: 6px 0 0; opacity: 0.9; font-size: 14px; }}
    .stats {{ display: flex; padding: 20px 32px; gap: 16px; border-bottom: 1px solid #e0e0e0; flex-wrap: wrap; }}
    .stat-box {{ flex: 1; text-align: center; padding: 12px; border-radius: 8px; min-width: 100px; }}
    .stat-box.emailed {{ background: #e8f5e9; color: #2e7d32; }}
    .stat-box.skipped {{ background: #fff3e0; color: #e65100; }}
    .stat-box.errors {{ background: #fce4ec; color: #c62828; }}
    .stat-box.total {{ background: #e3f2fd; color: #1565c0; }}
    .stat-num {{ font-size: 28px; font-weight: bold; }}
    .stat-label {{ font-size: 11px; text-transform: uppercase; margin-top: 4px; }}
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
        <h1>Job Application Agent - Daily Summary</h1>
        <p>{date_str} &nbsp;|&nbsp; Run ID: {run_id}</p>
    </div>
    <div class="stats">
        <div class="stat-box total"><div class="stat-num">{stats.get('processed', 0)}</div><div class="stat-label">Processed</div></div>
        <div class="stat-box emailed"><div class="stat-num">{email_sent_count}</div><div class="stat-label">Emailed</div></div>
        <div class="stat-box skipped"><div class="stat-num">{stats.get('skipped', 0)}</div><div class="stat-label">Skipped</div></div>
        <div class="stat-box errors"><div class="stat-num">{stats.get('errors', 0)}</div><div class="stat-label">Errors</div></div>
    </div>
    {"" if not emailed else f'''
    <div class="section">
        <h2>Jobs Emailed to You ({len(emailed)})</h2>
        <p>Individual emails with PDF resumes were sent for each job below. Click "Apply" to open the job posting.</p>
        <table>
            <tr><th>#</th><th>Code</th><th>Company</th><th>Position</th><th>Platform</th><th>Location</th><th>ATS</th><th>Link</th><th>Resume</th></tr>
            {emailed_rows}
        </table>
    </div>'''}
    {"" if not skipped else f'''
    <div class="section">
        <h2>Skipped Jobs ({len(skipped)}) - Low ATS Match</h2>
        <p>These jobs had low ATS scores but resumes and apply links are included for manual review.</p>
        <table>
            <tr><th>#</th><th>Code</th><th>Company</th><th>Position</th><th>Platform</th><th>ATS</th><th>Link</th><th>Resume</th><th>Reason</th></tr>
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

    def _attach_all_pdfs(
        self, msg: MIMEMultipart, records: list[ApplicationRecord]
    ) -> None:
        """Attach all PDF resumes from the current run to the summary email."""
        attached = 0
        for rec in records:
            if not rec.resume_path:
                continue
            path = Path(rec.resume_path)
            if not path.exists():
                continue
            try:
                data = path.read_bytes()
                fname = rec.resume_filename or path.name
                subtype = "pdf" if path.suffix.lower() == ".pdf" else "octet-stream"
                part = MIMEApplication(data, _subtype=subtype, Name=fname)
                part["Content-Disposition"] = f'attachment; filename="{fname}"'
                msg.attach(part)
                attached += 1
            except Exception as e:
                logger.warning("Could not attach %s: %s", path, e)

        for pdf in self._output_dir.glob("*.pdf"):
            already = any(
                Path(r.resume_path).name == pdf.name
                for r in records if r.resume_path
            )
            if already:
                continue
            try:
                data = pdf.read_bytes()
                part = MIMEApplication(data, _subtype="pdf", Name=pdf.name)
                part["Content-Disposition"] = f'attachment; filename="{pdf.name}"'
                msg.attach(part)
                attached += 1
            except Exception as e:
                logger.warning("Could not attach extra PDF %s: %s", pdf, e)

        logger.info("Summary email: attached %d PDF resume(s)", attached)
