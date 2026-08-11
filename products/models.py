from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from core.constants import IMAGE_ALLOWED_EXTENSIONS
from core.validators import validate_image_size
from users.constants import COMPANY_TYPE_SUPPLIER
from users.models import Company

from .constants import (
    PRODUCT_UNIT_CHOICES,
    PRODUCT_UNIT_KILOGRAM,
)


class Category(models.Model):
    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"

    def __str__(self):
        return self.name


class ProductQuerySet(models.QuerySet["Product"]):
    def active(self) -> "ProductQuerySet":
        return self.filter(is_active=True)

    def for_catalog(self) -> "ProductQuerySet":
        return (
            self.active()
            .filter(
                company__is_active=True,
                company__company_type=COMPANY_TYPE_SUPPLIER,
            )
            .select_related("company", "category")
            .order_by("-id")
        )

    def for_company(self, company: Company) -> "ProductQuerySet":
        return self.filter(company=company).select_related("category")


class Product(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="products",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    unit = models.CharField(
        max_length=20,
        choices=PRODUCT_UNIT_CHOICES,
        default=PRODUCT_UNIT_KILOGRAM,
    )
    min_order = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    region = models.CharField(max_length=150)
    image = models.ImageField(
        upload_to="products/",
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(IMAGE_ALLOWED_EXTENSIONS),
            validate_image_size,
        ],
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(price__gt=0),
                name="product_price_must_be_positive",
            ),
            models.CheckConstraint(
                condition=Q(min_order__gt=0),
                name="product_min_order_must_be_positive",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.company_id and self.company.company_type != COMPANY_TYPE_SUPPLIER:
            raise ValidationError(
                {"company": "Публиковать товары может только поставщик."}
            )

    def save(self, *args, **kwargs):
        self.full_clean(validate_constraints=False)
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.title
