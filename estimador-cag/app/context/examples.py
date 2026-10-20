ESTIMATION_EXAMPLES: list[dict] = [
    {
        "meeting_summary": (
            "The client needs an autonomous mobile robot (AMR) to handle materials for an "
            "engineering workshop. The robot must pick up raw materials, tools and parts from "
            "storage locations, deliver them to workstations, and return empty containers, "
            "navigating safely among staff and fixed equipment. Each material must be identified "
            "by barcode or RFID so the system can track it in real time and update stock. The "
            "platform needs a mission dispatcher that assigns transport tasks by priority, a "
            "web dashboard to monitor the fleet and inventory, and an integration with the "
            "client's existing ERP for material requests and stock levels. Safety is critical: "
            "obstacle detection, emergency stop and speed limits in shared areas. The team will "
            "commission the robot on site, and documentation must be generated with Sphinx for "
            "operators and maintenance staff."
        ),
        "estimation": """\
## Autonomous Material Handling Robot for Engineering Workshop

### Task Breakdown

| Task | Hours | Cost (EUR) |
|------|------:|------------|
| Requirements analysis and system design | 20 | 1,250 |
| Navigation, mapping and ROS 2 configuration | 24 | 1,500 |
| Mission dispatcher and task planner | 24 | 1,500 |
| Material inventory backend (FastAPI and PostgreSQL) | 24 | 1,500 |
| Barcode/RFID material identification integration | 16 | 1,000 |
| ERP integration for material requests and stock | 12 | 750 |
| Fleet monitoring dashboard | 20 | 1,250 |
| Safety validation: obstacle detection and emergency stop | 12 | 750 |
| Hardware integration and on-site commissioning | 12 | 750 |
| Testing (unit, simulation and field tests) | 16 | 1,000 |
| Sphinx documentation and operator training | 10 | 625 |
| Code review, QA, and bug fixing | 10 | 625 |

### Totals

- **Total hours:** 200
- **Total cost:** 12,500 EUR

### Recommended Team

- 1 Senior Robotics and Backend Engineer (lead)
- 1 Mid-level Full-Stack Developer
- 1 Robotics Test Engineer (part-time, during commissioning and field tests)

### Estimated Duration

**12 weeks** with a three-person team, including two weeks of on-site commissioning.""",
    },
    {
            "meeting_summary": (
            "The client is a hotel that wants an autonomous service robot to move materials between "
            "the central storage room, housekeeping stations and guest floors. The robot would carry "
            "clean linens, amenities, minibar restocking items and maintenance supplies, using the "
            "hotel elevators and doors. Housekeeping tasks and room service requests must come from "
            "the hotel's property management system (PMS), and the robot must update linen and "
            "amenity stock in real time. Staff will assign and monitor missions from tablets with a "
            "web interface. Guest safety is the priority: the robot must avoid people in corridors, "
            "respect speed limits near rooms, and stop immediately when the emergency button is "
            "pressed. The project includes on-site commissioning, staff training and documentation "
            "generated with Sphinx."
        ),
        "estimation": """\
## Autonomous Material Delivery Robot for Hotel Operations

### Task Breakdown

| Task | Hours | Cost (EUR) |
|------|------:|------------|
| Requirements analysis and system design | 16 | 1,000 |
| Floor navigation and mapping with ROS 2 | 24 | 1,500 |
| Mission scheduler for deliveries and pickups | 20 | 1,250 |
| PMS integration (housekeeping tasks and room requests) | 20 | 1,250 |
| Linen and amenity inventory tracking backend | 20 | 1,250 |
| Staff web panel for tablets | 16 | 1,000 |
| Guest safety validation: crowd avoidance and emergency stop | 12 | 750 |
| Elevator and door hardware integration | 12 | 750 |
| On-site commissioning and staff training | 14 | 875 |
| Testing (simulation and field tests in a live hotel) | 16 | 1,000 |
| Sphinx documentation | 8 | 500 |
| Code review, QA, and bug fixing | 10 | 625 |

### Totals

- **Total hours:** 188
- **Total cost:** 11,750 EUR

### Recommended Team

- 1 Senior Robotics Engineer (lead)
- 1 Mid-level Backend and Integration Developer (PMS)
- 1 QA Engineer (part-time, during field tests)

### Estimated Duration

**9 weeks**, with the last two weeks on site in the hotel.""",
    }
]

def format_examples_for_prompt(examples: list[dict]) -> str:
    blocks = (
        f"--- EXAMPLE {i} ---\n"
        f"Meeting Summary:\n{example['meeting_summary']}\n\n"
        f"Estimation:\n{example['estimation']}\n"
        for i, example in enumerate(examples, start=1)
    )
    return "\n".join(blocks)