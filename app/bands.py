"""Equalizer band layout and migration of saved five-band preferences."""
from bisect import bisect_right
import math

FREQUENCIES = (60, 150, 400, 1000, 2400, 15000)
GAIN_LIMIT = 10
LEGACY_FREQUENCIES = (60, 250, 1000, 4000, 12000)


def valid_bands(values, counts=(6,), limit=GAIN_LIMIT):
    return isinstance(values, (list, tuple)) and len(values) in counts and all(
        type(value) in (int, float) and math.isfinite(value) and -limit <= value <= limit for value in values
    )


def migrate_bands(values):
    if not valid_bands(values, (5, 6), limit=12):
        raise ValueError("Ongeldige equaliserbanden.")
    # Accept earlier saved values up to +/-12 dB without discarding the preset.
    values = tuple(max(-GAIN_LIMIT, min(GAIN_LIMIT, value)) for value in values)
    if len(values) == 6:
        return tuple(values)
    # Interpolate in log-frequency space and round to the slider's half-dB step.
    result = []
    for frequency in FREQUENCIES:
        index = bisect_right(LEGACY_FREQUENCIES, frequency) - 1
        if index >= len(values) - 1:
            gain = values[-1]
        else:
            lower, upper = LEGACY_FREQUENCIES[index:index + 2]
            position = math.log(frequency / lower) / math.log(upper / lower)
            gain = values[index] + position * (values[index + 1] - values[index])
        result.append(round(gain * 2) / 2)
    return tuple(result)
