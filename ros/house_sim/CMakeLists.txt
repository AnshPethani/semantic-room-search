cmake_minimum_required(VERSION 3.8)
project(house_sim)

find_package(ament_cmake REQUIRED)

install(DIRECTORY launch worlds maps layout models config
  DESTINATION share/${PROJECT_NAME})
# room_tour.py imports room_goals.py, which imports generate_house.py: install all three together.
install(PROGRAMS scripts/generate_house.py scripts/room_goals.py scripts/room_tour.py
  DESTINATION lib/${PROJECT_NAME})

ament_package()
