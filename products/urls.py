from django.urls import path

from . import views

urlpatterns = [
    path("", views.list_products, name="product_list"),
    path("my/", views.list_my_products, name="my_products"),
    path("create/", views.create_product, name="product_create"),
    path("<int:product_id>/", views.show_product, name="product_detail"),
    path("<int:product_id>/edit/", views.edit_product, name="product_edit"),
    path("<int:product_id>/archive/", views.archive_product, name="archive_product"),
]
