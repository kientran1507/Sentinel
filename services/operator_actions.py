"""Shared validation for authenticated, bounded operator audit reasons."""


def operator_reason(platform, actor_id, reason, action):
    if not isinstance(platform, str) or platform not in {"discord", "telegram"}:
        raise ValueError(f"{action} requires a supported operator platform")
    if not isinstance(actor_id, str) or not actor_id.isascii() or not actor_id.isdigit() or len(actor_id) > 64:
        raise ValueError(f"{action} requires a numeric operator ID of at most 64 digits")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason must be nonempty text")
    reason = reason.strip()
    if len(reason) > 500 or not reason.isprintable():
        raise ValueError(f"{action} reason must be a single printable line of 1 through 500 characters")
    return reason
