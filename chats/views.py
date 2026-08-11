from typing import Protocol, cast

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import OuterRef, Prefetch, Q, QuerySet, Subquery
from django.http import Http404, HttpRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from products.models import Product
from users.constants import COMPANY_TYPE_BUYER, COMPANY_TYPE_SUPPLIER
from users.models import Company, Review

from .constants import CHAT_MESSAGES_PER_PAGE, DEAL_STATUS_PENDING
from .forms import DealAgreementForm, MessageForm
from .models import Conversation, DealAgreement, Message
from .presenters import ChatListItem, build_agreement_displays
from .services.deal_workflow import (
    AgreementAccessError,
    AgreementNotFoundError,
    AgreementTransitionError,
    PendingAgreementExistsError,
    cancel_agreement as cancel_agreement_workflow,
    complete_agreement,
    confirm_agreement as confirm_agreement_workflow,
    create_agreement as create_agreement_workflow,
    get_agreement_permissions,
    request_agreement_completion as request_agreement_completion_workflow,
)
from .services.system_messages import contact_established, create_chat_message


class AgreementAction(Protocol):
    def __call__(
        self,
        *,
        conversation_id: int,
        agreement_id: int,
        actor: User,
    ) -> DealAgreement: ...


class ConversationDetails(Protocol):
    ordered_agreements: list[DealAgreement]


def _get_authenticated_user(request: HttpRequest) -> User:
    if not request.user.is_authenticated:
        raise Http404
    return request.user


def _get_persisted_user_id(user: User) -> int:
    if user.pk is None:
        raise Http404
    return user.pk


def _ordered_agreements_queryset(
    *,
    current_user_id: int | None = None,
) -> QuerySet[DealAgreement]:
    queryset: QuerySet[DealAgreement] = DealAgreement.objects.select_related(
        "initiator",
        "confirmed_by",
        "completion_requested_by",
        "completed_by",
        "cancelled_by",
    ).order_by("-sequence_number")

    if current_user_id is not None:
        queryset = queryset.prefetch_related(
            Prefetch(
                "reviews",
                queryset=Review.objects.filter(author_id=current_user_id),
                to_attr="reviews_by_current_user",
            ),
        )

    return queryset


def _get_conversation_for_participant(
    request: HttpRequest,
    conversation_id: int,
    *,
    detailed: bool = False,
) -> Conversation:
    user = _get_authenticated_user(request)
    user_id = _get_persisted_user_id(user)
    queryset: QuerySet[Conversation] = Conversation.objects.all()

    if detailed:
        queryset = cast(
            QuerySet[Conversation],
            queryset.select_related(
                "buyer",
                "buyer__company",
                "supplier",
                "supplier__company",
                "product",
                "product__company",
            ).prefetch_related(
                Prefetch(
                    "agreements",
                    queryset=_ordered_agreements_queryset(
                        current_user_id=user_id,
                    ),
                    to_attr="ordered_agreements",
                ),
            ),
        )

    return get_object_or_404(
        queryset.filter(
            Q(buyer_id=user_id) | Q(supplier_id=user_id),
        ),
        id=conversation_id,
    )


def _has_pending_agreement(*, conversation_id: int) -> bool:
    return DealAgreement.objects.filter(
        conversation_id=conversation_id,
        status=DEAL_STATUS_PENDING,
    ).exists()


@login_required
def list_chats(request: HttpRequest):
    user = _get_authenticated_user(request)
    latest_message = Message.objects.filter(
        conversation_id=OuterRef("pk"),
    ).order_by("-created_at", "-id")
    latest_agreement = DealAgreement.objects.filter(
        conversation_id=OuterRef("pk"),
    ).order_by("-sequence_number")
    conversations = (
        Conversation.objects.filter(
            Q(buyer=user) | Q(supplier=user),
        )
        .select_related(
            "buyer",
            "buyer__company",
            "supplier",
            "supplier__company",
            "product",
            "product__company",
        )
        .annotate(
            latest_message_text=Subquery(latest_message.values("text")[:1]),
            latest_agreement_status=Subquery(latest_agreement.values("status")[:1]),
        )
    )
    chat_items = [
        ChatListItem(
            conversation=conversation,
            latest_message_text=conversation.latest_message_text,
            latest_agreement_status=conversation.latest_agreement_status,
        )
        for conversation in conversations
    ]

    return render(
        request,
        "chats/chat_list.html",
        {
            "chat_items": chat_items,
        },
    )


@login_required
@require_POST
def start_chat(request: HttpRequest, product_id: int):
    user = _get_authenticated_user(request)
    product = get_object_or_404(
        Product.objects.select_related("company", "company__owner"),
        id=product_id,
        is_active=True,
        company__is_active=True,
    )

    try:
        user_company = user.company
    except Company.DoesNotExist:
        return redirect("product_detail", product_id=product.id)

    if (
        user_company.company_type != COMPANY_TYPE_BUYER
        or product.company.company_type != COMPANY_TYPE_SUPPLIER
        or product.company.owner_id == _get_persisted_user_id(user)
    ):
        return redirect("product_detail", product_id=product.id)

    with transaction.atomic():
        conversation, created = Conversation.objects.get_or_create(
            buyer=user,
            supplier=product.company.owner,
            product=product,
        )

        if created:
            create_chat_message(
                conversation=conversation,
                sender=user,
                text=contact_established(),
                is_system=True,
            )

    return redirect("chat_detail", conversation_id=conversation.id)


