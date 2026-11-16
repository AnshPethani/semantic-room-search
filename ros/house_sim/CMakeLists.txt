cmake_minimum_required(VERSION 3.8)
project(house_sim)

find_package(ament_cmake REQUIRED)

install(DIRECTORY launch worlds maps layout models config objects
  DESTINATION share/${PROJECT_NAME})
# The scripts import each other (room_tour -> room_goals -> generate_house; house_objects ->
# room_goals, generate_house), so they are installed together.
install(PROGRAMS scripts/generate_house.py scripts/room_goals.py scripts/room_tour.py
  scripts/house_objects.py scripts/viewpoints.py scripts/clutter.py
  scripts/touch_logic.py scripts/touch_target.py
  DESTINATION lib/${PROJECT_NAME})

ament_package()
