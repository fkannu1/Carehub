# core/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.db import transaction

from .models import User, PatientProfile, PhysicianProfile, HealthRecord


# ----------------------------
# Bootstrap helper
# ----------------------------
class BootstrapFormMixin:
    """Apply Bootstrap .form-control to inputs (except checkbox/radio)."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _, field in self.fields.items():
            w = field.widget
            if getattr(w, "input_type", "") in {"checkbox", "radio", "file"}:
                continue
            existing = w.attrs.get("class", "")
            w.attrs["class"] = (existing + " form-control").strip()
            if isinstance(w, forms.Textarea):
                w.attrs.setdefault("rows", 3)


class BootstrapLoginForm(BootstrapFormMixin, AuthenticationForm):
    """Styled login form (username/password get .form-control)."""
    pass


# ----------------------------
# Signup Forms
# ----------------------------
class PatientSignUpForm(BootstrapFormMixin, UserCreationForm):
    # Profile fields captured at signup
    full_name = forms.CharField(max_length=150, label="Full name")
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"})
    )
    phone = forms.CharField(required=False)
    address = forms.CharField(required=False, widget=forms.Textarea)
    height_cm = forms.DecimalField(
        required=False, min_value=0, decimal_places=2, max_digits=6
    )
    weight_kg = forms.DecimalField(
        required=False, min_value=0, decimal_places=2, max_digits=6
    )
    physician_connect_code = forms.CharField(
        required=False,
        help_text="Ask your physician for their code (optional)."
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")  # passwords handled by UserCreationForm

    @transaction.atomic
    def save(self, commit=True):
        """
        Create the User and the related PatientProfile in one atomic step.
        Also links physician if a valid connect_code is supplied.
        """
        user = super().save(commit=False)
        # Set role if present on your custom User model
        try:
            user.role = User.Roles.PATIENT
        except Exception:
            pass

        if commit:
            user.save()

            # Create the patient profile with fields from the form
            patient = PatientProfile.objects.create(
                user=user,
                full_name=self.cleaned_data["full_name"],
                date_of_birth=self.cleaned_data.get("date_of_birth"),
                phone=self.cleaned_data.get("phone") or "",
                address=self.cleaned_data.get("address") or "",
                height_cm=self.cleaned_data.get("height_cm"),
                weight_kg=self.cleaned_data.get("weight_kg"),
            )

            # Optional: link to a physician via connect code
            code = self.cleaned_data.get("physician_connect_code")
            if code:
                try:
                    doc = PhysicianProfile.objects.get(connect_code=code)
                    patient.physician = doc
                    patient.save(update_fields=["physician"])
                except PhysicianProfile.DoesNotExist:
                    # Silently ignore invalid code on signup; user can link later
                    pass

        return user


class PhysicianSignUpForm(BootstrapFormMixin, UserCreationForm):
    full_name = forms.CharField(max_length=150)
    specialization = forms.CharField(required=False)
    clinic_name = forms.CharField(required=False)
    connect_code = forms.CharField(
        max_length=12,
        help_text="Create a short code to share with patients."
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        try:
            user.role = User.Roles.PHYSICIAN
        except Exception:
            pass

        if commit:
            user.save()
            PhysicianProfile.objects.create(
                user=user,
                full_name=self.cleaned_data["full_name"],
                specialization=self.cleaned_data.get("specialization") or "",
                clinic_name=self.cleaned_data.get("clinic_name") or "",
                connect_code=self.cleaned_data["connect_code"],
            )
        return user


# ----------------------------
# Edit Forms
# ----------------------------
class PatientProfileForm(BootstrapFormMixin, forms.ModelForm):
    """
    Lets a patient update their profile and (optionally) link to a physician
    using a connect code. We handle the linking in save().
    """
    physician_connect_code = forms.CharField(
        required=False,
        help_text="Update/link physician using connect code."
    )

    class Meta:
        model = PatientProfile
        fields = [
            "full_name",
            "date_of_birth",
            "phone",
            "address",
            "height_cm",
            "weight_kg",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "address": forms.Textarea,
        }

    def clean_height_cm(self):
        v = self.cleaned_data.get("height_cm")
        if v is not None and v < 0:
            raise forms.ValidationError("Height must be ≥ 0.")
        return v

    def clean_weight_kg(self):
        v = self.cleaned_data.get("weight_kg")
        if v is not None and v < 0:
            raise forms.ValidationError("Weight must be ≥ 0.")
        return v

    @transaction.atomic
    def save(self, commit=True):
        profile = super().save(commit=False)

        # Attempt to link physician if code provided
        code = self.cleaned_data.get("physician_connect_code")
        if code:
            try:
                doc = PhysicianProfile.objects.get(connect_code=code)
                profile.physician = doc
            except PhysicianProfile.DoesNotExist:
                # Attach a form error and do NOT save invalid link
                self.add_error(
                    "physician_connect_code",
                    "No physician found with this connect code."
                )

        if commit and not self.errors:
            profile.save()

        return profile


class HealthRecordForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = HealthRecord
        fields = [
            "systolic_bp",
            "diastolic_bp",
            "sugar_fasting",
            "sugar_pp",
            "notes",
            "attachment",
        ]
