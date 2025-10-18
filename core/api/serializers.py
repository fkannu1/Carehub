# core/api/serializers.py
from rest_framework import serializers
from core.models import PatientProfile

class PatientSerializer(serializers.ModelSerializer):
    public_id = serializers.UUIDField(read_only=True)
    physician_name = serializers.CharField(source="physician.full_name", read_only=True)

    class Meta:
        model = PatientProfile
        fields = [
            "public_id",      # exposed identifier (UUID)
            "full_name",
            "date_of_birth",
            "phone",
            "address",
            "height_cm",
            "weight_kg",
            "physician_name",
        ]
        read_only_fields = ("public_id", "physician_name")

    def validate_height_cm(self, v):
        if v is not None and v < 0:
            raise serializers.ValidationError("height_cm must be ≥ 0.")
        return v

    def validate_weight_kg(self, v):
        if v is not None and v < 0:
            raise serializers.ValidationError("weight_kg must be ≥ 0.")
        return v
