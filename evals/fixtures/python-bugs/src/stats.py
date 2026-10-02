def mean(values):
    """Arithmetic mean; an empty list has mean 0.0."""
    return sum(values) / len(values)  # SEEDED BUG PY-3: ZeroDivisionError on empty input
