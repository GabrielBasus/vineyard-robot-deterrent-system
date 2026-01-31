import sys
if sys.prefix == '/usr':
    sys.real_prefix = sys.prefix
    sys.prefix = sys.exec_prefix = '/home/gabrielbasus/Thesis/vineyard-robot-deterrent-ROS/ros2_ws/install/bird_deterrent_vineyard'
