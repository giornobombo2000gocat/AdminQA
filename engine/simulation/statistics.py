from fractions import Fraction
from math import log, sqrt
from statistics import NormalDist

from .models import MeanEstimate, ProportionEstimate


def mean_estimate(name: str,n: int,total: Fraction,squares: Fraction,
                  bounds: tuple[Fraction,Fraction],confidence: float) -> MeanEstimate:
    mean=total/n
    variance=(squares-total*total/n)/(n-1) if n>1 else None
    if variance is not None and variance<0:
        raise ValueError("Invalid negative sample variance")
    error=sqrt(float(variance)/n) if variance is not None else None
    low,high=map(float,bounds)
    z=NormalDist().inv_cdf((1+confidence)/2)
    interval=(max(low,float(mean)-z*error),min(high,float(mean)+z*error)) if error is not None else None
    bound=(high-low)*sqrt(log(2/(1-confidence))/(2*n))
    conservative=(max(low,float(mean)-bound),min(high,float(mean)+bound))
    return MeanEstimate(name,n,mean,variance,error,confidence,interval,bound,conservative)


def proportion_estimate(name: str,n: int,successes: int,confidence: float) -> ProportionEstimate:
    p=Fraction(successes,n)
    z=NormalDist().inv_cdf((1+confidence)/2)
    denominator=1+z*z/n
    center=(float(p)+z*z/(2*n))/denominator
    half=z*sqrt(float(p*(1-p))/n+z*z/(4*n*n))/denominator
    return ProportionEstimate(name,n,successes,p,sqrt(float(p*(1-p))/n),confidence,
                              (0.0 if successes==0 else max(0.0,center-half),
                               1.0 if successes==n else min(1.0,center+half)))
