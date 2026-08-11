from datetime import date

from django.core.exceptions import ValidationError
from django.utils import timezone


def validate_new_delivery_date(delivery_date: date) -> None:
    if delivery_date < timezone.localdate():
        raise ValidationError("Дата поставки не может быть в прошлом.")
