from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from chats.constants import DEAL_STATUS_COMPLETED
from chats.models import DealAgreement

from ..models import Company, Review

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from products.models import Product


class ReviewAccessError(Exception):
    pass


class ReviewAlreadyExistsError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ReviewTarget:
    agreement: DealAgreement
    company: Company
    product: Product | None


def get_review_target(
    *,
    agreement_id: int,
    actor: User,
) -> ReviewTarget:
    try:
        agreement = DealAgreement.objects.select_related(
            "conversation__buyer__company",
            "conversation__supplier__company",
            "conversation__product",
        ).get(
            id=agreement_id,
            status=DEAL_STATUS_COMPLETED,
        )
    except DealAgreement.DoesNotExist as error:
        raise ReviewAccessError from error

    conversation = agreement.conversation
    if actor.id == conversation.buyer_id:
        return ReviewTarget(
            agreement=agreement,
            company=conversation.supplier.company,
            product=conversation.product,
        )
    if actor.id == conversation.supplier_id:
        return ReviewTarget(
            agreement=agreement,
            company=conversation.buyer.company,
            product=None,
        )
    raise ReviewAccessError


@transaction.atomic
def create_review(
    *,
    agreement_id: int,
    actor: User,
    rating: int,
    text: str,
) -> Review:
    target = get_review_target(agreement_id=agreement_id, actor=actor)
    agreement = DealAgreement.objects.select_for_update().get(id=target.agreement.id)

    if Review.objects.filter(agreement=agreement, author=actor).exists():
        raise ReviewAlreadyExistsError

    review = Review(
        agreement=agreement,
        author=actor,
        company=target.company,
        product=target.product,
        rating=rating,
        text=text,
    )
    try:
        review.save()
    except IntegrityError as error:
        raise ReviewAlreadyExistsError from error
    except ValidationError as error:
        raise ReviewAccessError from error
    return review
