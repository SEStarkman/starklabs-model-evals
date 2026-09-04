# Case 2: Python Murmuration Simulation

## Instructions for the candidate model

Build a Python simulation of a starling murmuration (bird flocking) that follows the mouse cursor.

### Requirements

1. Create a flock of ~200-500 simulated birds that exhibit realistic flocking behavior:
   - **Separation:** Avoid crowding neighbors
   - **Alignment:** Steer toward average heading of neighbors
   - **Cohesion:** Move toward average position of neighbors
   - **Mouse attraction:** The flock as a whole follows the mouse cursor position

2. Render the simulation as a real-time window where:
   - Birds are visible as small shapes (triangles, dots, or simple bird silhouettes)
   - Movement is smooth (60 FPS target)
   - The window is at least 800x600 pixels
   - The background is dark (night sky aesthetic preferred)

3. The simulation must:
   - Start running immediately when launched
   - Track the mouse cursor in real-time
   - Run for at least 10 seconds without crashing
   - Exit cleanly with the Escape key or window close

### Constraints

- **Allowed dependencies:** Python standard library, `pygame`, `numpy`
- **NOT allowed:** Any package that implements flocking/boids/murmuration behavior (e.g., `boids`, `flocking`, `murmuration` packages)
- You must implement the flocking algorithms (separation, alignment, cohesion) yourself
- The code must be complete and runnable — write all files needed

### Output

Provide all code as Python files. Include:
- A main simulation file (`murmuration.py`) that can be run directly with `python3 murmuration.py`
- Any supporting modules you create
- Brief instructions for running the simulation
