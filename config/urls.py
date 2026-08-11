from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path

urlpatterns: list[URLPattern | URLResolver] = [
    path("", include("core.urls")),
    path("products/", include("products.urls")),
    path("users/", include("users.urls")),
    path("admin/", admin.site.urls),
    path("chat/", include("chats.urls")),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
