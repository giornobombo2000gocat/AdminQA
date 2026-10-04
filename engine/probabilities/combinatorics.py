from fractions import Fraction
from math import comb


def combinations_count(n: int, k: int) -> int:
    return comb(n, k) if 0 <= k <= n else 0


def hypergeometric_pmf(population: int, successes: int, draws: int) -> tuple[Fraction, ...]:
    """P(X=k), k=0..draws, for sampling without replacement."""
    if any(type(n) is not int or n < 0 for n in (population, successes, draws)):
        raise ValueError("Parameters must be nonnegative integers")
    if successes > population or draws > population:
        raise ValueError("Successes/draws exceed population")
    denominator = comb(population, draws)
    return tuple(Fraction(combinations_count(successes, k) * combinations_count(population-successes, draws-k), denominator)
                 for k in range(draws + 1))
