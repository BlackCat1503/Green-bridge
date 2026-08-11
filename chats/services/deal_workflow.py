from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from ..constants import (
    DEAL_CANCELLABLE_STATUSES,
    DEAL_STATUS_CANCELLED,
    DEAL_STATUS_COMPLETED,
    DEAL_STATUS_CONFIRMED,
    DEAL_STATUS_PENDING,
)
from ..models import Conversation, DealAgreement
from .system_messages import (
    agreement_cancelled,
    agreement_completed,
    agreement_completion_requested,
    agreement_confirmed,
    agreement_created,
    create_chat_message,
)

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from django.contrib.auth.models import User


class AgreementWorkflowError(Exception):
    pass


class AgreementAccessError(AgreementWorkflowError):
    pass


class AgreementNotFoundError(AgreementWorkflowError):
    pass


class AgreementTransitionError(AgreementWorkflowError):
    pass


class PendingAgreementExistsError(AgreementWorkflowError):
    pass


@dataclass(frozen=True, slots=True)
class AgreementPermissions:
    can_confirm: bool
    can_request_completion: bool
    can_confirm_completion: bool
    can_cancel: bool
    completion_requested_by_actor: bool


def get_agreement_permissions(
    *,
    agreement: DealAgreement | None,
    actor_id: int,
) -> AgreementPermissions:
    if agreement is None:
        return AgreementPermissions(
            can_confirm=False,
            can_request_completion=False,
            can_confirm_completion=False,
            can_cancel=False,
            completion_requested_by_actor=False,
        )

    is_pending = agreement.status == DEAL_STATUS_PENDING
    is_confirmed = agreement.status == DEAL_STATUS_CONFIRMED
    completion_requested = agreement.completion_requested_by_id is not None
    completion_requested_by_actor = (
        completion_requested and agreement.completion_requested_by_id == actor_id
    )

    return AgreementPermissions(
        can_confirm=is_pending and agreement.initiator_id != actor_id,
        can_request_completion=is_confirmed and not completion_requested,
        can_confirm_completion=(
            is_confirmed and completion_requested and not completion_requested_by_actor
        ),
        can_cancel=agreement.status in DEAL_CANCELLABLE_STATUSES,
        completion_requested_by_actor=completion_requested_by_actor,
    )


@transaction.atomic
def create_agreement(
    *,
    conversation_id: int,
    actor: User,
    amount: Decimal,
    delivery_date: date,
    terms: str,
) -> DealAgreement:
    conversation = _get_locked_conversation_for_actor(
        conversation_id=conversation_id,
        actor_id=actor.id,
    )

    if _has_pending_agreement(conversation_id=conversation.id):
        raise PendingAgreementExistsError

    sequence_number = _get_next_sequence_number(conversation_id=conversation.id)
    agreement = DealAgreement(
        conversation=conversation,
        initiator=actor,
        amount=amount,
        delivery_date=delivery_date,
        terms=terms,
        status=DEAL_STATUS_PENDING,
        sequence_number=sequence_number,
    )

    try:
        agreement.save()
    except IntegrityError as error:
        raise PendingAgreementExistsError from error

    create_chat_message(
        conversation=conversation,
        sender=actor,
        text=agreement_created(agreement),
        is_system=True,
    )
    return agreement


@transaction.atomic
def confirm_agreement(
    *,
    conversation_id: int,
    agreement_id: int,
    actor: User,
) -> DealAgreement:
    agreement = _get_locked_agreement_for_actor(
        conversation_id=conversation_id,
        agreement_id=agreement_id,
        actor_id=actor.id,
    )
    _require_transition(
        agreement.status == DEAL_STATUS_PENDING,
        "Подтверждать можно только ожидающую сделку.",
    )
    _require_transition(
        agreement.initiator_id != actor.id,
        "Инициатор не может подтвердить свою сделку.",
    )

    agreement.status = DEAL_STATUS_CONFIRMED
    agreement.confirmed_by = actor
    agreement.confirmed_at = timezone.now()
    _save_agreement(
        agreement=agreement,
        update_fields=["status", "confirmed_by", "confirmed_at"],
    )

    create_chat_message(
        conversation=agreement.conversation,
        sender=actor,
        text=agreement_confirmed(agreement),
        is_system=True,
    )
    return agreement


