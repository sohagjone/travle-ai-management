from typing import Dict, Any
from datetime import datetime
from html import escape

from .base_agent import BaseAgent
from utils.config import get_secret, logger, redact
from utils.report_data import fmt_money, safe_http_url
from utils.validation import is_valid_email


def _h(value: Any) -> str:
    """HTML-escape any text coming from the user or from a provider."""
    return escape("" if value is None else str(value), quote=True)


class EmailAgent(BaseAgent):
    """Builds and (only when the user asks) sends the itinerary email.

    Emailing is OPTIONAL and separate from report downloads. The sender address
    and SendGrid key come from configuration, never from the source code.
    """

    def __init__(self):
        super().__init__(
            name="EmailAgent",
            instructions="""Create detailed travel itinerary emails.
            Include: flight details, hotel information, pricing, and booking links.
            Format content in clean, professional HTML with images and logos.
            Ensure all pricing and scheduling information is clearly presented.""",
            agent_type="email",
        )

    async def run(self, messages: list) -> Dict[str, Any]:
        """Create and send the travel email. `success` is True ONLY if SendGrid accepted it."""
        email_data = self._load_payload(messages)
        to_email = (email_data.get("to_email") or "").strip()
        if not is_valid_email(to_email):
            return {"success": False, "error": "Please enter a valid email address.", "recipient": to_email}

        content = self._generate_email_content(email_data)
        success, error = self.send_email(to_email, content)
        return {
            "success": success,
            "error": error,
            "content": content,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "recipient": to_email,
        }

    def _generate_email_content(self, email_data: Dict[str, Any]) -> str:
        """Generate HTML for the email from the report dict (all text is escaped)."""
        report = email_data["report"]
        req = report["request"]
        summary = (
            f"Flights from {req.get('origin')} to {req.get('destination')}, "
            f"{req.get('departure_date')} to {req.get('return_date')}"
        )

        def link(url, label):
            safe = safe_http_url(url)
            return f'<a href="{_h(safe)}" style="color:#007bff;">{_h(label)}</a>' if safe else ""

        flights_html = "<h2>Flight Options</h2>"
        if not report["flights"]:
            flights_html += "<p>No flight options were returned for this search.</p>"
        for f in report["flights"][:15]:
            logo = safe_http_url(f.get("logo_url"))
            flights_html += f"""
            <div style="margin:10px 0;padding:10px;border:1px solid #ddd;border-radius:8px;">
              <strong>{_h(f.get('airline') or 'Airline n/a')}</strong><br>
              <strong>Flight:</strong> {_h(f.get('flight_number') or 'n/a')}<br>
              <strong>Departure:</strong> {_h(f.get('departure') or 'n/a')}<br>
              <strong>Arrival:</strong> {_h(f.get('arrival') or 'n/a')}<br>
              <strong>Duration:</strong> {_h(f.get('duration') or 'n/a')}<br>
              <strong>Price:</strong> {_h(fmt_money(f.get('price'), f.get('currency') or 'USD'))}<br>
              {f'<img src="{_h(logo)}" alt="" style="width:80px;height:auto;"><br>' if logo else ''}
              {link(f.get('booking_url'), 'View on Google Flights')}
            </div>"""

        hotels_html = "<h2>Hotel Options</h2>"
        if not report["hotels"]:
            hotels_html += "<p>No hotel options were returned for this search.</p>"
        for h in report["hotels"][:15]:
            rating = f"{h['rating']:.1f}" if h.get("rating") is not None else "n/a"
            img = safe_http_url(h.get("image_url"))
            hotels_html += f"""
            <div style="margin:10px 0;padding:10px;border:1px solid #ddd;border-radius:8px;">
              <strong>{_h(h.get('name'))}</strong><br>
              <strong>Rating:</strong> {_h(rating)}<br>
              <strong>Price per night:</strong> {_h(fmt_money(h.get('price_per_night'), h.get('currency') or 'USD'))}<br>
              <strong>Total price:</strong> {_h(fmt_money(h.get('total_price'), h.get('currency') or 'USD'))}<br>
              <strong>Amenities:</strong> {_h(', '.join(h.get('amenities_list') or []) or 'n/a')}<br>
              {f'<img src="{_h(img)}" alt="" style="width:150px;height:auto;"><br>' if img else ''}
              {link(h.get('booking_url'), 'Visit hotel link')}
            </div>"""

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Travel Itinerary</title>
<style>body {{ font-family: Arial, sans-serif; line-height: 1.6; }} h1 {{ color: #333; }} h2 {{ color: #0056b3; }}</style>
</head><body>
<h1>Your Travel Search Results</h1>
<h3>{_h(summary)}</h3>
{flights_html}
{hotels_html}
<p style="color:#666;font-size:12px;">Prices are search results, not bookings. Verify prices and availability before booking.</p>
</body></html>"""

    def send_email(self, to_email: str, content: str):
        """Returns (success, error_message). Success only when SendGrid returns 2xx."""
        api_key = get_secret("SENDGRID_KEY")
        from_address = get_secret("SENDGRID_FROM_EMAIL")
        if not api_key or not from_address:
            return False, "Email is not configured (SENDGRID_KEY and SENDGRID_FROM_EMAIL are required)."
        try:
            from sendgrid import SendGridAPIClient  # lazy import: app starts without it
            from sendgrid.helpers.mail import Mail

            message = Mail(
                from_email=from_address,
                to_emails=to_email,
                subject="Your Travel Recommendations",
                html_content=content,
            )
            response = SendGridAPIClient(api_key).send(message)
            if 200 <= int(response.status_code) < 300:
                logger.info("SendGrid accepted the email (status %s)", response.status_code)
                return True, None
            return False, f"The email provider did not accept the message (status {response.status_code})."
        except Exception as exc:
            logger.warning("Error sending email: %s", redact(exc))
            return False, f"The email could not be sent: {redact(exc)}"
