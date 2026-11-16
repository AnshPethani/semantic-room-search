# house_sim

Gazebo house world, Nav2 map and room layout for the project
*LLM-Grounded Semantic Object Search in a Known Floorplan*.

Everything is generated from **one file**, `layout/house_layout.yaml`, so the
Gazebo world, the Nav2 map and the scene graph can never disagree:

| Generated file | Used by |
|---|---|
| `worlds/house.sdf` | Gazebo Harmonic |
| `maps/house_map.pgm`, `maps/house_map.yaml` | Nav2 `map_server` + AMCL (known map, no SLAM needed) |
| `<repo>/data/scene_graph.json` | `lang_grounding` (LLM grounding) and the room-order planner: room polygons, centroids, areas, doors (neighbors are derived from doors) |
| `maps/house_map_preview.png` | humans only (`--preview`, needs Pillow) |

```
house (12 x 9 m)          E  = entry hall (robot start)  K = kitchen
                          LR = living room (hub, L-shaped)  D = dining area
                          B1 = bedroom 1   B2 = bedroom 2
Doors: d_E_LR, d_E_K, d_K_LR, d_LR_D, d_LR_B1, d_LR_B2   (1.0 m wide; d_LR_D is 1.4 m)
       d_E_out: exterior door on E's north wall, CLOSED (solid panel, occupied on the map)
Clear opening of a door = width - wall thickness (0.85 m, or 1.25 m for d_LR_D)
```

**Frame (D-050):** the Gazebo world frame is the Nav2 `map` frame. Origin at the
bottom-left outer corner of the house, x to the right, y up, meters. The map yaml
origin is `[-margin, -margin, 0]` = `[-0.5, -0.5, 0.0]`.

## 1. One-time setup (Ubuntu 24.04)

```bash
# ROS 2 Jazzy desktop should already be installed (docs.ros.org/en/jazzy/Installation.html)
sudo apt install ros-jazzy-ros-gz ros-jazzy-navigation2 ros-jazzy-nav2-bringup \
                 ros-jazzy-turtlebot3-gazebo ros-jazzy-turtlebot3-msgs ros-jazzy-turtlebot3-description
echo "source /opt/ros/jazzy/setup.bash" >> ~/.bashrc
echo "export TURTLEBOT3_MODEL=waffle"   >> ~/.bashrc
source ~/.bashrc
```

If `ros-jazzy-turtlebot3-gazebo` is not available from apt, build it from source
(`git clone -b jazzy https://github.com/ROBOTIS-GIT/turtlebot3_simulations.git`
into `~/ros2_ws/src`, together with `turtlebot3` and `turtlebot3_msgs` on the jazzy branch).

## 2. Build

```bash
mkdir -p ~/ros2_ws/src && cp -r house_sim ~/ros2_ws/src/
cd ~/ros2_ws && colcon build --packages-select house_sim
source install/setup.bash
```

## 3. Run

```bash
ros2 launch house_sim house_world.launch.py            # Gazebo GUI + robot in the entry hall
ros2 launch house_sim house_world.launch.py gui:=false # headless
```

### Check that it works

In a second terminal (`source ~/ros2_ws/install/setup.bash` first):

```bash
ros2 topic list | grep -E "scan|odom|cmd_vel|camera"   # all four should be listed
ros2 topic echo /scan --once | head -20                  # numbers, not all inf
ros2 run turtlebot3_teleop teleop_keyboard               # drive through a doorway
```

Things to confirm by eye in Gazebo:
- [ ] Walls and colored floors match `maps/house_map_preview.png`
- [ ] Robot spawns in the entry hall E (top-left), not inside a wall
- [ ] Robot fits through every interior doorway when driven with teleop
- [ ] Robot is blocked by the brown closed door `d_E_out` on E's north wall
- [ ] Lidar rays (Gazebo: right-click robot → *View* → *Sensors*) hit the walls

## 4. Localization and navigation (AMCL + Nav2)

```bash
ros2 launch house_sim house_nav.launch.py          # Gazebo + Nav2 + RViz
# second terminal, robot still at the start pose:
ros2 run house_sim room_tour.py                    # drives to K, LR, D, B2, B1, E
```

AMCL starts at `robot_start` (from the layout), so no "2D Pose Estimate" is needed.
Nav2 parameters are in `config/nav2_params.yaml`: a copy of the Jazzy `nav2_bringup`
default, with this house's changes marked `# house_sim:`. The tour goal of each room
is the interior point farthest from its walls (`scripts/room_goals.py`); the tour
prints SUCCEEDED/FAILED/TIMEOUT per room and exits 1 if any room is not reached.

## 5. Target objects

