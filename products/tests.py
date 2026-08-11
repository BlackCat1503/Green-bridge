from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from chats.models import Conversation
from users.constants import COMPANY_TYPE_BUYER, COMPANY_TYPE_SUPPLIER
from users.models import Company

from .filters import ProductCatalogFilter
from .forms import ProductForm
from .models import Product


class ProductCatalogAndArchiveTests(TestCase):
    def setUp(self):
        self.supplier = User.objects.create_user(
            username="supplier@example.com",
            email="supplier@example.com",
            password="StrongPass123!",
        )
        self.supplier_company = Company.objects.create(
            owner=self.supplier,
            company_type=COMPANY_TYPE_SUPPLIER,
            name="Supplier",
            inn="1234567890",
            ogrn="1234567890123",
            region="Moscow",
            contact_person="Supplier Contact",
        )
        self.buyer = User.objects.create_user(
            username="buyer@example.com",
            email="buyer@example.com",
            password="StrongPass123!",
        )
        self.buyer_company = Company.objects.create(
            owner=self.buyer,
            company_type=COMPANY_TYPE_BUYER,
            name="Buyer",
            inn="0987654321",
            ogrn="1098765432109",
            region="Moscow",
            contact_person="Buyer Contact",
        )
        self.product = Product.objects.create(
            company=self.supplier_company,
            title="Tomatoes",
            description="Fresh tomatoes",
            price="100.00",
            min_order=1,
            region="Moscow",
        )

    def test_archive_requires_post(self):
        self.client.force_login(self.supplier)

        response = self.client.get(reverse("archive_product", args=[self.product.id]))

        self.assertEqual(response.status_code, 405)
        self.product.refresh_from_db()
        self.assertTrue(self.product.is_active)

    def test_archive_keeps_conversation_history(self):
        conversation = Conversation.objects.create(
            buyer=self.buyer,
            supplier=self.supplier,
            product=self.product,
        )
        self.client.force_login(self.supplier)

        response = self.client.post(reverse("archive_product", args=[self.product.id]))

        self.assertRedirects(response, reverse("my_products"))
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_active)
        self.assertTrue(Conversation.objects.filter(id=conversation.id).exists())

    def test_invalid_catalog_filter_returns_validation_error_instead_of_500(self):
        response = self.client.get(
            reverse("product_list"), {"price_min": "not-a-number"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Введите число")

    def test_invalid_price_range_keeps_catalog_unfiltered(self):
        response = self.client.get(
            reverse("product_list"),
            {"price_min": "200", "price_max": "100"},
        )

        self.assertContains(
            response,
            "Максимальная цена не может быть меньше минимальной.",
        )
        self.assertContains(response, self.product.title)

    def test_catalog_hides_products_of_deactivated_company(self):
        self.supplier_company.is_active = False
        self.supplier_company.save(update_fields=["is_active"])

        response = self.client.get(reverse("product_list"))

        self.assertNotContains(response, self.product.title)

    def test_product_detail_is_hidden_for_deactivated_company(self):
        self.supplier_company.is_active = False
        self.supplier_company.save(update_fields=["is_active"])
        self.client.force_login(self.buyer)

        response = self.client.get(
            reverse("product_detail", args=[self.product.id]),
        )

        self.assertEqual(response.status_code, 404)

    def test_catalog_filter_uses_company_identity_when_names_match(self):
        another_supplier = User.objects.create_user(
            username="another-supplier@example.com",
            email="another-supplier@example.com",
            password="StrongPass123!",
        )
        another_company = Company.objects.create(
            owner=another_supplier,
            company_type=COMPANY_TYPE_SUPPLIER,
            name="Supplier",
            inn="5555555555",
            ogrn="5555555555555",
            region="Tver",
            contact_person="Another Contact",
        )
        Product.objects.create(
            company=another_company,
            title="Other tomatoes",
            description="Other product",
            price="50.00",
            min_order=1,
            region="Tver",
        )
        self.client.force_login(self.buyer)

        response = self.client.get(
            reverse("product_list"),
            {"company": self.supplier_company.id},
        )

        self.assertContains(response, self.product.title)
        self.assertNotContains(response, "Other tomatoes")
        self.assertContains(
            response,
            "Supplier — Moscow · ИНН 1234567890 · активных предложений: 1",
        )

    def test_catalog_context_exposes_declarative_filter(self):
        response = self.client.get(reverse("product_list"))

        self.assertIsInstance(
            response.context["catalog_filter"],
            ProductCatalogFilter,
        )
        self.assertEqual(response.context["page_obj"].paginator.count, 1)

    def test_product_form_does_not_expose_untracked_volume(self):
        self.assertNotIn("available_volume", ProductForm.base_fields)
        self.assertNotIn(
            "available_volume",
            {field.name for field in Product._meta.fields},
        )

    def test_product_rejects_a_buyer_company_even_outside_the_form(self):
        product = Product(
            company=self.buyer_company,
            title="Invalid product",
            description="A buyer cannot publish this.",
            price="100.00",
            min_order=1,
            region="Moscow",
        )

        with self.assertRaises(ValidationError):
            product.save()
