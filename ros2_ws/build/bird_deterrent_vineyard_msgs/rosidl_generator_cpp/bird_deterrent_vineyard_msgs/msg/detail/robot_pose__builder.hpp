// generated from rosidl_generator_cpp/resource/idl__builder.hpp.em
// with input from bird_deterrent_vineyard_msgs:msg/RobotPose.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ROBOT_POSE__BUILDER_HPP_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ROBOT_POSE__BUILDER_HPP_

#include <algorithm>
#include <utility>

#include "bird_deterrent_vineyard_msgs/msg/detail/robot_pose__struct.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


namespace bird_deterrent_vineyard_msgs
{

namespace msg
{

namespace builder
{

class Init_RobotPose_y
{
public:
  explicit Init_RobotPose_y(::bird_deterrent_vineyard_msgs::msg::RobotPose & msg)
  : msg_(msg)
  {}
  ::bird_deterrent_vineyard_msgs::msg::RobotPose y(::bird_deterrent_vineyard_msgs::msg::RobotPose::_y_type arg)
  {
    msg_.y = std::move(arg);
    return std::move(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::RobotPose msg_;
};

class Init_RobotPose_x
{
public:
  explicit Init_RobotPose_x(::bird_deterrent_vineyard_msgs::msg::RobotPose & msg)
  : msg_(msg)
  {}
  Init_RobotPose_y x(::bird_deterrent_vineyard_msgs::msg::RobotPose::_x_type arg)
  {
    msg_.x = std::move(arg);
    return Init_RobotPose_y(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::RobotPose msg_;
};

class Init_RobotPose_robot_id
{
public:
  explicit Init_RobotPose_robot_id(::bird_deterrent_vineyard_msgs::msg::RobotPose & msg)
  : msg_(msg)
  {}
  Init_RobotPose_x robot_id(::bird_deterrent_vineyard_msgs::msg::RobotPose::_robot_id_type arg)
  {
    msg_.robot_id = std::move(arg);
    return Init_RobotPose_x(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::RobotPose msg_;
};

class Init_RobotPose_t
{
public:
  Init_RobotPose_t()
  : msg_(::rosidl_runtime_cpp::MessageInitialization::SKIP)
  {}
  Init_RobotPose_robot_id t(::bird_deterrent_vineyard_msgs::msg::RobotPose::_t_type arg)
  {
    msg_.t = std::move(arg);
    return Init_RobotPose_robot_id(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::RobotPose msg_;
};

}  // namespace builder

}  // namespace msg

template<typename MessageType>
auto build();

template<>
inline
auto build<::bird_deterrent_vineyard_msgs::msg::RobotPose>()
{
  return bird_deterrent_vineyard_msgs::msg::builder::Init_RobotPose_t();
}

}  // namespace bird_deterrent_vineyard_msgs

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ROBOT_POSE__BUILDER_HPP_
