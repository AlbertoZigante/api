"""Server-side input bounds. Deliberately looser than the UI limits
(modeller: PANEL_SIZE_LIMITS_MM 1500x2000, DESIGN_LIMITS_MM +-3000) so a
legitimate design is never rejected, but tight enough to stop abuse.
All lengths in millimetres (canonical unit)."""

MAX_PANELS = 500
MAX_DIM_MM = 5000.0          # width / height of one panel
MAX_THICKNESS_MM = 100.0
MAX_COORD_MM = 10_000.0      # |position| / |offset| on any axis
MAX_ROTATION = 1000.0        # radians, generous (UI uses multiples of pi/2)
MAX_STR = 200
MAX_LIST = 64
MAX_QUANTITY = 1000
