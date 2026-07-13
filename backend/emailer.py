import resend

from config import db, logger, RESEND_API_KEY, EMAIL_FROM, APP_PUBLIC_URL


def _thumbs_html(job: dict) -> str:
    photos = job.get("photos") or []
    if not photos:
        return ""
    base = APP_PUBLIC_URL
    cells = ""
    for p in photos[:6]:
        src = f"{base}/api/public/job-photo/{job['id']}/{p['id']}"
        cells += (
            f'<td style="padding:4px;">'
            f'<img src="{src}" width="96" height="96" alt="Service photo" '
            f'style="border-radius:10px;display:block;object-fit:cover;border:1px solid #E2E8F0;" />'
            f"</td>"
        )
    return (
        '<p style="margin:20px 0 8px;font-family:Arial,sans-serif;font-size:14px;color:#334155;">'
        "Photos from your visit:</p>"
        '<table role="presentation" border="0" cellpadding="0" cellspacing="0"><tr>'
        f"{cells}</tr></table>"
    )


def _completion_html(job: dict, customer_name: str) -> str:
    report_url = f"{APP_PUBLIC_URL}/job/{job['id']}"
    service = job.get("service_type", "service")
    when = (job.get("scheduled_date") or "")[:10]
    return f"""
    <div style="max-width:560px;margin:0 auto;font-family:Arial,sans-serif;color:#1A2B3C;">
      <div style="background:#003C5F;padding:24px;border-radius:12px 12px 0 0;">
        <h1 style="color:#fff;margin:0;font-size:20px;">Pool &amp; Landscaping of Vistancia</h1>
      </div>
      <div style="border:1px solid #E2E8F0;border-top:none;border-radius:0 0 12px 12px;padding:24px;">
        <h2 style="font-size:18px;margin:0 0 8px;">Your service is complete ✅</h2>
        <p style="font-size:14px;color:#334155;line-height:20px;margin:0 0 4px;">
          Hi {customer_name}, we've finished your <strong>{service}</strong>{f' on {when}' if when else ''}.
          Your full service report — checklist, water readings and chemicals added — is ready to view.
        </p>
        {_thumbs_html(job)}
        <div style="text-align:center;margin:28px 0 8px;">
          <a href="{report_url}"
             style="background:#0EA5B7;color:#fff;text-decoration:none;font-size:15px;font-weight:bold;
                    padding:14px 28px;border-radius:10px;display:inline-block;">
            View Your Service Report
          </a>
        </div>
        <p style="font-size:12px;color:#94A3B8;text-align:center;margin:12px 0 0;">
          Questions? Just reply in the app and our team (and Marina, our assistant) will help.
        </p>
      </div>
    </div>
    """


async def send_completion_email(job: dict) -> bool:
    """Email the customer that their job is complete, with photo thumbnails + a report link."""
    if not RESEND_API_KEY:
        logger.info("Resend not configured — skipping completion email.")
        return False
    cid = job.get("customer_id")
    if not cid:
        return False
    cust = await db.customers.find_one({"id": cid}, {"_id": 0}) or {}
    to_email = cust.get("email")
    if not to_email:
        user = await db.users.find_one({"customer_id": cid, "role": "customer"}, {"_id": 0})
        to_email = user.get("email") if user else None
    if not to_email:
        logger.info("No customer email — skipping completion email.")
        return False
    try:
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": EMAIL_FROM,
            "to": to_email,
            "subject": f"Your {job.get('service_type', 'service')} is complete",
            "html": _completion_html(job, cust.get("name", "there")),
        })
        return True
    except Exception as e:
        logger.warning(f"Completion email failed: {e}")
        return False


def _reminder_html(inv: dict, name: str) -> str:
    balance = round(float(inv.get("total") or 0) - float(inv.get("amount_paid") or 0), 2)
    due = inv.get("due_date") or "now"
    pay_link = f"{APP_PUBLIC_URL}" if APP_PUBLIC_URL else ""
    link_html = f'<p><a href="{pay_link}" style="background:#0891b2;color:#fff;padding:12px 20px;border-radius:8px;text-decoration:none;display:inline-block">Pay Now</a></p>' if pay_link else ""
    return (
        f'<div style="font-family:sans-serif;max-width:520px;margin:auto">'
        f"<h2>Payment reminder</h2><p>Hi {name},</p>"
        f"<p>This is a friendly reminder that invoice <b>{inv.get('title','')}</b> has an outstanding balance of "
        f"<b>${balance:,.2f}</b> (was due {due}).</p>{link_html}"
        f"<p>Thank you,<br/>Pool &amp; Landscaping of Vistancia</p></div>"
    )


async def send_invoice_reminder_email(inv: dict) -> bool:
    """Email the customer a payment reminder for an outstanding invoice."""
    if not RESEND_API_KEY:
        logger.info("Resend not configured — skipping invoice reminder email.")
        return False
    cid = inv.get("customer_id")
    if not cid:
        return False
    cust = await db.customers.find_one({"id": cid}, {"_id": 0}) or {}
    to_email = cust.get("email")
    if not to_email:
        user = await db.users.find_one({"customer_id": cid, "role": "customer"}, {"_id": 0})
        to_email = user.get("email") if user else None
    if not to_email:
        logger.info("No customer email — skipping reminder email.")
        return False
    try:
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": EMAIL_FROM,
            "to": to_email,
            "subject": f"Payment reminder — {inv.get('title', 'invoice')}",
            "html": _reminder_html(inv, cust.get("name", "there")),
        })
        return True
    except Exception as e:
        logger.warning(f"Reminder email failed: {e}")
        return False
