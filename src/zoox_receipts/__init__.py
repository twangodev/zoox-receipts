"""Export structured ride data from Zoox receipt emails."""

from .models import Ride
from .receipts import extract_rides

__all__ = ["Ride", "extract_rides"]
