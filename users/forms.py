from collections.abc import Callable

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db import transaction

from .constants import COMPANY_TYPE_CHOICES
from .models import Company, Review
from .validators import normalize_company_number, validate_inn, validate_ogrn


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label="Почта",
        widget=forms.EmailInput(attrs={"placeholder": "Почта"}),
    )
    password = forms.CharField(
        label="Пароль",
        widget=forms.PasswordInput(attrs={"placeholder": "Пароль"}),
    )


class CompanyRegisterForm(UserCreationForm):
    email = forms.EmailField(
        label="Рабочий email компании",
        widget=forms.EmailInput(attrs={"placeholder": "Рабочий email компании"}),
    )
    password1 = forms.CharField(
        label="Пароль",
        widget=forms.PasswordInput(attrs={"placeholder": "Пароль"}),
    )
    password2 = forms.CharField(
        label="Подтверждение пароля",
        widget=forms.PasswordInput(attrs={"placeholder": "Подтверждение пароля"}),
    )
    inn = forms.CharField(
        label="ИНН",
        required=True,
        widget=forms.TextInput(attrs={"placeholder": "ИНН"}),
    )
    ogrn = forms.CharField(
        label="ОГРН",
        required=True,
        widget=forms.TextInput(attrs={"placeholder": "ОГРН"}),
    )
    company_type = forms.ChoiceField(
        label="Выбор роли",
        choices=COMPANY_TYPE_CHOICES,
        widget=forms.RadioSelect,
    )
    company_name = forms.CharField(
        label="Название компании",
        widget=forms.TextInput(attrs={"placeholder": "Название компании"}),
    )
    region = forms.CharField(
        label="Регион",
        widget=forms.TextInput(attrs={"placeholder": "Регион"}),
    )
    contact_person = forms.CharField(
        label="ФИО контактного лица",
        widget=forms.TextInput(attrs={"placeholder": "ФИО контактного лица"}),
    )
    contacts = forms.CharField(
        label="Контакты",
        widget=forms.TextInput(attrs={"placeholder": "Контакты"}),
    )
    agreement = forms.BooleanField(
        label="Я соглашаюсь с условиями использования платформы и обработкой данных",
        required=True,
    )

    class Meta:
        model = get_user_model()
        fields = [
            "email",
            "password1",
            "password2",
            "inn",
            "ogrn",
            "company_type",
            "company_name",
            "region",
            "contact_person",
            "contacts",
            "agreement",
        ]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(username=email).exists():
            raise forms.ValidationError("Аккаунт с таким email уже существует.")
        return email

    def _clean_company_number(
        self,
        field_name: str,
        validator: Callable[[str], None],
        label: str,
    ) -> str:
        value = normalize_company_number(self.cleaned_data[field_name])
        validator(value)
        if Company.objects.filter(**{field_name: value}).exists():
            raise forms.ValidationError(
                f"Компания с таким {label} уже зарегистрирована."
            )
        return value

    def clean_inn(self):
        return self._clean_company_number("inn", validate_inn, "ИНН")

    def clean_ogrn(self):
        return self._clean_company_number("ogrn", validate_ogrn, "ОГРН")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["email"]
        user.email = self.cleaned_data["email"]
        user.is_active = False

        if not commit:
            return user

        with transaction.atomic():
            user.save()
            Company.objects.create(
                owner=user,
                company_type=self.cleaned_data["company_type"],
                name=self.cleaned_data["company_name"],
                inn=self.cleaned_data["inn"],
                ogrn=self.cleaned_data["ogrn"],
                region=self.cleaned_data["region"],
                contact_person=self.cleaned_data["contact_person"],
                contacts=self.cleaned_data["contacts"],
            )

        return user


class CompanyProfileForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = [
            "name",
            "region",
            "contact_person",
            "contacts",
            "email",
            "website",
            "description",
            "logo",
        ]
        labels = {
            "name": "Название компании",
            "region": "Регион",
            "contact_person": "Контактное лицо",
            "contacts": "Контакты",
            "email": "Контактный email",
            "website": "Сайт",
            "description": "Описание компании",
            "logo": "Логотип / фото компании",
        }
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": (
                        "Расскажите о компании, продукции, условиях сотрудничества"
                    ),
                }
            ),
            "logo": forms.ClearableFileInput(
                attrs={
                    "accept": ".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp",
                }
            ),
        }


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ["rating", "text"]
        widgets = {
            "rating": forms.NumberInput(attrs={"min": 1, "max": 5, "step": 1}),
            "text": forms.Textarea(attrs={"rows": 4}),
        }
