from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from products.models import Product
from users.constants import COMPANY_TYPE_BUYER, COMPANY_TYPE_SUPPLIER
from users.models import Company

from .constants import (
    DEAL_STATUS_CANCELLED,
    DEAL_STATUS_COMPLETED,
    DEAL_STATUS_CONFIRMED,
    DEAL_STATUS_PENDING,
)
from .forms import DealAgreementForm
from .models import Conversation, DealAgreement, Message
from .services.deal_workflow import (
    AgreementAccessError,
    AgreementTransitionError,
    cancel_agreement,
    complete_agreement,
    confirm_agreement,
    create_agreement,
    request_agreement_completion,
)


class DealAgreementFormTests(SimpleTestCase):
    def _form_data(self, **overrides):
        data = {
            "amount": "1500.00",
            "delivery_date": timezone.localdate().isoformat(),
            "terms": "Поставка по согласованному адресу.",
        }
        data.update(overrides)
        return data

    def test_amount_must_be_positive(self):
        for amount in ("0", "-10.00"):
            with self.subTest(amount=amount):
                form = DealAgreementForm(self._form_data(amount=amount))

                self.assertFalse(form.is_valid())
                self.assertIn("amount", form.errors)

    def test_delivery_date_cannot_be_in_the_past(self):
        form = DealAgreementForm(
            self._form_data(
                delivery_date=(timezone.localdate() - timedelta(days=1)).isoformat(),
            ),
        )

        with patch.object(DealAgreement, "validate_constraints"):
            self.assertFalse(form.is_valid())
        self.assertIn("delivery_date", form.errors)

    def test_delivery_date_today_is_valid(self):
        form = DealAgreementForm(self._form_data())

        with patch.object(DealAgreement, "validate_constraints"):
            self.assertTrue(form.is_valid(), form.errors)


class ChatDomainTestCase(TestCase):
    def setUp(self):
        self.buyer = User.objects.create_user(
            username="buyer@example.com",
            email="buyer@example.com",
            password="StrongPass123!",
        )
        Company.objects.create(
            owner=self.buyer,
            company_type=COMPANY_TYPE_BUYER,
            name="Buyer",
            inn="1234567890",
            ogrn="1234567890123",
            region="Moscow",
            contact_person="Buyer Contact",
        )
        self.supplier = User.objects.create_user(
            username="supplier@example.com",
            email="supplier@example.com",
            password="StrongPass123!",
        )
        self.supplier_company = Company.objects.create(
            owner=self.supplier,
            company_type=COMPANY_TYPE_SUPPLIER,
            name="Supplier",
            inn="0987654321",
            ogrn="1098765432109",
            region="Moscow",
            contact_person="Supplier Contact",
        )
        self.product = Product.objects.create(
            company=self.supplier_company,
            title="Tomatoes",
            description="Fresh tomatoes",
            price="100.00",
            min_order=1,
            region="Moscow",
        )

    def create_conversation(self):
        return Conversation.objects.create(
            buyer=self.buyer,
            supplier=self.supplier,
            product=self.product,
        )

    def create_pending_agreement(self, conversation):
        return create_agreement(
            conversation_id=conversation.id,
            actor=self.buyer,
            amount=Decimal("100.00"),
            delivery_date=timezone.localdate(),
            terms="Delivery terms",
        )


class ChatWorkflowEndpointTests(ChatDomainTestCase):
    def test_start_chat_requires_post_and_creates_a_system_message(self):
        self.client.force_login(self.buyer)
        url = reverse("start_chat", args=[self.product.id])

        self.assertEqual(self.client.get(url).status_code, 405)

        response = self.client.post(url)

        conversation = Conversation.objects.get(
            buyer=self.buyer,
            supplier=self.supplier,
            product=self.product,
        )
        self.assertRedirects(response, reverse("chat_detail", args=[conversation.id]))
        self.assertTrue(
            Message.objects.filter(conversation=conversation, is_system=True).exists(),
        )

    def test_only_one_pending_agreement_can_exist_per_conversation(self):
        conversation = self.create_conversation()
        DealAgreement.objects.create(
            conversation=conversation,
            initiator=self.buyer,
            amount="100.00",
            delivery_date=timezone.localdate(),
            terms="Delivery terms",
            sequence_number=1,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            DealAgreement.objects.create(
                conversation=conversation,
                initiator=self.supplier,
                amount="200.00",
                delivery_date=timezone.localdate(),
                terms="Other delivery terms",
                sequence_number=2,
            )

    def test_chat_messages_do_not_replace_global_flash_messages(self):
        conversation = self.create_conversation()
        Message.objects.create(
            conversation=conversation,
            sender=self.buyer,
            text="A private chat message",
        )
        self.client.force_login(self.buyer)

        response = self.client.get(reverse("chat_detail", args=[conversation.id]))

        self.assertContains(response, "A private chat message")
        self.assertNotContains(response, "flash-message")

    def test_chat_detail_paginates_messages_without_loading_the_full_history(self):
        conversation = self.create_conversation()
        for message_number in range(51):
            Message.objects.create(
                conversation=conversation,
                sender=self.buyer,
                text=f"Message {message_number}",
            )
        self.client.force_login(self.buyer)

        newest_page = self.client.get(
            reverse("chat_detail", args=[conversation.id]),
        )
        older_page = self.client.get(
            reverse("chat_detail", args=[conversation.id]),
            {"messages_page": 2},
        )

        self.assertContains(newest_page, "Message 50")
        self.assertNotContains(newest_page, "Message 0")
        self.assertContains(older_page, "Message 0")
        self.assertEqual(newest_page.context["messages_page"].paginator.count, 51)

    def test_agreement_endpoints_delegate_to_workflow(self):
        conversation = self.create_conversation()
        agreement = self.create_pending_agreement(conversation)

        self.client.force_login(self.supplier)
        response = self.client.post(
            reverse("confirm_agreement", args=[conversation.id, agreement.id]),
        )
        self.assertRedirects(response, reverse("chat_detail", args=[conversation.id]))

        agreement.refresh_from_db()
        self.assertEqual(agreement.status, DEAL_STATUS_CONFIRMED)
        self.assertEqual(agreement.confirmed_by, self.supplier)

        self.client.force_login(self.buyer)
        self.client.post(
            reverse("request_complete_agreement", args=[conversation.id, agreement.id]),
        )
        agreement.refresh_from_db()
        self.assertEqual(agreement.completion_requested_by, self.buyer)

        self.client.force_login(self.supplier)
        self.client.post(
            reverse("confirm_complete_agreement", args=[conversation.id, agreement.id]),
        )
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, DEAL_STATUS_COMPLETED)


