from django.utils.translation import gettext_lazy as _

# Master inspection checklist grouped by category.
# Each item is rendered as one InspectionPoint when a structured inspection
# is created.  Codes must remain stable; labels are user-facing and translatable.
INSPECTION_CHECKLIST = [
    {
        "category": "dashboard",
        "label": _("Dashboard & controls"),
        "items": [
            {"code": "dashboard_lights", "label": _("Any dashboard light")},
            {"code": "brake_works", "label": _("Brake works?")},
            {"code": "handbrake_works", "label": _("Working hand-brake?")},
            {"code": "brake_pedal_feel", "label": _("Brake pedal is stiff or soft?")},
        ],
    },
    {
        "category": "steering",
        "label": _("Steering & fluids"),
        "items": [
            {"code": "steering_wheel_shaft", "label": _("Steering wheel and steering shaft seem ok?")},
            {"code": "power_steering_fluid", "label": _("Power steering fluid (if power steering is hydraulic)")},
            {"code": "power_steering_cooling", "label": _("Power steering cooling")},
        ],
    },
    {
        "category": "brakes",
        "label": _("Brake system"),
        "items": [
            {"code": "abs_control_module", "label": _("ABS control module / Brake booster")},
            {"code": "brake_fluid_level", "label": _("Level of brake fluids")},
            {
                "code": "brake_flexible_hoses",
                "label": _("Brake lines and flexible hoses (or brake hoses and fittings)"),
            },
            {"code": "brake_metal_lines", "label": _("Brake metal lines")},
            {"code": "brake_hose_clamps", "label": _("Hose clamps and lines (hoses)")},
            {"code": "brake_wear", "label": _("Brake wear")},
            {"code": "pad_lining_size", "label": _("Pad lining size front and rear")},
            {"code": "disc_wear", "label": _("Disc wear")},
            {"code": "drum_brakes", "label": _("If drum brakes")},
            {"code": "brake_warping", "label": _("Measure of the warping if there is a warp")},
            {"code": "brake_specs_mitchell", "label": _("Brake specs found on Mitchell by the tech/mechanic")},
        ],
    },
    {
        "category": "tires_wheels",
        "label": _("Tires & wheels"),
        "items": [
            {"code": "oem_tire_size", "label": _("OEM tire size")},
            {"code": "oem_tire_pressure", "label": _("OEM tire pressure front and rear")},
            {"code": "wheel_size", "label": _("Size of the wheel on the car")},
            {"code": "wheel_rotation_direction", "label": _("Wheel rotation in the right direction")},
            {"code": "tire_wear", "label": _("Is there any wear")},
            {"code": "tire_inflation", "label": _("How inflated they are")},
            {"code": "wheel_bolts_wear", "label": _("Wheel bolts wear")},
            {"code": "air_valve", "label": _("Air valve")},
            {"code": "rim_general_state", "label": _("General state of the rim")},
        ],
    },
    {
        "category": "belts",
        "label": _("Belts"),
        "items": [
            {"code": "serpentine_belt", "label": _("Serpentine belt for power distribution state")},
        ],
    },
    {
        "category": "suspension_drivetrain",
        "label": _("Suspension & driveline"),
        "items": [
            {"code": "struts", "label": _("Everything related to the struts")},
            {"code": "bushings", "label": _("Bushings")},
            {"code": "cv_axle", "label": _("CV Axle")},
        ],
    },
]


def flatten_checklist():
    """Return a flat ordered list of all checklist items with their category."""
    flat = []
    position = 0
    for group in INSPECTION_CHECKLIST:
        for item in group["items"]:
            flat.append(
                {
                    "category": group["category"],
                    "category_label": group["label"],
                    "code": item["code"],
                    "label": item["label"],
                    "position": position,
                }
            )
            position += 1
    return flat
