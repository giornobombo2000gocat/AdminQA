from engine.cards import Card, validate_unique


def sum_combinations(cards: tuple[Card, ...], target: int) -> tuple[tuple[Card, ...], ...]:
    """All nonempty identity-distinct subsets; deterministic, no repeated cards."""
    cards = tuple(sorted(validate_unique(cards), key=lambda c: c.id))
    if type(target) is not int or target <= 0:
        raise ValueError("Target must be a positive integer")
    found: list[tuple[Card, ...]] = []

    def visit(start: int, remaining: int, chosen: tuple[Card, ...]) -> None:
        if remaining == 0:
            found.append(chosen)
            return
        for i in range(start, len(cards)):
            if cards[i].value <= remaining:
                visit(i + 1, remaining - cards[i].value, chosen + (cards[i],))

    visit(0, target, ())
    return tuple(found)
