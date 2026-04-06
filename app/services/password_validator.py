"""Password policy validator.

Policy: minimum 8 characters, at least one uppercase letter, one lowercase
letter, and one digit.
"""


def validate_password(password: str) -> tuple[bool, str]:
    """Validate *password* against the site password policy.

    Returns:
        (True, "") if the password is valid.
        (False, error_message) describing the first policy violation found.
    """
    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter."
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter."
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one digit."
    return True, ""
