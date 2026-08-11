from collections.abc import Iterable
from decimal import Decimal
from typing import TypedDict, cast

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from chats.models import Conversation
from chats.services.deal_workflow import (
    complete_agreement,
    confirm_agreement,
    create_agreement,
    request_agreement_completion,
)
from products.models import Product

from .constants import COMPANY_TYPE_BUYER, COMPANY_TYPE_SUPPLIER
from .forms import CompanyRegisterForm
from .models import Company, EmailVerification, Review
from .services.analytics import build_buyer_analytics


class SupplierComparison(TypedDict):
    supplier_id: int


class CompanyRegisterFormTests(TestCase):
    def test_email_must_be_unique(self):
        get_user_model().objects.create_user(
            username="existing@example.com",
            email="existing@example.com",
            password="StrongPass123!",
        )

        form = CompanyRegisterForm(
            data={
                "email": "existing@example.com",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "inn": "1234567890",
                "ogrn": "1234567890123",
                "company_type": "supplier",
                "company_name": "Test Company",
                "region": "Moscow",
                "contact_person": "Ivan Ivanov",
                "contacts": "+79990000000",
                "agreement": True,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_account_email_is_not_automatically_published_as_company_contact(self):
        form = CompanyRegisterForm(
            data={
                "email": "new@example.com",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "inn": "1234567890",
                "ogrn": "1234567890123",
                "company_type": "supplier",
                "company_name": "Test Company",
                "region": "Moscow",
                "contact_person": "Ivan Ivanov",
                "contacts": "+79990000000",
                "agreement": True,
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()

        self.assertEqual(user.email, "new@example.com")
        self.assertEqual(user.company.email, "")


class RegisterViewTests(TestCase):
    def test_register_view_shows_error_for_existing_account(self):
        get_user_model().objects.create_user(
            username="existing@example.com",
            email="existing@example.com",
            password="StrongPass123!",
        )

        response = self.client.post(
            reverse("register"),
            data={
                "email": "Existing@Example.com",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "inn": "1234567890",
                "ogrn": "1234567890123",
                "company_type": "supplier",
                "company_name": "Test Company",
                "region": "Moscow",
                "contact_person": "Ivan Ivanov",
                "contacts": "+79990000000",
                "agreement": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Аккаунт с таким email уже существует.")
        self.assertEqual(
            get_user_model()
            .objects.filter(
                username="existing@example.com",
            )
            .count(),
            1,
        )
        self.assertEqual(EmailVerification.objects.count(), 0)


class ReviewAndAnalyticsTests(TestCase):
    def setUp(self):
        self.buyer = self._create_user_with_company(
            email="buyer@example.com",
            company_name="Buyer",
            company_type=COMPANY_TYPE_BUYER,
            inn="1111111111",
            ogrn="1111111111111",
        )
        self.first_supplier = self._create_user_with_company(
            email="supplier-one@example.com",
            company_name="Greenhouse",
            company_type=COMPANY_TYPE_SUPPLIER,
            inn="2222222222",
            ogrn="2222222222222",
        )
        self.second_supplier = self._create_user_with_company(
            email="supplier-two@example.com",
            company_name="Greenhouse",
            company_type=COMPANY_TYPE_SUPPLIER,
            inn="3333333333",
            ogrn="3333333333333",
        )

    def _create_user_with_company(
        self,
        *,
        email,
        company_name,
        company_type,
        inn,
        ogrn,
    ):
        user = get_user_model().objects.create_user(
            username=email,
            email=email,
            password="StrongPass123!",
        )
        Company.objects.create(
            owner=user,
            company_type=company_type,
            name=company_name,
            inn=inn,
            ogrn=ogrn,
            region="Moscow",
            contact_person="Contact person",
        )
        return user

    def _create_completed_agreement(self, supplier, title):
        product = Product.objects.create(
            company=supplier.company,
            title=title,
            description="Fresh product",
            price="100.00",
            min_order=1,
            region="Moscow",
        )
        conversation = Conversation.objects.create(
            buyer=self.buyer,
            supplier=supplier,
            product=product,
        )
        agreement = create_agreement(
            conversation_id=conversation.id,
            actor=self.buyer,
            amount=Decimal("100.00"),
            delivery_date=timezone.localdate(),
            terms="Delivery terms",
        )
        confirm_agreement(
            conversation_id=conversation.id,
            agreement_id=agreement.id,
            actor=supplier,
        )
        request_agreement_completion(
            conversation_id=conversation.id,
            agreement_id=agreement.id,
            actor=self.buyer,
        )
        return complete_agreement(
            conversation_id=conversation.id,
            agreement_id=agreement.id,
            actor=supplier,
        )

    def test_supplier_analytics_does_not_merge_companies_with_same_name(self):
        self._create_completed_agreement(self.first_supplier, "Tomatoes")
        self._create_completed_agreement(self.second_supplier, "Cucumbers")

        context = build_buyer_analytics(self.buyer.company)

        supplier_comparison = cast(
            Iterable[SupplierComparison],
            context["supplier_comparison"],
        )
        suppliers = list(supplier_comparison)
        self.assertEqual(len(suppliers), 2)
        self.assertEqual(
            {supplier["supplier_id"] for supplier in suppliers},
            {self.first_supplier.id, self.second_supplier.id},
        )

    def test_review_must_target_the_other_party_and_completed_agreement(self):
        agreement = self._create_completed_agreement(
            self.first_supplier,
            "Tomatoes",
        )

        review = Review(
            agreement=agreement,
            author=self.buyer,
            company=self.buyer.company,
            product=agreement.conversation.product,
            rating=5,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Отзыв должен быть оставлен о второй стороне сделки.",
        ):
            review.full_clean()

        valid_review = Review.objects.create(
            agreement=agreement,
            author=self.buyer,
            company=self.first_supplier.company,
            product=agreement.conversation.product,
            rating=5,
        )
        self.assertEqual(valid_review.rating, 5)
