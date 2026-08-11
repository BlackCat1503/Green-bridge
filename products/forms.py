from django import forms

from .models import Product


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "title",
            "category",
            "description",
            "price",
            "unit",
            "min_order",
            "region",
            "image",
            "is_active",
        ]
        labels = {
            "title": "Название товара",
            "category": "Категория",
            "description": "Описание",
            "price": "Цена",
            "unit": "Единица измерения",
            "min_order": "Минимальный заказ",
            "region": "Регион",
            "image": "Фото товара",
            "is_active": "Опубликовать предложение",
        }
        widgets = {
            "title": forms.TextInput(
                attrs={"placeholder": "Например: Органические томаты"}
            ),
            "description": forms.Textarea(
                attrs={
                    "placeholder": (
                        "Опишите продукцию, условия хранения, особенности поставки"
                    ),
                    "rows": 5,
                }
            ),
            "price": forms.NumberInput(
                attrs={"placeholder": "Цена", "min": "0.01", "step": "0.01"}
            ),
            "min_order": forms.NumberInput(
                attrs={"placeholder": "Минимальный заказ", "min": 1}
            ),
            "region": forms.TextInput(attrs={"placeholder": "Регион поставки"}),
        }
