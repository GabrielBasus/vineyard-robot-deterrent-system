cmake_minimum_required(VERSION 3.8)
project(bird-deterrent-vineyard)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/Point2D.msg"
  "msg/Polygon2D.msg"
  "msg/Zone.msg"
  "msg/Zones.msg"
  "msg/Detection.msg"
  "msg/Task.msg"
  "msg/TaskStatus.msg"
  "msg/RobotPose.msg"
)

ament_python_install_package(bird_deterrent_vineyard)

ament_package()
