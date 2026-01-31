// generated from rosidl_generator_cpp/resource/idl__builder.hpp.em
// with input from bird_deterrent_vineyard_msgs:msg/Detection.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__DETECTION__BUILDER_HPP_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__DETECTION__BUILDER_HPP_

#include <algorithm>
#include <utility>

#include "bird_deterrent_vineyard_msgs/msg/detail/detection__struct.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


namespace bird_deterrent_vineyard_msgs
{

namespace msg
{

namespace builder
{

class Init_Detection_source
{
public:
  explicit Init_Detection_source(::bird_deterrent_vineyard_msgs::msg::Detection & msg)
  : msg_(msg)
  {}
  ::bird_deterrent_vineyard_msgs::msg::Detection source(::bird_deterrent_vineyard_msgs::msg::Detection::_source_type arg)
  {
    msg_.source = std::move(arg);
    return std::move(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Detection msg_;
};

class Init_Detection_t
{
public:
  explicit Init_Detection_t(::bird_deterrent_vineyard_msgs::msg::Detection & msg)
  : msg_(msg)
  {}
  Init_Detection_source t(::bird_deterrent_vineyard_msgs::msg::Detection::_t_type arg)
  {
    msg_.t = std::move(arg);
    return Init_Detection_source(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Detection msg_;
};

class Init_Detection_y
{
public:
  explicit Init_Detection_y(::bird_deterrent_vineyard_msgs::msg::Detection & msg)
  : msg_(msg)
  {}
  Init_Detection_t y(::bird_deterrent_vineyard_msgs::msg::Detection::_y_type arg)
  {
    msg_.y = std::move(arg);
    return Init_Detection_t(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Detection msg_;
};

class Init_Detection_x
{
public:
  Init_Detection_x()
  : msg_(::rosidl_runtime_cpp::MessageInitialization::SKIP)
  {}
  Init_Detection_y x(::bird_deterrent_vineyard_msgs::msg::Detection::_x_type arg)
  {
    msg_.x = std::move(arg);
    return Init_Detection_y(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Detection msg_;
};

}  // namespace builder

}  // namespace msg

template<typename MessageType>
auto build();

template<>
inline
auto build<::bird_deterrent_vineyard_msgs::msg::Detection>()
{
  return bird_deterrent_vineyard_msgs::msg::builder::Init_Detection_x();
}

}  // namespace bird_deterrent_vineyard_msgs

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__DETECTION__BUILDER_HPP_
