from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Message

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from ..models import Conversation, DealAgreement


def create_chat_message(
    *,
    conversation: Conversation,
    sender: User,
    text: str,
    is_system: bool = False,
) -> Message:
    message = Message(
        conversation=conversation,
        sender=sender,
        text=text,
        is_system=is_system,
    )
    message.save()
    conversation.touch()
    return message


def contact_established() -> str:
    return "Контакт установлен через платформу."


def agreement_created(agreement: DealAgreement) -> str:
    return (
        f"Создана сделка №{agreement.sequence_number} и отправлена на подтверждение. "
        f"Сумма: {agreement.amount} ₽. "
        f"Дата поставки: {agreement.delivery_date}. "
        f"Условия: {agreement.terms}"
    )


def agreement_confirmed(agreement: DealAgreement) -> str:
    return (
        f"Сделка №{agreement.sequence_number} подтверждена второй стороной. "
        "Условия зафиксированы."
    )


def agreement_completion_requested(agreement: DealAgreement) -> str:
    return (
        f"По сделке №{agreement.sequence_number} запрошено завершение. "
        "Требуется подтверждение второй стороны."
    )


def agreement_completed(agreement: DealAgreement) -> str:
    return (
        f"Сделка №{agreement.sequence_number} завершена после подтверждения "
        "второй стороны."
    )


def agreement_cancelled(agreement: DealAgreement) -> str:
    return f"Сделка №{agreement.sequence_number} отменена одной из сторон."
