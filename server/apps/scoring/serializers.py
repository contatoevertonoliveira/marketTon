from rest_framework import serializers

from .models import Explanation, ScoreRecord


class ExplanationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Explanation
        fields = ["polarity", "text"]


class ScoreRecordSerializer(serializers.ModelSerializer):
    reasons = ExplanationSerializer(many=True, read_only=True)

    class Meta:
        model = ScoreRecord
        fields = [
            "id",
            "product",
            "score_type",
            "version",
            "inputs",
            "weights",
            "result",
            "reliability",
            "computed_at",
            "reasons",
        ]
