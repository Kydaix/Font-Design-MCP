"""Original geometric test drawings made for this project; no third-party font input."""


def contour(identifier, coordinates, types=None):
    return {
        "id": identifier,
        "points": [
            {"id": f"{identifier}_{i}", "x": x, "y": y, "type": types[i] if types else "line"}
            for i, (x, y) in enumerate(coordinates)
        ],
    }


def fixture():
    cubic = ["curve", "offcurve", "offcurve"] * 4
    outer = contour(
        "Oouter",
        [
            (300, 0),
            (438, 0),
            (550, 157),
            (550, 350),
            (550, 543),
            (438, 700),
            (300, 700),
            (162, 700),
            (50, 543),
            (50, 350),
            (50, 157),
            (162, 0),
        ],
        cubic,
    )
    inner = contour(
        "Oinner",
        [
            (300, 100),
            (210, 100),
            (150, 212),
            (150, 350),
            (150, 488),
            (210, 600),
            (300, 600),
            (390, 600),
            (450, 488),
            (450, 350),
            (450, 212),
            (390, 100),
        ],
        cubic,
    )
    return {
        "A": {
            "advance": 600,
            "unicodes": [65],
            "contours": [
                contour("Aouter", [(50, 0), (300, 700), (550, 0)]),
                contour("Ainner", [(235, 240), (365, 240), (300, 440)]),
            ],
            "anchors": [{"id": "Atop", "name": "top", "x": 300, "y": 700}],
        },
        "V": {
            "advance": 600,
            "unicodes": [86],
            "contours": [
                contour(
                    "Vouter", [(50, 700), (170, 700), (300, 180), (430, 700), (550, 700), (360, 0), (240, 0)]
                )
            ],
        },
        "O": {"advance": 600, "unicodes": [79], "contours": [outer, inner]},
        "Q": {
            "advance": 600,
            "unicodes": [81],
            "contours": [
                contour(
                    "Qquad",
                    [(80, 0), (520, 0), (600, 700), (300, 700), (0, 700)],
                    ["qcurve", "line", "offcurve", "qcurve", "offcurve"],
                )
            ],
        },
        "acute": {
            "advance": 300,
            "contours": [contour("acutecontour", [(0, 0), (120, 130), (220, 130), (70, 0)])],
        },
        "Aacute": {
            "advance": 600,
            "unicodes": [193],
            "components": [
                {"id": "baseA", "base": "A"},
                {"id": "accent", "base": "acute", "transform": [1, 0, 0, 1, 220, 730]},
            ],
        },
    }
