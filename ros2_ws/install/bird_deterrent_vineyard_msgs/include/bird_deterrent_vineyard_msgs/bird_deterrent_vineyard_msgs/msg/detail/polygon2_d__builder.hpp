// generated from rosidl_generator_cpp/resource/idl__builder.hpp.em
// with input from bird_deterrent_vineyard_msgs:msg/Polygon2D.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__POLYGON2_D__BUILDER_HPP_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__POLYGON2_D__BUILDER_HPP_

#include <algorithm>
#include <utility>

#include "bird_deterrent_vineyard_msgs/msg/detail/polygon2_d__struct.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


namespace bird_deterrent_vineyard_msgs
{

namespace msg
{

namespace builder
{

class Init_Polygon2D_points
{
public:
  Init_Polygon2D_points()
  : msg_(::rosidl_runtime_cpp::MessageInitialization::SKIP)
  {}
  ::bird_deterrent_vineyard_msgs::msg::Polygon2D points(::bird_deterrent_vineyard_msgs::msg::Polygon2D::_points_type arg)
  {
    msg_.points = std::move(arg);
    return std::move(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Polygon2D msg_;
};

}  // namespace builder

}  // namespace msg

template<typename MessageType>
auto build();

template<>
inline
auto build<::bird_deterrent_vineyard_msgs::msg::Polygon2D>()
{
  return bird_deterrent_vineyard_msgs::msg::builder::Init_Polygon2D_points();
}

}  // namespace bird_deterrent_vineyard_msgs

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__POLYGON2_D__BUILDER_HPP_
