from typing import Protocol

from django.core.exceptions import ValidationError

from .constants import MAX_IMAGE_SIZE_BYTES


class SizedUpload(Protocol):
    @property
    def size(self) -> int: ...


def validate_image_size(image: SizedUpload | None) -> None:
    if image is not None and image.size > MAX_IMAGE_SIZE_BYTES:
        raise ValidationError("Размер изображения не должен превышать 5 МБ.")
