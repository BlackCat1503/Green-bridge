import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models
from django.db.models import Q

from chats.constants import DEAL_STATUS_COMPLETED
from core.constants import IMAGE_ALLOWED_EXTENSIONS
from core.validators import validate_image_size

from .constants import (
    COMPANY_TYPE_CHOICES,
    EMAIL_VERIFICATION_CODE_LENGTH,
    EMAIL_VERIFICATION_CODE_SPACE,
)
from .validators import validate_inn, validate_ogrn


class Company(models.Model):
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="company",
    )
    company_type = models.CharField(max_length=20, choices=COMPANY_TYPE_CHOICES)

    name = models.CharField(max_length=200)
    inn = models.CharField(max_length=20, unique=True, validators=[validate_inn])
    ogrn = models.CharField(max_length=20, unique=True, validators=[validate_ogrn])

    region = models.CharField(max_length=150)
    contact_person = models.CharField(max_length=150)
    contacts = models.CharField(max_length=150, blank=True)

    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(
        upload_to="companies/logos/",
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(IMAGE_ALLOWED_EXTENSIONS),
            validate_image_size,
        ],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Review(models.Model):
    agreement = models.ForeignKey(
        "chats.DealAgreement",
        on_delete=models.PROTECT,
        related_name="reviews",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="written_reviews",
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="reviews",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="reviews",
        null=True,
        blank=True,
    )
    rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["agreement", "author"],
                name="unique_review_per_agreement_author",
            ),
            models.CheckConstraint(
                condition=Q(rating__gte=1) & Q(rating__lte=5),
                name="review_rating_between_1_and_5",
            ),
        ]

    def __str__(self):
        return f"{self.rating}★ {self.company.name}"

    def clean(self):
        super().clean()
        if not self.agreement_id or not self.author_id or not self.company_id:
            return

        conversation = self.agreement.conversation
        expected_company_id = None
        if self.author_id == conversation.buyer_id:
            expected_company_id = conversation.supplier.company.id
        elif self.author_id == conversation.supplier_id:
            expected_company_id = conversation.buyer.company.id

        errors = {}
        if expected_company_id is None:
            errors["author"] = "Отзыв может оставить только участник сделки."
        elif self.company_id != expected_company_id:
            errors["company"] = "Отзыв должен быть оставлен о второй стороне сделки."

        if self.product_id and self.product_id != conversation.product_id:
            errors["product"] = "Отзыв должен относиться к товару сделки."

        if self.agreement.status != DEAL_STATUS_COMPLETED:
            errors["agreement"] = "Отзыв можно оставить только по завершённой сделке."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class EmailVerification(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    code = models.CharField(max_length=128)
    verified = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_sent_at = models.DateTimeField()

    @staticmethod
    def generate_code():
        code = secrets.randbelow(EMAIL_VERIFICATION_CODE_SPACE)
        return f"{code:0{EMAIL_VERIFICATION_CODE_LENGTH}d}"
