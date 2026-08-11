"""Constants that define the agreement lifecycle for the chats domain."""

DEAL_STATUS_PENDING = "pending"
DEAL_STATUS_CONFIRMED = "confirmed"
DEAL_STATUS_COMPLETED = "completed"
DEAL_STATUS_CANCELLED = "cancelled"

DEAL_STATUS_CHOICES = (
    (DEAL_STATUS_PENDING, "Ожидает подтверждения"),
    (DEAL_STATUS_CONFIRMED, "Подтверждена"),
    (DEAL_STATUS_COMPLETED, "Завершена"),
    (DEAL_STATUS_CANCELLED, "Отменена"),
)

DEAL_STATUS_LABELS = dict(DEAL_STATUS_CHOICES)
DEAL_STATUS_VALUES = tuple(status for status, _ in DEAL_STATUS_CHOICES)
DEAL_CANCELLABLE_STATUSES = frozenset(
    {
        DEAL_STATUS_PENDING,
        DEAL_STATUS_CONFIRMED,
    }
)

MAX_AGREEMENT_TERMS_LENGTH = 5_000
MAX_MESSAGE_TEXT_LENGTH = 5_000
CHAT_MESSAGES_PER_PAGE = 50
