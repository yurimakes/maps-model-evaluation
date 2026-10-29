"""Explicitly distinguish missing evidence from justified non-applicability."""
import math
WEIGHTS={'NAME':.15,'DESCRIPTION':.10,'DOMAIN':.10,'DATATYPE':.15,'SAMPLE':.20,'CODE':.15,'RELATION':.15}

def evaluate_scores(scores,status=None,na_reasons=None):
    scores=scores if isinstance(scores,dict) else {};status=status if isinstance(status,dict) else {};na_reasons=na_reasons if isinstance(na_reasons,dict) else {}
    missing=[];invalid=[];observed=[];na=[];denominator=0.;numerator=0.
    for key,weight in WEIGHTS.items():
        value=scores.get(key);state=str(status.get(key) or ('OBSERVED' if value is not None else 'MISSING')).upper()
        if state=='NA':
            if value is None and isinstance(na_reasons.get(key),str) and na_reasons[key].strip():na.append(key);continue
            invalid.append(key)
        denominator+=weight
        if state=='MISSING' or value is None:missing.append(key);continue
        if state!='OBSERVED' or isinstance(value,bool):invalid.append(key);continue
        try:number=float(value)
        except (TypeError,ValueError):invalid.append(key);continue
        if not math.isfinite(number) or not 0<=number<=1:invalid.append(key);continue
        observed.append(key);numerator+=number*weight
    confidence=round(numerator/denominator,3) if observed and denominator else None
    return {'confidence':confidence,'missing':missing,'invalid':sorted(set(invalid)),'observed':observed,'na':na,'applicable_weight':round(denominator,6)}
