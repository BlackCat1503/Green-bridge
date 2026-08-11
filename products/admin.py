from django.contrib import admin

from .models import Category, Product


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "company",
        "category",
        "price",
        "unit",
        "is_active",
        "created_at",
    )

    list_filter = (
        "category",
        "unit",
        "is_active",
        "region",
    )

    search_fields = (
        "title",
        "description",
        "company__name",
        "region",
    )
