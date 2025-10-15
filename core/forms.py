from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User, PatientProfile, PhysicianProfile, HealthRecord

class BootstrapFormMixin:
    """Add Bootstrap .form-control to most inputs for consistent styling."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _, field in self.fields.items():
            widget = field.widget
            # Skip checkboxes/radios
            if getattr(widget, "input_type", "") in {"checkbox", "radio"}:
                continue
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = (existing + " form-control").strip()
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 3)


class PatientSignUpForm(BootstrapFormMixin, UserCreationForm):
    full_name = forms.CharField(max_length=150)
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    phone = forms.CharField(required=False)
    address = forms.CharField(required=False, widget=forms.Textarea)
    height_cm = forms.DecimalField(required=False)
    weight_kg = forms.DecimalField(required=False)
    physician_connect_code = forms.CharField(
        required=False,
        help_text="Ask your physician for their code (optional)."
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Roles.PATIENT
        if commit:
            user.save()
            patient = PatientProfile.objects.create(
                user=user,
                full_name=self.cleaned_data["full_name"],
                date_of_birth=self.cleaned_data.get("date_of_birth"),
                phone=self.cleaned_data.get("phone") or "",
                address=self.cleaned_data.get("address") or "",
                height_cm=self.cleaned_data.get("height_cm"),
                weight_kg=self.cleaned_data.get("weight_kg"),
            )
            code = self.cleaned_data.get("physician_connect_code")
            if code:
                try:
                    doc = PhysicianProfile.objects.get(connect_code=code)
                    patient.physician = doc
                    patient.save()
                except PhysicianProfile.DoesNotExist:
                    pass
        return user


class PhysicianSignUpForm(BootstrapFormMixin, UserCreationForm):
    full_name = forms.CharField(max_length=150)
    specialization = forms.CharField(required=False)
    clinic_name = forms.CharField(required=False)
    connect_code = forms.CharField(max_length=12, help_text="Create a short code to share with patients.")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Roles.PHYSICIAN
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


class PatientProfileForm(BootstrapFormMixin, forms.ModelForm):
    physician_connect_code = forms.CharField(required=False, help_text="Update/link physician using connect code.")
    class Meta:
        model = PatientProfile
        fields = ["full_name", "date_of_birth", "phone", "address", "height_cm", "weight_kg"]
        widgets = {"date_of_birth": forms.DateInput(attrs={"type": "date"}), "address": forms.Textarea}


class HealthRecordForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = HealthRecord
        fields = ["systolic_bp", "diastolic_bp", "sugar_fasting", "sugar_pp", "notes", "attachment"]