@login_required
def show_chat(request: HttpRequest, conversation_id: int):
    user = _get_authenticated_user(request)
    user_id = _get_persisted_user_id(user)
    conversation = _get_conversation_for_participant(
        request,
        conversation_id,
        detailed=True,
    )

    if request.method == "POST":
        form = MessageForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                locked_conversation = Conversation.objects.select_for_update().get(
                    id=conversation.id,
                )
                create_chat_message(
                    conversation=locked_conversation,
                    sender=user,
                    text=form.cleaned_data["text"],
                )
            return redirect("chat_detail", conversation_id=conversation.id)
    else:
        form = MessageForm()

    message_page = Paginator(
        Message.objects.filter(conversation=conversation)
        .select_related("sender")
        .order_by("-created_at", "-id"),
        CHAT_MESSAGES_PER_PAGE,
    ).get_page(request.GET.get("messages_page"))
    chat_messages = list(reversed(message_page.object_list))

    conversation_details = cast(ConversationDetails, conversation)
    agreements = list(conversation_details.ordered_agreements)
    pending_agreement = next(
        (
            agreement
            for agreement in agreements
            if agreement.status == DEAL_STATUS_PENDING
        ),
        None,
    )
    current_agreement_model = pending_agreement or (
        agreements[0] if agreements else None
    )
    agreement_permissions = get_agreement_permissions(
        agreement=current_agreement_model,
        actor_id=user_id,
    )
    agreement_displays = build_agreement_displays(
        agreements=agreements,
        conversation=conversation,
        current_user_id=user_id,
    )
    agreement_displays_by_id = {
        agreement_display.id: agreement_display
        for agreement_display in agreement_displays
    }

    return render(
        request,
        "chats/chat_detail.html",
        {
            "conversation": conversation,
            "chat_messages": chat_messages,
            "messages_page": message_page,
            "form": form,
            "agreements": agreement_displays,
            "current_agreement": (
                agreement_displays_by_id.get(current_agreement_model.id)
                if current_agreement_model
                else None
            ),
            "pending_agreement": (
                agreement_displays_by_id.get(pending_agreement.id)
                if pending_agreement
                else None
            ),
            "can_manage_pending_agreement": agreement_permissions.can_confirm,
            "can_request_completion": agreement_permissions.can_request_completion,
            "completion_requested_by_user": (
                agreement_permissions.completion_requested_by_actor
            ),
            "can_confirm_completion": agreement_permissions.can_confirm_completion,
            "can_cancel_current_agreement": agreement_permissions.can_cancel,
        },
    )


@login_required
def create_agreement(request: HttpRequest, conversation_id: int):
    user = _get_authenticated_user(request)
    conversation = _get_conversation_for_participant(request, conversation_id)

    if _has_pending_agreement(conversation_id=conversation.id):
        return redirect("chat_detail", conversation_id=conversation.id)

    if request.method == "POST":
        form = DealAgreementForm(request.POST)
        if form.is_valid():
            try:
                create_agreement_workflow(
                    conversation_id=conversation.id,
                    actor=user,
                    amount=form.cleaned_data["amount"],
                    delivery_date=form.cleaned_data["delivery_date"],
                    terms=form.cleaned_data["terms"],
                )
            except PendingAgreementExistsError:
                return redirect("chat_detail", conversation_id=conversation.id)
            except AgreementAccessError as error:
                raise Http404 from error

            return redirect("chat_detail", conversation_id=conversation.id)
    else:
        form = DealAgreementForm()

    return render(
        request,
        "chats/agreement_form.html",
        {
            "form": form,
            "conversation": conversation,
        },
    )


@login_required
@require_POST
def confirm_agreement(
    request: HttpRequest,
    conversation_id: int,
    agreement_id: int,
):
    _get_conversation_for_participant(request, conversation_id)
    _run_agreement_action(
        action=confirm_agreement_workflow,
        request=request,
        conversation_id=conversation_id,
        agreement_id=agreement_id,
    )
    return redirect("chat_detail", conversation_id=conversation_id)


@login_required
@require_POST
def request_agreement_completion(
    request: HttpRequest,
    conversation_id: int,
    agreement_id: int,
):
    _get_conversation_for_participant(request, conversation_id)
    _run_agreement_action(
        action=request_agreement_completion_workflow,
        request=request,
        conversation_id=conversation_id,
        agreement_id=agreement_id,
    )
    return redirect("chat_detail", conversation_id=conversation_id)


@login_required
@require_POST
def confirm_agreement_completion(
    request: HttpRequest,
    conversation_id: int,
    agreement_id: int,
):
    _get_conversation_for_participant(request, conversation_id)
    _run_agreement_action(
        action=complete_agreement,
        request=request,
        conversation_id=conversation_id,
        agreement_id=agreement_id,
    )
    return redirect("chat_detail", conversation_id=conversation_id)


@login_required
@require_POST
def cancel_agreement(
    request: HttpRequest,
    conversation_id: int,
    agreement_id: int,
):
    _get_conversation_for_participant(request, conversation_id)
    _run_agreement_action(
        action=cancel_agreement_workflow,
        request=request,
        conversation_id=conversation_id,
        agreement_id=agreement_id,
    )
    return redirect("chat_detail", conversation_id=conversation_id)


def _run_agreement_action(
    *,
    action: AgreementAction,
    request: HttpRequest,
    conversation_id: int,
    agreement_id: int,
) -> None:
    try:
        action(
            conversation_id=conversation_id,
            agreement_id=agreement_id,
            actor=_get_authenticated_user(request),
        )
    except AgreementNotFoundError as error:
        raise Http404 from error
    except (AgreementAccessError, AgreementTransitionError):
        return
