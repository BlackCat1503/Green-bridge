import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from chats.constants import DEAL_STATUS_CANCELLED, DEAL_STATUS_COMPLETED
from chats.models import DealAgreement
from products.models import Product

from .constants import (
    EMAIL_RESEND_COOLDOWN_SECONDS,
    EMAIL_VERIFICATION_MAX_ATTEMPTS,
    EMAIL_VERIFICATION_TTL_MINUTES,
)
from .forms import (
    CompanyProfileForm,
    CompanyRegisterForm,
    EmailAuthenticationForm,
    ReviewForm,
)
from .models import Company, EmailVerification, Review
from .services.analytics import build_analytics, calculate_percentage
from .services.reviews import (
    ReviewAccessError,
    ReviewAlreadyExistsError,
    create_review as create_review_service,
    get_review_target,
)

logger = logging.getLogger(__name__)


def _get_current_company(request):
    return get_object_or_404(
        Company.objects.select_related("owner"),
        owner=request.user,
        is_active=True,
    )


def _format_decimal_with_comma(value):
    if value is None:
        return None

    return f"{value:.1f}".replace(".", ",")


def _build_company_metrics(company):
    user = company.owner
    company_deals = DealAgreement.objects.filter(
        Q(conversation__buyer=user) | Q(conversation__supplier=user)
    )
    deal_metrics = company_deals.aggregate(
        completed=Count(
            "id",
            filter=Q(status=DEAL_STATUS_COMPLETED),
        ),
        cancelled_by_company=Count(
            "id",
            filter=Q(
                status=DEAL_STATUS_CANCELLED,
                cancelled_by=user,
            ),
        ),
    )
    completed_deals = deal_metrics["completed"]
    cancelled_by_company = deal_metrics["cancelled_by_company"]
    success_rate = calculate_percentage(
        completed_deals,
        completed_deals + cancelled_by_company,
        digits=0,
    )

    reviews = company.reviews.select_related(
        "author__company",
        "product",
    ).order_by("-created_at")
    review_metrics = reviews.aggregate(
        count=Count("id"),
        average_rating=Avg("rating"),
    )
    reviews_count = review_metrics["count"]
    average_rating = review_metrics["average_rating"]
    rating = round(average_rating, 1) if average_rating else None

    return {
        "reviews": reviews,
        "reviews_count": reviews_count,
        "rating": rating,
        "rating_display": _format_decimal_with_comma(rating) or "—",
        "completed_deals_count": completed_deals,
        "success_rate": success_rate,
    }


def _issue_email_verification(user, verification=None):
    now = timezone.now()
    code = EmailVerification.generate_code()
    values = {
        "code": make_password(code),
        "verified": False,
        "attempts": 0,
        "expires_at": now + timedelta(minutes=EMAIL_VERIFICATION_TTL_MINUTES),
        "last_sent_at": now,
    }

    if verification is None:
        verification = EmailVerification.objects.create(user=user, **values)
    else:
        for field, value in values.items():
            setattr(verification, field, value)
        verification.save(update_fields=[*values.keys()])

    return verification, code


def _send_verification_email(user, code):
    sent = send_mail(
        "Код подтверждения GreenBridge",
        f"Ваш код подтверждения: {code}",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )
    if not sent:
        raise RuntimeError("Email backend did not accept the verification message.")


def _get_pending_verification(request):
    user_id = request.session.get("verify_user_id")
    if not user_id:
        return None

    user = get_user_model().objects.filter(id=user_id, is_active=False).first()
    verification = (
        EmailVerification.objects.filter(user=user, verified=False).first()
        if user
        else None
    )
    if not verification:
        request.session.pop("verify_user_id", None)
        return None

    return user, verification


def _safe_next_url(request):
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return None


def register_view(request):
    if request.method == "POST":
        form = CompanyRegisterForm(request.POST)
        if form.is_valid():
            try:
                user = form.save()
            except IntegrityError:
                form.add_error("email", "Аккаунт с таким email уже существует.")
            else:
                _, code = _issue_email_verification(user)
                request.session["verify_user_id"] = user.id
                try:
                    _send_verification_email(user, code)
                except Exception:
                    logger.exception(
                        "Unable to send verification email for user %s", user.id
                    )
                    messages.error(
                        request,
                        (
                            "Аккаунт создан, но письмо не отправилось. "
                            "Попробуйте запросить код ещё раз."
                        ),
                    )
                else:
                    messages.success(
                        request, "Код подтверждения отправлен на вашу почту."
                    )
                return redirect("verify_email")
    else:
        form = CompanyRegisterForm()

    return render(request, "users/register.html", {"form": form})


