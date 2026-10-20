from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import RequestStatus, ServiceRequest, ServiceRequestStatusEvent


ALLOWED_REQUEST_STATUS_TRANSITIONS = {
    RequestStatus.PENDING: {RequestStatus.IN_PROGRESS, RequestStatus.RESOLVED},
    RequestStatus.IN_PROGRESS: {RequestStatus.PENDING, RequestStatus.RESOLVED},
    RequestStatus.RESOLVED: {RequestStatus.IN_PROGRESS},
}


@transaction.atomic
def transition_request_status(service_request, new_status, actor):
    if new_status not in RequestStatus.values:
        raise ValidationError('Choose a valid request status.')

    previous_status = service_request.status
    if new_status == previous_status:
        return None
    if new_status not in ALLOWED_REQUEST_STATUS_TRANSITIONS.get(previous_status, set()):
        raise ValidationError(
            f'{RequestStatus(previous_status).label} cannot transition to '
            f'{RequestStatus(new_status).label}.'
        )

    now = timezone.now()
    update_fields = ['status', 'updated_at']
    service_request.status = new_status

    if previous_status == RequestStatus.PENDING and service_request.first_response_at is None:
        service_request.first_response_at = now
        update_fields.append('first_response_at')

    if new_status == RequestStatus.RESOLVED:
        service_request.resolved_at = now
        update_fields.append('resolved_at')
    elif previous_status == RequestStatus.RESOLVED:
        service_request.resolved_at = None
        update_fields.append('resolved_at')

    service_request.save(update_fields=update_fields)
    return ServiceRequestStatusEvent.objects.create(
        service_request=service_request,
        actor=actor,
        previous_status=previous_status,
        new_status=new_status,
    )


ALLOWED_FEEDBACK_STATUS_TRANSITIONS = {
    'new': {'under_review', 'closed'},
    'under_review': {'action_planned', 'addressed', 'closed'},
    'action_planned': {'under_review', 'addressed', 'closed'},
    'addressed': {'under_review', 'closed'},
    'closed': {'under_review'},
}


@transaction.atomic
def update_feedback_review(feedback, cleaned_data, actor):
    from .models import FeedbackReviewStatus, ServiceRequestFeedback, ServiceRequestFeedbackEvent

    feedback = ServiceRequestFeedback.objects.select_for_update().get(pk=feedback.pk)
    previous_status = feedback.review_status
    new_status = cleaned_data['review_status']
    if new_status != previous_status and new_status not in ALLOWED_FEEDBACK_STATUS_TRANSITIONS[previous_status]:
        raise ValidationError(
            f'{FeedbackReviewStatus(previous_status).label} cannot transition to '
            f'{FeedbackReviewStatus(new_status).label}.'
        )

    previous_note = feedback.internal_note
    previous_action = feedback.planned_action
    previous_response = feedback.admin_response
    previous_published_at = feedback.response_published_at

    feedback.review_status = new_status
    feedback.internal_note = cleaned_data['internal_note']
    feedback.planned_action = cleaned_data['planned_action']
    feedback.admin_response = cleaned_data['admin_response']
    feedback.reviewed_by = actor
    feedback.reviewed_at = timezone.now()

    if new_status == FeedbackReviewStatus.ADDRESSED:
        feedback.action_completed_at = feedback.action_completed_at or timezone.now()
    elif new_status != FeedbackReviewStatus.CLOSED:
        feedback.action_completed_at = None

    if cleaned_data['publish_response']:
        feedback.response_published_at = feedback.response_published_at or timezone.now()
    else:
        feedback.response_published_at = None

    feedback.save()
    events = []
    if previous_status != new_status:
        events.append(ServiceRequestFeedbackEvent(
            feedback=feedback,
            actor=actor,
            event_type=ServiceRequestFeedbackEvent.EventType.STATUS_CHANGED,
            previous_status=previous_status,
            new_status=new_status,
            summary=f'Review status changed to {feedback.get_review_status_display()}.',
        ))
    if previous_note != feedback.internal_note:
        events.append(ServiceRequestFeedbackEvent(
            feedback=feedback,
            actor=actor,
            event_type=ServiceRequestFeedbackEvent.EventType.NOTE_UPDATED,
            summary='Internal review note updated.',
        ))
    if previous_action != feedback.planned_action:
        events.append(ServiceRequestFeedbackEvent(
            feedback=feedback,
            actor=actor,
            event_type=ServiceRequestFeedbackEvent.EventType.ACTION_UPDATED,
            summary='Planned corrective action updated.',
        ))
    if previous_response != feedback.admin_response:
        events.append(ServiceRequestFeedbackEvent(
            feedback=feedback,
            actor=actor,
            event_type=ServiceRequestFeedbackEvent.EventType.RESPONSE_UPDATED,
            summary='Administrative response text updated.',
        ))
    if previous_published_at is None and feedback.response_published_at is not None:
        events.append(ServiceRequestFeedbackEvent(
            feedback=feedback,
            actor=actor,
            event_type=ServiceRequestFeedbackEvent.EventType.RESPONSE_PUBLISHED,
            summary='Administrative response published to the citizen.',
        ))
    elif previous_published_at is not None and feedback.response_published_at is None:
        events.append(ServiceRequestFeedbackEvent(
            feedback=feedback,
            actor=actor,
            event_type=ServiceRequestFeedbackEvent.EventType.RESPONSE_UNPUBLISHED,
            summary='Administrative response unpublished.',
        ))
    ServiceRequestFeedbackEvent.objects.bulk_create(events)
    return feedback


ALLOWED_IMPROVEMENT_STATUS_TRANSITIONS = {
    'proposed': {'approved', 'deferred'},
    'approved': {'in_progress', 'deferred'},
    'in_progress': {'completed', 'deferred'},
    'completed': {'in_progress'},
    'deferred': {'proposed', 'approved'},
}


@transaction.atomic
def save_improvement_action(action, cleaned_data, actor):
    from .models import ImprovementAction, ImprovementActionStatus

    is_new = action.pk is None
    if is_new:
        if cleaned_data['status'] != ImprovementActionStatus.PROPOSED:
            raise ValidationError('New improvement actions must start as Proposed.')
    else:
        action = ImprovementAction.objects.select_for_update().get(pk=action.pk)
        if (
            cleaned_data['status'] != action.status
            and cleaned_data['status'] not in ALLOWED_IMPROVEMENT_STATUS_TRANSITIONS[action.status]
        ):
            raise ValidationError(
                f'{ImprovementActionStatus(action.status).label} cannot transition to '
                f'{ImprovementActionStatus(cleaned_data["status"]).label}.'
            )

    previous_status = action.status
    action.title = cleaned_data['title']
    action.issue_description = cleaned_data['issue_description']
    action.responsible_officer = cleaned_data['responsible_officer']
    action.priority = cleaned_data['priority']
    action.planned_action = cleaned_data['planned_action']
    action.target_date = cleaned_data['target_date']
    action.status = cleaned_data['status']
    action.admin_note = cleaned_data['admin_note']
    action.updated_by = actor
    if is_new:
        action.created_by = actor
    if action.status == ImprovementActionStatus.COMPLETED:
        action.completed_at = action.completed_at or timezone.now()
    elif previous_status == ImprovementActionStatus.COMPLETED:
        action.completed_at = None
    action.save()
    action.related_feedback.set(cleaned_data['related_feedback'])
    return action