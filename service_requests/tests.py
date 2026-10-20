import io
from datetime import timedelta
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .forms import MAX_IMAGE_SIZE, ServiceRequestForm
from .models import (
    FeedbackReviewStatus,
    FeedbackSuggestionCategory,
    ImprovementAction,
    ImprovementActionPriority,
    ImprovementActionStatus,
    RequestCategory,
    RequestStatus,
    ServiceRequest,
    ServiceRequestFeedback,
    ServiceRequestFeedbackEvent,
)


class ServiceRequestFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='citizen',
            email='citizen@example.com',
            password='StrongPass123!'
        )
        self.staff_user = get_user_model().objects.create_user(
            username='staff',
            email='staff@example.com',
            password='StrongPass123!',
            is_staff=True,
        )

    def test_registration_page_is_available(self):
        response = self.client.get(reverse('register'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-toggle-password')

    def test_login_page_includes_password_visibility_control(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-toggle-password')

    def test_empty_citizen_dashboard_prompts_for_a_report(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('request_list'))

        self.assertContains(response, 'You have not reported an issue yet')
        self.assertContains(response, 'Report an Issue')
        self.assertContains(response, 'In Progress')

    def test_public_landing_shows_request_actions_and_service_categories(self):
        response = self.client.get(reverse('landing'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Submit a Request')
        self.assertContains(response, 'Track My Request')
        self.assertContains(response, 'Water Supply')
        self.assertContains(response, 'id="services"')
        self.assertContains(response, 'id="how-it-works"')
        self.assertContains(response, 'id="help"')
        self.assertContains(response, reverse('create_request') + '?category=water_supply')
        self.assertFalse(response.context['has_request_stats'])

    def test_public_landing_statistics_use_database_counts(self):
        ServiceRequest.objects.create(
            citizen=self.user,
            category=RequestCategory.WATER_SUPPLY,
            location='Main Street',
            description='A water service request.',
            status=RequestStatus.RESOLVED,
        )
        response = self.client.get(reverse('landing'))

        self.assertTrue(response.context['has_request_stats'])
        self.assertEqual(response.context['landing_stats'][0]['value'], 1)
        self.assertEqual(response.context['landing_stats'][3]['value'], 1)

    def test_category_card_prefills_the_existing_request_form(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('create_request'),
            {'category': RequestCategory.WATER_SUPPLY},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['form']['category'].value(),
            RequestCategory.WATER_SUPPLY,
        )

    def test_citizen_summary_counts_all_statuses_independent_of_filters(self):
        for status_value in RequestStatus.values:
            ServiceRequest.objects.create(
                citizen=self.user,
                category=RequestCategory.OTHER,
                location='County Road',
                description='A reported public service issue.',
                status=status_value,
            )

        self.client.force_login(self.user)
        response = self.client.get(reverse('request_list'), {'status': RequestStatus.PENDING})

        self.assertEqual(response.context['total_cases'], 3)
        self.assertEqual(response.context['pending_cases'], 1)
        self.assertEqual(response.context['in_progress_cases'], 1)
        self.assertEqual(response.context['resolved_cases'], 1)
        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        self.assertContains(response, 'Welcome, citizen')

    def test_logged_out_user_redirected_to_login(self):
        response = self.client.get(reverse('request_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_request_submission_rejects_posts_without_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(
            reverse('create_request'),
            {
                'category': RequestCategory.OTHER,
                'location': 'Main Road',
                'description': 'A reported public service issue.',
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_successful_login_redirects_to_citizen_requests(self):
        response = self.client.post(
            reverse('login'),
            {'username': 'citizen', 'password': 'StrongPass123!'},
        )

        self.assertRedirects(response, reverse('request_list'))

    def test_successful_staff_login_redirects_to_admin_dashboard(self):
        response = self.client.post(
            reverse('login'),
            {'username': 'staff', 'password': 'StrongPass123!'},
        )

        self.assertRedirects(response, reverse('admin_dashboard'))

    def test_staff_is_redirected_away_from_citizen_portal_routes(self):
        self.client.force_login(self.staff_user)

        for route_name in ('request_list', 'create_request', 'register'):
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))
                self.assertRedirects(response, reverse('admin_dashboard'))

    def test_staff_navigation_only_shows_admin_portal_links(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('admin_dashboard'))

        self.assertContains(response, 'Dashboard')
        self.assertNotContains(response, 'My Requests')
        self.assertNotContains(response, 'New Request')

    def test_staff_landing_page_links_to_admin_dashboard(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('landing'))

        self.assertContains(response, 'Open Admin Dashboard')
        self.assertNotContains(response, 'Track My Requests')
        self.assertNotContains(response, 'Report an Issue')

    def test_logout_requires_post_and_ends_the_session(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('logout'))
        self.assertEqual(response.status_code, 405)

        response = self.client.get(reverse('request_list'))
        self.assertContains(response, 'name="csrfmiddlewaretoken"')

        response = self.client.post(reverse('logout'))
        self.assertRedirects(response, reverse('login'))
        response = self.client.get(reverse('request_list'))
        self.assertRedirects(response, f'{reverse("login")}?next={reverse("request_list")}')

    def test_service_request_model_defaults(self):
        req = ServiceRequest.objects.create(
            citizen=self.user,
            category=RequestCategory.WATER_SUPPLY,
            location='Main Street',
            description='Water leak reported near the school.',
        )
        self.assertEqual(req.status, RequestStatus.PENDING)
        self.assertTrue(req.reference_number.startswith('SR-'))

    def test_citizen_cannot_change_status_via_request_detail(self):
        req = ServiceRequest.objects.create(
            citizen=self.user,
            category=RequestCategory.WATER_SUPPLY,
            location='Main Street',
            description='Water leak reported near the school.',
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('request_detail', args=[req.pk]),
            {'status': RequestStatus.IN_PROGRESS},
            follow=True,
        )
        self.assertEqual(response.status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, RequestStatus.PENDING)

    def test_citizen_cannot_view_another_citizens_request(self):
        service_request = ServiceRequest.objects.create(
            citizen=self.user,
            category=RequestCategory.WATER_SUPPLY,
            location='Main Street',
            description='Water leak reported near the school.',
        )
        other_citizen = get_user_model().objects.create_user(
            username='other-citizen',
            password='StrongPass123!',
        )
        self.client.force_login(other_citizen)

        response = self.client.get(reverse('request_detail', args=[service_request.pk]))

        self.assertEqual(response.status_code, 404)

    def test_admin_dashboard_requires_staff(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 403)

    def test_admin_dashboard_exposes_open_and_resolved_counts(self):
        self.client.force_login(self.staff_user)
        ServiceRequest.objects.create(
            citizen=self.user,
            category=RequestCategory.GARBAGE_COLLECTION,
            location='Town Hall',
            description='Overflowing bins.',
            status=RequestStatus.PENDING,
        )
        ServiceRequest.objects.create(
            citizen=self.user,
            category=RequestCategory.ROAD_DAMAGE,
            location='Old Road',
            description='Potholes filled in.',
            status=RequestStatus.RESOLVED,
        )

        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'In Progress')
        self.assertContains(response, 'Resolved Cases')
        self.assertContains(response, 'Manage status for')
        self.assertContains(response, 'status-chart-legend')

    def test_admin_dashboard_shows_recent_feedback_comments_and_suggestions(self):
        service_request = ServiceRequest.objects.create(
            citizen=self.user,
            category=RequestCategory.WATER_SUPPLY,
            location='Main Street',
            description='A resolved water issue.',
            status=RequestStatus.RESOLVED,
        )
        ServiceRequestFeedback.objects.create(
            service_request=service_request,
            citizen=self.user,
            rating=2,
            comment='The repair took too long.',
            suggestion='Please provide progress updates.',
        )
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse('admin_dashboard'))

        self.assertContains(response, 'Recent citizen feedback')
        self.assertContains(response, 'The repair took too long.')
        self.assertContains(response, 'Please provide progress updates.')
        self.assertContains(response, reverse('admin_feedback_detail', args=[service_request.feedback.pk]))
        self.assertEqual(len(response.context['recent_feedback']), 1)

    def test_admin_dashboard_metrics_and_charts_ignore_table_filters(self):
        for status_value in RequestStatus.values:
            ServiceRequest.objects.create(
                citizen=self.user,
                category=RequestCategory.WATER_SUPPLY,
                location='Main Road',
                description='A public service issue.',
                status=status_value,
            )

        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('admin_dashboard'), {'status': RequestStatus.PENDING})

        self.assertEqual(response.context['total'], 3)
        self.assertEqual(response.context['pending_cases'], 1)
        self.assertEqual(response.context['in_progress_cases'], 1)
        self.assertEqual(response.context['resolved_cases'], 1)
        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        self.assertEqual(response.context['status_values'], [1, 1, 1])

    def test_admin_dashboard_validates_date_range_and_sorts_filtered_requests(self):
        old_request = ServiceRequest.objects.create(
            citizen=self.user,
            category=RequestCategory.WATER_SUPPLY,
            location='Old service location',
            description='Older report.',
            status=RequestStatus.PENDING,
        )
        current_request = ServiceRequest.objects.create(
            citizen=self.user,
            category=RequestCategory.ROAD_DAMAGE,
            location='Current service location',
            description='Current report.',
            status=RequestStatus.IN_PROGRESS,
        )
        ServiceRequest.objects.filter(pk=old_request.pk).update(
            created_at=timezone.now() - timedelta(days=3)
        )

        self.client.force_login(self.staff_user)
        today = timezone.localdate().isoformat()
        response = self.client.get(
            reverse('admin_dashboard'),
            {'date_from': today, 'date_to': today, 'sort': 'oldest'},
        )

        self.assertEqual(response.context['total'], 2)
        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        self.assertEqual(response.context['page_obj'][0].pk, current_request.pk)
        self.assertEqual(response.context['sort'], 'oldest')

    def test_admin_dashboard_rejects_reversed_date_range(self):
        self.client.force_login(self.staff_user)
        today = timezone.localdate()
        response = self.client.get(
            reverse('admin_dashboard'),
            {
                'date_from': (today + timedelta(days=1)).isoformat(),
                'date_to': today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('date_to', response.context['filter_form'].errors)
        self.assertContains(response, 'End date must be on or after the start date.')

    def test_admin_dashboard_reports_invalid_status_filter(self):
        ServiceRequest.objects.create(
            citizen=self.user,
            category=RequestCategory.WATER_SUPPLY,
            location='Main Road',
            description='A public service issue.',
        )
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('admin_dashboard'), {'status': 'invalid-status'})

        self.assertEqual(response.status_code, 200)
        self.assertIn('status', response.context['filter_form'].errors)
        self.assertContains(response, 'id="id_status_errors"')
        self.assertEqual(response.context['page_obj'].paginator.count, 1)

    def test_empty_admin_dashboard_has_chart_and_table_empty_states(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('admin_dashboard'))

        self.assertContains(response, 'Charts will appear when requests are submitted.')
        self.assertContains(response, 'No service requests have been submitted yet.')

    def test_staff_status_update_requires_confirmation_markup_and_updates(self):
        service_request = ServiceRequest.objects.create(
            citizen=self.user,
            category=RequestCategory.OTHER,
            location='County Road',
            description='A reported public service issue.',
        )
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('request_detail', args=[service_request.pk]))

        self.assertContains(response, 'data-confirm-status')

        response = self.client.post(
            reverse('request_detail', args=[service_request.pk]),
            {'status': RequestStatus.IN_PROGRESS},
        )

        self.assertRedirects(response, reverse('request_detail', args=[service_request.pk]))
        service_request.refresh_from_db()
        self.assertEqual(service_request.status, RequestStatus.IN_PROGRESS)

    def test_citizen_sees_status_after_staff_processes_their_request(self):
        citizen_client = Client()
        citizen_client.force_login(self.user)
        response = citizen_client.post(
            reverse('create_request'),
            {
                'category': RequestCategory.WATER_SUPPLY,
                'location': 'Main Street',
                'description': 'A leaking pipe needs repair.',
            },
        )
        service_request = ServiceRequest.objects.get(citizen=self.user)
        self.assertRedirects(response, reverse('request_detail', args=[service_request.pk]))

        staff_client = Client()
        staff_client.force_login(self.staff_user)
        response = staff_client.post(
            reverse('request_detail', args=[service_request.pk]),
            {'status': RequestStatus.RESOLVED},
        )
        self.assertRedirects(response, reverse('request_detail', args=[service_request.pk]))

        response = citizen_client.get(reverse('request_detail', args=[service_request.pk]))
        self.assertContains(response, 'Resolved')
        self.assertEqual(response.context['request_detail'].status, RequestStatus.RESOLVED)

    def test_valid_image_upload_is_accepted(self):
        buffer = io.BytesIO()
        Image.new('RGB', (100, 100), color='blue').save(buffer, format='PNG')
        image = SimpleUploadedFile(
            'issue.png',
            buffer.getvalue(),
            content_type='image/png',
        )
        form = ServiceRequestForm(
            data={
                'category': RequestCategory.WATER_SUPPLY,
                'location': 'Kiambu Road',
                'description': 'Water leak report with photo.',
            },
            files={'image': image},
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_oversized_image_upload_is_rejected(self):
        buffer = io.BytesIO()
        Image.new('RGB', (10, 10), color='blue').save(buffer, format='PNG')
        image = SimpleUploadedFile(
            'oversized.png',
            buffer.getvalue(),
            content_type='image/png',
        )
        image.size = MAX_IMAGE_SIZE + 1
        form = ServiceRequestForm(
            data={
                'category': RequestCategory.OTHER,
                'location': 'Main Road',
                'description': 'A service request with an oversized image.',
            },
            files={'image': image},
        )

        self.assertFalse(form.is_valid())
        self.assertIn('5MB or less', str(form.errors['image']))

    def test_request_images_require_owner_or_staff_access(self):
        buffer = io.BytesIO()
        Image.new('RGB', (10, 10), color='blue').save(buffer, format='PNG')
        image_bytes = buffer.getvalue()

        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            service_request = ServiceRequest.objects.create(
                citizen=self.user,
                category=RequestCategory.WATER_SUPPLY,
                location='Main Street',
                description='Water leak with attached photo.',
                image=SimpleUploadedFile('issue.png', image_bytes, content_type='image/png'),
            )
            image_url = service_request.image.url

            anonymous_response = Client().get(image_url)
            self.assertEqual(anonymous_response.status_code, 302)

            self.client.force_login(self.user)
            owner_response = self.client.get(image_url)
            self.assertEqual(owner_response.status_code, 200)
            self.assertEqual(owner_response['Content-Type'], 'image/png')
            self.assertEqual(b''.join(owner_response.streaming_content), image_bytes)
            owner_response.close()

            other_citizen = get_user_model().objects.create_user(
                username='image-outsider',
                password='StrongPass123!',
            )
            outsider_client = Client()
            outsider_client.force_login(other_citizen)
            self.assertEqual(outsider_client.get(image_url).status_code, 404)

            staff_client = Client()
            staff_client.force_login(self.staff_user)
            staff_response = staff_client.get(image_url)
            self.assertEqual(staff_response.status_code, 200)
            staff_response.close()

    def test_request_form_groups_fields_and_includes_image_preview(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('create_request'))

        self.assertContains(response, 'Issue details')
        self.assertContains(response, 'Supporting evidence')
        self.assertContains(response, 'data-image-preview')
        self.assertContains(response, 'Maximum file size: 5 MB')

    def test_invalid_request_fields_reference_their_errors_accessibly(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('create_request'),
            {
                'category': RequestCategory.OTHER,
                'location': '',
                'description': '',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, 'aria-describedby="location-help id_location_errors"')
        self.assertContains(response, 'id="id_location_errors"')
        self.assertContains(response, 'aria-describedby="description-help id_description_errors"')

    def test_request_detail_shows_progress_for_current_status(self):
        service_request = ServiceRequest.objects.create(
            citizen=self.user,
            category=RequestCategory.WATER_SUPPLY,
            location='Main Street',
            description='Water leak reported near the school.',
            status=RequestStatus.IN_PROGRESS,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse('request_detail', args=[service_request.pk]))

        self.assertContains(response, 'Request progress')
        self.assertContains(response, 'Pending')
        self.assertContains(response, 'In Progress')
        self.assertContains(response, 'Resolved')
        self.assertEqual(len(response.context['status_steps']), 3)

    def test_invalid_image_type_is_rejected(self):
        file_obj = SimpleUploadedFile(
            'issue.txt',
            b'not-an-image',
            content_type='text/plain',
        )
        form = ServiceRequestForm(
            data={
                'category': RequestCategory.OTHER,
                'location': 'Nairobi Road',
                'description': 'A text file was uploaded accidentally.',
            },
            files={'image': file_obj},
        )
        self.assertFalse(form.is_valid())
        self.assertIn('image', form.errors)


class CitizenFeedbackTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.citizen = user_model.objects.create_user(
            username='feedback-citizen',
            password='StrongPass123!',
        )
        self.other_citizen = user_model.objects.create_user(
            username='feedback-outsider',
            password='StrongPass123!',
        )
        self.staff = user_model.objects.create_user(
            username='feedback-staff',
            password='StrongPass123!',
            is_staff=True,
        )
        self.service_request = ServiceRequest.objects.create(
            citizen=self.citizen,
            category=RequestCategory.WATER_SUPPLY,
            location='Main Street',
            description='A resolved water service issue.',
            status=RequestStatus.RESOLVED,
        )
        now = timezone.now()
        ServiceRequest.objects.filter(pk=self.service_request.pk).update(
            created_at=now - timedelta(days=1),
            first_response_at=now - timedelta(hours=18),
            resolved_at=now - timedelta(hours=2),
        )

    def feedback_post(self, client=None, **overrides):
        client = client or self.client
        data = {
            'action': 'submit_feedback',
            'rating': '5',
            'comment': 'The repair was completed and updates were clear.',
            'suggestion_category': '',
            'suggestion': '',
        }
        data.update(overrides)
        return client.post(reverse('request_detail', args=[self.service_request.pk]), data)

    def test_citizen_can_submit_feedback_for_own_resolved_request(self):
        self.client.force_login(self.citizen)
        response = self.feedback_post()

        self.assertRedirects(response, reverse('request_detail', args=[self.service_request.pk]))
        feedback = ServiceRequestFeedback.objects.get(service_request=self.service_request)
        self.assertEqual(feedback.citizen, self.citizen)
        self.assertEqual(feedback.rating, 5)
        self.assertEqual(feedback.comment, 'The repair was completed and updates were clear.')
        self.assertEqual(feedback.events.count(), 1)
        self.assertEqual(
            feedback.events.first().event_type,
            ServiceRequestFeedbackEvent.EventType.CITIZEN_SUBMITTED,
        )

    def test_feedback_rating_must_be_from_one_to_five(self):
        self.client.force_login(self.citizen)
        response = self.feedback_post(rating='6')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ServiceRequestFeedback.objects.exists())
        self.assertContains(response, 'Select a valid choice')

    def test_citizen_can_edit_existing_feedback_without_creating_a_duplicate(self):
        feedback = ServiceRequestFeedback.objects.create(
            service_request=self.service_request,
            citizen=self.citizen,
            rating=2,
        )
        self.client.force_login(self.citizen)
        response = self.feedback_post(rating='4', comment='Updated comment.')

        self.assertRedirects(response, reverse('request_detail', args=[self.service_request.pk]))
        self.assertEqual(ServiceRequestFeedback.objects.count(), 1)
        feedback.refresh_from_db()
        self.assertEqual(feedback.rating, 4)
        self.assertEqual(feedback.comment, 'Updated comment.')
        self.assertEqual(
            feedback.events.first().event_type,
            ServiceRequestFeedbackEvent.EventType.CITIZEN_EDITED,
        )

    def test_feedback_is_unavailable_until_request_is_resolved(self):
        self.service_request.status = RequestStatus.IN_PROGRESS
        self.service_request.save(update_fields=['status'])
        self.client.force_login(self.citizen)

        page = self.client.get(reverse('request_detail', args=[self.service_request.pk]))
        self.assertContains(page, 'after this request has been resolved')
        self.assertNotContains(page, 'Submit feedback')
        self.assertEqual(self.feedback_post().status_code, 403)
        self.assertFalse(ServiceRequestFeedback.objects.exists())

    def test_feedback_is_preserved_when_request_reopens_and_cannot_be_edited(self):
        feedback = ServiceRequestFeedback.objects.create(
            service_request=self.service_request,
            citizen=self.citizen,
            rating=4,
            comment='Original comment.',
        )
        self.service_request.status = RequestStatus.IN_PROGRESS
        self.service_request.save(update_fields=['status'])
        self.client.force_login(self.citizen)

        page = self.client.get(reverse('request_detail', args=[self.service_request.pk]))
        self.assertContains(page, 'Original comment.')
        self.assertContains(page, 'can be updated after the request is resolved again')
        self.assertEqual(self.feedback_post(rating='1').status_code, 403)
        feedback.refresh_from_db()
        self.assertEqual(feedback.rating, 4)

    def test_citizen_cannot_submit_feedback_for_another_citizens_request(self):
        self.client.force_login(self.other_citizen)

        response = self.feedback_post()

        self.assertEqual(response.status_code, 404)
        self.assertFalse(ServiceRequestFeedback.objects.exists())

    def test_feedback_submission_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.citizen)

        response = self.feedback_post(client=csrf_client)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ServiceRequestFeedback.objects.exists())

    def test_other_suggestion_category_requires_explanation(self):
        self.client.force_login(self.citizen)

        response = self.feedback_post(
            suggestion_category=FeedbackSuggestionCategory.OTHER,
            suggestion='',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('suggestion', response.context['feedback_form'].errors)

    def test_private_feedback_and_internal_notes_are_owner_and_staff_protected(self):
        feedback = ServiceRequestFeedback.objects.create(
            service_request=self.service_request,
            citizen=self.citizen,
            rating=2,
            comment='Private citizen comment.',
            internal_note='Private staff-only note.',
            admin_response='Published response.',
            response_published_at=timezone.now(),
        )
        self.client.force_login(self.other_citizen)
        self.assertEqual(
            self.client.get(reverse('request_detail', args=[self.service_request.pk])).status_code,
            404,
        )

        self.client.force_login(self.citizen)
        page = self.client.get(reverse('request_detail', args=[self.service_request.pk]))
        self.assertContains(page, 'Private citizen comment.')
        self.assertContains(page, 'Published response.')
        self.assertNotContains(page, 'Private staff-only note.')
        self.assertEqual(feedback.citizen, self.citizen)

    def test_unpublished_response_and_internal_note_are_hidden_from_citizen(self):
        ServiceRequestFeedback.objects.create(
            service_request=self.service_request,
            citizen=self.citizen,
            rating=3,
            internal_note='Confidential review context.',
            admin_response='Response not yet published.',
        )
        self.client.force_login(self.citizen)
        page = self.client.get(reverse('request_detail', args=[self.service_request.pk]))

        self.assertNotContains(page, 'Confidential review context.')
        self.assertNotContains(page, 'Response not yet published.')

    def test_staff_can_review_and_publish_response_with_audit_events(self):
        feedback = ServiceRequestFeedback.objects.create(
            service_request=self.service_request,
            citizen=self.citizen,
            rating=1,
        )
        self.client.force_login(self.staff)
        dashboard = self.client.get(reverse('admin_feedback_dashboard'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, 'Citizen Feedback &amp; Service Quality')

        response = self.client.post(
            reverse('admin_feedback_detail', args=[feedback.pk]),
            {
                'review_status': FeedbackReviewStatus.UNDER_REVIEW,
                'internal_note': 'Checking the service record.',
                'planned_action': '',
                'admin_response': 'Thank you. We are reviewing this.',
                'publish_response': 'on',
            },
        )
        self.assertRedirects(response, reverse('admin_feedback_detail', args=[feedback.pk]))
        feedback.refresh_from_db()
        self.assertEqual(feedback.review_status, FeedbackReviewStatus.UNDER_REVIEW)
        self.assertEqual(feedback.reviewed_by, self.staff)
        self.assertIsNotNone(feedback.response_published_at)
        event_types = set(feedback.events.values_list('event_type', flat=True))
        self.assertIn(ServiceRequestFeedbackEvent.EventType.STATUS_CHANGED, event_types)
        self.assertIn(ServiceRequestFeedbackEvent.EventType.NOTE_UPDATED, event_types)
        self.assertIn(ServiceRequestFeedbackEvent.EventType.RESPONSE_PUBLISHED, event_types)
        self.assertIn(ServiceRequestFeedbackEvent.EventType.RESPONSE_UPDATED, event_types)

        self.client.force_login(self.citizen)
        citizen_page = self.client.get(reverse('request_detail', args=[self.service_request.pk]))
        self.assertContains(citizen_page, 'Thank you. We are reviewing this.')
        self.assertNotContains(citizen_page, 'Checking the service record.')

        self.client.force_login(self.staff)
        self.client.post(
            reverse('admin_feedback_detail', args=[feedback.pk]),
            {
                'review_status': FeedbackReviewStatus.UNDER_REVIEW,
                'internal_note': 'Checking the service record.',
                'planned_action': '',
                'admin_response': 'We have updated our response.',
                'publish_response': 'on',
            },
        )
        feedback.refresh_from_db()
        self.assertTrue(
            feedback.events.filter(
                event_type=ServiceRequestFeedbackEvent.EventType.RESPONSE_UPDATED
            ).exists()
        )

    def test_staff_cannot_skip_review_status_workflow(self):
        feedback = ServiceRequestFeedback.objects.create(
            service_request=self.service_request,
            citizen=self.citizen,
            rating=1,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse('admin_feedback_detail', args=[feedback.pk]),
            {
                'review_status': FeedbackReviewStatus.ADDRESSED,
                'internal_note': '',
                'planned_action': 'Repair the underlying issue.',
                'admin_response': '',
            },
        )

        self.assertEqual(response.status_code, 200)
        feedback.refresh_from_db()
        self.assertEqual(feedback.review_status, FeedbackReviewStatus.NEW)
        self.assertFalse(feedback.events.exists())

    def test_non_staff_cannot_access_feedback_management(self):
        self.client.force_login(self.citizen)

        self.assertEqual(self.client.get(reverse('admin_feedback_dashboard')).status_code, 403)

    def test_dashboard_calculates_feedback_and_timing_metrics_from_records(self):
        ServiceRequestFeedback.objects.create(
            service_request=self.service_request,
            citizen=self.citizen,
            rating=5,
            suggestion='Share more progress updates.',
            suggestion_category=FeedbackSuggestionCategory.COMMUNICATION,
        )
        unresolved = ServiceRequest.objects.create(
            citizen=self.citizen,
            category=RequestCategory.ROAD_DAMAGE,
            location='County Road',
            description='A road issue still being processed.',
            status=RequestStatus.IN_PROGRESS,
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse('admin_feedback_dashboard'))

        self.assertEqual(response.context['total_feedback'], 1)
        self.assertEqual(response.context['positive_count'], 1)
        self.assertEqual(response.context['positive_percentage'], 100)
        self.assertEqual(response.context['suggestions_count'], 1)
        self.assertEqual(response.context['suggestion_categories'][0]['label'], 'Communication')
        self.assertEqual(response.context['eligible_without_feedback'], 0)
        self.assertEqual(response.context['unresolved_count'], 1)
        self.assertEqual(response.context['response_sample_count'], 1)
        self.assertEqual(response.context['resolution_sample_count'], 1)
        self.assertAlmostEqual(response.context['average_rating'], 5.0)
        self.assertAlmostEqual(response.context['average_response_hours'], 6.0)
        self.assertAlmostEqual(response.context['median_response_hours'], 6.0)
        self.assertAlmostEqual(response.context['average_resolution_hours'], 22.0)
        self.assertEqual(response.context['monthly_trends'][0]['request_count'], 2)
        self.assertEqual(response.context['monthly_trends'][0]['feedback_count'], 1)
        self.assertAlmostEqual(response.context['monthly_trends'][0]['response_average'], 6.0)
        self.assertEqual(unresolved.status, RequestStatus.IN_PROGRESS)

    def test_feedback_dashboard_handles_no_feedback_and_zero_denominators(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse('admin_feedback_dashboard'))

        self.assertEqual(response.context['total_feedback'], 0)
        self.assertIsNone(response.context['average_rating'])
        self.assertEqual(response.context['positive_percentage'], 0)
        self.assertEqual(response.context['low_percentage'], 0)
        self.assertEqual(response.context['eligible_without_feedback'], 1)
        self.assertContains(response, 'No feedback is available yet.')


class ImprovementActionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.citizen = user_model.objects.create_user(
            username='action-citizen',
            password='StrongPass123!',
        )
        self.staff = user_model.objects.create_user(
            username='action-staff',
            password='StrongPass123!',
            is_staff=True,
        )
        self.assignee = user_model.objects.create_user(
            username='action-assignee',
            password='StrongPass123!',
            is_staff=True,
        )
        service_request = ServiceRequest.objects.create(
            citizen=self.citizen,
            category=RequestCategory.ROAD_DAMAGE,
            location='County Road',
            description='A pothole was reported.',
            status=RequestStatus.RESOLVED,
        )
        self.feedback = ServiceRequestFeedback.objects.create(
            service_request=service_request,
            citizen=self.citizen,
            rating=2,
            suggestion='Repair roads more quickly.',
        )

    def action_data(self, **overrides):
        data = {
            'title': 'Improve road repair updates',
            'issue_description': 'Residents asked for clearer repair information.',
            'related_feedback': [str(self.feedback.pk)],
            'responsible_officer': str(self.assignee.pk),
            'priority': ImprovementActionPriority.HIGH,
            'planned_action': 'Publish progress updates for road repairs.',
            'target_date': (timezone.localdate() + timedelta(days=14)).isoformat(),
            'status': ImprovementActionStatus.PROPOSED,
            'admin_note': 'Discuss at the service review meeting.',
        }
        data.update(overrides)
        return data

    def test_staff_can_create_action_linked_to_feedback(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse('admin_improvement_create'),
            self.action_data(),
        )

        action = ImprovementAction.objects.get()
        self.assertRedirects(response, reverse('admin_improvement_detail', args=[action.pk]))
        self.assertEqual(list(action.related_feedback.all()), [self.feedback])
        self.assertEqual(action.created_by, self.staff)
        self.assertEqual(action.responsible_officer, self.assignee)
        self.assertEqual(action.priority, ImprovementActionPriority.HIGH)

    def test_improvement_status_transitions_record_completion(self):
        action = ImprovementAction.objects.create(
            title='Improve road repair updates',
            issue_description='Residents asked for clearer repair information.',
            responsible_officer=self.assignee,
            priority=ImprovementActionPriority.HIGH,
            planned_action='Publish progress updates.',
            status=ImprovementActionStatus.PROPOSED,
            created_by=self.staff,
        )
        action.related_feedback.add(self.feedback)
        self.client.force_login(self.staff)

        invalid = self.client.post(
            reverse('admin_improvement_detail', args=[action.pk]),
            self.action_data(status=ImprovementActionStatus.COMPLETED),
        )
        self.assertEqual(invalid.status_code, 200)
        action.refresh_from_db()
        self.assertEqual(action.status, ImprovementActionStatus.PROPOSED)
        self.assertIsNone(action.completed_at)

        for next_status in (
            ImprovementActionStatus.APPROVED,
            ImprovementActionStatus.IN_PROGRESS,
            ImprovementActionStatus.COMPLETED,
        ):
            response = self.client.post(
                reverse('admin_improvement_detail', args=[action.pk]),
                self.action_data(status=next_status),
            )
            self.assertRedirects(response, reverse('admin_improvement_detail', args=[action.pk]))
            action.refresh_from_db()
            self.assertEqual(action.status, next_status)

        self.assertIsNotNone(action.completed_at)
        self.assertEqual(action.updated_by, self.staff)

    def test_staff_can_filter_overdue_actions_and_citizens_cannot_manage_them(self):
        expired_action = ImprovementAction.objects.create(
            title='Past due action',
            issue_description='An action with an old target date.',
            priority=ImprovementActionPriority.MEDIUM,
            planned_action='Complete the work.',
            target_date=timezone.localdate() - timedelta(days=1),
            status=ImprovementActionStatus.IN_PROGRESS,
            created_by=self.staff,
        )
        expired_action.related_feedback.add(self.feedback)
        self.client.force_login(self.staff)

        response = self.client.get(reverse('admin_improvement_list'), {'overdue_only': 'on'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        self.assertEqual(response.context['actions'][0].pk, expired_action.pk)
        self.assertContains(response, 'Overdue')

        self.client.force_login(self.citizen)
        self.assertEqual(self.client.get(reverse('admin_improvement_list')).status_code, 403)
        self.assertEqual(
            self.client.post(reverse('admin_improvement_create'), self.action_data()).status_code,
            403,
        )
