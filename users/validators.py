from django.core.exceptions import ValidationError

from .constants import INN_ALLOWED_LENGTHS, OGRN_ALLOWED_LENGTHS


def normalize_company_number(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def validate_inn(value: str) -> None:
    _validate_company_number(
        value=value,
        allowed_lengths=INN_ALLOWED_LENGTHS,
        label="ИНН",
    )


def validate_ogrn(value: str) -> None:
    _validate_company_number(
        value=value,
        allowed_lengths=OGRN_ALLOWED_LENGTHS,
        label="ОГРН",
    )


def _validate_company_number(
    *,
    value: str,
    allowed_lengths: tuple[int, ...],
    label: str,
) -> None:
    if not value.isdigit() or len(value) not in allowed_lengths:
        lengths = " или ".join(str(length) for length in allowed_lengths)
        raise ValidationError(
            f"{label} должен содержать {lengths} цифр.",
        )
