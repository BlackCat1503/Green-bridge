from decimal import Decimal
from typing import Protocol, cast

from django.db.models import Avg, Count, F, Q, QuerySet, Sum

from chats.constants import (
    DEAL_STATUS_CANCELLED,
    DEAL_STATUS_COMPLETED,
    DEAL_STATUS_CONFIRMED,
    DEAL_STATUS_PENDING,
)
from chats.models import Conversation, DealAgreement
from products.models import Category, Product

from ..constants import (
    ANALYTICS_TOP_PRODUCTS_LIMIT,
    ANALYTICS_TOP_REGIONS_LIMIT,
    ANALYTICS_TOP_SUPPLIERS_LIMIT,
    COMPANY_TYPE_SUPPLIER,
)
from ..models import Company, Review


class ProductDemand(Protocol):
    title: str
    category: Category | None
    conversations_count: int
    deals_count: int


def calculate_percentage(
    numerator: int,
    denominator: int,
    *,
    digits: int = 1,
) -> float:
    if not denominator:
        return 0
    return round((numerator / denominator) * 100, digits)


def build_analytics(company: Company) -> dict[str, object]:
    if company.company_type == COMPANY_TYPE_SUPPLIER:
        return build_supplier_analytics(company)
    return build_buyer_analytics(company)


def build_supplier_analytics(company: Company) -> dict[str, object]:
    user = company.owner
    products = Product.objects.filter(company=company)
    conversations = Conversation.objects.filter(supplier=user)
    agreements = DealAgreement.objects.filter(conversation__supplier=user)

    context = _build_common_context(
        company=company,
        products=products,
        conversations=conversations,
        agreements=agreements,
        partner_rating_queryset=company.reviews.all(),
    )
    products_with_demand = products.select_related("category").annotate(
        conversations_count=Count("conversations", distinct=True),
        deals_count=Count(
            "conversations__agreements",
            filter=Q(
                conversations__agreements__status=DEAL_STATUS_COMPLETED,
            ),
            distinct=True,
        ),
    )
    top_products = [
        cast(ProductDemand, product)
        for product in products_with_demand.order_by(
            "-conversations_count",
            "-deals_count",
            "title",
        )[:ANALYTICS_TOP_PRODUCTS_LIMIT]
    ]
    max_conversations = max(
        (product.conversations_count for product in top_products),
        default=0,
    )
    active_products_with_interest = products_with_demand.filter(
        is_active=True,
        conversations_count__gt=0,
    ).count()

    context.update(
        {
            "offer_conversion": calculate_percentage(
                active_products_with_interest,
                cast(int, context["active_products"]),
            ),
            "top_products_chart": [
                {
                    "title": product.title,
                    "category": str(product.category)
                    if product.category
                    else "Без категории",
                    "conversations_count": product.conversations_count,
                    "deals_count": product.deals_count,
                    "percentage": calculate_percentage(
                        product.conversations_count,
                        max_conversations,
                    ),
                }
                for product in top_products
            ],
            "category_demand": products.values("category__name")
            .annotate(
                conversations_count=Count("conversations", distinct=True),
                deals_count=Count(
                    "conversations__agreements",
                    filter=Q(
                        conversations__agreements__status=DEAL_STATUS_COMPLETED,
                    ),
                    distinct=True,
                ),
            )
            .order_by("-conversations_count", "-deals_count")[
                :ANALYTICS_TOP_PRODUCTS_LIMIT
            ],
            "demand_regions": conversations.values(
                "buyer__company__region",
            )
            .annotate(
                total=Count("id"),
            )
            .exclude(
                buyer__company__region="",
            )
            .order_by("-total")[:ANALYTICS_TOP_REGIONS_LIMIT],
            "analytics_title": "Аналитика продавца",
            "analytics_description": (
                "Спрос на предложения, переговоры и результат завершённых сделок."
            ),
        }
    )
    return context


