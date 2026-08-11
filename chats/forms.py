from datetime import date

from django import forms
from django.utils import timezone

from .models import DealAgreement, Message
from .validators import validate_new_delivery_date


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ["text"]

        widgets = {
            "text": forms.Textarea(
                attrs={
                    "class": "chat-detail-page__composer-input",
                    "placeholder": "Введите сообщение",
                    "rows": 4,
                }
            )
        }

        labels = {"text": ""}


class DealAgreementForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["delivery_date"].widget.attrs["min"] = (
            timezone.localdate().isoformat()
        )

    def clean_delivery_date(self) -> date:
        delivery_date: date = self.cleaned_data["delivery_date"]
        validate_new_delivery_date(delivery_date)
        return delivery_date

    class Meta:
        model = DealAgreement
        fields = [
            "amount",
            "delivery_date",
            "terms",
        ]

        labels = {
            "amount": "Сумма сделки",
            "delivery_date": "Дата поставки",
            "terms": "Условия договорённости",
        }

        widgets = {
            "delivery_date": forms.DateInput(attrs={"type": "date"}),
            "terms": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": (
                        "Укажите основные условия: объём, сроки, формат поставки, "
                        "дополнительные договорённости"
                    ),
                }
            ),
        }
