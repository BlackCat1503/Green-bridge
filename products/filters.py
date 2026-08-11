from typing import Protocol, cast

import django_filters
from django import forms
from django.db.models import Count, Q, QuerySet

from users.constants import COMPANY_TYPE_SUPPLIER
from users.models import Company

from .models import Category, Product

CATALOG_SORT_CHOICES = (
    ("", "Новые"),
    ("price_asc", "Цена ↑"),
    ("price_desc", "Цена ↓"),
)


def get_catalog_categories() -> QuerySet[Category]:
    return Category.objects.order_by("name")


def get_supplier_companies() -> QuerySet[Company]:
    return Company.objects.filter(
        company_type=COMPANY_TYPE_SUPPLIER,
        is_active=True,
    ).order_by("name", "region", "inn")


def get_supplier_filter_options() -> QuerySet[Company]:
    return get_supplier_companies().annotate(
        active_products_count=Count(
            "products",
            filter=Q(products__is_active=True),
        ),
    )


class SupplierOption(Protocol):
    name: str
    region: str
    inn: str
    active_products_count: int


class SupplierChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, company: Company) -> str:
        supplier_option = cast(SupplierOption, company)
        return (
            f"{supplier_option.name} — {supplier_option.region} · "
            f"ИНН {supplier_option.inn} · активных предложений: "
            f"{supplier_option.active_products_count}"
        )


class SupplierFilter(django_filters.ModelChoiceFilter):
    field_class = SupplierChoiceField


class ProductCatalogFilterForm(forms.Form):
    def clean(self):
        cleaned_data = super().clean() or {}
        price_min = cleaned_data.get("price_min")
        price_max = cleaned_data.get("price_max")

        if price_min is not None and price_max is not None and price_min > price_max:
            self.add_error(
                "price_max",
                "Максимальная цена не может быть меньше минимальной.",
            )

        return cleaned_data


class ProductCatalogFilter(django_filters.FilterSet):
    q = django_filters.CharFilter(
        field_name="title",
        lookup_expr="icontains",
    )
    category = django_filters.ModelChoiceFilter(
        queryset=get_catalog_categories(),
    )
    region = django_filters.CharFilter(
        field_name="region",
        lookup_expr="icontains",
    )
    company = SupplierFilter(
        queryset=get_supplier_filter_options(),
    )
    price_min = django_filters.NumberFilter(
        field_name="price",
        lookup_expr="gte",
        min_value=0,
    )
    price_max = django_filters.NumberFilter(
        field_name="price",
        lookup_expr="lte",
        min_value=0,
    )
    sort = django_filters.ChoiceFilter(
        choices=CATALOG_SORT_CHOICES,
        method="filter_sort",
    )

    class Meta:
        model = Product
        fields = ()
        form = ProductCatalogFilterForm

    def filter_sort(
        self,
        queryset: QuerySet[Product],
        _name: str,
        value: str,
    ) -> QuerySet[Product]:
        if value == "price_asc":
            return queryset.order_by("price", "-id")
        if value == "price_desc":
            return queryset.order_by("-price", "-id")
        return queryset.order_by("-id")