```bash
ros2 launch house_sim house_nav.launch.py             # or house_world.launch.py
# second terminal:
ros2 launch house_sim spawn_objects.launch.py         # scenario:=demo (default)
```

`objects/catalog.yaml` holds the target classes (the 12 COCO names of
`configs/vocabulary.json`) as colored placeholder shapes; `objects/scenarios/demo.yaml`
places one of each in a plausible room. The oracle detector's ground truth is
`data/objects_<scenario>.json`; regenerate it after editing a scenario with
`python ros/house_sim/scripts/house_objects.py` (from the repository root). Gazebo model
names are `obj_<label>_<k>` (e.g. `obj_teddy_bear_0`). Placements are checked before
spawning: inside the declared room, clear of walls (0.3 m), door gaps (0.5 m), room tour
goals (0.6 m), the start (0.8 m) and each other (0.3 m).

## 6. Search viewpoints

Every room in `data/scene_graph.json` has a `viewpoints` list: 1–3 positions where the
robot turns 360° to look for targets (green squares in `maps/house_map_preview.png`).
They are chosen by `scripts/viewpoints.py` so that every floor point of the room is within
`camera_range` (3 m) and in line of sight of a viewpoint, with as few viewpoints as possible.
Settings are in the `viewpoints` section of `layout/house_layout.yaml`; regenerate after
changing them.

## 7. Clutter

```bash
ros2 launch house_sim house_nav.launch.py
ros2 launch house_sim spawn_objects.launch.py                    # targets (demo)
ros2 launch house_sim spawn_clutter.launch.py count:=10 seed:=0  # 0-10 obstacles
```

Clutter (boxes, bins, chairs from `objects/clutter.yaml`) is not on the map; Nav2 only
sees it through the lidar. Placement is random but fixed by `seed`, keeps 0.5 m from door
gaps, viewpoints and tour goals, and a reachability check makes sure every viewpoint and
target can still be reached. Model names are `clutter_<type>_<k>`.

## 8. Contact sensor (bumper)

The robot is spawned from `models/turtlebot3_waffle_bumper/model.sdf`, a copy of the
TurtleBot3 Waffle with a contact sensor on its body. Every contact (targets, clutter,
walls) is published on ROS `/bumper` (`ros_gz_interfaces/msg/Contacts`):

```bash
ros2 topic echo /bumper     # prints messages only while something touches the robot body
```

## 9. Depth camera

Next to the RGB camera (`/camera/image_raw`, 1920 × 1080) the robot has a depth camera
with the same view at a third of the resolution: `/camera/depth/image_raw` (640 × 360,
meters, 32-bit float, 15 Hz) and `/camera/depth/camera_info`. RGB pixel (u, v) is depth
pixel (u/3, v/3). Both use frame `camera_rgb_frame` (x forward, not an optical frame).

## 10. Approach and touch

```bash
ros2 launch house_sim house_nav.launch.py
ros2 launch house_sim spawn_objects.launch.py
ros2 run house_sim touch_target.py --name obj_bottle_0
```

Nav2 drives to a pose 0.5 m in front of the target, then a slow servo turns toward it and
drives until the bumper touches it, the depth camera reads ≤ 0.15 m where it is, or the
estimated gap is ≤ 0.05 m (for flat objects the camera and bumper cannot see). It prints
`RESULT <name>: SUCCEEDED|FAILED (<reason>)`.

## 11. Changing the house

Edit `layout/house_layout.yaml` (walls, doors, room polygons, start pose), then,
from the **repository root** (the scene graph is written to `<repo>/data/`):

```bash
python3 ros/house_sim/scripts/generate_house.py --preview
python3 -m pytest tests/test_house_sim.py    # includes a drift test against the committed files
colcon build --packages-select house_sim     # reinstall
```

Rooms are counter-clockwise polygons on wall center-lines with axis-aligned
edges; the Gazebo floor tiles are derived from them. The script stops with an
error if a door is not fully on a wall segment, a polygon is clockwise or not
axis-aligned, or the start pose is not inside a room. The generator is ROS-free
(standard library + PyYAML), so its tests run with plain `pytest`.
`maps/house_map_preview.png` shows the map with room IDs and the start pose (blue circle).

## Next steps (Kristika)

1. **Localization + Nav2 on the known map**: `nav2_bringup` with `maps/house_map.yaml`,
   initial pose = `robot_start`, then send goals to each room (note: the centroid of a
   non-convex room such as LR is not guaranteed to be inside it).
2. Furniture and target objects (COCO classes) placed in rooms.
3. Clutter spawner (random boxes away from doorways).
4. Viewpoints per room, and the approach-and-touch controller.
