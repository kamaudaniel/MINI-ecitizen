import os

from django import forms
from django.contrib.auth import get_user_model
from PIL import Image

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
)


MAX_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


class ServiceRequestForm(forms.ModelForm):
    class Meta:
        model = ServiceRequest
        fields = ['category', 'location', 'description', 'image']
        widgets = {
            'category': forms.Select(attrs={'class': 'form-select'}),
            'location': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Enter the service location',
                    'aria-describedby': 'location-help',
                }
            ),
            'description': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 5,
                    'placeholder': 'Describe the issue in detail',
                    'aria-describedby': 'description-help',
                }
            ),
            'image': forms.ClearableFileInput(
                attrs={
                    'class': 'form-control',
                    'accept': 'image/png,image/jpeg,image/gif,image/webp',
                    'aria-describedby': 'image-help',
                    'data-image-preview': '',
                }
            ),
        }

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if not image:
            return image

        extension = os.path.splitext(image.name)[1].lower().lstrip('.')
        if extension not in ALLOWED_IMAGE_TYPES:
            raise forms.ValidationError('Only PNG, JPG, JPEG, GIF, and WEBP images are allowed.')

        if image.size > MAX_IMAGE_SIZE:
            raise forms.ValidationError('Image size must be 5MB or less.')

        try:
            with Image.open(image) as img:
                img.verify()
        except Exception:
            raise forms.ValidationError('Upload a valid image. The file you uploaded was either not an image or a corrupted image.')

        image.seek(0)
        return image


class AdminRequestFilterForm(forms.Form):
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
            'type': 'search',
                'class': 'form-control',
                'placeholder': 'Reference, citizen, location or issue',
            }
        ),
    )
    category = forms.ChoiceField(
        required=False,
        choices=[('', 'All categories'), *RequestCategory.choices],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    status = forms.ChoiceField(
        required=False,
        choices=[('', 'All statuses'), *RequestStatus.choices],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )
    sort = forms.ChoiceField(
        required=False,
        choices=[('newest', 'Newest first'), ('oldest', 'Oldest first')],
        widget=forms.Select(attrs={'class': 'form-select'}),
        initial='newest',
    )

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')
        if date_from and date_to and date_from > date_to:
            self.add_error('date_to', 'End date must be on or after the start date.')
        return cleaned_data

class CitizenFeedbackForm(forms.ModelForm):
    class Meta:
        model = ServiceRequestFeedback
        fields = ['rating', 'comment', 'suggestion_category', 'suggestion']
        widgets = {
            'rating': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'comment': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 4,
                    'maxlength': 2000,
                    'placeholder': 'What went well or what was difficult? Were you kept informed?',
                }
            ),
            'suggestion_category': forms.Select(attrs={'class': 'form-select'}),
            'suggestion': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 3,
                    'maxlength': 2000,
                    'placeholder': 'What can we do better?',
                }
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get('suggestion_category') == FeedbackSuggestionCategory.OTHER
            and not cleaned_data.get('suggestion', '').strip()
        ):
            self.add_error('suggestion', 'Please describe your suggestion for the Other category.')
        return cleaned_data


class FeedbackReviewForm(forms.ModelForm):
    publish_response = forms.BooleanField(
        required=False,
        label='Publish this response to the citizen',
    )

    class Meta:
        model = ServiceRequestFeedback
        fields = ['review_status', 'internal_note', 'planned_action', 'admin_response']
        widgets = {
            'review_status': forms.Select(attrs={'class': 'form-select'}),
            'internal_note': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 4, 'maxlength': 3000}
            ),
            'planned_action': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 3, 'maxlength': 2000}
            ),
            'admin_response': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 3, 'maxlength': 2000}
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get('review_status')
        planned_action = cleaned_data.get('planned_action', '').strip()
        if status in {FeedbackReviewStatus.ACTION_PLANNED, FeedbackReviewStatus.ADDRESSED} and not planned_action:
            self.add_error('planned_action', 'Provide the planned action before using this review status.')
        if cleaned_data.get('publish_response') and not cleaned_data.get('admin_response', '').strip():
            self.add_error('admin_response', 'Enter a response before publishing it to the citizen.')
        return cleaned_data


class AdminFeedbackFilterForm(forms.Form):
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={'type': 'search', 'class': 'form-control', 'placeholder': 'Request reference'}
        ),
    )
    rating = forms.ChoiceField(
        required=False,
        choices=[('', 'All ratings'), *ServiceRequestFeedback._meta.get_field('rating').choices],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    category = forms.ChoiceField(
        required=False,
        choices=[('', 'All services'), *RequestCategory.choices],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    review_status = forms.ChoiceField(
        required=False,
        choices=[('', 'All review statuses'), *FeedbackReviewStatus.choices],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )
    sort = forms.ChoiceField(
        required=False,
        choices=[('newest', 'Newest first'), ('oldest', 'Oldest first')],
        widget=forms.Select(attrs={'class': 'form-select'}),
        initial='newest',
    )

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')
        if date_from and date_to and date_from > date_to:
            self.add_error('date_to', 'End date must be on or after the start date.')
        return cleaned_data


class ImprovementActionForm(forms.ModelForm):
    class Meta:
        model = ImprovementAction
        fields = [
            'title',
            'issue_description',
            'related_feedback',
            'responsible_officer',
            'priority',
            'planned_action',
            'target_date',
            'status',
            'admin_note',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 200}),
            'issue_description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'maxlength': 3000}),
            'related_feedback': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 6}),
            'responsible_officer': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'planned_action': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'maxlength': 3000}),
            'target_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'admin_note': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'maxlength': 3000}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['related_feedback'].queryset = ServiceRequestFeedback.objects.select_related(
            'service_request'
        ).order_by('-created_at')
        self.fields['related_feedback'].label_from_instance = (
            lambda feedback: f'{feedback.service_request.reference_number} - {feedback.rating}/5'
        )
        self.fields['responsible_officer'].queryset = get_user_model().objects.filter(
            is_staff=True
        ).order_by('username')
        self.fields['responsible_officer'].required = False
        self.fields['target_date'].required = False
        self.fields['admin_note'].required = False


class ImprovementActionFilterForm(forms.Form):
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'type': 'search', 'class': 'form-control', 'placeholder': 'Action title'}),
    )
    priority = forms.ChoiceField(
        required=False,
        choices=[('', 'All priorities'), *ImprovementActionPriority.choices],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    status = forms.ChoiceField(
        required=False,
        choices=[('', 'All statuses'), *ImprovementActionStatus.choices],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    owner = forms.ModelChoiceField(
        queryset=get_user_model().objects.filter(is_staff=True).order_by('username'),
        required=False,
        empty_label='All responsible officers',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    due_before = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )
    overdue_only = forms.BooleanField(required=False, widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))
