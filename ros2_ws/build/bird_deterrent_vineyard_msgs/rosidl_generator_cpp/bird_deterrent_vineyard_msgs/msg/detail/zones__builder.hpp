// generated from rosidl_generator_cpp/resource/idl__builder.hpp.em
// with input from bird_deterrent_vineyard_msgs:msg/Zones.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONES__BUILDER_HPP_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONES__BUILDER_HPP_

#include <algorithm>
#include <utility>

#include "bird_deterrent_vineyard_msgs/msg/detail/zones__struct.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


namespace bird_deterrent_vineyard_msgs
{

namespace msg
{

namespace builder
{

class Init_Zones_zones
{
public:
  explicit Init_Zones_zones(::bird_deterrent_vineyard_msgs::msg::Zones & msg)
  : msg_(msg)
  {}
  ::bird_deterrent_vineyard_msgs::msg::Zones zones(::bird_deterrent_vineyard_msgs::msg::Zones::_zones_type arg)
  {
    msg_.zones = std::move(arg);
    return std::move(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Zones msg_;
};

class Init_Zones_t
{
public:
  Init_Zones_t()
  : msg_(::rosidl_runtime_cpp::MessageInitialization::SKIP)
  {}
  Init_Zones_zones t(::bird_deterrent_vineyard_msgs::msg::Zones::_t_type arg)
  {
    msg_.t = std::move(arg);
    return Init_Zones_zones(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Zones msg_;
};

}  // namespace builder

}  // namespace msg

template<typename MessageType>
auto build();

template<>
inline
auto build<::bird_deterrent_vineyard_msgs::msg::Zones>()
{
  return bird_deterrent_vineyard_msgs::msg::builder::Init_Zones_t();
}

}  // namespace bird_deterrent_vineyard_msgs

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONES__BUILDER_HPP_
