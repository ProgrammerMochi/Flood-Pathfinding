"""Conservative vehicle wading-depth presets, expressed in centimetres."""

VEHICLES: dict[str, int] = {
    "motorcycle": 15,
    "sedan_hatchback": 15,
    "crossover_small_suv": 25,
    "suv_pickup": 30,
}


def safe_depth_for(vehicle: str) -> int:
    """Return the configured safe depth for a preset vehicle.

    Custom clearances are deliberately supplied directly to the routing API,
    rather than being added to this shared preset mapping.
    """
    try:
        return VEHICLES[vehicle]
    except KeyError as error:
        raise ValueError(f"Unknown vehicle preset: {vehicle}") from error
