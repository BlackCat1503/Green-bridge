from django.urls import path

from . import views

urlpatterns = [
    path("", views.list_chats, name="chat_list"),
    path("start/<int:product_id>/", views.start_chat, name="start_chat"),
    path("<int:conversation_id>/", views.show_chat, name="chat_detail"),
    path(
        "<int:conversation_id>/agreement/create/",
        views.create_agreement,
        name="create_agreement",
    ),
    path(
        "<int:conversation_id>/agreement/<int:agreement_id>/confirm/",
        views.confirm_agreement,
        name="confirm_agreement",
    ),
    path(
        "<int:conversation_id>/agreement/<int:agreement_id>/complete/request/",
        views.request_agreement_completion,
        name="request_complete_agreement",
    ),
    path(
        "<int:conversation_id>/agreement/<int:agreement_id>/complete/confirm/",
        views.confirm_agreement_completion,
        name="confirm_complete_agreement",
    ),
    path(
        "<int:conversation_id>/agreement/<int:agreement_id>/cancel/",
        views.cancel_agreement,
        name="cancel_agreement",
    ),
]