@transaction.atomic
def request_agreement_completion(
    *,
    conversation_id: int,
    agreement_id: int,
    actor: User,
) -> DealAgreement:
    agreement = _get_locked_agreement_for_actor(
        conversation_id=conversation_id,
        agreement_id=agreement_id,
        actor_id=actor.id,
    )
    _require_transition(
        agreement.status == DEAL_STATUS_CONFIRMED,
        "Запрашивать завершение можно только для подтверждённой сделки.",
    )
    _require_transition(
        agreement.completion_requested_by_id is None,
        "По этой сделке уже запрошено завершение.",
    )

    agreement.completion_requested_by = actor
    agreement.completion_requested_at = timezone.now()
    _save_agreement(
        agreement=agreement,
        update_fields=["completion_requested_by", "completion_requested_at"],
    )

    create_chat_message(
        conversation=agreement.conversation,
        sender=actor,
        text=agreement_completion_requested(agreement),
        is_system=True,
    )
    return agreement


@transaction.atomic
def complete_agreement(
    *,
    conversation_id: int,
    agreement_id: int,
    actor: User,
) -> DealAgreement:
    agreement = _get_locked_agreement_for_actor(
        conversation_id=conversation_id,
        agreement_id=agreement_id,
        actor_id=actor.id,
    )
    _require_transition(
        agreement.status == DEAL_STATUS_CONFIRMED,
        "Завершать можно только подтверждённую сделку.",
    )
    _require_transition(
        agreement.completion_requested_by_id is not None,
        "Сначала одна из сторон должна запросить завершение.",
    )
    _require_transition(
        agreement.completion_requested_by_id != actor.id,
        "Инициатор запроса не может подтвердить завершение.",
    )

    agreement.status = DEAL_STATUS_COMPLETED
    agreement.completed_by = actor
    agreement.completed_at = timezone.now()
    _save_agreement(
        agreement=agreement,
        update_fields=["status", "completed_by", "completed_at"],
    )

    create_chat_message(
        conversation=agreement.conversation,
        sender=actor,
        text=agreement_completed(agreement),
        is_system=True,
    )
    return agreement


@transaction.atomic
def cancel_agreement(
    *,
    conversation_id: int,
    agreement_id: int,
    actor: User,
) -> DealAgreement:
    agreement = _get_locked_agreement_for_actor(
        conversation_id=conversation_id,
        agreement_id=agreement_id,
        actor_id=actor.id,
    )
    _require_transition(
        agreement.status in DEAL_CANCELLABLE_STATUSES,
        "Отменить можно только ожидающую или подтверждённую сделку.",
    )

    agreement.status = DEAL_STATUS_CANCELLED
    agreement.cancelled_by = actor
    agreement.cancelled_at = timezone.now()
    _save_agreement(
        agreement=agreement,
        update_fields=["status", "cancelled_by", "cancelled_at"],
    )

    create_chat_message(
        conversation=agreement.conversation,
        sender=actor,
        text=agreement_cancelled(agreement),
        is_system=True,
    )
    return agreement


def _get_locked_conversation_for_actor(
    *,
    conversation_id: int,
    actor_id: int,
) -> Conversation:
    try:
        conversation = Conversation.objects.select_for_update().get(
            id=conversation_id,
        )
    except Conversation.DoesNotExist as error:
        raise AgreementAccessError from error

    if actor_id not in {conversation.buyer_id, conversation.supplier_id}:
        raise AgreementAccessError
    return conversation


def _get_locked_agreement_for_actor(
    *,
    conversation_id: int,
    agreement_id: int,
    actor_id: int,
) -> DealAgreement:
    conversation = _get_locked_conversation_for_actor(
        conversation_id=conversation_id,
        actor_id=actor_id,
    )
    try:
        return (
            DealAgreement.objects.select_for_update()
            .select_related(
                "conversation",
            )
            .get(
                id=agreement_id,
                conversation=conversation,
            )
        )
    except DealAgreement.DoesNotExist as error:
        raise AgreementNotFoundError from error


def _has_pending_agreement(*, conversation_id: int) -> bool:
    return DealAgreement.objects.filter(
        conversation_id=conversation_id,
        status=DEAL_STATUS_PENDING,
    ).exists()


def _get_next_sequence_number(*, conversation_id: int) -> int:
    last_sequence_number = DealAgreement.objects.filter(
        conversation_id=conversation_id,
    ).aggregate(max_sequence_number=Max("sequence_number"))["max_sequence_number"]
    return (last_sequence_number or 0) + 1


def _save_agreement(*, agreement: DealAgreement, update_fields: list[str]) -> None:
    agreement.save(update_fields=update_fields)


def _require_transition(condition: bool, message: str) -> None:
    if not condition:
        raise AgreementTransitionError(message)
