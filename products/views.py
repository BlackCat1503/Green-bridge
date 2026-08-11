from typing import cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Avg, Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from users.constants import COMPANY_TYPE_SUPPLIER
from users.models import Company

from .constants import PRODUCTS_PER_PAGE
from .filters import ProductCatalogFilter
from .forms import ProductForm
from .models import Product


def _get_supplier_company_for_request(request: HttpRequest) -> Company | None:
    user = cast(User, request.user)
    company = Company.objects.filter(owner=user).first()
    if not company:
        messages.error(request, "Для работы с предложениями нужен профиль компании.")
        return None
    if company.company_type != COMPANY_TYPE_SUPPLIER:
        messages.info(
            request, "Создавать и редактировать предложения могут только поставщики."
        )
        return None
    return company


def list_products(request: HttpRequest) -> HttpResponse:
    catalog_products = Product.objects.for_catalog()
    catalog_filter = ProductCatalogFilter(
        request.GET or None,
        queryset=catalog_products,
    )
    filtered_products = (
        catalog_filter.qs if catalog_filter.is_valid() else catalog_products
    )
    paginator = Paginator(filtered_products, PRODUCTS_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)

    return render(
        request,
        "products/product_list.html",
        {
            "catalog_filter": catalog_filter,
            "page_obj": page_obj,
            "query_string": query_params.urlencode(),
        },
    )


@login_required
def show_product(request: HttpRequest, product_id: int) -> HttpResponse:
    product = get_object_or_404(
        Product.objects.for_catalog(),
        id=product_id,
    )
    reviews = product.reviews.select_related(
        "author__company",
        "company",
    ).order_by("-created_at")
    review_metrics = reviews.aggregate(
        reviews_count=Count("id"),
        average_rating=Avg("rating"),
    )
    average_rating = review_metrics["average_rating"]

    return render(
        request,
        "products/product_detail.html",
        {
            "product": product,
            "reviews": reviews,
            "reviews_count": review_metrics["reviews_count"],
            "rating": round(average_rating, 1) if average_rating else None,
        },
    )


@login_required
def list_my_products(request: HttpRequest) -> HttpResponse:
    company = _get_supplier_company_for_request(request)
    if not company:
        return redirect("dashboard")

    products = Product.objects.for_company(company)
    return render(request, "products/my_products.html", {"products": products})


@login_required
def create_product(request: HttpRequest) -> HttpResponse:
    company = _get_supplier_company_for_request(request)
    if not company:
        return redirect("dashboard")

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            product.company = company
            product.region = product.region or company.region
            product.save()
            messages.success(request, "Предложение создано.")
            return redirect("my_products")
    else:
        form = ProductForm(initial={"region": company.region})

    return render(
        request,
        "products/product_form.html",
        {
            "form": form,
            "title": "Новое предложение",
            "button_text": "Создать предложение",
        },
    )


@login_required
def edit_product(request: HttpRequest, product_id: int) -> HttpResponse:
    company = _get_supplier_company_for_request(request)
    if not company:
        return redirect("dashboard")

    product = get_object_or_404(Product, id=product_id, company=company)
    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, "Предложение обновлено.")
            return redirect("my_products")
    else:
        form = ProductForm(instance=product)

    return render(
        request,
        "products/product_form.html",
        {
            "form": form,
            "title": "Редактировать предложение",
            "button_text": "Сохранить изменения",
        },
    )


@login_required
@require_POST
def archive_product(request: HttpRequest, product_id: int) -> HttpResponse:
    company = _get_supplier_company_for_request(request)
    if not company:
        return redirect("dashboard")

    product = get_object_or_404(Product, id=product_id, company=company)
    if product.is_active:
        product.is_active = False
        product.save(update_fields=["is_active", "updated_at"])
        messages.success(
            request, "Предложение снято с публикации. История переговоров сохранена."
        )
    else:
        messages.info(request, "Предложение уже находится в архиве.")
    return redirect("my_products")
