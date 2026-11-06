from django.utils.translation import gettext_lazy as _

# Master inspection checklist based on the Aviron Québec
# "Inspection multipoint (tenue de route 60 points de vérification)" form.
# Each item is rendered as one InspectionPoint when a structured inspection
# is created. Codes must remain stable; labels are user-facing and translatable.
#
# Optional "validation" values:
#   - "numeric:mm"            : millimeter measurement
#   - "numeric:psi"           : PSI pressure measurement
#   - "numeric:32nds"         : tire tread depth in 1/32 inch
#   - "numeric:percent"       : percentage (0-100)
#   - "choice:a|x,b|y"        : one of the listed choices; the first value in each
#                               pipe-separated group is the canonical value stored
#                               in the database. Accepts both English and French.
#   - "tire_size"             : tire size such as 225/45R17
INSPECTION_CHECKLIST = [
    {
        "category": "exterior_cabin",
        "label": _("Exterior and cabin"),
        "items": [
            {"code": "dashboard_warning_lights", "label": _("Dashboard warning lights")},
            {"code": "parking_brake_operation", "label": _("Parking brake operation")},
            {"code": "brake_operation", "label": _("Brake operation")},
            {"code": "brake_lights", "label": _("Brake lights")},
            {"code": "tire_size_match", "label": _("Tire size match / pressure")},
            {"code": "steering_wheel_column", "label": _("Steering wheel and column")},
            {
                "code": "brake_pedal_feel",
                "label": _("Brake pedal feel"),
                "validation": "choice:firm|ferme,spongy|molle|mou,hard|dur,other|autre",
            },
        ],
    },
    {
        "category": "under_hood",
        "label": _("Under the hood"),
        "items": [
            {"code": "brake_booster", "label": _("Brake booster / emergency reserve")},
            {"code": "master_cylinder_abs", "label": _("Master cylinder / ABS unit")},
            {"code": "power_steering_fluid", "label": _("Power steering fluid")},
            {"code": "hoses_and_clamps", "label": _("Hoses and clamps")},
            {
                "code": "brake_fluid_level",
                "label": _("Brake fluid level"),
                "validation": "choice:high|haut,ok|ok,too low|trop bas,missing|manquant",
            },
            {"code": "brake_hoses_and_fittings", "label": _("Brake hoses and fittings")},
            {"code": "brake_rigid_lines", "label": _("Brake rigid lines")},
            {"code": "drive_belts", "label": _("Drive belts")},
            {"code": "power_steering_radiator", "label": _("Power steering radiator")},
        ],
    },
    {
        "category": "tires",
        "label": _("Tires"),
        "items": [
            {
                "group": _("General"),
                "code": "tire_size_on_vehicle",
                "label": _("Tire size on vehicle"),
                "validation": "tire_size",
            },
            {"group": _("General"), "code": "rotation_direction", "label": _("Rotation direction")},
            {"group": _("General"), "code": "tire_notes", "label": _("Tire notes")},
            {"group": _("Front axle"), "code": "visual_wear_front_right", "label": _("Visual wear - front right")},
            {"group": _("Front axle"), "code": "visual_wear_front_left", "label": _("Visual wear - front left")},
            {"group": _("Rear axle"), "code": "visual_wear_rear_left", "label": _("Visual wear - rear left")},
            {"group": _("Rear axle"), "code": "visual_wear_rear_right", "label": _("Visual wear - rear right")},
            {
                "group": _("General"),
                "code": "wear_pattern",
                "label": _("Wear pattern"),
                "validation": "choice:equal|égal,uneven|inégal,outer|extérieur,inner|intérieur",
            },
            {
                "group": _("Front axle"),
                "code": "tread_depth_front_right",
                "label": _("Tread depth - front right (1/32)"),
                "validation": "numeric:32nds",
            },
            {
                "group": _("Front axle"),
                "code": "tread_depth_front_left",
                "label": _("Tread depth - front left (1/32)"),
                "validation": "numeric:32nds",
            },
            {
                "group": _("Rear axle"),
                "code": "tread_depth_rear_left",
                "label": _("Tread depth - rear left (1/32)"),
                "validation": "numeric:32nds",
            },
            {
                "group": _("Rear axle"),
                "code": "tread_depth_rear_right",
                "label": _("Tread depth - rear right (1/32)"),
                "validation": "numeric:32nds",
            },
            {
                "group": _("Front axle"),
                "code": "pressure_front_right",
                "label": _("Tire pressure - front right (psi)"),
                "validation": "numeric:psi",
            },
            {
                "group": _("Front axle"),
                "code": "pressure_front_left",
                "label": _("Tire pressure - front left (psi)"),
                "validation": "numeric:psi",
            },
            {
                "group": _("Rear axle"),
                "code": "pressure_rear_left",
                "label": _("Tire pressure - rear left (psi)"),
                "validation": "numeric:psi",
            },
            {
                "group": _("Rear axle"),
                "code": "pressure_rear_right",
                "label": _("Tire pressure - rear right (psi)"),
                "validation": "numeric:psi",
            },
        ],
    },
    {
        "category": "wheels",
        "label": _("Wheels"),
        "items": [
            {"code": "wheel_general_condition", "label": _("Wheels general condition")},
            {"code": "valves_caps", "label": _("Valves / caps")},
            {"code": "lugs_bolts", "label": _("Lugs / bolts")},
        ],
    },
    {
        "category": "brakes",
        "label": _("Brakes"),
        "items": [
            {"group": _("General"), "code": "brake_wear_general", "label": _("Brake wear (general)")},
            {
                "group": _("General"),
                "code": "rear_brake_type",
                "label": _("Rear brake type"),
                "validation": "choice:disc|disque,drum|tambour",
            },
            {
                "group": _("Front axle"),
                "code": "pad_front_right",
                "label": _("Front right pad (mm)"),
                "validation": "numeric:mm",
            },
            {
                "group": _("Front axle"),
                "code": "pad_front_left",
                "label": _("Front left pad (mm)"),
                "validation": "numeric:mm",
            },
            {
                "group": _("Rear axle"),
                "code": "pad_rear_right",
                "label": _("Rear right pad (mm)"),
                "validation": "numeric:mm",
            },
            {
                "group": _("Rear axle"),
                "code": "pad_rear_left",
                "label": _("Rear left pad (mm)"),
                "validation": "numeric:mm",
            },
            {
                "group": _("Rear axle"),
                "code": "shoe_rear_right",
                "label": _("Rear right shoe (mm)"),
                "validation": "numeric:mm",
            },
            {
                "group": _("Rear axle"),
                "code": "shoe_rear_left",
                "label": _("Rear left shoe (mm)"),
                "validation": "numeric:mm",
            },
            {"group": _("Front axle"), "code": "disc_front_right", "label": _("Front right disc condition")},
            {"group": _("Front axle"), "code": "disc_front_left", "label": _("Front left disc condition")},
            {"group": _("Rear axle"), "code": "disc_rear_right", "label": _("Rear right disc condition")},
            {"group": _("Rear axle"), "code": "disc_rear_left", "label": _("Rear left disc condition")},
            {"group": _("Rear axle"), "code": "drum_rear_right", "label": _("Rear right drum condition")},
            {"group": _("Rear axle"), "code": "drum_rear_left", "label": _("Rear left drum condition")},
            {"group": _("General"), "code": "disc_drum_specs", "label": _("Disc / drum specifications")},
            {"group": _("General"), "code": "warping_specs", "label": _("Warping specifications")},
            {
                "group": _("Front axle"),
                "code": "warping_measurement_front_right",
                "label": _("Warping measurement - front right"),
            },
            {
                "group": _("Front axle"),
                "code": "warping_measurement_front_left",
                "label": _("Warping measurement - front left"),
            },
            {
                "group": _("Rear axle"),
                "code": "warping_measurement_rear_left",
                "label": _("Warping measurement - rear left"),
            },
            {
                "group": _("Rear axle"),
                "code": "warping_measurement_rear_right",
                "label": _("Warping measurement - rear right"),
            },
            {"group": _("General"), "code": "emergency_brake_adjustment", "label": _("Emergency brake adjustment")},
            {"group": _("General"), "code": "brake_cables_lines", "label": _("Brake cables / lines")},
        ],
    },
    {
        "category": "underbody",
        "label": _("Under the vehicle"),
        "items": [
            {"code": "struts_mac_pherson", "label": _("Struts / MacPherson")},
            {"code": "shock_absorbers", "label": _("Shock absorbers")},
            {"code": "springs", "label": _("Springs")},
            {"code": "ball_joints", "label": _("Ball joints")},
            {"code": "control_arms", "label": _("Control arms")},
            {"code": "control_arm_bushings", "label": _("Control arm bushings")},
            {"code": "rack_and_pinion", "label": _("Rack and pinion")},
            {"code": "steering_bellows", "label": _("Steering bellows")},
            {"code": "transfer_case", "label": _("Transfer case (pick-up)")},
            {"code": "outer_tie_rods", "label": _("Outer tie rods")},
            {"code": "inner_tie_rods", "label": _("Inner tie rods")},
            {"code": "wheel_bearings", "label": _("Wheel bearings")},
            {"code": "cv_boots", "label": _("CV boots")},
            {"code": "cv_joints", "label": _("CV joints")},
            {"code": "stabilizer_bars", "label": _("Stabilizer bars")},
            {"code": "stabilizer_links", "label": _("Stabilizer links")},
            {"code": "universal_joints", "label": _("Universal joints")},
            {"code": "differentials", "label": _("Differential(s)")},
            {
                "code": "fluid_leaks",
                "label": _("Fluid leaks (engine, coolant, transmission, brakes, fuel, power steering)"),
                "validation": "choice:none|aucun,present|présent",
            },
            {"code": "underbody_other", "label": _("Other underbody observations")},
        ],
    },
    {
        "category": "final_diagnostics",
        "label": _("Final diagnostics"),
        "items": [
            {"code": "diag_wheels_tires_bearings", "label": _("Wheels / tires / bearings diagnostic")},
            {"code": "diag_braking_system", "label": _("Braking system diagnostic")},
            {"code": "diag_suspension", "label": _("Suspension diagnostic")},
            {"code": "diag_steering", "label": _("Steering diagnostic")},
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
                    "group": item.get("group", ""),
                    "code": item["code"],
                    "label": item["label"],
                    "validation": item.get("validation"),
                    "position": position,
                }
            )
            position += 1
    return flat


# Build a lookup for validation rules so forms can validate efficiently.
VALIDATION_RULES = {item["code"]: item.get("validation") for item in flatten_checklist()}


def validation_rule_for_code(code: str) -> str | None:
    """Return the validation rule for a checklist item code, if any."""
    return VALIDATION_RULES.get(code)