def build_buyer_analytics(company: Company) -> dict[str, object]:
    user = company.owner
    conversations = Conversation.objects.filter(buyer=user)
    agreements = DealAgreement.objects.filter(conversation__buyer=user)
    partner_reviews = Review.objects.filter(
        agreement__conversation__buyer=user,
        agreement__status=DEAL_STATUS_COMPLETED,
        company__owner=F("agreement__conversation__supplier"),
    )

    context = _build_common_context(
        company=company,
        products=Product.objects.none(),
        conversations=conversations,
        agreements=agreements,
        partner_rating_queryset=partner_reviews,
    )
    completed_conversations = (
        conversations.filter(
            agreements__status=DEAL_STATUS_COMPLETED,
        )
        .distinct()
        .count()
    )

    context.update(
        {
            "suppliers_count": conversations.values("supplier_id").distinct().count(),
            "deal_conversion": calculate_percentage(
                completed_conversations,
                cast(int, context["total_conversations"]),
            ),
            "supplier_comparison": conversations.values(
                "supplier_id",
                "supplier__company__name",
                "supplier__company__region",
                "supplier__company__inn",
            )
            .annotate(
                negotiations_count=Count("id", distinct=True),
                completed_deals=Count(
                    "agreements",
                    filter=Q(agreements__status=DEAL_STATUS_COMPLETED),
                    distinct=True,
                ),
                supplier_rating=Avg(
                    "agreements__reviews__rating",
                    filter=Q(
                        agreements__status=DEAL_STATUS_COMPLETED,
                        agreements__reviews__company__owner=F("supplier_id"),
                    ),
                ),
            )
            .order_by(
                "-completed_deals",
                "-negotiations_count",
                "supplier__company__name",
                "supplier_id",
            )[:ANALYTICS_TOP_SUPPLIERS_LIMIT],
            "category_spend": agreements.filter(
                status=DEAL_STATUS_COMPLETED,
            )
            .values(
                "conversation__product__category__name",
            )
            .annotate(
                deals_count=Count("id"),
                total_amount=Sum("amount"),
            )
            .order_by("-total_amount", "-deals_count")[:ANALYTICS_TOP_PRODUCTS_LIMIT],
            "partner_regions": conversations.values(
                "supplier__company__region",
            )
            .annotate(
                total=Count("id"),
            )
            .exclude(
                supplier__company__region="",
            )
            .order_by("-total")[:ANALYTICS_TOP_REGIONS_LIMIT],
            "analytics_title": "Аналитика покупателя",
            "analytics_description": (
                "Переговоры, завершённые сделки, поставщики и структура закупок."
            ),
        }
    )
    return context


def _build_common_context(
    *,
    company: Company,
    products: QuerySet[Product],
    conversations: QuerySet[Conversation],
    agreements: QuerySet[DealAgreement],
    partner_rating_queryset: QuerySet[Review],
) -> dict[str, object]:
    total_conversations = conversations.count()
    product_metrics = products.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True)),
    )
    agreement_metrics = agreements.aggregate(
        confirmed=Count("id", filter=Q(status=DEAL_STATUS_CONFIRMED)),
        pending=Count("id", filter=Q(status=DEAL_STATUS_PENDING)),
        cancelled=Count("id", filter=Q(status=DEAL_STATUS_CANCELLED)),
        completed=Count("id", filter=Q(status=DEAL_STATUS_COMPLETED)),
        completed_amount=Sum(
            "amount",
            filter=Q(status=DEAL_STATUS_COMPLETED),
        ),
        average_completed_amount=Avg(
            "amount",
            filter=Q(status=DEAL_STATUS_COMPLETED),
        ),
    )
    partner_rating = partner_rating_queryset.aggregate(
        average=Avg("rating"),
    )["average"]
    completed_conversations = (
        conversations.filter(
            agreements__status=DEAL_STATUS_COMPLETED,
        )
        .distinct()
        .count()
    )

    return {
        "company": company,
        "role": company.company_type,
        "total_products": product_metrics["total"],
        "active_products": product_metrics["active"],
        "total_conversations": total_conversations,
        "confirmed_agreements": agreement_metrics["confirmed"],
        "pending_agreements": agreement_metrics["pending"],
        "cancelled_agreements": agreement_metrics["cancelled"],
        "completed_agreements": agreement_metrics["completed"],
        "completed_amount": agreement_metrics["completed_amount"] or Decimal("0"),
        "average_deal_amount": (
            round(agreement_metrics["average_completed_amount"], 2)
            if agreement_metrics["average_completed_amount"]
            else None
        ),
        "average_rating": round(partner_rating, 1) if partner_rating else None,
        "deal_conversion": calculate_percentage(
            completed_conversations,
            total_conversations,
        ),
    }
