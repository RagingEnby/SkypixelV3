"""Compare colors using the formulas from artificialair/seymoursniper."""

import math
from functools import lru_cache

Lab = tuple[float, float, float]


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


@lru_cache(maxsize=1024)
def hex_to_lab(hex_code: str) -> Lab:
    hex_code = hex_code.removeprefix("0x").removeprefix("#")
    if len(hex_code) != 6:
        raise ValueError(hex_code)
    red, green, blue = (int(hex_code[i : i + 2], 16) for i in (0, 2, 4))
    return rgb_to_lab((red, green, blue))


@lru_cache(maxsize=1024)
def int_to_lab(color: int) -> Lab:
    return rgb_to_lab(((color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF))


@lru_cache(maxsize=1024)
def rgb_to_lab(rgb: tuple[int, int, int]) -> Lab:
    return xyz_to_cielab(rgb_to_xyz(rgb))


def _linearize(channel: int) -> float:
    value = channel / 255
    if value > 0.04045:
        value = ((value + 0.055) / 1.055) ** 2.4
    else:
        value /= 12.92
    return value * 100


@lru_cache(maxsize=1024)
def rgb_to_xyz(rgb: tuple[int, int, int]) -> Lab:
    var_r, var_g, var_b = map(_linearize, rgb)
    x = var_r * 0.4124 + var_g * 0.3576 + var_b * 0.1805
    y = var_r * 0.2126 + var_g * 0.7152 + var_b * 0.0722
    z = var_r * 0.0193 + var_g * 0.1192 + var_b * 0.9505
    return x, y, z


def _lab_curve(value: float) -> float:
    if value > 0.008856:
        return value ** (1 / 3)
    return (7.787 * value) + (16 / 116)


@lru_cache(maxsize=1024)
def xyz_to_cielab(xyz: Lab) -> Lab:
    x_nat = _lab_curve(xyz[0] / 95.047)
    y_nat = _lab_curve(xyz[1] / 100)
    z_nat = _lab_curve(xyz[2] / 108.883)
    return (116 * y_nat) - 16, 500 * (x_nat - y_nat), 200 * (y_nat - z_nat)


@lru_cache(maxsize=1024)
def compare_delta_e_2000(lab1: Lab, lab2: Lab) -> float:
    l1, a1, b1 = lab1
    c1 = math.sqrt(a1**2 + b1**2)
    l2, a2, b2 = lab2
    c2 = math.sqrt(a2**2 + b2**2)
    c_bar = (c1 + c2) / 2

    g = 0.5 * (1 - math.sqrt(c_bar**7 / (c_bar**7 + 6103525625)))

    xa1 = (1 + g) * a1
    xa2 = (1 + g) * a2
    xc1 = math.sqrt(xa1**2 + b1**2)
    xc2 = math.sqrt(xa2**2 + b2**2)
    h1 = math.degrees(math.atan2(b1, xa1))
    h1 += (h1 < 0) * 360
    h2 = math.degrees(math.atan2(b2, xa2))
    h2 += (h2 < 0) * 360

    delta_l_dash = l2 - l1
    delta_c_dash = xc2 - xc1
    delta_h = 0.0

    if xc1 * xc2:
        if abs(h2 - h1) <= 180:
            delta_h = h2 - h1
        elif h2 - h1 > 180:
            delta_h = (h2 - h1) - 360
        elif h2 - h1 < -180:
            delta_h = (h2 - h1) + 360

    delta_h_dash = 2 * math.sqrt(xc1 * xc2) * math.sin(math.radians(delta_h) / 2.0)

    l_bar = (l1 + l2) / 2
    c_bar = (xc1 + xc2) / 2
    h_bar = h1 + h2

    if xc1 * xc2:
        if abs(h1 - h2) <= 180:
            h_bar = (h1 + h2) / 2
        else:
            h_bar = (h1 + h2 + 360) / 2 if (h1 + h2) < 360 else (h1 + h2 - 360) / 2

    t = (
        1
        - 0.17 * math.cos(math.radians(h_bar - 30))
        + 0.24 * math.cos(math.radians(2 * h_bar))
        + 0.32 * math.cos(math.radians(3 * h_bar + 6))
        - 0.20 * math.cos(math.radians(4 * h_bar - 63))
    )

    delta_theta = 30 * math.exp(-(((h_bar - 275) / 25) ** 2))
    xrc = 2 * math.sqrt(c_bar**7 / (c_bar**7 + 6103525625))
    xsl = 1 + 0.015 * (l_bar - 50) ** 2 / math.sqrt(20 + (l_bar - 50) ** 2)
    xsc = 1 + 0.045 * c_bar
    xsh = 1 + 0.015 * c_bar * t
    xrt = -xrc * math.sin(2 * math.radians(delta_theta))

    xkl, xkc, xkh = 1, 1, 1

    final_l = delta_l_dash / (xkl * xsl)
    final_c = delta_c_dash / (xkc * xsc)
    final_h = delta_h_dash / (xkh * xsh)

    delta = math.sqrt(final_l**2 + final_c**2 + final_h**2 + xrt * final_c * final_h)
    return delta


def compare_delta_cie(lab1: Lab, lab2: Lab) -> float:
    """Return the CIE76 distance, which is the Euclidean distance in Lab space.

    This is not cached. A cache lookup costs more than the arithmetic, and
    colors.find_closest_pieces already caches the result of each search.
    """
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    return math.sqrt((l1 - l2) ** 2 + (a1 - a2) ** 2 + (b1 - b2) ** 2)
