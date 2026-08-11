from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from users.constants import COMPANY_TYPE_BUYER, COMPANY_TYPE_SUPPLIER

from .constants import (
    DEAL_STATUS_CHOICES,
    DEAL_STATUS_LABELS,
    DEAL_STATUS_PENDING,
    DEAL_STATUS_VALUES,
    MAX_AGREEMENT_TERMS_LENGTH,
    MAX_MESSAGE_TEXT_LENGTH,
)
from .validators import validate_new_delivery_date


class Conversation(models.Model):
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="buyer_conversations",
    )
    supplier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="supplier_conversations",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="conversations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        unique_together = ("buyer", "supplier", "product")
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(buyer=models.F("supplier")),
                name="conversation_buyer_and_supplier_must_differ",
            ),
        ]
        indexes = [
            models.Index(
                fields=["buyer", "-updated_at"],
                name="chat_conv_buyer_updated_idx",
            ),
            models.Index(
                fields=["supplier", "-updated_at"],
                name="chat_conv_supplier_updated_idx",
            ),
        ]
        verbose_name = "Диалог"
        verbose_name_plural = "Диалоги"

    def __str__(self) -> str:
        return f"{self.buyer} -> {self.supplier} / {self.product}"

    def touch(self) -> None:
        self.updated_at = timezone.now()
        self.save(update_fields=["updated_at"])

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}

        if self.buyer_id and self.supplier_id and self.buyer_id == self.supplier_id:
            errors["supplier"] = (
                "Покупатель и поставщик должны быть разными пользователями."
            )

        if self.buyer_id and self.supplier_id and self.product_id:
            try:
                buyer_company = self.buyer.company
            except ObjectDoesNotExist:
                buyer_company = None

            try:
                supplier_company = self.supplier.company
            except ObjectDoesNotExist:
                supplier_company = None

            product_company = self.product.company

            if not buyer_company or buyer_company.company_type != COMPANY_TYPE_BUYER:
                errors["buyer"] = "Участник диалога должен быть покупателем."

            if (
                not supplier_company
                or supplier_company.company_type != COMPANY_TYPE_SUPPLIER
            ):
                errors["supplier"] = "Участник диалога должен быть поставщиком."

            if product_company.owner_id != self.supplier_id:
                errors["product"] = "Товар должен принадлежать поставщику диалога."

        if errors:
            raise ValidationError(errors)


class DealAgreement(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.PROTECT,
        related_name="agreements",
    )
    initiator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="initiated_deals",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[
            MinValueValidator(
                Decimal("0.01"),
                message="Сумма сделки должна быть больше нуля.",
            )
        ],
    )
    delivery_date = models.DateField()
    terms = models.TextField(max_length=MAX_AGREEMENT_TERMS_LENGTH)
    status = models.CharField(
        max_length=20,
        choices=DEAL_STATUS_CHOICES,
        default=DEAL_STATUS_PENDING,
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="confirmed_deals",
        null=True,
        blank=True,
    )
    completion_requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="completion_requested_deals",
        null=True,
        blank=True,
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="completed_deals",
        null=True,
        blank=True,
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="cancelled_deals",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completion_requested_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    sequence_number = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        editable=False,
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="deal_agreement_amount_gt_zero",
            ),
            models.UniqueConstraint(
                fields=["conversation"],
                condition=models.Q(status=DEAL_STATUS_PENDING),
                name="one_pending_agreement_per_conversation",
            ),
            models.UniqueConstraint(
                fields=["conversation", "sequence_number"],
                name="unique_agreement_sequence_per_conversation",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=DEAL_STATUS_VALUES),
                name="deal_agreement_status_is_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["conversation", "status"],
                name="chat_agreement_conv_status_idx",
            ),
            models.Index(
                fields=["conversation", "created_at"],
                name="chat_agreement_conv_date_ix",
            ),
        ]
        verbose_name = "Договоренность"
        verbose_name_plural = "Договоренности"

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str | list[str]] = {}

        if self._state.adding and self.delivery_date:
            try:
                validate_new_delivery_date(self.delivery_date)
            except ValidationError as error:
                errors["delivery_date"] = error.messages

        if self.conversation_id:
            participant_ids = {
                self.conversation.buyer_id,
                self.conversation.supplier_id,
            }
            actor_fields = {
                "initiator": self.initiator_id,
                "confirmed_by": self.confirmed_by_id,
                "completion_requested_by": self.completion_requested_by_id,
                "completed_by": self.completed_by_id,
                "cancelled_by": self.cancelled_by_id,
            }
            for field_name, actor_id in actor_fields.items():
                if actor_id and actor_id not in participant_ids:
                    errors[field_name] = "Участник действия должен состоять в диалоге."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean(validate_constraints=False)
        return super().save(*args, **kwargs)

    @property
    def status_label(self) -> str:
        return DEAL_STATUS_LABELS.get(self.status, self.status)

    def __str__(self) -> str:
        return f"Сделка #{self.pk} в диалоге #{self.conversation_id}"


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.PROTECT,
        related_name="messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="chat_messages",
    )
    text = models.TextField(max_length=MAX_MESSAGE_TEXT_LENGTH)
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["conversation", "created_at"],
                name="chat_message_conv_created_idx",
            ),
        ]
        verbose_name = "Сообщение"
        verbose_name_plural = "Сообщения"

    def clean(self) -> None:
        super().clean()
        if (
            self.conversation_id
            and self.sender_id
            and self.sender_id
            not in {
                self.conversation.buyer_id,
                self.conversation.supplier_id,
            }
        ):
            raise ValidationError(
                {
                    "sender": "Отправитель должен быть участником диалога.",
                }
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Сообщение #{self.pk} в диалоге #{self.conversation_id}"