def login_view(request):
    if request.method == "POST":
        form = EmailAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect(_safe_next_url(request) or "dashboard")
    else:
        form = EmailAuthenticationForm()

    return render(
        request,
        "users/login.html",
        {
            "form": form,
            "next": _safe_next_url(request),
        },
    )


@require_POST
def logout_view(request):
    logout(request)
    return redirect("home")


@login_required
def show_dashboard(request):
    company = _get_current_company(request)
    products = Product.objects.for_company(company).active()

    metrics = _build_company_metrics(company)

    return render(
        request,
        "users/dashboard.html",
        {
            "company": company,
            "products": products,
            "products_count": products.count(),
            **metrics,
        },
    )


@login_required
def edit_company(request):
    company = _get_current_company(request)

    if request.method == "POST":
        form = CompanyProfileForm(request.POST, request.FILES, instance=company)

        if form.is_valid():
            form.save()
            return redirect("dashboard")
    else:
        form = CompanyProfileForm(instance=company)

    return render(
        request, "users/edit_company.html", {"form": form, "company": company}
    )


@login_required
def show_company_profile(request, company_id):
    company = get_object_or_404(
        Company.objects.filter(is_active=True),
        id=company_id,
    )

    products = Product.objects.for_catalog().filter(company=company)

    metrics = _build_company_metrics(company)

    return render(
        request,
        "users/company_profile.html",
        {
            "company": company,
            "products": products,
            "products_count": products.count(),
            **metrics,
        },
    )


@login_required
def create_review(request, agreement_id):
    try:
        review_target = get_review_target(
            agreement_id=agreement_id,
            actor=request.user,
        )
    except ReviewAccessError:
        return redirect("chat_list")

    if Review.objects.filter(
        agreement=review_target.agreement,
        author=request.user,
    ).exists():
        return redirect(
            "chat_detail",
            conversation_id=review_target.agreement.conversation_id,
        )

    if request.method == "POST":
        form = ReviewForm(request.POST)
        if form.is_valid():
            try:
                create_review_service(
                    agreement_id=agreement_id,
                    actor=request.user,
                    rating=form.cleaned_data["rating"],
                    text=form.cleaned_data["text"],
                )
            except ReviewAlreadyExistsError:
                messages.info(request, "Отзыв по этой сделке уже оставлен.")
                return redirect(
                    "chat_detail",
                    conversation_id=review_target.agreement.conversation_id,
                )
            except ReviewAccessError:
                form.add_error(None, "Не удалось сохранить отзыв.")
            else:
                return redirect(
                    "company_profile",
                    company_id=review_target.company.id,
                )
    else:
        form = ReviewForm()

    return render(
        request,
        "users/review_form.html",
        {
            "form": form,
            "agreement": review_target.agreement,
            "target_company": review_target.company,
        },
    )


def verify_email(request):
    pending = _get_pending_verification(request)
    if not pending:
        messages.info(
            request, "Сначала зарегистрируйте аккаунт или запросите новый код."
        )
        return redirect("register")

    user, verification = pending
    error = None

    if request.method == "POST":
        if verification.expires_at <= timezone.now():
            error = "Срок действия кода истёк. Запросите новый код."
        elif verification.attempts >= EMAIL_VERIFICATION_MAX_ATTEMPTS:
            error = "Превышено число попыток. Запросите новый код."
        else:
            code = request.POST.get("code", "").strip()
            if check_password(code, verification.code):
                with transaction.atomic():
                    verification.verified = True
                    verification.save(update_fields=["verified"])
                    user.is_active = True
                    user.save(update_fields=["is_active"])

                request.session.pop("verify_user_id", None)
                login(request, user)
                return redirect("dashboard")

            verification.attempts += 1
            verification.save(update_fields=["attempts"])
            error = "Неверный код."

    return render(request, "users/verify_email.html", {"error": error})


@require_POST
def resend_verification(request):
    pending = _get_pending_verification(request)
    if not pending:
        messages.info(
            request, "Сессия подтверждения истекла. Зарегистрируйтесь ещё раз."
        )
        return redirect("register")

    user, verification = pending
    if timezone.now() - verification.last_sent_at < timedelta(
        seconds=EMAIL_RESEND_COOLDOWN_SECONDS,
    ):
        messages.info(request, "Новый код можно запросить через минуту.")
        return redirect("verify_email")

    _, code = _issue_email_verification(user, verification)
    try:
        _send_verification_email(user, code)
    except Exception:
        logger.exception("Unable to resend verification email for user %s", user.id)
        messages.error(request, "Не удалось отправить письмо. Попробуйте позже.")
    else:
        messages.success(request, "Новый код подтверждения отправлен на вашу почту.")
    return redirect("verify_email")


@login_required
def show_analytics(request):
    company = _get_current_company(request)
    return render(
        request,
        "users/analytics.html",
        build_analytics(company),
    )
