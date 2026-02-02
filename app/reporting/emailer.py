"""Email delivery providers."""

import smtplib
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from app.logging_config import get_logger


logger = get_logger()


class EmailProvider(ABC):
    """Abstract base class for email providers."""

    @abstractmethod
    def send(
        self,
        recipients: list[str],
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        attachments: Optional[list[tuple[str, bytes]]] = None
    ) -> bool:
        """Send an email.

        Args:
            recipients: List of email addresses.
            subject: Email subject.
            html_body: HTML body content.
            text_body: Plain text body (optional).
            attachments: List of (filename, content) tuples.

        Returns:
            True if sent successfully.
        """
        pass


class SMTPProvider(EmailProvider):
    """SMTP email provider."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_address: str,
        use_tls: bool = True
    ):
        """Initialize SMTP provider.

        Args:
            host: SMTP server host.
            port: SMTP server port.
            username: SMTP username.
            password: SMTP password.
            from_address: Sender email address.
            use_tls: Whether to use TLS.
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_address = from_address
        self.use_tls = use_tls

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def send(
        self,
        recipients: list[str],
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        attachments: Optional[list[tuple[str, bytes]]] = None
    ) -> bool:
        """Send email via SMTP."""
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.from_address
        msg['To'] = ', '.join(recipients)

        # Add text part
        if text_body:
            msg.attach(MIMEText(text_body, 'plain'))

        # Add HTML part
        msg.attach(MIMEText(html_body, 'html'))

        # Add attachments
        if attachments:
            for filename, content in attachments:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(content)
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename="{filename}"'
                )
                msg.attach(part)

        try:
            with smtplib.SMTP(self.host, self.port) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.from_address, recipients, msg.as_string())

            logger.info(f"Email sent to {len(recipients)} recipients via SMTP")
            return True

        except Exception as e:
            logger.error(f"SMTP send failed: {e}")
            return False


class SendGridProvider(EmailProvider):
    """SendGrid email provider."""

    def __init__(self, api_key: str, from_address: str):
        """Initialize SendGrid provider.

        Args:
            api_key: SendGrid API key.
            from_address: Sender email address.
        """
        self.api_key = api_key
        self.from_address = from_address

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def send(
        self,
        recipients: list[str],
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        attachments: Optional[list[tuple[str, bytes]]] = None
    ) -> bool:
        """Send email via SendGrid."""
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import (
                Mail, Attachment, FileContent, FileName,
                FileType, Disposition
            )
            import base64
        except ImportError:
            logger.error("SendGrid package not installed")
            return False

        message = Mail(
            from_email=self.from_address,
            to_emails=recipients,
            subject=subject,
            html_content=html_body
        )

        if text_body:
            message.plain_text_content = text_body

        # Add attachments
        if attachments:
            for filename, content in attachments:
                encoded = base64.b64encode(content).decode()
                # Determine file type from extension
                if filename.endswith('.pdf'):
                    file_type = 'application/pdf'
                elif filename.endswith('.csv'):
                    file_type = 'text/csv'
                elif filename.endswith('.txt'):
                    file_type = 'text/plain'
                else:
                    file_type = 'application/octet-stream'

                attachment = Attachment(
                    FileContent(encoded),
                    FileName(filename),
                    FileType(file_type),
                    Disposition('attachment')
                )
                message.add_attachment(attachment)

        try:
            sg = SendGridAPIClient(self.api_key)
            response = sg.send(message)

            if response.status_code in (200, 201, 202):
                logger.info(f"Email sent to {len(recipients)} recipients via SendGrid")
                return True
            else:
                logger.error(f"SendGrid returned status {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"SendGrid send failed: {e}")
            return False


def create_email_provider(
    provider_type: str,
    from_address: str,
    smtp_host: Optional[str] = None,
    smtp_port: int = 587,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
    sendgrid_api_key: Optional[str] = None
) -> EmailProvider:
    """Factory function to create email provider.

    Args:
        provider_type: One of 'smtp' or 'sendgrid'.
        from_address: Sender email address.
        smtp_host: SMTP server host.
        smtp_port: SMTP server port.
        smtp_user: SMTP username.
        smtp_password: SMTP password.
        sendgrid_api_key: SendGrid API key.

    Returns:
        Configured EmailProvider instance.

    Raises:
        ValueError: If required parameters are missing.
    """
    if provider_type == 'smtp':
        if not all([smtp_host, smtp_user, smtp_password]):
            raise ValueError("SMTP requires host, user, and password")
        return SMTPProvider(
            host=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_password,
            from_address=from_address
        )
    elif provider_type == 'sendgrid':
        if not sendgrid_api_key:
            raise ValueError("SendGrid requires API key")
        return SendGridProvider(
            api_key=sendgrid_api_key,
            from_address=from_address
        )
    else:
        raise ValueError(f"Unknown email provider: {provider_type}")
