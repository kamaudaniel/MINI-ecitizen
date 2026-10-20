import os
import secrets

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class RequestCategory(models.TextChoices):
    WATER_SUPPLY = 'water_supply', 'Water Supply'
    BROKEN_STREETLIGHT = 'broken_streetlight', 'Broken Streetlight'
    GARBAGE_COLLECTION = 'garbage_collection', 'Garbage Collection'
    ROAD_DAMAGE = 'road_damage', 'Road Damage'
    DRAINAGE = 'drainage', 'Drainage'
    OTHER = 'other', 'Other'


class RequestStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    IN_PROGRESS = 'in_progress', 'In Progress'
    RESOLVED = 'resolved', 'Resolved'


class FeedbackReviewStatus(models.TextChoices):
    NEW = 'new', 'New'
    UNDER_REVIEW = 'under_review', 'Under Review'
    ACTION_PLANNED = 'action_planned', 'Action Planned'
    ADDRESSED = 'addressed', 'Addressed'
    CLOSED = 'closed', 'Closed'


class FeedbackSuggestionCategory(models.TextChoices):
    COMMUNICATION = 'communication', 'Communication'
    PROCESSING_SPEED = 'processing_speed', 'Processing speed'
    STAFF_RESPONSIVENESS = 'staff_responsiveness', 'Staff responsiveness'
    INSTRUCTIONS = 'instructions', 'Clarity of instructions'
    ACCESSIBILITY = 'accessibility', 'Accessibility'
    SUBMISSION = 'submission', 'Ease of submitting a request'
    OTHER = 'other', 'Other'


def request_image_upload_path(instance, filename):
    timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
    safe_name = f"{timestamp}_{secrets.token_hex(4)}_{os.path.basename(filename)}"
    return os.path.join('request_images', safe_name)


class ServiceRequest(models.Model):
    citizen = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='service_requests',
        verbose_name='Citizen'
    )
    reference_number = models.CharField(max_length=20, unique=True, editable=False)
    category = models.CharField(max_length=40, choices=RequestCategory.choices, default=RequestCategory.OTHER)
    location = models.CharField(max_length=255)
    description = models.TextField()
    image = models.ImageField(upload_to=request_image_upload_path, blank=True, null=True)
    status = models.CharField(max_length=20, choices=RequestStatus.choices, default=RequestStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    first_response_at = models.DateTimeField(blank=True, null=True)
    resolved_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Service Request'
        verbose_name_plural = 'Service Requests'

    def save(self, *args, **kwargs):
        if not self.reference_number:
            prefix = 'SR'
            random_part = secrets.token_hex(4).upper()
            self.reference_number = f'{prefix}-{random_part}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.reference_number} - {self.get_category_display()}'


class ServiceRequestStatusEvent(models.Model):
    service_request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name='status_events',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='service_request_status_events',
        blank=True,
        null=True,
    )
    previous_status = models.CharField(max_length=20, choices=RequestStatus.choices)
    new_status = models.CharField(max_length=20, choices=RequestStatus.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.service_request.reference_number}: {self.previous_status} -> {self.new_status}'


class ServiceRequestFeedback(models.Model):
    service_request = models.OneToOneField(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name='feedback',
    )
    citizen = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='submitted_service_feedback',
    )
    rating = models.PositiveSmallIntegerField(
        choices=[
            (1, '1 star - Very poor'),
            (2, '2 stars - Poor'),
            (3, '3 stars - Fair'),
            (4, '4 stars - Good'),
            (5, '5 stars - Excellent'),
        ],
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    comment = models.CharField(max_length=2000, blank=True)
    suggestion_category = models.CharField(
        max_length=32,
        choices=FeedbackSuggestionCategory.choices,
        blank=True,
    )
    suggestion = models.CharField(max_length=2000, blank=True)
    review_status = models.CharField(
        max_length=20,
        choices=FeedbackReviewStatus.choices,
        default=FeedbackReviewStatus.NEW,
    )
    internal_note = models.CharField(max_length=3000, blank=True)
    planned_action = models.CharField(max_length=2000, blank=True)
    admin_response = models.CharField(max_length=2000, blank=True)
    response_published_at = models.DateTimeField(blank=True, null=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='reviewed_service_feedback',
        blank=True,
        null=True,
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    action_completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Service Request Feedback'
        verbose_name_plural = 'Service Request Feedback'
        constraints = [
            models.CheckConstraint(
                check=Q(rating__gte=1) & Q(rating__lte=5),
                name='service_feedback_rating_1_to_5',
            ),
        ]

    def __str__(self):
        return f'{self.service_request.reference_number} - {self.rating}/5'


class ServiceRequestFeedbackEvent(models.Model):
    class EventType(models.TextChoices):
        CITIZEN_SUBMITTED = 'citizen_submitted', 'Citizen feedback submitted'
        CITIZEN_EDITED = 'citizen_edited', 'Citizen feedback edited'
        STATUS_CHANGED = 'status_changed', 'Review status changed'
        NOTE_UPDATED = 'note_updated', 'Internal note updated'
        ACTION_UPDATED = 'action_updated', 'Planned action updated'
        RESPONSE_PUBLISHED = 'response_published', 'Citizen response published'
        RESPONSE_UPDATED = 'response_updated', 'Administrative response updated'
        RESPONSE_UNPUBLISHED = 'response_unpublished', 'Citizen response unpublished'

    feedback = models.ForeignKey(
        ServiceRequestFeedback,
        on_delete=models.CASCADE,
        related_name='events',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='service_feedback_events',
        blank=True,
        null=True,
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    previous_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20, blank=True)
    summary = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.feedback.service_request.reference_number} - {self.get_event_type_display()}'


class ImprovementActionPriority(models.TextChoices):
    LOW = 'low', 'Low'
    MEDIUM = 'medium', 'Medium'
    HIGH = 'high', 'High'


class ImprovementActionStatus(models.TextChoices):
    PROPOSED = 'proposed', 'Proposed'
    APPROVED = 'approved', 'Approved'
    IN_PROGRESS = 'in_progress', 'In Progress'
    COMPLETED = 'completed', 'Completed'
    DEFERRED = 'deferred', 'Deferred'


class ImprovementAction(models.Model):
    title = models.CharField(max_length=200)
    issue_description = models.TextField(max_length=3000)
    related_feedback = models.ManyToManyField(
        ServiceRequestFeedback,
        related_name='improvement_actions',
    )
    responsible_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='assigned_improvement_actions',
        blank=True,
        null=True,
    )
    priority = models.CharField(
        max_length=10,
        choices=ImprovementActionPriority.choices,
        default=ImprovementActionPriority.MEDIUM,
    )
    planned_action = models.TextField(max_length=3000)
    target_date = models.DateField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=ImprovementActionStatus.choices,
        default=ImprovementActionStatus.PROPOSED,
    )
    completed_at = models.DateTimeField(blank=True, null=True)
    admin_note = models.TextField(max_length=3000, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='created_improvement_actions',
        blank=True,
        null=True,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='updated_improvement_actions',
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['target_date', '-created_at']
        indexes = [
            models.Index(fields=['status', 'target_date']),
            models.Index(fields=['priority', 'status']),
        ]

    def __str__(self):
        return self.title
