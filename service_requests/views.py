from functools import wraps
from mimetypes import guess_type
from statistics import mean, median

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Q
from django.http import FileResponse
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .forms import (
    AdminFeedbackFilterForm,
    AdminRequestFilterForm,
    CitizenFeedbackForm,
    FeedbackReviewForm,
    ImprovementActionFilterForm,
    ImprovementActionForm,
    ServiceRequestForm,
)
from .models import (
    FeedbackReviewStatus,
    ImprovementAction,
    ImprovementActionStatus,
    RequestCategory,
    RequestStatus,
    ServiceRequest,
    ServiceRequestFeedback,
    ServiceRequestFeedbackEvent,
)
from .services import (
    save_improvement_action,
    transition_request_status,
    update_feedback_review,
)


class CustomLoginView(LoginView):
    template_name = 'registration/login.html'
    redirect_authenticated_user = True

    def get_success_url(self):
        if self.request.user.is_staff:
            return reverse_lazy('admin_dashboard')
        return super().get_success_url()


class CustomLogoutView(LogoutView):
    next_page = reverse_lazy('login')


def _set_form_accessibility(form):
    for field_name, field in form.fields.items():
        bound_field = form[field_name]
        described_by = field.widget.attrs.get('aria-describedby', '').split()

        if bound_field.help_text:
            described_by.append(f'{bound_field.auto_id}_helptext')
        if bound_field.errors:
            described_by.append(f'{bound_field.auto_id}_errors')
            field.widget.attrs['aria-invalid'] = 'true'

        if described_by:
            field.widget.attrs['aria-describedby'] = ' '.join(dict.fromkeys(described_by))


def staff_only(view_func):
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not request.user.is_staff:
            raise PermissionDenied('Only staff members can access the admin dashboard.')
        return view_func(request, *args, **kwargs)

    return wrapped_view


def register(request):
    if request.user.is_authenticated:
        return redirect('admin_dashboard' if request.user.is_staff else 'request_list')

    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Your account was created successfully.')
            return redirect('request_list')
    else:
        form = UserCreationForm()
    _set_form_accessibility(form)
    return render(request, 'service_requests/register.html', {'form': form})


def landing(request):
    category_details = {
        RequestCategory.WATER_SUPPLY: ('bi-droplet', 'Leaks, interruptions and other water access concerns.'),
        RequestCategory.BROKEN_STREETLIGHT: ('bi-lightbulb', 'Streetlights that are damaged or not working.'),
        RequestCategory.GARBAGE_COLLECTION: ('bi-trash3', 'Missed collections and overflowing public bins.'),
        RequestCategory.ROAD_DAMAGE: ('bi-sign-turn-right', 'Potholes and damaged public roads.'),
        RequestCategory.DRAINAGE: ('bi-water', 'Blocked drains and local flooding concerns.'),
        RequestCategory.OTHER: ('bi-three-dots', 'Other public services and infrastructure issues.'),
    }
    category_cards = [
        {
            'value': value,
            'label': label,
            'icon': category_details[value][0],
            'description': category_details[value][1],
        }
        for value, label in RequestCategory.choices
    ]
    status_counts = {
        item['status']: item['count']
        for item in ServiceRequest.objects.values('status').annotate(count=Count('pk'))
    }
    request_total = ServiceRequest.objects.count()
    landing_stats = [
        {'label': 'Requests received', 'value': request_total},
        {'label': 'Pending', 'value': status_counts.get(RequestStatus.PENDING, 0)},
        {'label': 'In progress', 'value': status_counts.get(RequestStatus.IN_PROGRESS, 0)},
        {'label': 'Resolved', 'value': status_counts.get(RequestStatus.RESOLVED, 0)},
        {'label': 'Available services', 'value': len(category_cards)},
    ]
    return render(
        request,
        'service_requests/landing.html',
        {
            'category_cards': category_cards,
            'category_count': len(category_cards),
            'landing_stats': landing_stats,
            'has_request_stats': request_total > 0,
        },
    )


