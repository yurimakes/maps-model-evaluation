"""Pair metrics, abstention and ranking use explicit, separate denominators."""
def divide(a, b):
    return a / b if b else 0.0

def summarize(rows):
    tp = fp = fn = positive = correct = exact = gold_pairs = proposals = 0
    hit = {k: 0 for k in (1, 3, 5)}
    pairs = {k: 0 for k in (1, 3, 5)}
    for row in rows:
        gold, pred, rank = set(row['gold']), set(row['predicted']), row['ranked']
        tp += len(gold & pred)
        fp += len(pred - gold)
        fn += len(gold - pred)
        exact += gold == pred
        correct += bool(gold & pred) if gold else not pred
        proposals += bool(pred)
        gold_pairs += len(gold)
        if gold:
            positive += 1
            for k in hit:
                hit[k] += bool(gold & set(rank[:k]))
                pairs[k] += len(gold & set(rank[:k]))
    precision, recall = divide(tp, tp + fp), divide(tp, tp + fn)
    return dict(questions=len(rows), positive_questions=positive, gold_pairs=gold_pairs,
        mapping_precision=precision, mapping_recall=recall,
        mapping_f1=divide(2 * tp, 2 * tp + fp + fn), tp=tp, fp=fp, fn=fn,
        decision_accuracy=divide(correct, len(rows)), exact_set_accuracy=divide(exact, len(rows)),
        proposed_queries=proposals,
        **{f'top{k}_hit_rate': divide(hit[k], positive) for k in hit},
        **{f'pair_recall_at{k}': divide(pairs[k], gold_pairs) for k in hit})
