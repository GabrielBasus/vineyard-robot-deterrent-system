// generated from rosidl_generator_cpp/resource/idl__builder.hpp.em
// with input from bird_deterrent_vineyard_msgs:msg/Zone.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONE__BUILDER_HPP_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONE__BUILDER_HPP_

#include <algorithm>
#include <utility>

#include "bird_deterrent_vineyard_msgs/msg/detail/zone__struct.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


namespace bird_deterrent_vineyard_msgs
{

namespace msg
{

namespace builder
{

class Init_Zone_neighbors
{
public:
  explicit Init_Zone_neighbors(::bird_deterrent_vineyard_msgs::msg::Zone & msg)
  : msg_(msg)
  {}
  ::bird_deterrent_vineyard_msgs::msg::Zone neighbors(::bird_deterrent_vineyard_msgs::msg::Zone::_neighbors_type arg)
  {
    msg_.neighbors = std::move(arg);
    return std::move(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Zone msg_;
};

class Init_Zone_polygon
{
public:
  explicit Init_Zone_polygon(::bird_deterrent_vineyard_msgs::msg::Zone & msg)
  : msg_(msg)
  {}
  Init_Zone_neighbors polygon(::bird_deterrent_vineyard_msgs::msg::Zone::_polygon_type arg)
  {
    msg_.polygon = std::move(arg);
    return Init_Zone_neighbors(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Zone msg_;
};

class Init_Zone_robot_id
{
public:
  Init_Zone_robot_id()
  : msg_(::rosidl_runtime_cpp::MessageInitialization::SKIP)
  {}
  Init_Zone_polygon robot_id(::bird_deterrent_vineyard_msgs::msg::Zone::_robot_id_type arg)
  {
    msg_.robot_id = std::move(arg);
    return Init_Zone_polygon(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Zone msg_;
};

}  // namespace builder

}  // namespace msg

template<typename MessageType>
auto build();

template<>
inline
auto build<::bird_deterrent_vineyard_msgs::msg::Zone>()
{
  return bird_deterrent_vineyard_msgs::msg::builder::Init_Zone_robot_id();
}

}  // namespace bird_deterrent_vineyard_msgs

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONE__BUILDER_HPP_