class DealWorkflowTests(ChatDomainTestCase):
    def test_workflow_records_each_transition_and_system_message(self):
        conversation = self.create_conversation()

        agreement = self.create_pending_agreement(conversation)
        self.assertEqual(agreement.status, DEAL_STATUS_PENDING)
        self.assertEqual(agreement.sequence_number, 1)

        agreement = confirm_agreement(
            conversation_id=conversation.id,
            agreement_id=agreement.id,
            actor=self.supplier,
        )
        self.assertEqual(agreement.status, DEAL_STATUS_CONFIRMED)
        self.assertEqual(agreement.confirmed_by, self.supplier)
        self.assertIsNotNone(agreement.confirmed_at)

        agreement = request_agreement_completion(
            conversation_id=conversation.id,
            agreement_id=agreement.id,
            actor=self.buyer,
        )
        self.assertEqual(agreement.completion_requested_by, self.buyer)
        self.assertIsNotNone(agreement.completion_requested_at)

        agreement = complete_agreement(
            conversation_id=conversation.id,
            agreement_id=agreement.id,
            actor=self.supplier,
        )
        self.assertEqual(agreement.status, DEAL_STATUS_COMPLETED)
        self.assertEqual(agreement.completed_by, self.supplier)
        self.assertIsNotNone(agreement.completed_at)
        self.assertEqual(
            Message.objects.filter(conversation=conversation, is_system=True).count(),
            4,
        )

    def test_initiator_cannot_confirm_own_agreement(self):
        conversation = self.create_conversation()
        agreement = self.create_pending_agreement(conversation)

        with self.assertRaises(AgreementTransitionError):
            confirm_agreement(
                conversation_id=conversation.id,
                agreement_id=agreement.id,
                actor=self.buyer,
            )

        agreement.refresh_from_db()
        self.assertEqual(agreement.status, DEAL_STATUS_PENDING)
        self.assertIsNone(agreement.confirmed_at)

    def test_cancellation_uses_cancelled_actor_and_timestamp(self):
        conversation = self.create_conversation()
        agreement = self.create_pending_agreement(conversation)

        agreement = cancel_agreement(
            conversation_id=conversation.id,
            agreement_id=agreement.id,
            actor=self.buyer,
        )

        self.assertEqual(agreement.status, DEAL_STATUS_CANCELLED)
        self.assertEqual(agreement.cancelled_by, self.buyer)
        self.assertIsNotNone(agreement.cancelled_at)

        self.client.force_login(self.supplier)
        response = self.client.get(reverse("chat_detail", args=[conversation.id]))
        self.assertContains(response, "Отменена покупателем")
        self.assertContains(response, "Buyer")
        self.assertContains(response, "№1")

    def test_agreement_sequence_number_is_unique_per_conversation(self):
        conversation = self.create_conversation()
        first_agreement = self.create_pending_agreement(conversation)
        cancel_agreement(
            conversation_id=conversation.id,
            agreement_id=first_agreement.id,
            actor=self.buyer,
        )

        second_agreement = self.create_pending_agreement(conversation)

        self.assertEqual(first_agreement.sequence_number, 1)
        self.assertEqual(second_agreement.sequence_number, 2)

    def test_non_participant_cannot_send_a_message(self):
        conversation = self.create_conversation()
        outsider = User.objects.create_user(
            username="outsider@example.com",
            password="StrongPass123!",
        )
        message = Message(
            conversation=conversation,
            sender=outsider,
            text="I should not be able to post here.",
        )

        with self.assertRaises(ValidationError):
            message.save()

    def test_conversation_validates_participant_roles_before_save(self):
        invalid_conversation = Conversation(
            buyer=self.supplier,
            supplier=self.buyer,
            product=self.product,
        )

        with self.assertRaises(ValidationError):
            invalid_conversation.save()

    def test_non_participant_cannot_change_an_agreement(self):
        conversation = self.create_conversation()
        agreement = self.create_pending_agreement(conversation)
        outsider = User.objects.create_user(
            username="outsider@example.com",
            password="StrongPass123!",
        )

        with self.assertRaises(AgreementAccessError):
            confirm_agreement(
                conversation_id=conversation.id,
                agreement_id=agreement.id,
                actor=outsider,
            )

    def test_deleting_chat_participant_preserves_commercial_history(self):
        self.create_conversation()

        with self.assertRaises(ProtectedError):
            self.buyer.delete()