@login_required
def request_list(request):
    if request.user.is_staff:
        return redirect('admin_dashboard')

    category = request.GET.get('category')
    status = request.GET.get('status')
    search = request.GET.get('search', '').strip()
    citizen_requests = ServiceRequest.objects.filter(citizen=request.user)
    queryset = citizen_requests.select_related('citizen')

    if search:
        queryset = queryset.filter(
            Q(reference_number__icontains=search)
            | Q(location__icontains=search)
            | Q(description__icontains=search)
        )
    if category:
        queryset = queryset.filter(category=category)
    if status:
        queryset = queryset.filter(status=status)

    status_counts = {
        entry['status']: entry['count']
        for entry in citizen_requests.values('status').annotate(count=Count('status'))
    }

    paginator = Paginator(queryset.order_by('-created_at'), 8)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        'service_requests/request_list.html',
        {
            'requests': page_obj,
            'page_obj': page_obj,
            'category': category,
            'status': status,
            'search': search,
            'total_cases': citizen_requests.count(),
            'pending_cases': status_counts.get(RequestStatus.PENDING, 0),
            'in_progress_cases': status_counts.get(RequestStatus.IN_PROGRESS, 0),
            'resolved_cases': status_counts.get(RequestStatus.RESOLVED, 0),
            'categories': [choice for choice in ServiceRequest._meta.get_field('category').choices],
            'statuses': [choice for choice in ServiceRequest._meta.get_field('status').choices],
        },
    )


@login_required
def create_request(request):
    if request.user.is_staff:
        return redirect('admin_dashboard')

    if request.method == 'POST':
        form = ServiceRequestForm(request.POST, request.FILES)
        if form.is_valid():
            service_request = form.save(commit=False)
            service_request.citizen = request.user
            service_request.save()
            messages.success(request, 'Your service request has been submitted successfully.')
            return redirect('request_detail', pk=service_request.pk)
    else:
        selected_category = request.GET.get('category')
        initial = {'category': selected_category} if selected_category in RequestCategory.values else None
        form = ServiceRequestForm(initial=initial)
    _set_form_accessibility(form)
    return render(request, 'service_requests/request_form.html', {'form': form})


@login_required
def request_detail(request, pk):
    if request.user.is_staff:
        service_request = get_object_or_404(ServiceRequest.objects.select_related('citizen'), pk=pk)
    else:
        service_request = get_object_or_404(
            ServiceRequest.objects.select_related('citizen'),
            pk=pk,
            citizen=request.user,
        )

    feedback = ServiceRequestFeedback.objects.filter(service_request=service_request).first()
    feedback_form = None
    can_submit_feedback = not request.user.is_staff and service_request.status == RequestStatus.RESOLVED
    if request.method == 'POST' and not request.user.is_staff:
        if request.POST.get('action') != 'submit_feedback':
            raise PermissionDenied('Citizens cannot update service statuses.')
        if service_request.status != RequestStatus.RESOLVED:
            raise PermissionDenied('Feedback can only be submitted for resolved requests.')
        feedback_form = CitizenFeedbackForm(request.POST, instance=feedback)
        if feedback_form.is_valid():
            try:
                with transaction.atomic():
                    saved_feedback = feedback_form.save(commit=False)
                    saved_feedback.service_request = service_request
                    saved_feedback.citizen = request.user
                    saved_feedback.save()
                    ServiceRequestFeedbackEvent.objects.create(
                        feedback=saved_feedback,
                        actor=request.user,
                        event_type=(
                            ServiceRequestFeedbackEvent.EventType.CITIZEN_EDITED
                            if feedback
                            else ServiceRequestFeedbackEvent.EventType.CITIZEN_SUBMITTED
                        ),
                        summary='Citizen updated their service feedback.' if feedback else 'Citizen submitted service feedback.',
                    )
            except IntegrityError:
                messages.error(request, 'Feedback has already been submitted for this request. Refresh the page to edit it.')
            else:
                messages.success(request, 'Thank you. Your service feedback has been saved.')
                return redirect('request_detail', pk=service_request.pk)
        _set_form_accessibility(feedback_form)
    elif request.method == 'POST':
        next_status = request.POST.get('status')
        try:
            status_event = transition_request_status(service_request, next_status, request.user)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            if status_event:
                messages.success(request, 'Status updated successfully.')
            else:
                messages.info(request, 'The request already has that status.')

        return redirect('request_detail', pk=service_request.pk)
    elif can_submit_feedback:
        feedback_form = CitizenFeedbackForm(instance=feedback)
        _set_form_accessibility(feedback_form)

    current_step = next(
        (index for index, (value, _) in enumerate(RequestStatus.choices) if value == service_request.status),
        0,
    )
    status_steps = [
        {
            'label': label,
            'state': 'complete' if index < current_step else 'current' if index == current_step else 'upcoming',
        }
        for index, (_, label) in enumerate(RequestStatus.choices)
    ]

    return render(
        request,
        'service_requests/request_detail.html',
        {
            'request_detail': service_request,
            'status_choices': ServiceRequest._meta.get_field('status').choices,
            'status_steps': status_steps,
            'feedback': feedback,
            'feedback_form': feedback_form,
            'can_submit_feedback': can_submit_feedback,
        },
    )


