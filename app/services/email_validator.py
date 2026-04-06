"""Email_Validator: format check (RFC 5322 regex) and DNS MX existence check."""
import re
import logging

logger = logging.getLogger(__name__)

# RFC 5322-compliant email regex (simplified but covers the vast majority of
# valid addresses without being overly permissive).
_RFC5322_RE = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*"
    r"\.[a-zA-Z]{2,}$"
)


class Email_Validator:
    """Validates email addresses by format and domain existence."""

    def validate_format(self, email: str) -> bool:
        """Return True if *email* matches the RFC 5322 pattern, else False."""
        if not email or not isinstance(email, str):
            return False
        return bool(_RFC5322_RE.match(email.strip()))

    def validate_existence(self, email: str) -> bool:
        """Return True if the email's domain has at least one MX record."""
        if not self.validate_format(email):
            return False
        domain = email.strip().rsplit("@", 1)[-1]
        try:
            import dns.resolver
            answers = dns.resolver.resolve(domain, "MX")
            return len(answers) > 0
        except Exception as exc:
            logger.warning("MX lookup failed for domain %r: %s", domain, exc)
            return False
