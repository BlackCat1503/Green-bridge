from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .constants import (
    DEAL_STATUS_CANCELLED,
    DEAL_STATUS_COMPLETED,
    DEAL_STATUS_CONFIRMED,
    DEAL_STATUS_LABELS,
    DEAL_STATUS_PENDING,
)
from .models import Conversation, DealAgreement


@dataclass(frozen=True, slots=True)
class AgreementDisplay:
    agreement: DealAgreement
    user_has_review: bool
    cancelled_by_role: str
    cancelled_by_name: str

    @property
    def id(self) -> int:
        return self.agreement.id

    @property
    def display_number(self) -> int:
        return self.agreement.sequence_number

    @property
    def normalized_status(self) -> str:
        return self.agreement.status

    @property
    def is_pending(self) -> bool:
        return self.agreement.status == DEAL_STATUS_PENDING

    @property
    def is_confirmed(self) -> bool:
        return self.agreement.status == DEAL_STATUS_CONFIRMED

    @property
    def is_completed(self) -> bool:
        return self.agreement.status == DEAL_STATUS_COMPLETED

    @property
    def is_cancelled(self) -> bool:
        return self.agreement.status == DEAL_STATUS_CANCELLED

    @property
    def status_label(self) -> str:
        return self.agreement.status_label

    @property
    def amount(self) -> Decimal:
        return self.agreement.amount

    @property
    def delivery_date(self) -> date:
        return self.agreement.delivery_date

    @property
    def terms(self) -> str:
        return self.agreement.terms


@dataclass(frozen=True, slots=True)
class ChatListItem:
    conversation: Conversation
    latest_message_text: str | None
    latest_agreement_status: str | None

    @property
    def latest_agreement_label(self) -> str:
        if self.latest_agreement_status is None:
            return "Переговоры активны"
        return DEAL_STATUS_LABELS.get(
            self.latest_agreement_status,
            "Статус уточняется",
        )


def build_agreement_displays(
    *,
    agreements: Iterable[DealAgreement],
    conversation: Conversation,
    current_user_id: int,
) -> list[AgreementDisplay]:
    return [
        _build_agreement_display(
            agreement=agreement,
            conversation=conversation,
            current_user_id=current_user_id,
        )
        for agreement in agreements
    ]


def _build_agreement_display(
    *,
    agreement: DealAgreement,
    conversation: Conversation,
    current_user_id: int,
) -> AgreementDisplay:
    cancelled_by_role, cancelled_by_name = _get_cancellation_actor_display(
        agreement=agreement,
        conversation=conversation,
    )
    reviews = getattr(agreement, "reviews_by_current_user", ())
    user_has_review = any(review.author_id == current_user_id for review in reviews)

    return AgreementDisplay(
        agreement=agreement,
        user_has_review=user_has_review,
        cancelled_by_role=cancelled_by_role,
        cancelled_by_name=cancelled_by_name,
    )


def _get_cancellation_actor_display(
    *,
    agreement: DealAgreement,
    conversation: Conversation,
) -> tuple[str, str]:
    if agreement.status != DEAL_STATUS_CANCELLED or agreement.cancelled_by_id is None:
        return "", ""

    if agreement.cancelled_by_id == conversation.buyer_id:
        return "покупателем", conversation.buyer.company.name

    if agreement.cancelled_by_id == conversation.supplier_id:
        return "поставщиком", conversation.supplier.company.name

    return "участником", ""