@login_required
@never_cache
@require_safe
def serve_request_image(request, image_path):
    requests_with_image = ServiceRequest.objects.filter(image=image_path)
    if not request.user.is_staff:
        requests_with_image = requests_with_image.filter(citizen=request.user)

    service_request = get_object_or_404(requests_with_image)
    image = service_request.image
    return FileResponse(
        image.open('rb'),
        content_type=guess_type(image.name)[0] or 'application/octet-stream',
    )


@login_required
def admin_dashboard(request):
    if not request.user.is_staff:
        raise PermissionDenied('Only staff members can access the admin dashboard.')

    filter_form = AdminRequestFilterForm(request.GET or None)
    if filter_form.is_bound:
        filter_form.is_valid()
        filter_values = filter_form.cleaned_data
    else:
        filter_values = {}
    _set_form_accessibility(filter_form)
    search = filter_values.get('search', '')
    category = filter_values.get('category', '')
    status = filter_values.get('status', '')
    date_from = filter_values.get('date_from')
    date_to = filter_values.get('date_to')
    sort = filter_values.get('sort') or 'newest'

    all_requests = ServiceRequest.objects.all()
    queryset = all_requests.select_related('citizen')

    if search:
        queryset = queryset.filter(
            Q(reference_number__icontains=search)
            | Q(location__icontains=search)
            | Q(description__icontains=search)
            | Q(citizen__username__icontains=search)
        )
    if category:
        queryset = queryset.filter(category=category)
    if status:
        queryset = queryset.filter(status=status)
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)

    queryset = queryset.order_by('created_at' if sort == 'oldest' else '-created_at')
    paginator = Paginator(queryset, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    total = all_requests.count()
    status_counts = {
        item['status']: item['count']
        for item in all_requests.values('status').annotate(count=Count('status'))
    }
    pending_cases = status_counts.get(RequestStatus.PENDING, 0)
    in_progress_cases = status_counts.get(RequestStatus.IN_PROGRESS, 0)
    resolved_cases = status_counts.get(RequestStatus.RESOLVED, 0)

    status_summary = [
        {'status': value, 'label': label, 'count': status_counts.get(value, 0)}
        for value, label in RequestStatus.choices
    ]
    category_counts = {
        item['category']: item['count']
        for item in all_requests.values('category').annotate(count=Count('category'))
    }
    category_summary = [
        {'category': value, 'label': label, 'count': category_counts.get(value, 0)}
        for value, label in RequestCategory.choices
    ]

    status_labels = [item['label'] for item in status_summary]
    status_values = [item['count'] for item in status_summary]
    category_labels = [item['label'] for item in category_summary]
    category_values = [item['count'] for item in category_summary]
    recent_feedback = ServiceRequestFeedback.objects.select_related(
        'service_request'
    ).order_by('-created_at')[:5]

    return render(
        request,
        'service_requests/dashboard.html',
        {
            'requests': page_obj,
            'page_obj': page_obj,
            'total': total,
            'open_cases': pending_cases + in_progress_cases,
            'resolved_cases': resolved_cases,
            'pending_cases': pending_cases,
            'in_progress_cases': in_progress_cases,
            'status_summary': status_summary,
            'category_summary': category_summary,
            'status_labels': status_labels,
            'status_values': status_values,
            'category_labels': category_labels,
            'category_values': category_values,
            'analytics_has_data': total > 0,
            'search': search,
            'category': category,
            'status': status,
            'date_from': date_from,
            'date_to': date_to,
            'sort': sort,
            'filter_form': filter_form,
            'categories': [choice for choice in ServiceRequest._meta.get_field('category').choices],
            'statuses': [choice for choice in ServiceRequest._meta.get_field('status').choices],
            'recent_feedback': recent_feedback,
        },
    )


@login_required
@staff_only
def admin_feedback_dashboard(request):
    feedback_filter_form = AdminFeedbackFilterForm(request.GET or None)
    if feedback_filter_form.is_bound:
        feedback_filter_form.is_valid()
        filter_values = feedback_filter_form.cleaned_data
    else:
        filter_values = {}
    _set_form_accessibility(feedback_filter_form)

    search = filter_values.get('search', '')
    rating = filter_values.get('rating', '')
    category = filter_values.get('category', '')
    review_status = filter_values.get('review_status', '')
    date_from = filter_values.get('date_from')
    date_to = filter_values.get('date_to')
    sort = filter_values.get('sort') or 'newest'

    all_feedback = ServiceRequestFeedback.objects.select_related(
        'service_request',
        'citizen',
    )
    feedback_queryset = all_feedback
    if search:
        feedback_queryset = feedback_queryset.filter(
            service_request__reference_number__icontains=search
        )
    if rating:
        feedback_queryset = feedback_queryset.filter(rating=rating)
    if category:
        feedback_queryset = feedback_queryset.filter(service_request__category=category)
    if review_status:
        feedback_queryset = feedback_queryset.filter(review_status=review_status)
    if date_from:
        feedback_queryset = feedback_queryset.filter(created_at__date__gte=date_from)
    if date_to:
        feedback_queryset = feedback_queryset.filter(created_at__date__lte=date_to)
    metric_feedback = feedback_queryset.order_by()
    feedback_queryset = feedback_queryset.order_by(
        'created_at' if sort == 'oldest' else '-created_at'
    )
    page_obj = Paginator(feedback_queryset, 10).get_page(request.GET.get('page'))

    total_feedback = metric_feedback.count()
    positive_count = metric_feedback.filter(rating__gte=4).count()
    low_count = metric_feedback.filter(rating__lte=2).count()
    awaiting_review_count = metric_feedback.filter(
        review_status__in=[FeedbackReviewStatus.NEW, FeedbackReviewStatus.UNDER_REVIEW]
    ).count()
    addressed_count = metric_feedback.filter(review_status=FeedbackReviewStatus.ADDRESSED).count()
    suggestions_count = metric_feedback.exclude(suggestion='').count()
    suggestion_categories = list(
        metric_feedback.exclude(suggestion_category='')
        .values('suggestion_category')
        .annotate(count=Count('pk'))
        .order_by('-count', 'suggestion_category')
    )
    suggestion_category_labels = dict(ServiceRequestFeedback._meta.get_field('suggestion_category').choices)
    for item in suggestion_categories:
        item['label'] = suggestion_category_labels[item['suggestion_category']]
    average_rating = metric_feedback.aggregate(value=Avg('rating'))['value']
    eligible_requests = ServiceRequest.objects.filter(status=RequestStatus.RESOLVED)
    if category:
        eligible_requests = eligible_requests.filter(category=category)
    if date_from:
        eligible_requests = eligible_requests.filter(resolved_at__date__gte=date_from)
    if date_to:
        eligible_requests = eligible_requests.filter(resolved_at__date__lte=date_to)
    if search:
        eligible_requests = eligible_requests.filter(reference_number__icontains=search)
    eligible_without_feedback = eligible_requests.filter(feedback__isnull=True).count()

    distribution_counts = {
        item['rating']: item['count']
        for item in metric_feedback.values('rating').annotate(count=Count('pk'))
    }
    rating_distribution = [
        {
            'rating': value,
            'label': label,
            'count': distribution_counts.get(value, 0),
            'percentage': round(distribution_counts.get(value, 0) * 100 / total_feedback) if total_feedback else 0,
        }
        for value, label in ServiceRequestFeedback._meta.get_field('rating').choices
    ]
    category_ratings = list(
        metric_feedback.values('service_request__category')
        .annotate(count=Count('pk'), average=Avg('rating'))
        .order_by('service_request__category')
    )
    category_labels = dict(RequestCategory.choices)
    for item in category_ratings:
        item['label'] = category_labels[item['service_request__category']]
    timed_requests = ServiceRequest.objects.all()
    if category:
        timed_requests = timed_requests.filter(category=category)
    if date_from:
        timed_requests = timed_requests.filter(created_at__date__gte=date_from)
    if date_to:
        timed_requests = timed_requests.filter(created_at__date__lte=date_to)
    if search:
        timed_requests = timed_requests.filter(reference_number__icontains=search)
    if rating or review_status:
        timed_requests = timed_requests.filter(pk__in=metric_feedback.values('service_request_id'))

    response_by_category = {}
    for service_category, created_at, first_response_at in timed_requests.filter(
        first_response_at__isnull=False
    ).values_list('category', 'created_at', 'first_response_at'):
        if first_response_at >= created_at:
            response_by_category.setdefault(service_category, []).append(
                (first_response_at - created_at).total_seconds() / 3600
            )
    resolution_by_category = {}
    for service_category, created_at, resolved_at in timed_requests.filter(
        status=RequestStatus.RESOLVED,
        resolved_at__isnull=False,
    ).values_list('category', 'created_at', 'resolved_at'):
        if resolved_at >= created_at:
            resolution_by_category.setdefault(service_category, []).append(
                (resolved_at - created_at).total_seconds() / 3600
            )
    response_hours = [
        hours for durations in response_by_category.values() for hours in durations
    ]
    resolution_hours = [
        hours for durations in resolution_by_category.values() for hours in durations
    ]
    timing_by_category = [
        {
            'label': label,
            'response_average': mean(response_by_category[value]) if response_by_category.get(value) else None,
            'resolution_average': mean(resolution_by_category[value]) if resolution_by_category.get(value) else None,
        }
        for value, label in RequestCategory.choices
        if value in response_by_category or value in resolution_by_category
    ]
    monthly_timings = {}
    for created_at, first_response_at, resolved_at, request_status in timed_requests.values_list(
        'created_at',
        'first_response_at',
        'resolved_at',
        'status',
    ):
        month = created_at.date().replace(day=1)
        item = monthly_timings.setdefault(
            month,
            {
                'month': month,
                'request_count': 0,
                'feedback_count': 0,
                'response_hours': [],
                'resolution_hours': [],
            },
        )
        item['request_count'] += 1
        if first_response_at and first_response_at >= created_at:
            item['response_hours'].append(
                (first_response_at - created_at).total_seconds() / 3600
            )
        if (
            request_status == RequestStatus.RESOLVED
            and resolved_at
            and resolved_at >= created_at
        ):
            item['resolution_hours'].append(
                (resolved_at - created_at).total_seconds() / 3600
            )
    for created_at in metric_feedback.values_list('created_at', flat=True):
        month = created_at.date().replace(day=1)
        item = monthly_timings.setdefault(
            month,
            {
                'month': month,
                'request_count': 0,
                'feedback_count': 0,
                'response_hours': [],
                'resolution_hours': [],
            },
        )
        item['feedback_count'] += 1
    monthly_trends = [
        {
            'month': item['month'],
            'request_count': item['request_count'],
            'feedback_count': item['feedback_count'],
            'response_average': mean(item['response_hours']) if item['response_hours'] else None,
            'resolution_average': mean(item['resolution_hours']) if item['resolution_hours'] else None,
        }
        for item in sorted(monthly_timings.values(), key=lambda trend: trend['month'])
    ]
    unresolved_count = timed_requests.exclude(status=RequestStatus.RESOLVED).count()
    overdue_action_count = ImprovementAction.objects.filter(
        target_date__lt=timezone.localdate(),
        status__in=[
            ImprovementActionStatus.PROPOSED,
            ImprovementActionStatus.APPROVED,
            ImprovementActionStatus.IN_PROGRESS,
        ],
    ).count()

    return render(
        request,
        'service_requests/feedback_dashboard.html',
        {
            'feedback_filter_form': feedback_filter_form,
            'page_obj': page_obj,
            'feedback_records': page_obj,
            'total_feedback': total_feedback,
            'average_rating': average_rating,
            'positive_count': positive_count,
            'positive_percentage': round(positive_count * 100 / total_feedback) if total_feedback else 0,
            'low_count': low_count,
            'low_percentage': round(low_count * 100 / total_feedback) if total_feedback else 0,
            'suggestions_count': suggestions_count,
            'suggestion_categories': suggestion_categories,
            'awaiting_review_count': awaiting_review_count,
            'addressed_count': addressed_count,
            'eligible_without_feedback': eligible_without_feedback,
            'rating_distribution': rating_distribution,
            'category_ratings': category_ratings,
            'timing_by_category': timing_by_category,
            'monthly_trends': monthly_trends,
            'average_response_hours': mean(response_hours) if response_hours else None,
            'median_response_hours': median(response_hours) if response_hours else None,
            'response_sample_count': len(response_hours),
            'average_resolution_hours': mean(resolution_hours) if resolution_hours else None,
            'median_resolution_hours': median(resolution_hours) if resolution_hours else None,
            'resolution_sample_count': len(resolution_hours),
            'unresolved_count': unresolved_count,
            'overdue_action_count': overdue_action_count,
            'search': search,
            'rating': rating,
            'category': category,
            'review_status': review_status,
            'date_from': date_from,
            'date_to': date_to,
            'sort': sort,
        },
    )


@login_required
@staff_only
def admin_feedback_detail(request, pk):
    feedback = get_object_or_404(
        ServiceRequestFeedback.objects.select_related(
            'service_request',
            'citizen',
            'reviewed_by',
        ).prefetch_related('events__actor'),
        pk=pk,
    )
    if request.method == 'POST':
        form = FeedbackReviewForm(request.POST, instance=feedback)
        if form.is_valid():
            try:
                updated_feedback = update_feedback_review(
                    feedback,
                    form.cleaned_data,
                    request.user,
                )
            except ValidationError as error:
                form.add_error('review_status', error.messages[0])
            else:
                messages.success(request, 'Feedback review has been updated.')
                return redirect('admin_feedback_detail', pk=updated_feedback.pk)
    else:
        form = FeedbackReviewForm(
            instance=feedback,
            initial={'publish_response': feedback.response_published_at is not None},
        )
    _set_form_accessibility(form)
    return render(
        request,
        'service_requests/feedback_detail.html',
        {'feedback': feedback, 'form': form},
    )


@login_required
@staff_only
def admin_improvement_list(request):
    filter_form = ImprovementActionFilterForm(request.GET or None)
    if filter_form.is_bound:
        filter_form.is_valid()
        values = filter_form.cleaned_data
    else:
        values = {}
    _set_form_accessibility(filter_form)

    actions = ImprovementAction.objects.select_related(
        'responsible_officer',
        'created_by',
        'updated_by',
    ).prefetch_related('related_feedback__service_request')
    search = values.get('search', '')
    priority = values.get('priority', '')
    status = values.get('status', '')
    owner = values.get('owner')
    due_before = values.get('due_before')
    overdue_only = values.get('overdue_only', False)
    if search:
        actions = actions.filter(Q(title__icontains=search) | Q(issue_description__icontains=search))
    if priority:
        actions = actions.filter(priority=priority)
    if status:
        actions = actions.filter(status=status)
    if owner:
        actions = actions.filter(responsible_officer=owner)
    if due_before:
        actions = actions.filter(target_date__lte=due_before)
    if overdue_only:
        actions = actions.filter(
            target_date__lt=timezone.localdate(),
            status__in=[
                ImprovementActionStatus.PROPOSED,
                ImprovementActionStatus.APPROVED,
                ImprovementActionStatus.IN_PROGRESS,
            ],
        )

    page_obj = Paginator(actions.order_by('target_date', '-created_at'), 10).get_page(
        request.GET.get('page')
    )
    return render(
        request,
        'service_requests/improvement_list.html',
        {
            'filter_form': filter_form,
            'page_obj': page_obj,
            'actions': page_obj,
            'today': timezone.localdate(),
            'overdue_action_count': ImprovementAction.objects.filter(
                target_date__lt=timezone.localdate(),
                status__in=[
                    ImprovementActionStatus.PROPOSED,
                    ImprovementActionStatus.APPROVED,
                    ImprovementActionStatus.IN_PROGRESS,
                ],
            ).count(),
            'search': search,
            'priority': priority,
            'status': status,
            'owner': owner,
            'due_before': due_before,
            'overdue_only': overdue_only,
        },
    )


@login_required
@staff_only
def admin_improvement_create(request):
    if request.method == 'POST':
        form = ImprovementActionForm(request.POST)
        if form.is_valid():
            try:
                action = save_improvement_action(form.save(commit=False), form.cleaned_data, request.user)
            except ValidationError as error:
                form.add_error('status', error.messages[0])
            else:
                messages.success(request, 'Improvement action created.')
                return redirect('admin_improvement_detail', pk=action.pk)
    else:
        form = ImprovementActionForm(initial={'status': ImprovementActionStatus.PROPOSED})
    _set_form_accessibility(form)
    return render(request, 'service_requests/improvement_form.html', {'form': form, 'is_new': True})


@login_required
@staff_only
def admin_improvement_detail(request, pk):
    action = get_object_or_404(
        ImprovementAction.objects.prefetch_related('related_feedback__service_request'),
        pk=pk,
    )
    if request.method == 'POST':
        form = ImprovementActionForm(request.POST, instance=action)
        if form.is_valid():
            try:
                updated_action = save_improvement_action(
                    form.save(commit=False),
                    form.cleaned_data,
                    request.user,
                )
            except ValidationError as error:
                form.add_error('status', error.messages[0])
            else:
                messages.success(request, 'Improvement action updated.')
                return redirect('admin_improvement_detail', pk=updated_action.pk)
    else:
        form = ImprovementActionForm(instance=action)
    _set_form_accessibility(form)
    return render(
        request,
        'service_requests/improvement_form.html',
        {'form': form, 'action': action, 'is_new': False},
    )
