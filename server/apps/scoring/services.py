from django.db import transaction

from .engine import compute_all_for_product
from .models import Explanation, ScoreRecord


@transaction.atomic
def recompute_scores(product) -> list[ScoreRecord]:
    """Computes every available score for a product and persists a fresh,
    versioned ScoreRecord (+ Explanation rows) for each. Past records are
    kept as history, not overwritten — briefing §5 requires scores to be
    versioned and auditable."""
    created: list[ScoreRecord] = []
    for score_type, (version, result) in compute_all_for_product(product).items():
        record = ScoreRecord.objects.create(
            product=product,
            score_type=score_type,
            version=version,
            inputs=result.inputs,
            weights=result.weights,
            result=result.result,
            reliability=result.reliability,
        )
        Explanation.objects.bulk_create(
            [
                Explanation(score_record=record, polarity=polarity, text=text, order=i)
                for i, (polarity, text) in enumerate(result.reasons)
            ]
        )
        created.append(record)
    return created
